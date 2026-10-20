"""Disk index operations preserve notes when SQLite paths are unsafe."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = Path(os.environ.get("TWIN_SQLITE_PRODUCT_ROOT", ROOT))
REAL_ROOT = Path(os.environ.get("TWIN_SQLITE_REAL_ROOT", ROOT))
BASE = Path(os.environ.get("TWIN_SQLITE_EVIDENCE_ROOT", ROOT / "work/gc-artifacts/.knowledgeos/database-safety-tests"))
SIDECARS = ("", "-wal", "-shm", "-journal")
REPORTS = ("check_alignment.py", "draft_weekly_synthesis.py", "experiment_dashboard.py",
           "refinement_report.py", "smoke_test.py", "weekly_data.py")


def sentinels():
    return {name: hashlib.sha256((REAL_ROOT / name).read_bytes()).hexdigest()
            if (REAL_ROOT / name).is_file() else None
            for name in ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}


class DatabaseSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = sentinels()
        cls.evidence = BASE / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        cls.evidence.mkdir(parents=True)
        cls.processes = []

    @classmethod
    def tearDownClass(cls):
        result = {"product": str(PRODUCT), "selected_root_sentinels_before": cls.before,
                  "selected_root_sentinels_after": sentinels(), "processes": cls.processes,
                  "all_started_processes_stopped": all(p["stopped"] for p in cls.processes)}
        (cls.evidence / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if cls.before != result["selected_root_sentinels_after"]:
            raise AssertionError("Selected real-vault sentinels changed")

    def command(self, vault, args, *, raw=False):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
                   KNOWLEDGEOS_STATE_DIR=str(vault.parent / "gate-state"))
        for name in ("PYTHONPATH", "PYTHONHOME", "KNOWLEDGEOS_VAULT", "VIRTUAL_ENV"):
            env.pop(name, None)
        argv = list(args) if raw else [sys.executable, "-B", *args]
        child = subprocess.Popen(argv, cwd=vault, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        timed_out = False
        try:
            stdout, stderr = child.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            stdout, stderr = child.communicate(timeout=15)
        record = {"argv": argv, "cwd": str(vault), "test": self._testMethodName,
                  "pid": child.pid, "exit_code": child.returncode, "stopped": child.poll() is not None,
                  "timed_out": timed_out}
        stem = self.evidence / ("command-%03d" % len(self.processes))
        self.processes.append(record)
        stem.with_suffix(".command.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        stem.with_suffix(".stdout.txt").write_text(stdout, encoding="utf-8")
        stem.with_suffix(".stderr.txt").write_text(stderr, encoding="utf-8")
        self.assertFalse(timed_out, stdout + stderr)
        return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)

    def fixture(self):
        vault = self.evidence / self._testMethodName / uuid.uuid4().hex[:8] / "vault"
        vault.mkdir(parents=True)
        for name in ("knowledgeos", "scripts", "Templates", ".cursor/hooks"):
            shutil.copytree(PRODUCT / name, vault / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "README.md", "pyproject.toml", "setup.py", "MANIFEST.in", "LICENSE",
                     "knowledgeos.config.example.json", "mcp.cursor.example.json"):
            shutil.copyfile(PRODUCT / name, vault / name)
        initialized = self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name",
                                            "Synthetic Owner", "--force", "--non-interactive"])
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        if not hasattr(self, "protected"):
            self.protected = {}
        self.protected[str(vault)] = {path.relative_to(vault).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in vault.rglob("*") if path.is_file() and path.suffix in (".py", ".md")}
        return vault

    def hardlink(self, source, destination):
        try:
            os.link(source, destination)
        except OSError as error:
            self.skipTest("Native hardlink setup unavailable: " + str(error))

    def symlink(self, source, destination, *, directory=False):
        try:
            destination.symlink_to(source, target_is_directory=directory)
        except OSError as error:
            self.skipTest("Native symlink setup unavailable: " + str(error))

    def target(self, vault, suffix):
        path = vault / ("knowledge_index.db" + suffix)
        if path.exists():
            path.rename(path.with_name(path.name + ".retained-before-probe"))
        return path

    def assert_refused(self, vault, result, before, target=None):
        self.assertEqual((vault / "People/Self.md").read_bytes(), before, result.stdout + result.stderr)
        changed = [name for name, digest in self.protected[str(vault)].items()
                   if not (vault / name).is_file() or hashlib.sha256((vault / name).read_bytes()).hexdigest() != digest]
        self.assertEqual(changed, [], "Source or note bytes changed")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Refusing", result.stdout + result.stderr)
        if target is not None:
            self.assertTrue(target.exists() or target.is_symlink(), "Unsafe entry was moved or removed")
        self.assertFalse(list(vault.glob("knowledge_index.db.corrupt-*")), "Unsafe entry was quarantined")

    def test_public_rebuild_refuses_hardlinked_shm(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        target = self.target(vault, "-shm")
        self.hardlink(vault / "People/Self.md", target)
        result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
        self.assert_refused(vault, result, original, target)

    def test_nominal_report_refuses_hardlinked_shm(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        target = self.target(vault, "-shm")
        self.hardlink(vault / "People/Self.md", target)
        result = self.command(vault, ["-c", "import runpy; runpy.run_path('scripts/weekly_data.py', run_name='__main__')"])
        self.assert_refused(vault, result, original, target)

    def test_every_public_database_entry_refuses_linked_sidecars(self):
        operations = {
            "state": "from knowledgeos.indexer import index_state; index_state('knowledge_index.db')",
            "schema": "from knowledgeos.indexer import index_schema_problem; index_schema_problem('knowledge_index.db')",
            "coverage": "from pathlib import Path; from knowledgeos.indexer import index_coverage_problem; index_coverage_problem(Path('.').resolve())",
            "manifest": "from pathlib import Path; from knowledgeos.indexer import manifest_diff; manifest_diff(Path('.').resolve())",
            "incremental": "from pathlib import Path; from knowledgeos.indexer import index_files; index_files('.', [Path('People/Self.md').resolve()])",
            "rebuild": "from knowledgeos.indexer import rebuild_index; rebuild_index('.')",
            "search": "from pathlib import Path; from knowledgeos.search import blended_search; blended_search(Path('knowledge_index.db'), 'Synthetic')",
            "memory_search": "from knowledgeos.memory import MemoryAPI; MemoryAPI('.').search('Synthetic')",
            "memory_decisions": "from knowledgeos.memory import MemoryAPI; MemoryAPI('.').decisions()",
            "doctor": "from pathlib import Path; from knowledgeos.doctor import run_doctor; raise SystemExit(run_doctor(Path('.')))",
        }
        for script in REPORTS:
            operations[script] = "import runpy; runpy.run_path('scripts/%s', run_name='__main__')" % script
        for name, code in operations.items():
            with self.subTest(entry=name):
                vault = self.fixture()
                original = (vault / "People/Self.md").read_bytes()
                outside = vault.parent / "outside-source.md"
                outside.write_bytes(b"PRESERVE EXTERNAL SOURCE\x00\xff")
                target = self.target(vault, "-shm")
                self.hardlink(outside, target)
                result = self.command(vault, ["-c", code])
                self.assert_refused(vault, result, original, target)
                self.assertEqual(outside.read_bytes(), b"PRESERVE EXTERNAL SOURCE\x00\xff")

    def test_all_database_and_sidecar_hardlinks_are_preserved(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix):
                vault = self.fixture()
                original = (vault / "People/Self.md").read_bytes()
                target = self.target(vault, suffix)
                self.hardlink(vault / "People/Self.md", target)
                result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
                self.assert_refused(vault, result, original, target)

    def test_all_database_and_sidecar_symlinks_are_preserved(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix):
                vault = self.fixture()
                original = (vault / "People/Self.md").read_bytes()
                target = self.target(vault, suffix)
                self.symlink(vault / "People/Self.md", target)
                result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
                self.assert_refused(vault, result, original, target)

    def test_dangling_sidecar_symlink_is_not_resolved_away(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        outside = vault.parent / "missing-external"
        target = self.target(vault, "-journal")
        self.symlink(outside, target)
        result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
        self.assert_refused(vault, result, original, target)
        self.assertFalse(outside.exists())

    def test_non_plain_database_and_sidecar_directories_are_preserved(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix):
                vault = self.fixture()
                original = (vault / "People/Self.md").read_bytes()
                target = self.target(vault, suffix)
                target.mkdir()
                (target / "unowned.bin").write_bytes(b"PRESERVE\x00\xff")
                result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
                self.assert_refused(vault, result, original, target)
                self.assertEqual((target / "unowned.bin").read_bytes(), b"PRESERVE\x00\xff")

    def test_database_ancestor_symlink_is_refused_before_resolution(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        alias = vault.parent / "linked-vault"
        self.symlink(vault, alias, directory=True)
        code = "from pathlib import Path; from knowledgeos.search import blended_search; blended_search(Path('../linked-vault/knowledge_index.db'), 'Synthetic')"
        result = self.command(vault, ["-c", code])
        self.assert_refused(vault, result, original, alias)

    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_database_ancestor_junction_is_refused_before_resolution(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        alias = vault.parent / "junction-vault"
        result = self.command(vault, ["cmd", "/c", "mklink", "/J", str(alias), str(vault)], raw=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        code = "from pathlib import Path; from knowledgeos.search import blended_search; blended_search(Path('../junction-vault/knowledge_index.db'), 'Synthetic')"
        result = self.command(vault, ["-c", code])
        self.assert_refused(vault, result, original, alias)

    @unittest.skipIf(os.name == "nt", "POSIX special-file boundary")
    def test_sidecar_fifo_is_refused_without_blocking(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        target = self.target(vault, "-shm")
        try:
            os.mkfifo(target)
        except OSError as error:
            self.skipTest("Native FIFO setup unavailable: " + str(error))
        result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
        self.assert_refused(vault, result, original, target)

    def test_ordinary_rebuild_search_and_capture_still_work(self):
        vault = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        result = self.command(vault, ["-c", "import json; from knowledgeos.memory import MemoryAPI; api=MemoryAPI('.'); print(json.dumps(api.capture('SQLite safety normal flow', 'The synthetic lighthouse is cobalt.')))"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("path", json.loads(result.stdout))
        result = self.command(vault, ["scripts/rebuild_index.py", "--vault", str(vault)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.command(vault, ["-c", "import json; from knowledgeos.memory import MemoryAPI; print(json.dumps(MemoryAPI('.').search('cobalt')))"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cobalt", result.stdout)
        self.assertEqual((vault / "People/Self.md").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
