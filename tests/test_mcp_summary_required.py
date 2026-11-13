"""Useful chat wrap-up must save a summary before closing through memory tools."""
import json
import os
import subprocess
import sys
import unittest

from support import ROOT, TempVaultCase


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
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(json.loads(stdout), {})
        state = json.loads((self.vault / ".knowledgeos/autopilot.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["hook-empty"]["status"], "orphaned")
        self.assertEqual(state.get("sessions_completed", 0), 0)
        self.assertEqual(set((self.vault / "Inbox").glob("capture-*.md")), notes_before)


if __name__ == "__main__":
    unittest.main()
