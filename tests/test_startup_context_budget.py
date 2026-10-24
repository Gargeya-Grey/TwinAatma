"""Startup context stays within its wire budget without losing source evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get(
    "TWIN_STARTUP_BUDGET_ROOT",
    ROOT / "work/gc-artifacts/.knowledgeos/resume-claude-20261022/context-budget",
))
SELF = (
    "# Self\n\nSynthetic identity.\n\n"
    "## Operating Heuristics & Rules of Thumb\nUnknown.\n\n"
    "## Values Hierarchy\nUnknown.\n\n"
    "## Mental Models\nUnknown.\n\n"
    "## Anti-Goals\nUnknown.\n\n"
    "## Active Bets\nUnknown.\n\n"
    "## Drift Log\nNo history.\n"
)


class StartupContextBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = EVIDENCE / self._testMethodName / uuid.uuid4().hex
        self.vault = self.directory / "vault"
        (self.vault / "People").mkdir(parents=True)
        (self.vault / "Research").mkdir()
        (self.vault / "People/Self.md").write_bytes(SELF.encode("utf-8"))

    def tool(self, name, arguments):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "startup-context-budget-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": name, "arguments": arguments}},
        ]
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp",
                   "--vault", str(self.vault), "--framing", "ndjson"]
        env = dict(os.environ, PYTHONPATH=str(ROOT),
                   KNOWLEDGEOS_STATE_DIR=str(self.directory / "gate-state"))
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate(
                "".join(json.dumps(message) + "\n" for message in messages), timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        with (self.directory / "protocol.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "command": command, "requests": messages, "stdout": stdout,
                "stderr": stderr, "pid": process.pid, "exit_code": process.returncode,
                "stopped": process.poll() is not None,
            }) + "\n")
        self.assertEqual(process.returncode, 0, stderr)
        responses = {row["id"]: row for row in map(json.loads, stdout.splitlines())}
        self.assertEqual(responses[1]["result"]["serverInfo"]["name"], "knowledgeos-memory")
        result = responses[2]["result"]
        self.assertFalse(result.get("isError"), result)
        text = result["content"][0]["text"]
        return text, json.loads(text)

    def test_startup_fits_16_kib_without_dropping_ranked_evidence(self):
        sources = {}
        for number in range(8):
            path = f"Research/Juniper-archive-{number}.md"
            claim = f"Juniper archive lane {number} requires locally signed manifests."
            body = (f"# Juniper archive lane {number}\n\n" + "Neutral shelving inventory. " * 80
                    + claim + " " + "Neutral appendix. " * 80)
            (self.vault / path).write_bytes(body.encode("utf-8"))
            sources[path] = (body, claim)
        text, payload = self.tool("memory_session_start", {
            "task_hint": "Review Juniper archive lanes and locally signed manifests.",
            "session_id": "budget-evidence",
        })
        self.assertLessEqual(len(text.encode("utf-8")), 16384)
        self.assertEqual(payload["session_id"], "budget-evidence")
        self.assertIn("never edit Self.md", " ".join(payload["agent_must"]))
        self.assertIn("soft_prompt", payload)
        context = payload["context"]
        self.assertEqual(context["self"]["sections"]["heuristics"], "Unknown.")
        rows = context["relevant"]["ranked"]
        self.assertEqual({row["path"] for row in rows}, set(sources))
        for row in rows:
            body, claim = sources[row["path"]]
            self.assertIn(claim, row["excerpt"])
            self.assertEqual(row["sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())
            self.assertEqual(body[row["excerpt_start"]:row["excerpt_end"]], row["excerpt"])
            self.assertTrue(row["excerpt_truncated"])
        self.assertEqual((self.vault / "People/Self.md").read_bytes(), SELF.encode("utf-8"))

    def test_multilingual_startup_preserves_eight_attributed_passages(self):
        sources = {}
        for number in range(8):
            path = f"Research/Navigation-{number}.md"
            claim = f"Café voyage lane {number} retains handwritten manifests."
            body = "# Navigation\n\n" + "甲乙丙丁" * 900 + " " + claim + " " + "甲乙丙丁" * 900
            (self.vault / path).write_bytes(body.encode("utf-8"))
            sources[path] = (body, claim)
        text, payload = self.tool("memory_session_start", {
            "task_hint": "Review café voyage lanes and handwritten manifests.",
            "session_id": "budget-multilingual",
        })
        self.assertLessEqual(len(text.encode("utf-8")), 16384)
        rows = payload["context"]["relevant"]["ranked"]
        self.assertEqual({row["path"] for row in rows}, set(sources))
        for row in rows:
            body, claim = sources[row["path"]]
            self.assertIn(claim, row["excerpt"])
            self.assertEqual(row["sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())
            self.assertEqual(body[row["excerpt_start"]:row["excerpt_end"]], row["excerpt"])
            self.assertTrue(row["excerpt_truncated"])

    def test_large_identity_sections_are_attributed_and_explicitly_partial(self):
        headings = ["Operating Heuristics & Rules of Thumb", "Values Hierarchy",
                    "Mental Models", "Anti-Goals", "Active Bets", "Drift Log"]
        source = "# Self\n\n" + "\n\n".join(
            "## " + heading + "\n" + "Synthetic preference details. " * 200
            for heading in headings) + "\n"
        (self.vault / "People/Self.md").write_bytes(source.encode("utf-8"))
        self.tool("memory_session_start", {"session_id": "budget-earlier"})
        (self.vault / "Decisions").mkdir()
        (self.vault / "Decisions/Pilot.md").write_bytes(
            b"---\ntype: decision\ntitle: Courier pilot\noutcome_status: pending\n---\n# Pilot\n")
        text, payload = self.tool("memory_session_start", {
            "task_hint": "Review current preferences.", "session_id": "budget-identity",
        })
        self.assertLessEqual(len(text.encode("utf-8")), 16384)
        self.assertEqual(payload["session_id"], "budget-identity")
        self.assertIn("budget-earlier", [row["session_id"] for row in payload["unfinished_sessions"]])
        self.assertEqual(payload["soft_prompt"], "Quick check — how did “Courier pilot” turn out?")
        identity = payload["context"]["self"]
        self.assertEqual(identity["sha256"], hashlib.sha256(source.encode("utf-8")).hexdigest())
        self.assertTrue(payload["context"]["context_budget"]["truncated"])
        self.assertIn("memory_self_get", payload["context"]["context_budget"]["retrieve"])
        _, full = self.tool("memory_self_get", {})
        self.assertEqual(set(identity["sections"]), set(full["sections"]))
        for key, section in identity["sections"].items():
            extent = identity["section_excerpt_ranges"][key]
            self.assertEqual(section, full["sections"][key][extent["start"]:extent["end"]])
            self.assertEqual(extent["total_chars"], len(full["sections"][key]))
            self.assertTrue(extent["truncated"])
        self.assertEqual((self.vault / "People/Self.md").read_bytes(), source.encode("utf-8"))

    def test_large_project_list_retains_paths_and_discloses_omissions(self):
        (self.vault / "Projects").mkdir()
        for number in range(20):
            source = ("---\ntype: project\nstatus: active\nupdated: 2026-01-01\ntitle: "
                      + f"Project {number} " + "Synthetic project description " * 90
                      + "\n---\n# Project\n")
            (self.vault / f"Projects/Project-{number}.md").write_bytes(source.encode("utf-8"))
        text, payload = self.tool("memory_session_start", {"limit": 200, "session_id": "budget-lists"})
        self.assertLessEqual(len(text.encode("utf-8")), 16384)
        context = payload["context"]
        self.assertGreater(len(context["active_projects"]), 0)
        self.assertLessEqual(len(context["active_projects"]), 8)
        self.assertTrue(context["context_budget"]["truncated"])
        self.assertIn("memory_get_note", context["context_budget"]["retrieve"])
        for row in context["active_projects"]:
            _, note = self.tool("memory_get_note", {"path_or_id": row["path"]})
            self.assertTrue(note["frontmatter"]["title"].startswith(row["title"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
