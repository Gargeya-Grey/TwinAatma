"""Public stale-project attention remains independent of the startup preview."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import unittest
import uuid
from unittest import mock

from knowledgeos import indexer
from knowledgeos.memory import MemoryAPI, dispatch


class OpsProjectFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1] / "work/gc-artifacts/.knowledgeos/project-context-controls" / uuid.uuid4().hex)
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        (self.vault / "Projects").mkdir()
        self.identity = self.vault / "People/Self.md"
        self.identity.write_text("# Self\n\nUnknown.\n", encoding="utf-8")
        self.identity_before = self.identity.read_bytes()
        self.environment = mock.patch.dict(os.environ, {
            "KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.gate_key = os.environ.pop("KNOWLEDGEOS_GATE_KEY", None)
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        if self.gate_key is not None:
            os.environ["KNOWLEDGEOS_GATE_KEY"] = self.gate_key
        self.environment.stop()
        self.assertEqual(self.identity.read_bytes(), self.identity_before)

    def project(self, name, *, title=None, status="active", kind="project", updated="2000-01-01"):
        path = self.vault / "Projects" / (name + ".md")
        path.write_text(
            "---\ntype: " + kind + "\ntitle: " + (title or name) +
            "\nstatus: " + status + "\nupdated: " + updated +
            "\n---\n\nA fictional orchard project needs a planning review.\n", encoding="utf-8")
        return path

    def ops(self):
        result = dispatch(self.api, "memory_ops_status", {})
        self.assertNotIn("error", result, result)
        return result

    def stale_message(self, result):
        return [text for text in result["plain_language"] if "active project(s) look stale" in text]

    def startup(self, *, limit=8, task_hint=""):
        result = dispatch(self.api, "memory_session_start", {
            "limit": limit, "task_hint": task_hint, "session_id": "project-attention"})
        self.assertNotIn("error", result, result)
        return result

    def test_startup_limit_does_not_reduce_the_five_project_ops_notice(self):
        for number in range(6):
            self.project("orchard-" + str(number))
        for limit in (1, 8):
            with self.subTest(limit=limit):
                result = self.startup(limit=limit)
                self.assertEqual(len(result["context"]["stale_warnings"]), min(limit, 6))
                self.assertEqual(self.stale_message(result["ops"]), [
                    "5 active project(s) look stale — mention only if advising on them."])
        self.assertEqual(self.stale_message(self.ops()), [
            "5 active project(s) look stale — mention only if advising on them."])

    def test_context_byte_trimming_cannot_erase_project_attention(self):
        for number in range(6):
            self.project("orchard-" + str(number))
        result = self.startup(task_hint=" " * 20000)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()), 16384)
        self.assertEqual(result["context"]["stale_warnings"], [])
        self.assertIn("stale_warnings", result["context"]["context_budget"]["truncated"])
        self.assertEqual(self.stale_message(result["ops"]), [
            "5 active project(s) look stale — mention only if advising on them."])

    def test_current_metadata_and_removal_win_over_a_busy_index(self):
        path = self.project("orchard")
        self.assertEqual(self.stale_message(self.ops()), [
            "1 active project(s) look stale — mention only if advising on them."])
        raw = path.read_bytes()
        edits = (
            (raw.replace(b"status: active", b"status: closed"), False),
            (raw.replace(b"type: project", b"type: concept"), False),
            (raw.replace(b"2000-01-01", datetime.date.today().isoformat().encode()), False),
            (raw.replace(b"title: orchard", b"title: Updated orchard"), True),
        )
        for replacement, expected_stale in edits:
            with self.subTest(replacement=replacement):
                before = path.stat()
                path.write_bytes(replacement)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                with mock.patch.object(indexer, "index_state", return_value="locked"):
                    result = self.ops()
                self.assertEqual(bool(self.stale_message(result)), expected_stale, result)
        path.replace(self.root / "retained-removed-project.md")
        with mock.patch.object(indexer, "index_state", return_value="locked"):
            self.assertEqual(self.stale_message(self.ops()), [])

    def test_same_size_restored_mtime_metadata_edit_is_seen_on_next_public_call(self):
        path = self.project("orchard")
        self.assertTrue(self.stale_message(self.ops()))
        before = path.stat()
        raw = path.read_bytes()
        replacement = raw.replace(b"status: active", b"status: closed")
        self.assertEqual(len(raw), len(replacement))
        path.write_bytes(replacement)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.stale_message(self.ops()), [])
        self.assertEqual(self.startup()["context"]["active_projects"], [])

    def test_signed_forgetting_removes_attention_without_deleting_source(self):
        path = self.project("orchard")
        self.assertTrue(self.stale_message(self.ops()))
        raw = path.read_bytes()
        forgotten = dispatch(self.api, "memory_forget", {
            "path_or_id": "Projects/orchard.md",
            "expected_sha256": hashlib.sha256(raw).hexdigest()})
        self.assertTrue(forgotten.get("ok"), forgotten)
        self.assertEqual(self.stale_message(self.ops()), [])
        self.assertEqual(self.startup()["context"]["active_projects"], [])
        self.assertEqual(path.read_bytes(), raw)

    def test_blocked_rebuild_still_reports_fault_and_current_project_status(self):
        self.project("orchard")
        self.assertTrue(self.stale_message(self.ops()))
        self.project("new-source")
        with mock.patch.object(indexer, "rebuild_index", side_effect=OSError("fixture disk full")):
            result = self.ops()
        self.assertIn("fixture disk full", result["index_blocked"])
        self.assertTrue(result["attention_needed"])
        self.assertIn(
            "The note index cannot be rebuilt, so search may quote older text. "
            "This needs a one-time fix on the machine.", result["plain_language"])
        self.assertEqual(self.stale_message(result), [
            "1 active project(s) look stale — mention only if advising on them."])

    def test_twenty_one_day_boundary_and_undated_project_keep_current_semantics(self):
        cutoff = datetime.date.today() - datetime.timedelta(days=21)
        self.project("boundary", updated=cutoff.isoformat())
        self.project("undated", updated="")
        self.assertEqual(self.stale_message(self.ops()), [])
        self.project("older", updated=(cutoff - datetime.timedelta(days=1)).isoformat())
        self.assertEqual(self.stale_message(self.ops()), [
            "1 active project(s) look stale — mention only if advising on them."])

    def test_project_candidate_selection_stays_bounded_at_two_hundred(self):
        for number in range(200):
            self.project("recent-" + str(number), status="closed", updated="2026-01-01")
        self.project("outside-selection", updated="1999-01-01")
        self.assertEqual(self.stale_message(self.ops()), [])
        self.assertEqual(self.startup()["context"]["active_projects"], [])

    def test_pending_decision_is_supplied_and_current_type_and_outcome_are_rechecked(self):
        from unittest import mock
        from knowledgeos import indexer
        from knowledgeos.memory import dispatch
        note = self.vault / "Decisions/orchard.md"
        note.parent.mkdir()
        raw = (b"---\ntype: decision\ntitle: Orchard planning\nstatus: active\n"
               b"updated: 2000-01-01\noutcome_status: pending\n---\n\nUse the north orchard for the fictional pilot.\n")
        note.write_bytes(raw)
        result = dispatch(self.api, "memory_bootstrap_context", {})
        self.assertEqual([r["path"] for r in result["pending_decision_outcomes"]], ["Decisions/orchard.md"])
        note.write_bytes(raw.replace(b"type: decision", b"type: concept"))
        with mock.patch.object(indexer, "index_state", return_value="locked"):
            result = dispatch(self.api, "memory_bootstrap_context", {})
        self.assertEqual(result["pending_decision_outcomes"], [])
        note.write_bytes(raw.replace(b"outcome_status: pending", b"outcome_status: complete"))
        with mock.patch.object(indexer, "index_state", return_value="locked"):
            result = dispatch(self.api, "memory_bootstrap_context", {})
        self.assertEqual(result["pending_decision_outcomes"], [])


    def test_sensitive_project_is_excluded_after_external_edit_under_busy_index(self):
        path = self.project("orchard")
        self.assertTrue(self.stale_message(self.ops()))
        detail = "My colleague has a malignant biopsy result."
        path.write_text(path.read_text(encoding="utf-8") + "\n" + detail + "\n", encoding="utf-8")
        with mock.patch.object(indexer, "index_state", return_value="locked"):
            ops = self.ops()
            startup = self.startup()
        self.assertEqual(self.stale_message(ops), [])
        self.assertEqual(startup["context"]["active_projects"], [])
        self.assertNotIn(detail, json.dumps(startup))

    def test_corrupted_signed_policy_refuses_ops_and_startup(self):
        from knowledgeos.remembering import RememberingPolicy
        path = self.project("forgotten")
        self.project("orchard")
        forgotten = dispatch(self.api, "memory_forget", {
            "path_or_id": "Projects/forgotten.md",
            "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        self.assertTrue(forgotten.get("ok"), forgotten)
        authority = RememberingPolicy(self.vault)._authority()
        envelope = json.loads(authority.read_text(encoding="utf-8"))
        envelope["mac"] = "0" * 64
        authority.write_text(json.dumps(envelope), encoding="utf-8")
        for tool in ("memory_ops_status", "memory_session_start"):
            with self.subTest(tool=tool):
                result = dispatch(self.api, tool, {})
                self.assertTrue(result.get("error"), result)
                self.assertFalse(result.get("ok", False), result)
                self.assertNotIn("orchard", json.dumps(result))



if __name__ == "__main__":
    unittest.main(verbosity=2)
