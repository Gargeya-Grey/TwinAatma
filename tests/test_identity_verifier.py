"""Identity source proof distinguishes truthful observations from false success."""
import importlib.util
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("identity_source_proof", SCRIPTS / "identity.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class IdentityVerifierTests(unittest.TestCase):
    def run_fixture(self, journey, kind):
        run = proof.IdentityRun(ROOT / "work/gc-artifacts/.knowledgeos/identity-proof-20261019/controls" / uuid.uuid4().hex[:8], journey)
        return run, run.prepare(kind)

    def override(self, fixture, definition):
        with (fixture["toolkit"] / "knowledgeos/memory.py").open("a", encoding="utf-8") as stream:
            stream.write("\n" + definition + "\n")

    def assert_stopped(self, run):
        self.assertTrue(run.processes)
        self.assertTrue(all(row["stopped"] and isinstance(row["exit_code"], int) for row in run.processes), run.processes)

    def test_empty_session_context_does_not_prove_unknown_identity(self):
        run, fixture = self.run_fixture("unknown", "cold")
        self.override(fixture, "MemoryAPI.bootstrap_context = lambda self, **kwargs: {}")
        run.read_case(fixture, "cold_session_start", session=True, unknown=True)
        self.assertEqual(run.cases[0]["verdict"], "FAIL", run.cases)
        self.assertFalse(run.cases[0]["observed"]["all_six_sections_present"])
        self.assert_stopped(run)

    def test_attributed_values_are_not_accepted_as_unknown(self):
        run, fixture = self.run_fixture("unknown", "cold")
        self.override(fixture, "_identity_original_self_get = MemoryAPI.self_get\n"
                      "def invented_self_get(self):\n"
                      "    payload = _identity_original_self_get(self)\n"
                      "    payload['sections']['values'] = '<!-- kos:section=values -->\\n1. Wealth is your highest priority.'\n"
                      "    return payload\n"
                      "MemoryAPI.self_get = invented_self_get")
        run.read_case(fixture, "cold_self_get", unknown=True)
        self.assertEqual(run.cases[0]["verdict"], "FAIL", run.cases)
        self.assertFalse(run.cases[0]["observed"]["unknown_attributes"]["values"])
        self.assert_stopped(run)

    def test_successful_proposal_response_without_persistence_fails(self):
        run, fixture = self.run_fixture("canonical", "marked")
        self.override(fixture, "def empty_proposal(self, summary, section, proposed_markdown, **kwargs):\n"
                      "    return {'ok':True, 'section':section, 'policy':'proposal_only', 'mutated_self':False, 'proposal_path':'People/Self-Proposals/not-written.md'}\n"
                      "MemoryAPI.propose_self_update = empty_proposal")
        run.proposals_case(fixture, "marked_proposals")
        self.assertEqual(run.cases[0]["verdict"], "FAIL", run.cases)
        self.assertEqual(len(run.cases[0]["observed"]["targets"]), 6)
        self.assertTrue(all(not row["plain_contained_proposal"] for row in run.cases[0]["observed"]["targets"]))
        self.assert_stopped(run)

    def test_guessing_a_duplicate_section_is_not_a_refusal(self):
        run, fixture = self.run_fixture("canonical", "duplicate")
        self.override(fixture, "MemoryAPI.self_get = lambda self: " + repr({"path": "People/Self.md", "sections": proof.expected_sections("marked")}))
        run.read_case(fixture, "duplicate_self_get", duplicate=True)
        self.assertEqual(run.cases[0]["verdict"], "FAIL", run.cases)
        self.assertFalse(run.cases[0]["observed"]["is_error"])
        self.assert_stopped(run)

    def test_actual_canonical_proposals_persist_without_changing_self(self):
        run, fixture = self.run_fixture("canonical", "aliases")
        run.proposals_case(fixture, "aliases_proposals")
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertTrue(run.cases[0]["observed"]["exact_six_draft_files"])
        self.assertTrue(run.cases[0]["observed"]["self_bytes_unchanged"])
        self.assertEqual([row["section"] for row in run.cases[0]["observed"]["targets"]], list(proof.SECTIONS))
        self.assert_stopped(run)

    def test_actual_duplicate_proposal_is_refused_without_new_evidence(self):
        run, fixture = self.run_fixture("canonical", "duplicate")
        run.proposals_case(fixture, "duplicate_proposal", duplicate=True)
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertTrue(run.cases[0]["observed"]["targets"][0]["proposal_evidence_unchanged"])
        self.assertTrue(run.cases[0]["observed"]["self_bytes_unchanged"])
        self.assert_stopped(run)


if __name__ == "__main__":
    unittest.main()
