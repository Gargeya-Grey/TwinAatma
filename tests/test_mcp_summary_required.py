"""Useful chat wrap-up must save a summary before closing through memory tools."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from support import ROOT, TempVaultCase

SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/host.py"
SPEC = importlib.util.spec_from_file_location("summary_host_driver", SCRIPT)
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)


class McpSummaryRequiredTests(TempVaultCase):
    def rpc(self, method, params):
        request = {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "summary-contract-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, request,
        ]
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp",
                   "--vault", str(self.vault), "--framing", "ndjson"]
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate("".join(json.dumps(m) + "\n" for m in messages), timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        evidence = os.environ.get("TA_SUMMARY_TEST_EVIDENCE")
        if evidence:
            with Path(evidence).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"command": command, "pid": process.pid,
                    "stopped": process.poll() is not None, "exit_code": process.returncode,
                    "requests": messages, "stdout": stdout, "stderr": stderr}) + "\n")
        self.assertEqual(process.returncode, 0, stderr)
        responses = {row["id"]: row for row in map(json.loads, stdout.splitlines())}
        self.assertEqual(responses[1]["result"]["serverInfo"]["name"], "knowledgeos-memory")
        return responses[2]["result"]

    def tool(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        return result, json.loads(result["content"][0]["text"])

    def test_discovered_wrap_schema_requires_a_nonempty_summary(self):
        result = self.rpc("tools/list", {})
        spec = next(row for row in result["tools"] if row["name"] == "memory_session_end")
        self.assertIn("summary", spec["inputSchema"].get("required", []))
        self.assertEqual(spec["inputSchema"]["properties"]["summary"]["minLength"], 1)

    def test_missing_and_blank_summary_leave_chat_open_until_idempotent_valid_retry(self):
        for label, invalid in (("missing", {}), ("empty", {"summary": ""}),
                               ("whitespace", {"summary": " \t\n "})):
            with self.subTest(label=label):
                session_id = "summary-" + label
                self.tool("memory_session_start", {"session_id": session_id})
                state_path = self.vault / ".knowledgeos/autopilot.json"
                before = state_path.read_bytes()
                notes_before = set((self.vault / "Inbox").glob("capture-*.md"))
                result, payload = self.tool("memory_session_end", {"session_id": session_id, **invalid})
                self.assertTrue(result.get("isError"), payload)
                self.assertEqual(payload.get("missing"), ["summary"])
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(set((self.vault / "Inbox").glob("capture-*.md")), notes_before)
                self.assertEqual(json.loads(before)["sessions"][session_id]["status"], "open")
                arguments = {"session_id": session_id, "summary": "Verified durable " + label + " outcome."}
                _, ended = self.tool("memory_session_end", arguments)
                _, replayed = self.tool("memory_session_end", arguments)
                self.assertTrue(ended["captured"]["ok"], ended)
                self.assertEqual(ended, replayed)
                new_notes = set((self.vault / "Inbox").glob("capture-*.md")) - notes_before
                self.assertEqual(new_notes, {self.vault / ended["captured"]["path"]})
                self.assertIn(arguments["summary"], next(iter(new_notes)).read_text(encoding="utf-8"))
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["sessions"][session_id]["status"], "ended")

    def test_direct_api_allows_an_empty_compatibility_wrap(self):
        api = self.api()
        api.session_start(session_id="direct-empty")
        result = api.session_end(session_id="direct-empty")
        self.assertNotIn("error", result)
        self.assertIsNone(result["captured"])

    def test_cli_memory_alias_refuses_empty_wrap_without_closing(self):
        self.tool("memory_session_start", {"session_id": "cli-empty"})
        state_path = self.vault / ".knowledgeos/autopilot.json"
        before = state_path.read_bytes()
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "memory", "memory_session_end",
                   "--vault", str(self.vault), "--args", json.dumps({"session_id": "cli-empty"})]
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate(timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        evidence = os.environ.get("TA_SUMMARY_TEST_EVIDENCE")
        if evidence:
            with Path(evidence).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"command": command, "pid": process.pid,
                    "stopped": process.poll() is not None, "exit_code": process.returncode,
                    "stdout": stdout, "stderr": stderr}) + "\n")
        self.assertEqual(process.returncode, 1, stdout + stderr)
        self.assertEqual(json.loads(stdout).get("missing"), ["summary"])
        self.assertEqual(state_path.read_bytes(), before)

    def test_summaryless_hook_retains_unfinished_work_without_inventing_an_episode(self):
        self.tool("memory_session_start", {"session_id": "hook-empty"})
        notes_before = set((self.vault / "Inbox").glob("capture-*.md"))
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "hook", "twin_session_end",
                   "--vault", str(self.vault)]
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate(json.dumps({"memory_session_id": "hook-empty"}), timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        evidence = os.environ.get("TA_SUMMARY_TEST_EVIDENCE")
        if evidence:
            with Path(evidence).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"command": command, "pid": process.pid,
                    "stopped": process.poll() is not None, "exit_code": process.returncode,
                    "stdout": stdout, "stderr": stderr}) + "\n")
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(json.loads(stdout), {})
        state = json.loads((self.vault / ".knowledgeos/autopilot.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["hook-empty"]["status"], "orphaned")
        self.assertEqual(state.get("sessions_completed", 0), 0)
        self.assertEqual(set((self.vault / "Inbox").glob("capture-*.md")), notes_before)


class SummaryGraderTests(TempVaultCase):
    def grade(self, receipt, *, path_case=None, summary_case=None):
        run = HOST.HostRun(self.root / "host-cases", "codex")
        run.vault.mkdir()
        (run.vault / "Inbox").mkdir()
        (run.vault / "People").mkdir()
        (run.vault / "People/Self.md").write_text("Synthetic unchanged identity\n", encoding="utf-8")
        run.identity = HOST.sha(run.vault / "People/Self.md")
        (run.vault / "Inbox/packing.md").write_text("The cabin luggage allowance is 7 kg.\n", encoding="utf-8")
        summary_text = lambda label: "A real synthetic " + label + " summary."
        for label in ("capture", "recall", "parallel"):
            (run.vault / ("Inbox/summary-" + label + ".md")).write_text(
                "# Session\n\n## Session summary\n\n" + summary_text(label) + "\n", encoding="utf-8")
        if path_case:
            outside = run.vault.parent / "outside-summary.md"
            outside.write_text("## Session summary\n\n" + summary_text("parallel") + "\n", encoding="utf-8")
            if path_case == "absolute": receipt = {"ok": True, "path": str(outside)}
            elif path_case == "parent": receipt = {"ok": True, "path": "../outside-summary.md"}
            elif path_case == "identity": receipt = {"ok": True, "path": "People/Self.md"}
            elif path_case == "hardlink":
                linked = run.vault / "Inbox/linked-summary.md"
                os.link(outside, linked)
                receipt = {"ok": True, "path": "Inbox/linked-summary.md"}
            elif path_case == "symbolic":
                linked = run.vault / "Inbox/linked-summary.md"
                try: linked.symlink_to(outside)
                except OSError as error: self.skipTest("Native symlink setup unavailable: " + str(error))
                receipt = {"ok": True, "path": "Inbox/linked-summary.md"}
            elif path_case == "duplicate": receipt = {"ok": True, "path": "Inbox/summary-capture.md"}
            else: raise AssertionError(path_case)
        (run.vault / ".knowledgeos").mkdir()
        state = {"sessions": {key: {"status": "ended"} for key in ("capture", "recall", "parallel")}}
        (run.vault / ".knowledgeos/autopilot.json").write_text(json.dumps(state), encoding="utf-8")
        chats = []
        for label in ("capture", "recall", "parallel"):
            calls = [{"name": "memory_session_start", "ok": True, "arguments": {},
                      "payload": {"session_id": label}}]
            if label == "capture":
                calls.append({"name": "memory_capture", "ok": True, "arguments": {},
                              "payload": {"ok": True, "path": "Inbox/packing.md"}})
            if label == "recall":
                calls.append({"name": "memory_search", "ok": True, "arguments": {},
                              "payload": {"ranked": [{"path": "Inbox/packing.md"}]}})
            calls.append({"name": "memory_session_end", "ok": True,
                          "arguments": {"session_id": label, "summary": summary_text(label)}, "payload": {
                              "session_id": label, "captured": receipt if label == "parallel" else {
                                  "ok": True, "path": "Inbox/summary-" + label + ".md"}}})
            if label == "parallel" and summary_case == "different":
                calls[-1]["arguments"]["summary"] = "This different outcome was never saved."
            elif label == "parallel" and summary_case == "missing":
                calls[-1]["arguments"].pop("summary")
            elif label == "parallel" and summary_case == "blank":
                calls[-1]["arguments"]["summary"] = " \t\n "
            answer = "Your cabin luggage allowance is 7 kg. Source Inbox/packing.md. I do not know your shoe size."
            chats.append({"exit_code": 0, "calls": calls, "evidence": [], "events": [],
                          "wire": [{"kind": "request", "message": {"method": "tools/list"}}], "answer": answer})
        run.grade(chats)
        return {row["id"]: row for row in run.cases}

    def test_missing_or_malformed_summary_is_a_failure_and_later_cases_still_run(self):
        invalid = [None, False, [], ["bad"], "bad", {}, {"ok": True},
                   {"ok": True, "path": None}, {"ok": True, "path": []},
                   {"ok": True, "path": ""}, {"ok": True, "path": "missing.md"},
                   {"ok": True, "path": "\0"}]
        for receipt in invalid:
            with self.subTest(receipt=receipt):
                cases = self.grade(receipt)
                self.assertEqual(len(cases), 10)
                self.assertEqual(cases["host.summary_persisted"]["verdict"], "FAIL")
                self.assertEqual(cases["host.no_user_ops"]["verdict"], "PASS")
                self.assertEqual(cases["host.identity_unchanged"]["verdict"], "PASS")

    def test_valid_summary_receipts_keep_the_complete_journey_passing(self):
        cases = self.grade({"ok": True, "path": "Inbox/summary-parallel.md"})
        self.assertEqual(len(cases), 10)
        self.assertEqual({row["verdict"] for row in cases.values()}, {"PASS"})


    def assert_summary_failure(self, **arguments):
        cases = self.grade({"ok": True, "path": "Inbox/summary-parallel.md"}, **arguments)
        self.assertEqual(len(cases), 10)
        self.assertEqual(cases["host.summary_persisted"]["verdict"], "FAIL")
        self.assertEqual(cases["host.identity_unchanged"]["verdict"], "PASS")

    def test_summary_receipt_cannot_name_an_absolute_foreign_file(self):
        self.assert_summary_failure(path_case="absolute")

    def test_summary_receipt_cannot_escape_with_parent_components(self):
        self.assert_summary_failure(path_case="parent")

    def test_identity_is_not_a_session_summary(self):
        self.assert_summary_failure(path_case="identity")

    def test_hardlinked_summary_is_not_owned_persistence(self):
        self.assert_summary_failure(path_case="hardlink")

    def test_symbolic_summary_is_not_owned_persistence(self):
        self.assert_summary_failure(path_case="symbolic")

    def test_wrap_must_persist_its_exact_submitted_summary(self):
        self.assert_summary_failure(summary_case="different")

    def test_missing_or_blank_summary_arguments_are_not_evidence(self):
        for case in ("missing", "blank"):
            with self.subTest(case=case):
                self.assert_summary_failure(summary_case=case)

    def test_distinct_chats_cannot_share_one_summary_receipt(self):
        self.assert_summary_failure(path_case="duplicate")


if __name__ == "__main__":
    unittest.main()
