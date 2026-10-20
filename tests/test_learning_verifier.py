"""Reject empty, stale, unattributed or overgeneralized source observations."""
import copy
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / ".agents/skills/verify-twinaatma/scripts/learning.py"
spec = importlib.util.spec_from_file_location("staged_learning_proof", MODULE)
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


def view(frozen=False):
    result = {"is_error": False, "payload": {"count": 1, "decisions": [{"path": "Decisions/Nova.md", "title": "Current Nova", "status": "archived", "project": "Nova"}]}}
    if frozen:
        result["payload"].update(index_frozen=True, index_frozen_note="Current rows are source-backed, but new notes may be missing.")
    return result


EXPECTED = {"Decisions/Nova.md": {"title": "Current Nova", "status": "archived", "project": "Nova"}}


def lesson():
    proposal = {"is_error": False, "payload": {"ok": True, "proposal_path": "People/Self-Proposals/lesson.md", "proposal_id": "synthetic-id", "section": "heuristics", "policy": "proposal_only", "mutated_self": False}}
    text = "status: draft\nproposal_section: heuristics\nproposal_mode: append\nproposal_target: People/Self.md\nDecision outcome 'confirmed' records this lesson. Source: Decisions/NovaComplete.md. This single recorded outcome does not establish a general belief; review before adopting.\n* **From decision [Synthetic Nova checkpoint](Decisions/NovaComplete.md)**: " + proof.LESSON
    source = "type: decision\noutcome_status: \"confirmed\"\nlesson: " + proof.LESSON
    opened = {"is_error": False, "payload": {"open": [{"path": "People/Self-Proposals/lesson.md", "id": "synthetic-id", "status": "draft"}], "untrusted": []}}
    return proposal, text, source, opened


class LearningVerifierControls(unittest.TestCase):
    def test_populated_current_literal_row_is_required(self):
        self.assertTrue(proof.view_observation(view(), "decisions", EXPECTED)["valid"])
        empty = {"is_error": False, "payload": {"count": 0, "decisions": []}}
        self.assertFalse(proof.view_observation(empty, "decisions", EXPECTED)["valid"])

    def test_stale_title_wrong_project_or_status_is_rejected(self):
        for field, value in (("title", "Stale Nova"), ("project", "Supernova"), ("status", "active")):
            candidate = view()
            candidate["payload"]["decisions"][0][field] = value
            with self.subTest(field=field):
                self.assertFalse(proof.view_observation(candidate, "decisions", EXPECTED)["valid"])

    def test_cross_project_extra_row_and_duplicate_cannot_pass(self):
        for path in ("Decisions/Supernova.md", "Decisions/Nova.md"):
            candidate = view()
            candidate["payload"]["decisions"].append(dict(candidate["payload"]["decisions"][0], path=path))
            candidate["payload"]["count"] = 2
            with self.subTest(path=path):
                self.assertFalse(proof.view_observation(candidate, "decisions", EXPECTED)["valid"])

    def test_busy_requires_visible_incompleteness_and_retry_requires_clear_flag(self):
        self.assertTrue(proof.view_observation(view(True), "decisions", EXPECTED, frozen=True)["valid"])
        self.assertFalse(proof.view_observation(view(), "decisions", EXPECTED, frozen=True)["valid"])
        self.assertFalse(proof.view_observation(view(True), "decisions", EXPECTED)["valid"])

    def test_count_mismatch_or_error_protocol_cannot_pass(self):
        wrong = view()
        wrong["payload"]["count"] = 2
        error = view()
        error["is_error"] = True
        for candidate in (wrong, error):
            self.assertFalse(proof.view_observation(candidate, "decisions", EXPECTED)["valid"])

    def test_timeline_scope_retains_unrelated_source_but_rejects_old_fixture(self):
        expected = {"Decisions/NovaPending.md": {"title": "Current Nova", "status": "archived", "project": "Nova"}}
        candidate = view()
        candidate["payload"]["notes"] = candidate["payload"].pop("decisions")
        candidate["payload"]["notes"][0]["path"] = "Decisions/NovaPending.md"
        candidate["payload"]["notes"].append({"path": "Decisions/_Index.md", "title": "Decisions", "status": "active"})
        candidate["payload"]["count"] = 2
        self.assertTrue(proof.view_observation(candidate, "notes", expected, synthetic_only=True)["valid"])
        candidate["payload"]["notes"].append({"path": "Concepts/LearningOld.md", "title": "Old fixture", "status": "active"})
        candidate["payload"]["count"] = 3
        self.assertFalse(proof.view_observation(candidate, "notes", expected, synthetic_only=True)["valid"])

    def test_completed_linked_uncertain_trusted_draft_can_pass(self):
        observed = proof.lesson_observation(*lesson())
        self.assertTrue(observed["valid"], observed)

    def test_missing_uncertainty_wrong_source_or_missing_lesson_is_rejected(self):
        for old, new in (("This single recorded outcome does not establish a general belief; review before adopting.", "The person always thinks this."), ("Decisions/NovaComplete.md", "Decisions/Fabricated.md"), (proof.LESSON, "Invented universal belief.")):
            proposal, text, source, opened = lesson()
            observed = proof.lesson_observation(proposal, text.replace(old, new), source, opened)
            with self.subTest(old=old):
                self.assertFalse(observed["valid"], observed)

    def test_fabricated_source_or_untrusted_proposal_is_rejected(self):
        proposal, text, source, opened = lesson()
        self.assertFalse(proof.lesson_observation(proposal, text, source.replace('"confirmed"', '"pending"'), opened)["valid"])
        opened["payload"]["open"] = []
        opened["payload"]["untrusted"] = ["People/Self-Proposals/lesson.md"]
        self.assertFalse(proof.lesson_observation(proposal, text, source, opened)["valid"])

    def test_self_mutation_or_accepted_draft_cannot_pass(self):
        proposal, text, source, opened = lesson()
        proposal["payload"]["mutated_self"] = True
        self.assertFalse(proof.lesson_observation(proposal, text, source, opened)["valid"])
        proposal["payload"]["mutated_self"] = False
        opened["payload"]["open"][0]["status"] = "accepted"
        self.assertFalse(proof.lesson_observation(proposal, text, source, opened)["valid"])

    def test_invalid_source_requires_visible_exact_refusal(self):
        result = {"is_error": True, "payload": {"error": "no lesson found on decision", "path": "Decisions/NoLesson.md"}}
        self.assertTrue(proof.refusal_observation(result, "no lesson found on decision", "Decisions/NoLesson.md")["valid"])
        candidate = copy.deepcopy(result)
        candidate["is_error"] = False
        self.assertFalse(proof.refusal_observation(candidate, "no lesson found on decision", "Decisions/NoLesson.md")["valid"])
        self.assertFalse(proof.refusal_observation(result, "no lesson found on decision", "Decisions/Other.md")["valid"])


if __name__ == "__main__":
    unittest.main()
