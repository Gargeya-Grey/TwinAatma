"""Explicit completed outcomes support uncertain proposals without repeated suggestions."""
from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
from pathlib import Path

from support import TempVaultCase
from knowledgeos.memory import dispatch


class EvidenceLearningTests(TempVaultCase):
    def decision(self, name, outcome="confirmed", actual=None, **changes):
        fields = {
            "id": f"kos:decision:{name}", "type": "decision", "title": name,
            "outcome_status": outcome,
            "actual_outcome": actual or f"The {name} trial found a different concrete limitation.",
            "lesson": "Prefer short cancellable trials before annual commitments",
            "belief_before": "Prefer annual commitments before running trials",
            "belief_after": "Prefer short cancellable trials before annual commitments",
        }
        fields.update(changes)
        self.write(f"Decisions/{name}.md", "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n\nRecorded outcome.\n")

    def test_distinct_completed_sources_yield_an_attributed_uncertain_change(self):
        self.decision("mail", actual="The mail trial found missing exports before renewal.")
        self.decision("calendar", actual="The calendar trial failed offline and was cancelled.")
        with self.guard() as guard:
            result = dispatch(self.api(), "memory_propose_from_drift", {})
        guard.assert_unchanged(self)
        self.assertTrue(result.get("proposed"), result)
        self.assertTrue(result["semantic_change_assessed"], result)
        self.assertEqual([s["path"] for s in result["evidence"]], ["Decisions/calendar.md", "Decisions/mail.md"])
        text = (self.vault / result["proposal_path"]).read_text(encoding="utf-8")
        for required in ("Prefer annual commitments before running trials", "Prefer short cancellable trials before annual commitments", "Decisions/mail.md", "Decisions/calendar.md", "uncertain", "not independent verification"):
            self.assertIn(required, text)

    def test_rejected_drift_requires_a_genuinely_new_completed_source(self):
        self.decision("mail")
        self.decision("calendar")
        with self.guard() as guard:
            prop = dispatch(self.api(), "memory_propose_from_drift", {})
            self.assertTrue(prop.get("proposed"), prop)
            repeated = dispatch(self.api(), "memory_propose_from_drift", {})
            self.assertEqual(repeated.get("suppression"), "already_suggested", repeated)
            rejected = dispatch(self.api(), "memory_reject_self_update", {"proposal_path": prop["proposal_path"]})
            self.assertTrue(rejected.get("ok"), rejected)
            self.decision("mail", title="Retitled", updated="2026-10-19", lesson="**Prefer** short cancellable trials before annual commitments", actual_outcome="The mail trial found a corrected limitation.")
            repeated = dispatch(self.api(), "memory_propose_from_drift", {})
            self.assertEqual(repeated.get("suppression"), "rejected_without_new_source", repeated)
            self.decision("storage")
            new = dispatch(self.api(), "memory_propose_from_drift", {})
            self.assertTrue(new.get("proposed"), new)
            self.assertNotEqual(new["proposal_path"], prop["proposal_path"])
            refusal = dispatch(self.api(), "memory_accept_self_update", {"proposal_path": new["proposal_path"]})
            self.assertIn("error", refusal)
        guard.assert_unchanged(self)

    def test_single_lesson_rejection_and_cross_tool_recurrence(self):
        self.decision("mail")
        with self.guard() as guard:
            prop = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
            self.assertTrue(prop.get("proposed"), prop)
            self.assertIn("does not establish a general belief", (self.vault / prop["proposal_path"]).read_text(encoding="utf-8"))
            dispatch(self.api(), "memory_reject_self_update", {"proposal_path": prop["proposal_path"]})
            self.decision("mail", title="Retitled", updated="2026-10-19", lesson="**Prefer** short cancellable trials before annual commitments")
            repeated = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
            self.assertEqual(repeated.get("suppression"), "rejected_without_new_source", repeated)
            self.decision("calendar")
            new = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:calendar"})
            self.assertTrue(new.get("proposed"), new)
            repeated = dispatch(self.api(), "memory_propose_from_drift", {})
            self.assertEqual(repeated.get("suppression"), "already_suggested", repeated)
        guard.assert_unchanged(self)

    def test_insufficient_pending_duplicate_or_superseded_records_never_establish_change(self):
        self.decision("mail")
        for changes in (
            {"outcome_status": "pending"},
            {"type": "concept"},
            {"id": "kos:decision:mail"},
            {"actual_outcome": "The mail trial found a different concrete limitation."},
            {"actual_outcome": ""},
            {"belief_after": "Prefer annual commitments before running trials"},
            {"outcome_status": "superseded"},
            {"belief_after": "An incompatible correction"},
        ):
            with self.subTest(changes=changes), self.guard() as guard:
                self.decision("calendar", **changes)
                result = dispatch(self.api(), "memory_propose_from_drift", {})
                self.assertFalse(result.get("proposed"), result)
                self.assertNotIn("proposal_path", result)
            guard.assert_unchanged(self)
        self.assertFalse(self.proposal_files())

    def test_live_source_correction_with_a_frozen_index_is_not_old_evidence(self):
        self.decision("mail")
        self.decision("calendar")
        api = self.api()
        api.decisions()
        holder = sqlite3.connect(api.db_path)
        try:
            holder.execute("BEGIN IMMEDIATE")
            self.decision("calendar", belief_after="Prefer annual commitments instead of trials")
            result = dispatch(api, "memory_propose_from_drift", {})
        finally:
            holder.rollback()
            holder.close()
        self.assertTrue(result.get("index_frozen"), result)
        self.assertFalse(result.get("proposed"), result)
        self.assertFalse(self.proposal_files())

    def test_incorporated_statement_is_a_synthetic_initial_condition(self):
        self.decision("mail")
        self.decision("calendar")
        path = self.vault / "People/Self.md"
        text = path.read_text(encoding="utf-8").replace("<!-- kos:section=heuristics -->", "<!-- kos:section=heuristics -->\n* Prefer short cancellable trials before annual commitments")
        path.write_text(text, encoding="utf-8")
        with self.guard() as guard:
            result = dispatch(self.api(), "memory_propose_from_drift", {})
            self.assertEqual(result.get("suppression"), "already_in_self", result)
        guard.assert_unchanged(self)
        self.assertFalse(self.proposal_files())

    def test_simultaneous_public_calls_create_one_suggestion(self):
        self.decision("mail")
        self.decision("calendar")
        self.api().decisions()
        with self.guard() as guard:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: dispatch(self.api(), "memory_propose_from_drift", {}), range(2)))
        guard.assert_unchanged(self)
        self.assertEqual(sum(bool(result.get("proposed")) for result in results), 1, results)
        self.assertEqual(len(self.proposal_files()), 1)

    def test_tampered_signed_history_does_not_reopen_rejected_suggestions(self):
        self.decision("mail")
        self.decision("calendar")
        first = dispatch(self.api(), "memory_propose_from_drift", {})
        self.assertTrue(first.get("proposed"), first)
        dispatch(self.api(), "memory_reject_self_update", {"proposal_path": first["proposal_path"]})
        ledgers = list(Path(os.environ["KNOWLEDGEOS_STATE_DIR"]).rglob("*.jsonl"))
        self.assertEqual(len(ledgers), 1)
        rows = [json.loads(line) for line in ledgers[0].read_text(encoding="utf-8").splitlines()]
        rows[0]["status"] = "untrusted mutation"
        ledgers[0].write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        with self.guard() as guard:
            result = dispatch(self.api(), "memory_propose_from_drift", {})
        guard.assert_unchanged(self)
        self.assertIn("error", result, result)
        self.assertEqual(len(self.proposal_files()), 1)

    def test_legacy_signed_lesson_rejection_survives_current_source_churn(self):
        self.decision("mail")
        api = self.api()
        old = api.propose_self_update(
            summary="Legacy lesson", section="heuristics", mode="append",
            proposed_markdown="* **From decision [mail](Decisions/mail.md)**: Prefer short cancellable trials before annual commitments",
        )
        self.assertTrue(old.get("ok"), old)
        dispatch(api, "memory_reject_self_update", {"proposal_path": old["proposal_path"]})
        self.decision("mail", title="Retitled", updated="2026-10-19", lesson="**Prefer** short cancellable trials before annual commitments")
        with self.guard() as guard:
            result = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
        guard.assert_unchanged(self)
        self.assertEqual(result.get("suppression"), "rejected_without_new_source", result)
        self.assertEqual(len(self.proposal_files()), 1)

    def test_lost_history_refuses_to_reopen_a_retained_rejected_proposal(self):
        self.decision("mail")
        first = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
        self.assertTrue(first.get("proposed"), first)
        dispatch(self.api(), "memory_reject_self_update", {"proposal_path": first["proposal_path"]})
        ledgers = list(Path(os.environ["KNOWLEDGEOS_STATE_DIR"]).rglob("*.jsonl"))
        self.assertEqual(len(ledgers), 1)
        ledgers[0].rename(ledgers[0].with_suffix(".retained"))
        with self.guard() as guard:
            result = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
        guard.assert_unchanged(self)
        self.assertIn("error", result, result)
        self.assertEqual(len(self.proposal_files()), 1)

    def test_contradictory_or_explicitly_superseding_sources_do_not_support_old_change(self):
        self.decision("mail")
        self.decision("calendar")
        for changes in ({}, {"supersedes": "kos:decision:mail"}):
            with self.subTest(changes=changes):
                self.decision("storage", belief_after="Prefer annual commitments instead of trials", lesson="Prefer annual commitments instead of trials", **changes)
                result = dispatch(self.api(), "memory_propose_from_drift", {})
                self.assertFalse(result.get("proposed"), result)
        self.assertFalse(self.proposal_files())

    def test_markdown_links_and_list_numbers_do_not_reopen_a_declined_lesson(self):
        self.decision("mail")
        first = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
        dispatch(self.api(), "memory_reject_self_update", {"proposal_path": first["proposal_path"]})
        self.decision("mail", lesson="1. [Prefer](https://example.invalid/format) short cancellable trials before annual commitments")
        result = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "kos:decision:mail"})
        self.assertEqual(result.get("suppression"), "rejected_without_new_source", result)
        self.assertEqual(len(self.proposal_files()), 1)

    def test_renaming_an_unidentified_source_is_not_new_outcome_evidence(self):
        self.decision("mail", id="")
        first = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "Decisions/mail.md"})
        dispatch(self.api(), "memory_reject_self_update", {"proposal_path": first["proposal_path"]})
        (self.vault / "Decisions/mail.md").rename(self.vault / "Decisions/renamed.md")
        result = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "Decisions/renamed.md"})
        self.assertEqual(result.get("suppression"), "rejected_without_new_source", result)
        self.assertEqual(len(self.proposal_files()), 1)

    def test_rekeying_an_existing_source_or_copying_its_outcome_is_not_new_evidence(self):
        self.decision("mail")
        first = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "Decisions/mail.md"})
        dispatch(self.api(), "memory_reject_self_update", {"proposal_path": first["proposal_path"]})
        self.decision("mail", id="kos:decision:rekeyed", actual_outcome="A corrected narrative on the existing source.")
        changed = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "Decisions/mail.md"})
        self.assertEqual(changed.get("suppression"), "rejected_without_new_source", changed)
        self.decision("copied", actual_outcome="The mail trial found a different concrete limitation.")
        copied = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "Decisions/copied.md"})
        self.assertEqual(copied.get("suppression"), "rejected_without_new_source", copied)
        self.assertEqual(len(self.proposal_files()), 1)


if __name__ == "__main__":
    unittest.main()
