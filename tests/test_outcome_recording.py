"""Reviewed decision outcomes close exactly once without acquiring identity authority."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from unittest import mock

from support import TempVaultCase
from knowledgeos.memory import dispatch
from knowledgeos.remembering import RememberingPolicy


class OutcomeRecordingTests(TempVaultCase):
    def decision(self, name="Courier", extra="", ending="\n"):
        text = ("---\ntype: decision\nid: kos:decision:" + name + "\ntitle: " + name + "\n"
                "status: active\noutcome_status: pending\nreview_after: 2000-01-01\nupdated: 2026-10-18\n"
                + extra + "---\n# Trial\nUnrelated body without final newline")
        path = self.vault / ("Decisions/" + name + ".md")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(text.replace("\n", ending).encode("utf-8"))
        return path

    def reviewed(self, name="Courier", **values):
        api = self.api()
        note = api.get_note("Decisions/" + name + ".md")
        request = {"path": note["path"], "expected_sha256": note["sha256"], "outcome_status": "confirmed",
                   "actual_outcome": "The pilot met all six delivery deadlines.", "lesson": "Try a short pilot first"}
        request.update(values)
        return request

    def record(self, request, api=None):
        return dispatch(api or self.api(), "memory_record_outcome", request)

    def assert_refused_unchanged(self, request, source):
        before = source.read_bytes()
        with self.guard() as guard:
            result = self.record(request)
        guard.assert_unchanged(self)
        self.assertIn("error", result)
        self.assertEqual(source.read_bytes(), before)
        return result

    def test_exact_retry_survives_a_fresh_api_and_preserves_unrelated_mixed_bytes(self):
        source = self.decision()
        raw = source.read_bytes().replace(b"type: decision\n", b"type: decision\r\n").replace(b"# Trial\n", b"# Trial\r\n")
        source.write_bytes(raw)
        request = self.reviewed()
        with self.guard() as guard:
            first = self.record(request)
            after = source.read_bytes()
            second = self.record(request)
        guard.assert_unchanged(self)
        self.assertTrue(first.get("recorded"), first)
        self.assertEqual(first, second)
        self.assertEqual(source.read_bytes(), after)
        self.assertEqual(after.count(b"outcome_recording:"), 1)
        self.assertIn(b"type: decision\r\n", after)
        self.assertEqual(after[after.index(b"# Trial"):], raw[raw.index(b"# Trial"):])
        self.assertNotIn(b"belief_before:", after)
        self.assertNotIn(b"belief_after:", after)
        note = self.api().get_note(request["path"])
        self.assertEqual(note["sha256"], hashlib.sha256(after).hexdigest())
        self.assertEqual(note["frontmatter"]["lesson"], request["lesson"])

    def test_current_source_correction_is_reviewed_and_stale_hash_never_writes(self):
        source = self.decision()
        stale = self.reviewed()
        source.write_bytes(source.read_bytes().replace(b"title: Courier", b"title: Courier corrected"))
        self.assert_refused_unchanged(stale, source)
        current = self.reviewed()
        result = self.record(current)
        self.assertTrue(result.get("recorded"), result)
        self.assertEqual(self.api().get_note(current["path"])["frontmatter"]["title"], "Courier corrected")

    def test_conflicting_retry_closed_version_and_changed_completed_source_refuse(self):
        source = self.decision()
        request = self.reviewed()
        self.assertTrue(self.record(request).get("recorded"))
        self.assert_refused_unchanged(dict(request, lesson="A different lesson"), source)
        self.assert_refused_unchanged(self.reviewed(), source)
        source.write_bytes(source.read_bytes().replace(b"Unrelated body", b"A current correction"))
        self.assert_refused_unchanged(request, source)

    def test_marker_churn_or_recorded_timestamp_edits_cannot_change_an_exact_retry_result(self):
        for name, old, new in (("Marker", b"outcome_recording: {", b"outcome_recording:  {"),
                               ("Timestamp", b"outcome_recorded_at: '", b"outcome_recorded_at: '1900-01-01T00:00:00+00:00 ignored ")):
            source = self.decision(name)
            request = self.reviewed(name)
            self.assertTrue(self.record(request).get("recorded"))
            source.write_bytes(source.read_bytes().replace(old, new))
            self.assert_refused_unchanged(request, source)

    def test_already_closed_external_decision_requires_source_review_and_is_not_replaced(self):
        source = self.decision(extra="lesson: Existing reviewed lesson\n")
        source.write_bytes(source.read_bytes().replace(b"outcome_status: pending", b"outcome_status: invalidated"))
        self.assert_refused_unchanged(self.reviewed(), source)

    def test_each_completed_status_closes_pending_views_with_a_real_lesson(self):
        for status in ("confirmed", "invalidated", "superseded"):
            self.decision(status)
            result = self.record(self.reviewed(status, outcome_status=status))
            self.assertTrue(result.get("recorded"), result)
        rows = dispatch(self.api(), "memory_pending_outcomes", {})
        self.assertEqual(rows["outcomes"], [])
        for name in ("confirmed", "invalidated", "superseded"):
            note = self.api().get_note("Decisions/" + name + ".md")
            self.assertEqual(note["frontmatter"]["outcome_status"], name)
            self.assertEqual(note["frontmatter"]["actual_outcome"], "The pilot met all six delivery deadlines.")

    def test_explicit_paired_beliefs_work_with_attributed_lesson_without_approval(self):
        self.decision()
        request = self.reviewed(belief_before="Prefer yearly commitments before pilots", belief_after="Prefer a short pilot first")
        with self.guard() as guard:
            result = self.record(request)
            proposal = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": request["path"]})
        guard.assert_unchanged(self)
        self.assertTrue(result.get("recorded"), result)
        self.assertTrue(proposal.get("proposed"), proposal)
        note = self.api().get_note(request["path"])
        self.assertEqual(note["frontmatter"]["belief_before"], request["belief_before"])
        self.assertEqual(note["frontmatter"]["belief_after"], request["belief_after"])
        text = (self.vault / proposal["proposal_path"]).read_text(encoding="utf-8")
        self.assertIn("Decisions/Courier.md", text)
        self.assertIn(request["lesson"], text)

    def test_recording_and_reformatting_do_not_invent_explicit_belief_evidence(self):
        for name in ("Courier", "Post"):
            source = self.decision(name)
            source.write_bytes(source.read_bytes().replace(b"title:", b"TITLE:"))
            self.assertTrue(self.record(self.reviewed(name)).get("recorded"))
        result = dispatch(self.api(), "memory_propose_from_drift", {})
        self.assertFalse(result.get("proposed"), result)
        self.assertFalse(self.proposal_files())

    def test_serialization_is_lossless_or_refuses_without_any_changed_bytes(self):
        values = ("A person's lesson", 'A "quoted" lesson', "C:\\Trips\\notes", "Keep [literal] brackets", " leading and trailing ")
        for index, value in enumerate(values):
            name = "valid" + str(index)
            self.decision(name)
            result = self.record(self.reviewed(name, lesson=value))
            self.assertTrue(result.get("recorded"), result)
            self.assertEqual(self.api().get_note("Decisions/" + name + ".md")["frontmatter"]["lesson"], value)
        rejected = ("true", "no", "[a, b]", "A person's \"quoted\" lesson", "line\nsecond", "nul\x00value", "", "   ")
        for index, value in enumerate(rejected):
            name = "refused" + str(index)
            source = self.decision(name)
            self.assert_refused_unchanged(self.reviewed(name, lesson=value), source)

    def test_invalid_arguments_duplicate_keys_and_multiline_fields_never_write(self):
        source = self.decision()
        valid = self.reviewed()
        for values in ({"expected_sha256": ""}, {"outcome_status": "pending"}, {"belief_before": "Only before"},
                       {"actual_outcome": ""}, {"lesson": False}, {"path": "../Decisions/Courier.md"},
                       {"path": "Decisions/./Courier.md"}, {"path": str(source)}):
            self.assert_refused_unchanged(dict(valid, **values), source)
        for extra in ("lesson: Earlier\nlesson: Duplicate\n", "lesson: |\n  Earlier multiline lesson\n"):
            source = self.decision("Malformed", extra=extra)
            self.assert_refused_unchanged(self.reviewed("Malformed"), source)

    def test_nondecisions_identity_proposals_templates_and_generated_reports_refuse(self):
        from knowledgeos.data_ops import write_generated
        source = self.decision()
        text = source.read_text(encoding="utf-8")
        self.write("Concepts/Concept.md", text.replace("type: decision", "type: concept"))
        self.write("People/Self-Proposals/ordinary.md", text)
        self.write("Templates/t-outcome.md", text)
        generated = self.vault / "Decisions/generated.md"
        write_generated(self.vault, generated, text)
        for relative in ("Concepts/Concept.md", "People/Self.md", "People/Self-Proposals/ordinary.md", "Templates/t-outcome.md", "Decisions/generated.md"):
            target = self.vault / relative
            request = dict(self.reviewed(), path=relative, expected_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            self.assert_refused_unchanged(request, target)

    def test_policy_covers_the_complete_proposed_source_while_the_policy_lock_is_held(self):
        source = self.decision()
        request = self.reviewed()
        real = RememberingPolicy.require_text
        observed = []
        def require(policy, text, metadata=None):
            if "outcome_recording:" in text:
                observed.append({"text": text, "locked": (self.vault / ".knowledgeos/remembering-policy.lock").is_file()})
            return real(policy, text, metadata)
        with mock.patch.object(RememberingPolicy, "require_text", require):
            result = self.record(request)
        self.assertTrue(result.get("recorded"), result)
        self.assertEqual([row["text"] for row in observed], [source.read_bytes().decode("utf-8")])
        self.assertTrue(all(row["locked"] for row in observed))

    def test_excluded_source_and_requested_secret_never_enter_results_or_state(self):
        source = self.decision()
        request = self.reviewed()
        forbidden = "api_key=synthetic_outcome_secret_784333"
        result = self.assert_refused_unchanged(dict(request, actual_outcome=forbidden), source)
        self.assertNotIn(forbidden, json.dumps(result))
        for path in (self.vault / ".knowledgeos").rglob("*"):
            if path.is_file():
                self.assertNotIn(forbidden.encode(), path.read_bytes())
        source.write_bytes(source.read_bytes().replace(b"type: decision", b"type: decision\nprivacy: do-not-remember"))
        result = self.assert_refused_unchanged(dict(request, expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest()), source)
        self.assertIn("error", result)

    def test_failed_publication_preserves_source_and_successful_retry_is_exact(self):
        source = self.decision()
        request = self.reviewed()
        with mock.patch("knowledgeos.outcomes.atomic_write_bytes", side_effect=OSError("sensitive-detail-should-not-leak")):
            result = self.assert_refused_unchanged(request, source)
        self.assertNotIn("sensitive-detail-should-not-leak", json.dumps(result))
        result = self.record(request)
        self.assertTrue(result.get("recorded"), result)
        self.assertEqual(self.record(request), result)
        self.assertEqual(source.read_bytes().count(b"outcome_recording:"), 1)

    def test_source_truth_closes_during_a_native_sqlite_hold_and_refreshes_after_release(self):
        source = self.decision()
        request = self.reviewed()
        api = self.api()
        api.decisions()
        holder = sqlite3.connect(api.db_path)
        try:
            holder.execute("BEGIN IMMEDIATE")
            result = self.record(request, api)
            self.assertTrue(result.get("recorded"), result)
            self.assertTrue(result.get("index_frozen"), result)
            self.assertEqual(result["index_refresh"]["status"], "busy")
            pending = dispatch(self.api(), "memory_pending_outcomes", {})
            self.assertEqual(pending["outcomes"], [], pending)
            self.assertTrue(pending.get("index_frozen"), pending)
        finally:
            holder.rollback()
            holder.close()
        rows = self.api().decisions()
        self.assertFalse(rows.get("index_frozen"), rows)
        self.assertEqual(rows["decisions"][0]["outcome_status"], "confirmed")
        self.assertEqual(self.api().get_note(request["path"])["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_blocked_index_cannot_turn_durable_outcome_into_a_failed_capture(self):
        self.decision()
        request = self.reviewed()
        self.api().decisions()
        obstruction = self.vault / ".knowledgeos/index-rebuild.lock"
        obstruction.mkdir()
        result = self.record(request)
        self.assertTrue(result.get("recorded"), result)
        self.assertEqual(result["index_refresh"]["status"], "blocked")
        self.assertTrue(result.get("index_frozen"), result)
        obstruction.rename(obstruction.with_name("retained-index-obstruction"))
        self.assertEqual(dispatch(self.api(), "memory_pending_outcomes", {})["outcomes"], [])

    def test_native_hardlink_target_refuses_without_target_changes(self):
        source = self.decision()
        target = self.vault / "Decisions/Linked.md"
        before = source.read_bytes()
        request = dict(self.reviewed(), path="Decisions/Linked.md", expected_sha256=hashlib.sha256(before).hexdigest())
        os.link(source, target)
        self.assert_refused_unchanged(request, target)
        self.assertEqual(source.read_bytes(), before)

    def test_native_symlink_targets_refuse_without_target_changes(self):
        plain = self.decision("Plain")
        plain_before = plain.read_bytes()
        request = self.reviewed("Plain")
        link = self.vault / "Decisions/Symlink.md"
        try:
            link.symlink_to(plain)
        except OSError as error:
            self.skipTest("Native symlink creation unavailable: " + type(error).__name__)
        self.assert_refused_unchanged(dict(request, path="Decisions/Symlink.md", expected_sha256=hashlib.sha256(plain_before).hexdigest()), plain)
        self.assertEqual(plain.read_bytes(), plain_before)
        directory = self.vault / "LinkedDecisions"
        directory.symlink_to(self.vault / "Decisions", target_is_directory=True)
        self.assert_refused_unchanged(dict(request, path="LinkedDecisions/Plain.md", expected_sha256=hashlib.sha256(plain_before).hexdigest()), plain)

    def test_concurrent_identical_requests_publish_one_outcome(self):
        source = self.decision()
        request = self.reviewed()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.record(request), range(3)))
        self.assertTrue(all(row.get("recorded") for row in results), results)
        self.assertEqual(len({row["sha256"] for row in results}), 1)
        self.assertEqual(source.read_bytes().count(b"outcome_recording:"), 1)
