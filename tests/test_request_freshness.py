"""Source-authority and request-lifetime controls for the memory API."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import unittest
from unittest import mock

from knowledgeos import evolution, indexer
from knowledgeos.memory import MemoryAPI, dispatch


class RequestFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/request-freshness-controls" / secrets.token_hex(8))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        (self.vault / "People/Self.md").write_text(
            "# Self\n\nUnknown.\n\n## Heuristics\n<!-- kos:section=heuristics -->\nUnknown.\n\n"
            "## Drift log\n<!-- kos:section=drift_log -->\nNo history.\n", encoding="utf-8")
        self.old_state = os.environ.get("KNOWLEDGEOS_STATE_DIR")
        os.environ["KNOWLEDGEOS_STATE_DIR"] = str(self.root / "gate-state")
        self.api = MemoryAPI(self.vault)
        self.self_hash = hashlib.sha256((self.vault / "People/Self.md").read_bytes()).hexdigest()
        self.write("Concepts/source.md", "ambertoken", "Amber title")
        self.assertIn("Concepts/source.md", self.paths(self.search("ambertoken")))

    def tearDown(self):
        if self.old_state is None:
            os.environ.pop("KNOWLEDGEOS_STATE_DIR", None)
        else:
            os.environ["KNOWLEDGEOS_STATE_DIR"] = self.old_state
        self.assertEqual(hashlib.sha256((self.vault / "People/Self.md").read_bytes()).hexdigest(), self.self_hash)

    def write(self, name, text, title="Synthetic source"):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: concept\ntitle: {title}\nstatus: active\n---\n\n{text}\n", encoding="utf-8")
        return path

    def search(self, query):
        result = dispatch(self.api, "memory_search", {"query": query})
        self.assertNotIn("error", result)
        return result

    @staticmethod
    def paths(result):
        return [row["path"] for row in result.get("ranked", [])]

    def test_same_size_restored_mtime_edit_is_visible_on_the_next_request(self):
        path = self.vault / "Concepts/source.md"
        before = path.stat()
        raw = path.read_bytes()
        changed = raw.replace(b"ambertoken", b"cedartoken").replace(b"Amber title", b"Cedar title")
        self.assertEqual(len(raw), len(changed))
        path.write_bytes(changed)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.paths(self.search("ambertoken")), [])
        current = self.search("cedartoken")["ranked"][0]
        self.assertEqual(current["path"], "Concepts/source.md")
        self.assertEqual(current["title"], "Cedar title")

    def test_addition_and_removal_are_visible_on_consecutive_requests(self):
        self.write("Concepts/added.md", "additionglyph")
        self.assertIn("Concepts/added.md", self.paths(self.search("additionglyph")))
        (self.vault / "Concepts/source.md").replace(self.root / "removed-source.md")
        self.assertEqual(self.paths(self.search("ambertoken")), [])

    def test_tampered_cache_is_repaired_on_the_next_request(self):
        with sqlite3.connect(self.api.db_path) as conn:
            conn.execute("UPDATE notes_fts SET body='forgedglyph' WHERE path='Concepts/source.md'")
            conn.execute("UPDATE notes SET title='Forged title', type='decision' WHERE path='Concepts/source.md'")
        self.assertEqual(self.paths(self.search("forgedglyph")), [])
        rows = self.search("ambertoken")["ranked"]
        self.assertEqual(rows[0]["title"], "Amber title")
        self.assertEqual(rows[0]["type"], "concept")
        changed, reason = indexer.manifest_diff(self.vault)
        self.assertFalse(changed, reason)

    def test_nested_candidates_still_read_current_source_bytes(self):
        path = self.vault / "Concepts/source.md"
        with self.api._request_scope():
            self.assertIn("Amber title", str(self.api.search("ambertoken")))
            path.write_bytes(path.read_bytes().replace(b"Amber title", b"Cedar title"))
            result = self.api.search("ambertoken")
            self.assertEqual(result["ranked"][0]["title"], "Cedar title")
            self.assertNotIn("Amber title", json.dumps(result))

    def test_capture_invalidates_a_prior_observation_in_the_same_scope(self):
        with self.api._request_scope():
            self.api.search("ambertoken")
            captured = self.api.capture("New source", "captureglyph is a fictional paper model.")
            self.assertTrue(captured.get("indexed"))
            self.assertIn(captured["path"], self.paths(self.api.search("captureglyph")))
            self.assertTrue(self.api._request_local.observation.freshness_checked)

    def test_recorded_outcome_refreshes_a_prior_observation_in_the_same_scope(self):
        source = self.vault / "Decisions/courier.md"
        source.parent.mkdir(exist_ok=True)
        source.write_text(
            "---\ntype: decision\nid: kos:decision:courier\ntitle: Courier trial\n"
            "status: active\noutcome_status: pending\nreview_after: 2000-01-01\n---\n"
            "\nA fictional courier trial awaits an outcome.\n", encoding="utf-8")
        with self.api._request_scope():
            reviewed = self.api.get_note("Decisions/courier.md")
            pending = dispatch(self.api, "memory_pending_outcomes", {})
            self.assertEqual(pending["count"], 1)
            result = dispatch(self.api, "memory_record_outcome", {
                "path": reviewed["path"], "expected_sha256": reviewed["sha256"],
                "outcome_status": "confirmed", "actual_outcome": "All six trial deliveries arrived on time.",
                "lesson": "Try a short pilot before a long commitment"})
            self.assertTrue(result.get("recorded"), result)
            changed, reason = indexer.manifest_diff(self.vault)
            self.assertFalse(changed, reason)
            self.assertEqual(dispatch(self.api, "memory_pending_outcomes", {})["count"], 0)

    def test_separate_threads_do_not_share_a_request_observation(self):
        ready = threading.Event()
        proceed = threading.Event()
        results, errors = {}, []

        def first():
            try:
                with self.api._request_scope():
                    results["first"] = self.api.search("ambertoken")
                    ready.set()
                    self.assertTrue(proceed.wait(15))
                    results["nested"] = self.api.search("ambertoken")
            except BaseException as error:
                errors.append(repr(error))
                ready.set()

        worker = threading.Thread(target=first)
        worker.start()
        try:
            self.assertTrue(ready.wait(15))
            path = self.vault / "Concepts/source.md"
            old_stat = path.stat()
            path.write_bytes(path.read_bytes().replace(b"ambertoken", b"cedartoken"))
            os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            results["second"] = self.search("cedartoken")
        finally:
            proceed.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertIn("Concepts/source.md", self.paths(results["second"]))
        self.assertEqual(self.paths(results["nested"]), [])

    def test_busy_result_is_incomplete_and_the_next_request_reprobes(self):
        holder = sqlite3.connect(self.api.db_path)
        holder.execute("BEGIN IMMEDIATE")
        try:
            self.write("Concepts/added.md", "busyadditionglyph")
            path = self.vault / "Concepts/source.md"
            path.write_bytes(path.read_bytes().replace(b"Amber title", b"Cedar title"))
            result = self.search("ambertoken")
            self.assertTrue(result.get("index_frozen"))
            self.assertFalse(result.get("index_blocked"))
            self.assertEqual(result["ranked"][0]["title"], "Cedar title")
            pending = dispatch(self.api, "memory_pending_outcomes")
            self.assertTrue(pending.get("index_frozen"))
        finally:
            holder.rollback()
            holder.close()
        recovered = self.search("busyadditionglyph")
        self.assertIn("Concepts/added.md", self.paths(recovered))
        self.assertFalse(recovered.get("index_frozen"))

    def test_blocked_result_keeps_the_fault_and_recovers_on_the_next_request(self):
        self.write("Concepts/added.md", "blockedadditionglyph")
        with mock.patch.object(indexer, "rebuild_index", side_effect=OSError("fixture disk full")):
            result = self.search("ambertoken")
            self.assertTrue(result.get("index_frozen"))
            self.assertIn("fixture disk full", result.get("index_blocked", ""))
        recovered = self.search("blockedadditionglyph")
        self.assertIn("Concepts/added.md", self.paths(recovered))
        self.assertFalse(recovered.get("index_frozen"))

    def test_forgetting_within_a_scope_still_excludes_current_and_literal_sources(self):
        fact = "Fictional Rill review meetings happen every second Thursday morning."
        captured = self.api.capture("Rill review", fact)
        path = self.vault / captured["path"]
        raw = path.read_bytes()
        copy = self.vault / "Concepts/copy.md"
        copy.write_bytes(raw)
        with self.api._request_scope():
            self.api.search("Rill")
            result = self.api.forget(captured["path"], hashlib.sha256(raw).hexdigest())
            self.assertTrue(result.get("ok"), result)
            self.assertTrue(self.api.get_note(captured["path"]).get("error"))
            self.assertTrue(self.api.get_note("Concepts/copy.md").get("error"))
            self.assertEqual(self.paths(self.api.search("Rill")), [])
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(copy.read_bytes(), raw)

    def test_correction_within_a_scope_preserves_history_and_uses_the_replacement(self):
        old = self.api.capture("Rill prior", "For fictional Rill, the trailglyph model was amber.")
        new = self.api.capture("Rill current", "For fictional Rill, the trailglyph model is cedar.")
        old_raw = (self.vault / old["path"]).read_bytes()
        new_raw = (self.vault / new["path"]).read_bytes()
        with self.api._request_scope():
            self.api.search("trailglyph")
            result = self.api.supersede(old["path"], hashlib.sha256(old_raw).hexdigest(),
                                        new["path"], hashlib.sha256(new_raw).hexdigest())
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(self.paths(self.api.search("trailglyph")), [new["path"]])
            history = self.api.get_note(old["path"])
            self.assertEqual(history["memory_status"], "historical")
            self.assertIn("was amber", history["body"])

    def test_pending_outcome_count_and_list_use_one_observation(self):
        expected = [{"path": "Decisions/fictional.md", "title": "Fictional decision"}]
        with mock.patch.object(evolution, "pending_outcome_reviews", side_effect=[expected, []]) as observed:
            result = dispatch(self.api, "memory_pending_outcomes")
        self.assertEqual(result, {"count": 1, "outcomes": expected})
        self.assertEqual(observed.call_count, 1)

    def test_weekly_drift_write_is_visible_in_the_same_startup_context(self):
        from knowledgeos.autopilot import save_state

        for name, actual in (("mail", "The mail trial found missing exports before renewal."),
                             ("calendar", "The calendar trial failed offline and was cancelled.")):
            path = self.vault / f"Decisions/{name}.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(
                f"---\nid: kos:decision:{name}\ntype: decision\ntitle: {name}\n"
                f"outcome_status: confirmed\nactual_outcome: {actual}\n"
                "lesson: Prefer short cancellable trials before annual commitments\n"
                "belief_before: Prefer annual commitments before running trials\n"
                "belief_after: Prefer short cancellable trials before annual commitments\n---\n\nRecorded outcome.\n",
                encoding="utf-8")
        save_state(self.vault, {"real_sessions": 3, "first_session_ts": time.time() - 4 * 86400})
        result = dispatch(self.api, "memory_session_start", {"task_hint": "uncertain", "session_id": "drift-write-control"})
        self.assertTrue(result.get("drift_tick", {}).get("proposed"), result)
        proposals = list((self.vault / "People/Self-Proposals").glob("*.md"))
        self.assertEqual(len(proposals), 1)
        expected_path = proposals[0].relative_to(self.vault).as_posix()
        actual_paths = [row["path"] for row in result["context"]["relevant"]["ranked"]]
        self.assertIn(expected_path, actual_paths)


if __name__ == "__main__":
    unittest.main()
