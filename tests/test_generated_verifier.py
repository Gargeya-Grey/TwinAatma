"""Generated-writer acceptance rejects empty success and destructive refusal."""
import importlib.util
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("generated_proof", SCRIPTS / "generated_writers.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class GeneratedVerifierTests(unittest.TestCase):
    def setUp(self):
        self.output = ROOT / "work/gc-artifacts/.knowledgeos/data-preservation-20261019/tg" / uuid.uuid4().hex[:8]

    def test_complete_inventory_includes_the_legacy_weekly_draft_writer(self):
        self.assertEqual(set(proof.WRITERS), {"draft", "trajectory", "weekly", "views", "experiments", "outcomes"})
        self.assertEqual(sum(len(row["outputs"]) for row in proof.WRITERS.values()), 10)
        self.assertEqual(proof.WRITERS["draft"]["outputs"], ["Research/Synthesis/{today}-weekly-draft.md"])

    def test_weekly_draft_recovers_after_real_report_replace_fault(self):
        run = proof.GeneratedRun(self.output)
        run.case("draft", "report_fault")
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertTrue(all(process["stopped"] for process in run.processes))

    def test_receipt_allowance_cannot_hide_unrelated_note_damage(self):
        before = {"vault/MOCs/user.md": {"sha256": "original"}}
        after = {"vault/MOCs/user.md": {"sha256": "edited"}, "vault/.knowledgeos/generated/receipt": {"sha256": "new"}}
        result = proof.compare(before, after, ["vault/MOCs/generated.md", "vault/.knowledgeos/generated"])
        self.assertEqual(result, {"unchanged": False, "changed": ["vault/MOCs/user.md"]})

    def test_output_must_be_a_nonempty_plain_generated_report(self):
        self.output.mkdir(parents=True)
        path = self.output / "report.md"
        for payload, expected in ((b"", False), (b"Wrote report", False), (b"---\ntitle: Draft\n---\nNewly recorded decision\n", True)):
            path.write_bytes(payload)
            observed = proof.report_evidence(self.output, ["report.md"])
            self.assertEqual(observed["usable"], expected)
        self.assertEqual(proof.report_evidence(self.output, ["missing.md"])["usable"], False)

    def test_actual_public_writer_recovers_after_real_report_replace_fault(self):
        run = proof.GeneratedRun(self.output)
        run.case("trajectory", "report_fault")
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        observed = run.cases[0]["observed"]
        self.assertEqual(observed["exit_code"] != 0, True)
        self.assertEqual(observed["unchanged"], True)
        self.assertEqual(observed["retry"]["exit_code"], 0)
        self.assertEqual(observed["repeat"]["unchanged"], True)
        self.assertTrue(all(process["stopped"] for process in run.processes))

    def test_zero_exit_without_actual_reports_cannot_pass_bootstrap(self):
        run = proof.GeneratedRun(self.output)
        actual = run.fixture
        def fixture(label):
            scope, vault, outside = actual(label)
            (vault / "scripts/experiment_dashboard.py").write_text("print('Wrote report successfully')\n", encoding="utf-8")
            return scope, vault, outside
        run.fixture = fixture
        with self.assertRaisesRegex(RuntimeError, "Initial public report"):
            run.case("experiments", "regenerate")
        self.assertFalse(run.cases)
        self.assertTrue(all(process["stopped"] for process in run.processes))

    def test_refusal_with_user_report_damage_is_failed(self):
        run = proof.GeneratedRun(self.output)
        actual = run.fixture
        def fixture(label):
            scope, vault, outside = actual(label)
            (vault / "scripts/experiment_dashboard.py").write_text(
                "from pathlib import Path\nimport sys\nPath('MOCs/_MOC_Experiments.md').write_bytes(b'damaged')\nprint('Refused', file=sys.stderr)\nraise SystemExit(1)\n", encoding="utf-8")
            return scope, vault, outside
        run.fixture = fixture
        run.case("experiments", "unowned")
        self.assertEqual(run.cases[0]["observed"]["exit_code"], 1)
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assertIn("vault/MOCs/_MOC_Experiments.md", run.cases[0]["observed"]["changed"])


if __name__ == "__main__":
    unittest.main()
