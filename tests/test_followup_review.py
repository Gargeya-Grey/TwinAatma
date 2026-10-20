"""Human follow-ups require explicit review intent through public CLI and MCP."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

TOOLKIT = Path(__file__).absolute().parents[1]
EVIDENCE = Path(os.environ.get("TWIN_FOLLOWUP_EVIDENCE",
                              TOOLKIT / "work/gc-artifacts/.knowledgeos/followup-review-controls"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FollowupReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = EVIDENCE / uuid.uuid4().hex[:8]
        self.directory.mkdir(parents=True)
        (self.directory / "test-id.txt").write_text(self.id(), encoding="utf-8")
        self.vault = self.directory / "vault"
        self.processes = []
        self.sources = {}
        self.env = dict(os.environ, PYTHONPATH=str(TOOLKIT), PYTHONIOENCODING="utf-8",
                        PYTHONDONTWRITEBYTECODE="1", KNOWLEDGEOS_VAULT=str(self.vault),
                        KNOWLEDGEOS_STATE_DIR=str(self.directory / "state"))
        self.env.pop("KNOWLEDGEOS_GATE_KEY", None)
        result = self.cli("init", str(self.vault), "--name", "Synthetic follow-up fixture", "--non-interactive")
        self.assertTrue(result["ok"], result)
        self.self_hash = sha(self.vault / "People/Self.md")

    def tearDown(self):
        if hasattr(self, "self_hash"):
            self.assertEqual(sha(self.vault / "People/Self.md"), self.self_hash)
        for relative, digest in self.sources.items():
            self.assertEqual(sha(self.vault / relative), digest)
        self.assertTrue(all(row["stopped"] for row in self.processes))
        (self.directory / "processes.json").write_text(json.dumps(self.processes, indent=2), encoding="utf-8")

    def record(self, value):
        with (self.directory / "transcript.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")

    def execute(self, command, text=""):
        started = time.time_ns()
        child = subprocess.Popen(command, cwd=self.directory, env=self.env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8")
        try:
            stdout, stderr = child.communicate(text, timeout=90)
        except BaseException:
            child.kill()
            child.communicate()
            raise
        finally:
            self.processes.append({"command": command, "pid": child.pid,
                                   "started_ns": started, "stopped_ns": time.time_ns(),
                                   "exit_code": child.returncode, "stopped": child.poll() is not None})
        self.record(dict(self.processes[-1], stdout=stdout, stderr=stderr, stdin=text))
        self.assertEqual(child.returncode, 0, stderr)
        return stdout

    def cli(self, *arguments):
        return json.loads(self.execute([sys.executable, "-B", "-P", "-m", "knowledgeos", *arguments]))

    def tool(self, name, **arguments):
        messages = [dict(jsonrpc="2.0", id=1, method="initialize", params={
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "followup-review-regression", "version": "1"}}),
            dict(jsonrpc="2.0", method="notifications/initialized"),
            dict(jsonrpc="2.0", id=2, method="tools/call", params={"name": name, "arguments": arguments})]
        stdout = self.execute([sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp",
                               "--vault", str(self.vault), "--framing", "ndjson"],
                              "".join(json.dumps(row) + "\n" for row in messages))
        responses = {row["id"]: row for row in map(json.loads, stdout.splitlines())}
        self.assertEqual(responses[1]["result"]["serverInfo"]["name"], "knowledgeos-memory")
        result = responses[2]["result"]
        self.assertFalse(result.get("isError"), result)
        value = json.loads(result["content"][0]["text"])
        self.assertNotIn("error", value)
        return value

    def decision(self, name="RoleBoundaries", extra="", title="Role boundaries"):
        relative = "Decisions/" + name + ".md"
        path = self.vault / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("---\ntype: decision\ntitle: " + title + "\nstatus: active\n"
                        "created: 2026-06-18\nupdated: 2026-06-18\n" + extra +
                        "---\n# Synthetic decision\nLilacboundarytoken describes enduring role boundaries.\n",
                        encoding="utf-8")
        self.sources[relative] = sha(path)
        return relative

    def test_unscheduled_policy_remains_discoverable_without_requesting_a_review(self):
        relative = self.decision()
        start = self.tool("memory_session_start", task_hint="Continue engineering", session_id="ordinary-policy")
        ops = self.cli("memory", "memory_ops_status", "--vault", str(self.vault), "--args", "{}")
        with self.subTest("no-premature-question"):
            self.assertIsNone(start["soft_prompt"])
        with self.subTest("no-human-attention-chore"):
            self.assertFalse(ops["attention_needed"], ops["plain_language"])
        pending = self.tool("memory_pending_outcomes")
        self.assertEqual([row["path"] for row in pending["outcomes"]], [relative])
        decisions = self.tool("memory_decisions")
        self.assertIn(relative, [row["path"] for row in decisions["decisions"]])
        search = self.tool("memory_search", query="Lilacboundarytoken")
        self.assertIn(relative, [row["path"] for row in search["ranked"]])
        note = self.tool("memory_get_note", path_or_id=relative)
        self.assertEqual(note["sha256"], self.sources[relative])

    def test_explicit_pending_undated_review_is_asked_once_across_processes(self):
        relative = self.decision(extra="outcome_status: pending\n", title="Courier pilot")
        start = self.tool("memory_session_start", task_hint="Review work", session_id="due-review")
        self.assertEqual(start["soft_prompt"], "Quick check — how did “Courier pilot” turn out?")
        ops = self.tool("memory_ops_status")
        self.assertTrue(ops["attention_needed"])
        self.assertEqual(ops["due_outcomes_count"], 1)
        self.assertEqual([row["path"] for row in ops["due_outcomes"]], [relative])
        end = self.tool("memory_session_end", session_id="due-review", summary="Synthetic engineering check completed.")
        self.assertIsNone(end["soft_prompt"])
        later = self.cli("breathe", "--vault", str(self.vault), "--task-hint", "New work")
        self.assertIsNone(later["soft_prompt"])
        self.assertEqual(self.tool("memory_pending_outcomes")["count"], 1)

    def test_valid_due_date_is_review_intent_without_an_outcome_status(self):
        self.decision(extra="review_after: 2000-01-01\n", title="Courier pilot")
        start = self.tool("memory_session_start", task_hint="Continue work", session_id="dated-review")
        self.assertEqual(start["soft_prompt"], "Quick check — how did “Courier pilot” turn out?")
        ops = self.tool("memory_ops_status")
        self.assertEqual(ops["due_outcomes_count"], 1)
        self.assertTrue(self.tool("memory_pending_outcomes")["outcomes"][0]["overdue"])

    def assert_no_review_attention(self, extra):
        self.decision(extra=extra)
        start = self.tool("memory_session_start", task_hint="Continue work", session_id="not-due")
        self.assertIsNone(start["soft_prompt"])
        ops = self.tool("memory_ops_status")
        self.assertFalse(ops["attention_needed"], ops["plain_language"])
        self.assertEqual(ops["due_outcomes_count"], 0)
        return self.tool("memory_pending_outcomes")

    def test_explicit_pending_review_with_a_future_date_is_not_asked_early(self):
        pending = self.assert_no_review_attention("outcome_status: pending\nreview_after: 9999-12-31\n")
        self.assertEqual(pending["count"], 1)
        self.assertFalse(pending["outcomes"][0]["overdue"])

    def test_malformed_date_cannot_become_due_by_lexical_order(self):
        pending = self.assert_no_review_attention("outcome_status: pending\nreview_after: 1000-00-00\n")
        self.assertEqual(pending["count"], 1)
        self.assertFalse(pending["outcomes"][0]["overdue"])

    def test_invalid_nontext_review_dates_are_not_treated_as_missing(self):
        for index, value in enumerate(("0", "false", "[]", "{}")):
            self.decision(name="InvalidDate" + str(index), extra="outcome_status: pending\nreview_after: " + value + "\n")
        start = self.tool("memory_session_start", task_hint="Continue work", session_id="invalid-dates")
        self.assertIsNone(start["soft_prompt"])
        ops = self.tool("memory_ops_status")
        self.assertFalse(ops["attention_needed"], ops["plain_language"])
        self.assertEqual(ops["due_outcomes_count"], 0)
        self.assertEqual(self.tool("memory_pending_outcomes")["count"], 4)

    def test_completed_outcome_is_excluded_even_with_a_past_review_date(self):
        pending = self.assert_no_review_attention("outcome_status: confirmed\nreview_after: 2000-01-01\n")
        self.assertEqual(pending["count"], 0)

    def test_due_review_is_not_hidden_behind_eight_unscheduled_decisions(self):
        for index in range(9):
            self.decision(name="Policy" + str(index))
        relative = self.decision(name="DuePilot", extra="review_after: 2000-01-01\n", title="Courier pilot")
        ops = self.tool("memory_ops_status")
        self.assertEqual(ops["pending_outcomes_count"], 10)
        self.assertEqual(len(ops["pending_outcomes"]), 8)
        self.assertNotIn(relative, [row["path"] for row in ops["pending_outcomes"]])
        self.assertEqual([row["path"] for row in ops["due_outcomes"]], [relative])
        start = self.tool("memory_session_start", task_hint="Continue work", session_id="visible-review")
        self.assertEqual(start["soft_prompt"], "Quick check — how did “Courier pilot” turn out?")

    def queue_first_eight_reviews(self):
        for index in range(9):
            self.decision(name="Due" + str(index).zfill(2), extra="outcome_status: pending\n",
                          title="Courier pilot " + str(index).zfill(2))
        for index in range(8):
            start = self.tool("memory_session_start", task_hint="Review a scheduled outcome",
                              session_id="queue-" + str(index))
            self.assertEqual(start["soft_prompt"],
                             "Quick check — how did “Courier pilot " + str(index).zfill(2) + "” turn out?")
        ops = self.tool("memory_ops_status")
        self.assertEqual(ops["due_outcomes_count"], 9)
        self.assertEqual(len(ops["due_outcomes"]), 8)

    def test_ninth_due_review_reaches_start_after_the_first_eight_were_asked(self):
        self.queue_first_eight_reviews()
        start = self.tool("memory_session_start", task_hint="Review the remaining outcome", session_id="queue-8")
        self.assertEqual(start["soft_prompt"], "Quick check — how did “Courier pilot 08” turn out?")
        end = self.tool("memory_session_end", session_id="queue-8", summary="Synthetic review queue check completed.")
        self.assertIsNone(end["soft_prompt"])
        later = self.tool("memory_session_start", task_hint="Continue work", session_id="queue-9")
        self.assertIsNone(later["soft_prompt"])
        self.assertEqual(self.tool("memory_pending_outcomes")["count"], 9)

    def test_ninth_due_review_reaches_end_after_the_first_eight_were_asked(self):
        self.queue_first_eight_reviews()
        end = self.tool("memory_session_end", session_id="queue-7", summary="Synthetic review queue check completed.")
        self.assertEqual(end["soft_prompt"], "Quick check — how did “Courier pilot 08” turn out?")
        later = self.tool("memory_session_start", task_hint="Continue work", session_id="queue-8")
        self.assertIsNone(later["soft_prompt"])
        self.assertEqual(self.tool("memory_ops_status")["due_outcomes_count"], 9)

    def test_external_completion_remains_excluded_during_a_native_index_hold(self):
        relative = self.decision(extra="outcome_status: pending\nreview_after: 2000-01-01\n")
        self.assertEqual(self.tool("memory_pending_outcomes")["count"], 1)
        code = ("import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
                "c.execute('BEGIN IMMEDIATE'); print('locked',flush=True); "
                "sys.stdin.read(); c.rollback(); c.close()")
        command = [sys.executable, "-B", "-c", code, str(self.vault / "knowledge_index.db")]
        started = time.time_ns()
        holder = subprocess.Popen(command, cwd=self.directory, env=self.env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            source = self.vault / relative
            source.write_bytes(source.read_bytes().replace(b"outcome_status: pending", b"outcome_status: confirmed"))
            self.sources[relative] = sha(source)
            start = self.tool("memory_session_start", task_hint="Continue work", session_id="closed-review")
            self.assertIsNone(start["soft_prompt"])
            ops = self.tool("memory_ops_status")
            self.assertEqual(ops["pending_outcomes_count"], 0)
            self.assertEqual(ops["due_outcomes_count"], 0)
            self.assertFalse(ops["attention_needed"], ops["plain_language"])
            self.assertEqual(self.tool("memory_pending_outcomes")["count"], 0)
        finally:
            try:
                stdout, stderr = holder.communicate("", timeout=15)
            except BaseException:
                holder.kill()
                stdout, stderr = holder.communicate()
                raise
            row = {"command": command, "pid": holder.pid, "started_ns": started,
                   "stopped_ns": time.time_ns(), "exit_code": holder.returncode,
                   "stopped": holder.poll() is not None}
            self.processes.append(row)
            self.record(dict(row, stdout="locked\n" + stdout, stderr=stderr))
            self.assertEqual(holder.returncode, 0, stderr)


class ReviewEligibilityTests(unittest.TestCase):
    def test_date_and_status_boundaries(self):
        from knowledgeos.evolution import outcome_review_due
        cases = [({}, False), ({"outcome_status": "pending"}, True),
                 ({"review_after": "2026-10-20"}, True),
                 ({"review_after": "2026-10-19"}, True),
                 ({"outcome_status": "pending", "review_after": "2026-10-21"}, False),
                 ({"review_after": "2026-10-21"}, False)]
        cases += [({"outcome_status": "pending", "review_after": value}, False)
                  for value in ("1000-00-00", "1999-02-29", "20000101", "2000-W01-1", "2000-01-01T00:00:00", "0", 0, False, [], {})]
        cases += [({"outcome_status": status, "review_after": "2000-01-01"}, False)
                  for status in ("confirmed", "invalidated", "superseded", "unknown")]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertIs(outcome_review_due(row, "2026-10-20"), expected)


if __name__ == "__main__":
    unittest.main()
