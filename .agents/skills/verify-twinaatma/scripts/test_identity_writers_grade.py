"""Focused grader rejection controls; these never invoke product memory operations."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import sys
import subprocess
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import identity_writers_grade as grade
import writer_census as census
from writer_contract import expected_case_ids, normal_calls, RUNTIME_OBSERVER

OUTPUT = None


def row(raw=b"fixture", links=1):
    return {"kind": "file", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "links": links}


def snapshot():
    return {"vault/People/Self.md": row(), "vault/People/Self-Proposals/pending.md": row(b"pending"),
            "vault/People/Self-Proposals/rejected.md": row(b"rejected")}


class RejectionControls(unittest.TestCase):
    def test_current_read_only_census_is_complete(self):
        found = census.read_census(grade.ROOT)
        self.assertEqual(set(found["files"]), set(census.FILE_ROLES))
        self.assertEqual(len(found["memory_tools"]), 24)
        self.assertTrue(found["mutation_sites"])
        self.assertEqual(set(tool for tool, _ in normal_calls()), set(found["memory_tools"]) - {"memory_accept_self_update", "memory_reject_self_update"})

    def test_missing_source_classification_is_rejected(self):
        changed = dict(census.FILE_ROLES)
        changed.pop("knowledgeos/memory.py")
        with patch.object(census, "FILE_ROLES", changed):
            with self.assertRaisesRegex(ValueError, "Unreviewed source-surface"):
                census.read_census(grade.ROOT)

    def test_new_mutation_sink_is_discovered(self):
        for text in ("path.write_bytes(payload)", "os.open(path, os.O_CREAT | os.O_WRONLY)", "connection.execute('DELETE FROM notes')"):
            node = ast.parse(text).body[0].value
            self.assertIsNotNone(census.mutating_call(node))

    def test_self_change_cannot_hide_behind_pass_flags(self):
        before, after = snapshot(), snapshot()
        after["vault/People/Self.md"] = dict(row(b"hidden change"), verdict="PASS")
        with self.assertRaisesRegex(ValueError, "Protected Self"):
            grade.preserved_identity(before, after)

    def test_pending_or_rejected_history_change_is_rejected(self):
        for name in ("pending", "rejected"):
            before, after = snapshot(), snapshot()
            after["vault/People/Self-Proposals/" + name + ".md"] = row(b"changed")
            with self.assertRaisesRegex(ValueError, "proposal history changed"):
                grade.preserved_identity(before, after)

    def test_missing_identity_is_not_an_empty_success(self):
        before, after = snapshot(), snapshot()
        after.pop("vault/People/Self.md")
        with self.assertRaisesRegex(ValueError, "Protected Self"):
            grade.preserved_identity(before, after)

    def test_alias_seed_cannot_authorize_a_runtime_link_change(self):
        before, after = snapshot(), snapshot()
        after["vault/People/Self.md"]["links"] = 2
        with self.assertRaisesRegex(ValueError, "Protected Self"):
            grade.preserved_identity(before, after)
        after["vault/People/Self.md"] = row(b"changed", links=2)
        with self.assertRaisesRegex(ValueError, "Protected Self"):
            grade.preserved_identity(before, after, expected_self_links=2)

    def test_safe_manifest_detach_requires_unchanged_original_inode_and_bytes(self):
        before = snapshot()
        before["vault/People/Self.md"]["links"] = 2
        before["vault/.knowledgeos/index-manifest.json"] = row(links=2)
        after = copy.deepcopy(before)
        after["vault/People/Self.md"]["links"] = 1
        after["vault/.knowledgeos/index-manifest.json"] = row(b"fresh manifest")
        original = dict(row(links=2), device=1, inode=10)
        detached = dict(row(b"fresh manifest"), device=1, inode=20)
        initial = {"self": original, "alias_relative": "vault/.knowledgeos/index-manifest.json", "alias": dict(original)}
        final = {"self": dict(original, links=1), "alias_relative": initial["alias_relative"], "alias": detached}
        self.assertEqual(grade.manifest_detach("hard-index-manifest", before, after, initial, final), detached)
        for key, value in (("inode", 11), ("device", 2), ("size", 0), ("sha256", "0" * 64), ("links", 2), ("links", 3)):
            changed = copy.deepcopy(final)
            changed["self"][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "Original Self"):
                grade.manifest_detach("hard-index-manifest", before, after, initial, changed)
        for key, value in (("inode", 10), ("links", 2)):
            changed = copy.deepcopy(final)
            changed["alias"][key] = value
            with self.subTest(alias_key=key), self.assertRaises(ValueError):
                grade.manifest_detach("hard-index-manifest", before, after, initial, changed)
        with self.assertRaisesRegex(ValueError, "Protected Self"):
            grade.preserved_identity(before, after)

        changed = copy.deepcopy(initial)
        changed["self"]["links"] = 3
        changed["alias"]["links"] = 3
        with self.assertRaisesRegex(ValueError, "unexpected original Self link count"):
            grade.manifest_detach("hard-index-manifest", before, after, changed, final)

    def test_safe_detach_audit_rejects_extra_writes_or_replacements(self):
        original = dict(row(links=2), device=1, inode=10)
        detached = dict(row(b"fresh manifest"), device=1, inode=20)
        observed = {key: original[key] for key in ("device", "inode", "size", "links", "sha256")}
        new_file = {key: detached[key] for key in ("device", "inode", "size", "links", "sha256")}
        fixture = {"scope": "/synthetic", "vault": "/synthetic/vault"}
        start = {"pid": 123, "self_path": "/synthetic/vault/People/Self.md", "self": observed}
        event = {"pid": 123, "event": "os.rename", "paths": [
            {"path": "/synthetic/vault/.knowledgeos/.gate-write-probe.tmp", "protected": False, "identity": new_file},
            {"path": "/synthetic/vault/.knowledgeos/index-manifest.json", "protected": True, "identity": observed}]}
        prefix = "IDENTITY_RUNTIME_START=" + json.dumps({"pid": 123}) + "\nIDENTITY_PROTECTED_AUDIT_START=" + json.dumps(start) + "\n"
        audit = "IDENTITY_PROTECTED_IO=" + json.dumps(event) + "\n"
        grade.protected_io(prefix + audit, {"pid": 123}, fixture, original, detach=detached)
        with self.assertRaises(ValueError):
            grade.protected_io(prefix + audit + audit, {"pid": 123}, fixture, original, detach=detached)
        with self.assertRaises(ValueError):
            grade.protected_io(prefix + audit.replace('"os.rename"', '"open"'), {"pid": 123}, fixture, original, detach=detached)
        with self.assertRaisesRegex(ValueError, "hidden write"):
            grade.protected_io(prefix + audit, {"pid": 123}, fixture, original)

    def test_physical_hidden_change_is_rejected(self):
        directory = OUTPUT / "physical-hidden-change"
        directory.mkdir()
        path = directory / "Self.md"
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "physical bytes disagree"):
            grade.physical_regular(path, row(b"fixture"))

    def test_escaped_evidence_is_rejected(self):
        for name in ("../report.json", "/tmp/report.json", "folder/../report.json", "C:/report.json", "folder\\report.json"):
            with self.assertRaises(ValueError):
                grade.plain_file(OUTPUT, name)

    def test_missing_and_extra_cases_have_no_full_coverage(self):
        nt, posix = expected_case_ids("nt"), expected_case_ids("posix")
        self.assertTrue(nt < posix)
        self.assertNotEqual(nt - {"writers.normal-tools"}, nt)
        self.assertNotEqual(nt | {"writers.hand-authored-pass"}, nt)

    def test_actual_protocol_refusal_cannot_claim_success(self):
        directory = OUTPUT / "protocol-mismatch"
        directory.mkdir()
        role = "example"
        calls = [("memory_self_get", {})]
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-identity", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_self_get", "arguments": {}}}]
        (directory / (role + ".requests.json")).write_text(json.dumps(requests), encoding="utf-8")
        responses = [{"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "knowledgeos-memory"}}},
                     {"jsonrpc": "2.0", "id": 2, "result": {"isError": False, "content": [{"type": "text", "text": json.dumps({"ok": False, "error": "synthetic refusal"})}]}}]
        (directory / (role + ".stdout.txt")).write_text("\n".join(json.dumps(r) for r in responses), encoding="utf-8")
        evidence = {p.name: grade.sha(p) for p in directory.iterdir()}
        with self.assertRaisesRegex(ValueError, "isError contradicts"):
            grade.parse_rpc(directory, evidence, role, calls)

    def test_nested_index_blocking_requires_explicit_public_refusal_fields(self):
        result = {"is_error": False, "payload": {"freshness": {"blocked": True, "error": "IndexLockUnusable: synthetic alias"},
                  "context": {"index_frozen": True, "index_blocked": "IndexLockUnusable: synthetic alias"}}}
        self.assertTrue(grade.alias_refused(result))
        for key in ("index_frozen", "index_blocked"):
            changed = copy.deepcopy(result)
            changed["payload"]["context"].pop(key)
            self.assertFalse(grade.alias_refused(changed))
        for key in ("blocked", "error"):
            changed = copy.deepcopy(result)
            changed["payload"]["freshness"].pop(key)
            self.assertFalse(grade.alias_refused(changed))
        self.assertFalse(grade.alias_refused({"is_error": False, "payload": {"ok": True}}))

    def test_runtime_audit_observes_writes_even_when_original_bytes_are_restored(self):
        directory = (OUTPUT / "runtime-write-restore").absolute()
        vault = directory / "vault"
        (vault / "People").mkdir(parents=True)
        identity = vault / "People/Self.md"
        identity.write_bytes(b"synthetic audit identity")
        (directory / "sitecustomize.py").write_text(RUNTIME_OBSERVER, encoding="utf-8")
        before = grade.physical(identity)
        operation = "from pathlib import Path\np = Path(" + repr(str(identity)) + ")\np.write_bytes(b'changed')\np.write_bytes(b'synthetic audit identity')"
        command = [sys.executable, "-B", "-P", "-c", operation]
        env = dict(os.environ, PYTHONPATH=str(directory), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", KNOWLEDGEOS_VAULT=str(vault))
        child = subprocess.Popen(command, cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = child.communicate(timeout=30)
        except BaseException:
            child.kill()
            child.communicate()
            raise
        record = {"pid": child.pid, "command": command, "exit_code": child.returncode, "stopped": child.poll() is not None}
        (directory / "audit.command.json").write_text(json.dumps(record), encoding="utf-8")
        (directory / "audit.stdout.txt").write_text(stdout, encoding="utf-8")
        (directory / "audit.stderr.txt").write_text(stderr, encoding="utf-8")
        self.assertEqual(child.returncode, 0)
        self.assertEqual(grade.physical(identity), before)
        with self.assertRaisesRegex(ValueError, "hidden write"):
            grade.protected_io(stderr, record, {"vault": str(vault), "scope": str(directory)}, before)

    def test_runtime_observer_binds_real_pid_and_original_argv(self):
        directory = (OUTPUT / "runtime-observer").absolute()
        directory.mkdir()
        (directory / "sitecustomize.py").write_text(RUNTIME_OBSERVER, encoding="utf-8")
        command = [sys.executable, "-B", "-P", "-c", "print('RUNTIME_OBSERVER_UNIT')"]
        env = dict(os.environ, PYTHONPATH=str(directory), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        started = time.monotonic()
        child = subprocess.Popen(command, cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = child.communicate(timeout=30)
        except BaseException:
            child.kill()
            child.communicate()
            raise
        self.assertEqual(child.returncode, 0)
        role = "runtime-observer"
        record = {"pid": child.pid, "command": command, "exit_code": child.returncode, "stopped": child.poll() is not None,
                  "shell": False, "error": None, "seconds": time.monotonic() - started, "import_path": str(directory), "state_dir": str(directory / "state")}
        (directory / (role + ".command.json")).write_text(json.dumps(record), encoding="utf-8")
        (directory / (role + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (directory / (role + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        evidence = {p.name: grade.sha(p) for p in directory.iterdir() if p.name != "sitecustomize.py"}
        class LocalBase:
            @staticmethod
            def data_repository_location(value):
                return Path(value).relative_to(grade.ROOT).as_posix()
        data = {"producer_pid": os.getpid(), "all_started_processes_stopped": True,
                "processes": [{"pid": child.pid, "role": role, "stopped": child.poll() is not None, "exit_code": child.returncode}]}
        self.assertIn(role, grade.checked_processes(data, directory, evidence, LocalBase))
        changed = copy.deepcopy(data)
        changed["processes"][0]["pid"] += 100000000
        with self.assertRaisesRegex(ValueError, "receipt disagrees"):
            grade.checked_processes(changed, directory, evidence, LocalBase)


def actual_report_rejections(report):
    base = grade.support_module("acceptance.py")
    data = grade.read(report)
    grade.focus_report(report, base)
    controls = []
    changes = {
        "wrong_scope": lambda d: d.update(scope="installed distribution"),
        "wrong_source": lambda d: d["product_hashes"].update({"knowledgeos/memory.py": "0" * 64}),
        "stale_producer": lambda d: d.update(producer_sha256="0" * 64),
        "missing_writer": lambda d: d["cases"].pop(),
        "fabricated_pid": lambda d: d["processes"][0].update(pid=d["processes"][0]["pid"] + 100000000),
        "changed_transcript_digest": lambda d: d["evidence_files"].update({next(n for n in d["evidence_files"] if n.endswith(".stdout.txt")): "0" * 64}),
    }
    for name, mutation in changes.items():
        changed = copy.deepcopy(data)
        mutation(changed)
        try:
            grade.focus_report(report, base, data_override=changed)
        except (ValueError, KeyError, OSError, TypeError) as error:
            controls.append({"id": name, "rejected": True, "reason": str(error)})
        else:
            controls.append({"id": name, "rejected": False})
    if not all(r["rejected"] for r in controls):
        raise AssertionError("A malformed actual writer report was accepted")
    return controls


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actual-report", type=Path)
    args = parser.parse_args()
    source_paths = [grade.HERE / name for name in ("identity_writers.py", "identity_writers_grade.py", "writer_census.py", "writer_contract.py", "physical_observer.py", "test_identity_writers_grade.py")]
    source_paths.append(grade.VERIFY / "acceptance.py")
    source_hashes = {str(path): grade.sha(path) for path in source_paths}
    actual_hash = grade.sha(args.actual_report) if args.actual_report else None
    OUTPUT = args.output / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    OUTPUT.mkdir(parents=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RejectionControls)
    with (OUTPUT / "unittest.txt").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    actual, actual_error = [], None
    try:
        actual = actual_report_rejections(args.actual_report) if args.actual_report else []
    except (AssertionError, ValueError, KeyError, OSError, TypeError) as error:
        actual_error = {"type": type(error).__name__, "message": str(error)}
    stable = all(grade.sha(path) == digest for path, digest in source_hashes.items())
    stable = stable and (args.actual_report is None or grade.sha(args.actual_report) == actual_hash)
    report = {"producer": "verify-twinaatma.identity-writers-grader-controls/v1", "pid": os.getpid(), "command": [sys.executable, *sys.argv],
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "verification_sources_sha256": source_hashes, "verification_sources_and_input_unchanged": stable,
              "actual_report": str(args.actual_report.absolute()) if args.actual_report else None, "actual_report_sha256": actual_hash,
              "actual_report_rejections": actual, "actual_report_error": actual_error,
              "verdict": "PASS" if result.wasSuccessful() and actual_error is None and stable else "FAIL",
              "scope": "grader rejection controls; no product memory operations or acceptance credit", "output": str(OUTPUT)}
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str((OUTPUT / "report.json").absolute()), "pid": report["pid"],
                      "verdict": report["verdict"], "tests_run": result.testsRun,
                      "actual_report_rejections": len(actual), "actual_report_error": actual_error,
                      "verification_sources_and_input_unchanged": stable}))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
