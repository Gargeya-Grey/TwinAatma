"""Capture must never authenticate index rows that disagree with source notes."""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
from pathlib import Path
import queue
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from knowledgeos import indexer
from knowledgeos.memory import MemoryAPI, dispatch


def process_stopped(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return True
        raise OSError(ctypes.get_last_error(), "could not inspect owned process")
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


class CaptureTransactionTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get(
            "TWIN_CAPTURE_TRANSACTION_ROOT",
            str(Path(__file__).resolve().parents[1] / "work/gc-artifacts/.knowledgeos/capture-transaction")))
        case_id = hashlib.sha256(self._testMethodName.encode()).hexdigest()[:8]
        self.root = base / (case_id + "-" + secrets.token_hex(3))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        (self.vault / "Projects").mkdir()
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\nUnknown.\n")
        self.source = self.vault / "Projects/Vendor.md"
        self.source.write_text(
            "---\ntype: project\nid: kos:project:vendor\ntitle: Vendor review\nstatus: active\n---\n\n"
            "# Vendor review\n\nThe quarterly review is due.\n", encoding="utf-8")
        self.original = {p: p.read_bytes() for p in (self.identity, self.source)}
        self.environment = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.record("case", {"test": self.id(), "vault": str(self.vault)})
        self.api = MemoryAPI(self.vault)
        warm = dispatch(self.api, "memory_search", {"query": "Vendor review"})
        self.assertEqual([r["path"] for r in warm["ranked"]], ["Projects/Vendor.md"])
        self.assert_signed_source()

    def tearDown(self):
        for path, before in self.original.items():
            self.assertEqual(path.read_bytes(), before)

    def record(self, name, value):
        (self.root / (name + ".json")).write_text(json.dumps(value, indent=2), encoding="utf-8")

    def row_type(self):
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            return conn.execute("SELECT type FROM notes WHERE path='Projects/Vendor.md'").fetchone()[0]
        finally:
            conn.close()

    def forge(self):
        conn = sqlite3.connect(self.vault / indexer.DB_NAME, timeout=1)
        try:
            conn.execute("UPDATE notes SET type='decision' WHERE path='Projects/Vendor.md'")
            conn.commit()
        finally:
            conn.close()

    def competing_writer(self, sql=None):
        code = (
            "import json,os,sqlite3,sys\n"
            "conn=sqlite3.connect(sys.argv[1],timeout=0.25)\n"
            "try:\n"
            " try:\n"
            "  conn.execute(sys.argv[2]); conn.commit(); result={'status':'committed'}\n"
            " except sqlite3.OperationalError as exc:\n"
            "  result={'status':'blocked','error':str(exc)}\n"
            "finally:\n"
            " conn.close()\n"
            "result['pid']=os.getpid()\n"
            "print(json.dumps(result))\n")
        command = [sys.executable, "-B", "-c", code, str(self.vault / indexer.DB_NAME),
                   sql or "UPDATE notes SET type='decision' WHERE path='Projects/Vendor.md'"]
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8")
        forced = False
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            forced = True
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
        result = json.loads(stdout) if stdout else {}
        actual_pid = result.pop("pid", None)
        actual_stopped = process_stopped(actual_pid) if isinstance(actual_pid, int) else False
        self.record("writer-" + str(proc.pid), {
            "command": command, "pid": proc.pid, "exit_code": proc.returncode,
            "actual_pid": actual_pid, "actual_stopped": actual_stopped,
            "forced": forced, "stopped": proc.poll() is not None, "stdout": stdout, "stderr": stderr})
        self.assertFalse(forced)
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertTrue(actual_stopped)
        return result

    def remove_signed_digest(self):
        manifest = indexer.load_manifest(self.vault)
        manifest.pop("index")
        indexer.save_manifest(self.vault, manifest)

    def capture(self, title="Unrelated capture", content="Something worth keeping.", **kwargs):
        result = dispatch(self.api, "memory_capture", {"title": title, "content": content, **kwargs})
        self.record("capture-" + title.replace(" ", "-"), result)
        self.assertEqual(result.get("ok"), True, result)
        self.assertEqual(result.get("indexed"), True, result)
        self.assertIn(content, (self.vault / result["path"]).read_text(encoding="utf-8"))
        return result

    def rows(self):
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            return {table: conn.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                    for table in ("notes", "notes_fts", "links", "metadata")}
        finally:
            conn.close()

    @contextlib.contextmanager
    def held_process(self, code):
        command = [sys.executable, "-B", "-c", code, str(self.vault)]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8")
        ready = queue.Queue()
        reader = threading.Thread(target=lambda: ready.put(proc.stdout.readline()), daemon=True)
        reader.start()
        first_line = ""
        forced = False
        actual_pid = None

        def release():
            if proc.stdin is not None:
                try:
                    proc.stdin.write("release\n")
                    proc.stdin.flush()
                except BrokenPipeError:
                    pass
                finally:
                    proc.stdin.close()
                    proc.stdin = None

        try:
            first_line = ready.get(timeout=10)
            reader.join(timeout=1)
            observation = json.loads(first_line)
            self.assertEqual(observation.get("status"), "held")
            actual_pid = observation["pid"]
            self.assertIsInstance(actual_pid, int)
            self.assertFalse(process_stopped(actual_pid))
            yield proc, release
        finally:
            release()
            try:
                stdout, stderr = proc.communicate(timeout=40)
            except subprocess.TimeoutExpired:
                forced = True
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
            reader.join(timeout=1)
            self.record("holder-" + str(proc.pid), {
                "command": command, "pid": proc.pid, "exit_code": proc.returncode,
                "actual_pid": actual_pid,
                "actual_stopped": process_stopped(actual_pid) if actual_pid is not None else False,
                "forced": forced, "stopped": proc.poll() is not None,
                "reader_stopped": not reader.is_alive(), "stdout": first_line + stdout, "stderr": stderr})
            self.assertFalse(forced)
            self.assertFalse(reader.is_alive())
            self.assertEqual(proc.returncode, 0, stderr)
            self.assertTrue(process_stopped(actual_pid))

    def assert_fallback_releases_owners(self):
        original_rebuild = indexer.rebuild_index
        probes = []
        code = (
            "import json,os,sqlite3,sys\n"
            "from pathlib import Path\n"
            "from knowledgeos import indexer\n"
            "from knowledgeos.locking import file_lock\n"
            "vault=Path(sys.argv[1])\n"
            "with file_lock(vault/indexer.LOCK_REL,timeout=0.5):\n"
            " conn=sqlite3.connect(vault/indexer.DB_NAME,timeout=0.5)\n"
            " try:\n"
            "  conn.execute('BEGIN IMMEDIATE'); conn.rollback()\n"
            " finally:\n"
            "  conn.close()\n"
            "print(json.dumps({'ownership':'available','pid':os.getpid()}))\n")

        def inspected_rebuild(vault):
            command = [sys.executable, "-B", "-c", code, str(vault)]
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8")
            forced = False
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                forced = True
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
            observation = json.loads(stdout) if stdout else {}
            actual_pid = observation.pop("pid", None)
            actual_stopped = process_stopped(actual_pid) if isinstance(actual_pid, int) else False
            self.record("fallback-probe-" + str(proc.pid), {
                "command": command, "pid": proc.pid, "exit_code": proc.returncode,
                "actual_pid": actual_pid, "actual_stopped": actual_stopped,
                "forced": forced, "stopped": proc.poll() is not None, "stdout": stdout, "stderr": stderr})
            self.assertFalse(forced)
            self.assertEqual(proc.returncode, 0, stderr)
            self.assertTrue(actual_stopped)
            probes.append(observation)
            return original_rebuild(vault)

        with mock.patch.object(indexer, "rebuild_index", inspected_rebuild):
            result = self.capture()
        self.assertEqual(probes, [{"ownership": "available"}])
        self.assert_signed_source()
        return result

    def assert_signed_source(self):
        manifest = indexer.load_manifest(self.vault)
        self.assertIsNotNone(manifest)
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            self.assertEqual(manifest["index"], indexer.index_digest(conn))
        finally:
            conn.close()
        actual = self.row_type()
        self.record("signed-row", {"type": actual, "expected": "project", "manifest": manifest,
                                   "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()})
        self.assertEqual(actual, "project")
        self.assertEqual(indexer.manifest_diff(self.vault), (False, "fresh"))

    def test_prelock_edit_is_rederived_before_capture_signs(self):
        original_lock = indexer._rebuild_lock
        injected = []

        @contextlib.contextmanager
        def interleaved(vault):
            if not injected:
                injected.append(True)
                self.forge()
            with original_lock(vault):
                yield

        with mock.patch.object(indexer, "_rebuild_lock", interleaved):
            self.capture()
        self.assertEqual(injected, [True])
        self.assert_signed_source()

    def test_independent_writer_between_verified_digest_and_update_is_blocked(self):
        original_digest = indexer.index_digest
        attempts = []

        def interleaved(conn):
            value = original_digest(conn)
            if not attempts:
                attempts.append(self.competing_writer())
            return value

        with mock.patch.object(indexer, "index_digest", interleaved):
            self.capture()
        self.assert_signed_source()
        self.assertEqual(attempts, [{"status": "blocked", "error": "database is locked"}])

    def test_fallback_result_digest_excludes_independent_writer(self):
        self.remove_signed_digest()
        original_digest = indexer.index_digest
        attempts = []

        def interleaved(conn):
            if not attempts:
                attempts.append(self.competing_writer())
            return original_digest(conn)

        with mock.patch.object(indexer, "index_digest", interleaved):
            result = self.capture()
        self.assertEqual(result.get("rebuilt"), "no_signed_digest")
        self.assert_signed_source()
        self.assertEqual(attempts, [{"status": "blocked", "error": "database is locked"}])

    def test_fallback_reconcile_excludes_independent_orphan_insert(self):
        self.remove_signed_digest()
        original_paths = indexer._indexed_paths
        attempts = []

        def interleaved(cur):
            paths = original_paths(cur)
            if not attempts:
                attempts.append(self.competing_writer(
                    "INSERT INTO notes_fts(path,title,body,tags,description) "
                    "VALUES ('Projects/Phantom.md','Phantom','forgedglyph','','')"))
            return paths

        with mock.patch.object(indexer, "_indexed_paths", interleaved):
            self.capture()
        self.assert_signed_source()
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            phantom = conn.execute("SELECT path FROM notes_fts WHERE path='Projects/Phantom.md'").fetchall()
        finally:
            conn.close()
        self.assertEqual(phantom, [])
        self.assertEqual(attempts, [{"status": "blocked", "error": "database is locked"}])

    def test_waiting_capture_uses_legitimate_new_signed_authority(self):
        code = (
            "import contextlib,json,os,sys\n"
            "from pathlib import Path\n"
            "from knowledgeos import indexer\n"
            "vault=Path(sys.argv[1])\n"
            "original=indexer._rebuild_lock\n"
            "@contextlib.contextmanager\n"
            "def held(vault):\n"
            " with original(vault):\n"
            "  print(json.dumps({'status':'held','pid':os.getpid()}),flush=True)\n"
            "  assert sys.stdin.readline().strip()=='release'\n"
            "  (vault/'Projects/Peer.md').write_bytes(b'---\\ntype: project\\ntitle: Peer authority\\n---\\n\\npeertruthglyph\\n')\n"
            "  yield\n"
            "indexer._rebuild_lock=held\n"
            "print(json.dumps(indexer.rebuild_index(vault)))\n")
        original_lock = indexer._rebuild_lock
        attempted = threading.Event()
        finished = threading.Event()
        outputs = []
        failures = []

        @contextlib.contextmanager
        def waiting(vault):
            attempted.set()
            with original_lock(vault):
                yield

        def capture():
            try:
                outputs.append(self.capture("Waiting capture"))
            except BaseException as exc:
                failures.append(exc)
            finally:
                finished.set()

        before = (self.vault / indexer.MANIFEST_REL).read_bytes()
        worker = threading.Thread(target=capture, daemon=True)
        with self.held_process(code) as (holder, release):
            with mock.patch.object(indexer, "_rebuild_lock", waiting):
                started = time.monotonic()
                worker.start()
                try:
                    self.assertTrue(attempted.wait(timeout=10))
                    self.assertFalse(finished.wait(timeout=0.2))
                    self.assertIsNone(holder.poll())
                finally:
                    release()
                    worker.join(timeout=40)
                self.record("waiting-capture", {"holder_pid": holder.pid,
                            "worker_stopped": not worker.is_alive(),
                            "elapsed_seconds": time.monotonic() - started})
                self.assertFalse(worker.is_alive())
        if failures:
            raise failures[0]
        self.assertEqual(len(outputs), 1)
        self.assertNotEqual((self.vault / indexer.MANIFEST_REL).read_bytes(), before)
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            self.assertEqual(conn.execute("SELECT type,title FROM notes WHERE path='Projects/Peer.md'").fetchall(),
                             [("project", "Peer authority")])
            self.assertEqual(conn.execute("SELECT body FROM notes_fts WHERE path='Projects/Peer.md'").fetchall(),
                             [("peertruthglyph\n",)])
        finally:
            conn.close()
        self.assertIn("Projects/Peer.md", indexer.load_manifest(self.vault)["files"])
        self.assert_signed_source()

    def test_absent_digest_fallback_releases_lock_and_database(self):
        self.remove_signed_digest()
        self.assertEqual(self.assert_fallback_releases_owners().get("rebuilt"), "no_signed_digest")

    def test_invalid_manifest_fallback_releases_lock_and_database(self):
        path = self.vault / indexer.MANIFEST_REL
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["mac"] = "invalid-signature"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIsNone(indexer.load_manifest(self.vault))
        self.assertEqual(self.assert_fallback_releases_owners().get("rebuilt"), "no_signed_digest")

    def test_malformed_signed_digest_fallback_releases_lock_and_database(self):
        manifest = indexer.load_manifest(self.vault)
        manifest["index"] = "malformed-digest-input"
        indexer.save_manifest(self.vault, manifest)
        self.assertEqual(indexer.load_manifest(self.vault)["index"], "malformed-digest-input")
        self.assert_fallback_releases_owners()

    def test_mismatched_digest_fallback_releases_lock_and_database(self):
        self.forge()
        self.assertEqual(self.row_type(), "decision")
        self.assert_fallback_releases_owners()

    def test_busy_writer_keeps_durable_capture_and_idempotent_retry_indexes_it(self):
        code = (
            "import json,os,sqlite3,sys\n"
            "from pathlib import Path\n"
            "conn=sqlite3.connect(Path(sys.argv[1])/'knowledge_index.db',timeout=1)\n"
            "try:\n"
            " conn.execute('BEGIN IMMEDIATE')\n"
            " print(json.dumps({'status':'held','pid':os.getpid()}),flush=True)\n"
            " assert sys.stdin.readline().strip()=='release'\n"
            " conn.rollback()\n"
            "finally:\n"
            " conn.close()\n")
        before = self.rows()
        manifest = (self.vault / indexer.MANIFEST_REL).read_bytes()
        arguments = {"title": "Busy capture", "content": "busydurableglyph remains remembered.",
                     "request_id": "busy-capture-once"}
        with self.held_process(code):
            result = dispatch(self.api, "memory_capture", arguments)
            self.record("busy-capture", result)
            self.assertEqual(result.get("ok"), True, result)
            self.assertEqual(result.get("indexed"), False, result)
            self.assertIn("database is locked", result.get("index_error", ""))
            saved = self.vault / result["path"]
            raw = saved.read_bytes()
            self.assertIn(b"busydurableglyph remains remembered.", raw)
            self.assertEqual(self.rows(), before)
            self.assertEqual((self.vault / indexer.MANIFEST_REL).read_bytes(), manifest)
        retried = dispatch(self.api, "memory_capture", arguments)
        self.record("busy-retry", retried)
        self.assertEqual({key: retried.get(key) for key in ("ok", "indexed", "path")},
                         {"ok": True, "indexed": True, "path": result["path"]})
        self.assertEqual(saved.read_bytes(), raw)
        self.assertEqual(list((self.vault / "Inbox").glob("*.md")), [saved])
        self.assertEqual([row["path"] for row in dispatch(
            self.api, "memory_search", {"query": "busydurableglyph"})["ranked"]], [result["path"]])
        self.assert_signed_source()

    def test_partial_sql_mutation_rolls_back_and_idempotent_retry_converges(self):
        sql = (
            "CREATE TRIGGER reject_capture_links BEFORE INSERT ON links "
            "WHEN NEW.source LIKE 'Inbox/%' "
            "AND EXISTS(SELECT 1 FROM notes WHERE path=NEW.source) "
            "AND EXISTS(SELECT 1 FROM notes_fts WHERE path=NEW.source) "
            "BEGIN SELECT RAISE(ABORT,'capture failed after notes and fulltext mutation'); END;")
        self.record("rollback-fault", {"sql": sql})
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            conn.execute(sql)
            conn.commit()
        finally:
            conn.close()
        before = self.rows()
        manifest = (self.vault / indexer.MANIFEST_REL).read_bytes()
        arguments = {"title": "Rollback capture", "content": "rollbackdurableglyph is retained.",
                     "request_id": "rollback-capture-once"}
        result = dispatch(self.api, "memory_capture", arguments)
        self.record("rollback-capture", result)
        self.assertEqual(result.get("ok"), True, result)
        self.assertEqual(result.get("indexed"), False, result)
        self.assertIn("capture failed after notes and fulltext mutation", result.get("index_error", ""))
        saved = self.vault / result["path"]
        raw = saved.read_bytes()
        self.assertIn(b"rollbackdurableglyph is retained.", raw)
        self.assertEqual(self.rows(), before)
        self.assertEqual((self.vault / indexer.MANIFEST_REL).read_bytes(), manifest)
        self.record("rollback-observed", {"tables_restored": True, "manifest_unchanged": True,
                                          "capture_sha256": hashlib.sha256(raw).hexdigest()})
        conn = sqlite3.connect(self.vault / indexer.DB_NAME)
        try:
            conn.execute("DROP TRIGGER reject_capture_links")
            conn.commit()
        finally:
            conn.close()
        retried = dispatch(self.api, "memory_capture", arguments)
        self.record("rollback-retry", retried)
        self.assertEqual({key: retried.get(key) for key in ("ok", "indexed", "path")},
                         {"ok": True, "indexed": True, "path": result["path"]})
        self.assertEqual(saved.read_bytes(), raw)
        self.assertEqual(list((self.vault / "Inbox").glob("*.md")), [saved])
        self.assertEqual([row["path"] for row in dispatch(
            self.api, "memory_search", {"query": "rollbackdurableglyph"})["ranked"]], [result["path"]])
        self.assert_signed_source()

    def test_valid_capture_is_signed_and_searchable_without_rebuild(self):
        result = self.capture("Valid capture", "validcaptureglyph survives a restart.", request_id="valid-once")
        self.assertNotIn("rebuilt", result)
        self.assertEqual([row["path"] for row in dispatch(
            MemoryAPI(self.vault), "memory_search", {"query": "validcaptureglyph"})["ranked"]], [result["path"]])
        self.assert_signed_source()

    def existing_module(self, name):
        prefix = (__package__ + ".") if __package__ else ""
        importlib.import_module(prefix + "spec")
        return importlib.import_module(prefix + name)

    def run_existing_control(self, case_type, method):
        case = case_type(method)
        case.vault = self.vault
        case.root = self.root
        self.record("existing-" + method, {"method": case.id(),
                    "fixture": "existing test body on the focused source fixture; full init not exercised"})
        getattr(case, method)()

    def test_existing_typed_digest_scenario_on_focused_fixture(self):
        module = self.existing_module("spec.scenarios")
        fixture = self.existing_module("spec").Case(self.root, self.root / "state", self.vault)
        module.reads_digest_null_vs_none_text(fixture)
        self.record("existing-typed-digest", {"scenario": "reads.the_digest_tells_null_from_the_word_none",
                    "fixture": "scenario body unchanged; no full initialization"})

    def test_existing_full_byte_and_full_text_controls_on_focused_fixture(self):
        module = self.existing_module("test_core")
        (self.vault / "Research").mkdir()
        self.run_existing_control(module.IndexIntegrityTests, "test_a_huge_note_is_still_hash_checked")
        self.run_existing_control(module.DispatchRobustnessTests,
                                  "test_long_note_is_searchable_past_the_old_1mb_cap")

    def test_existing_capture_deletion_control_on_focused_fixture(self):
        (self.vault / "Inbox").mkdir()
        module = self.existing_module("test_core")
        self.run_existing_control(module.IndexIntegrityTests,
                                  "test_capture_does_not_leave_a_deleted_note_in_the_manifest")
        self.assert_signed_source()

    def test_existing_forgetting_control_on_focused_fixture(self):
        module = self.existing_module("test_privacy_policy")
        case = module.RememberingPolicyTests(
            "test_forgetting_preserves_source_and_blocks_literal_copies_and_retries")
        case.vault, case.root, case.api = self.vault, self.root, self.api
        self.record("existing-forgetting", {"method": case.id(),
                    "fixture": "existing test body on the focused source fixture; full init not exercised"})
        case.test_forgetting_preserves_source_and_blocks_literal_copies_and_retries()
        self.capture("Permitted after forgetting", "permittedafterforgetglyph stays available.")
        self.assert_signed_source()


if __name__ == "__main__":
    unittest.main(verbosity=2)
