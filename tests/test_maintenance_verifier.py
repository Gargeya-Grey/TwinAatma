"""Source maintenance proof rejects false success and destructive refusals."""
import importlib.util
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("maintenance_proof", SCRIPTS / "maintenance.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class MaintenanceVerifierTests(unittest.TestCase):
    def run_fixture(self, journey, replacement=None, destination=None):
        output = ROOT / "work/gc-artifacts/.knowledgeos/maintenance-20261019/t" / uuid.uuid4().hex[:8]
        run = proof.MaintenanceRun(output, journey)
        original = run.prepared_fixture
        if replacement is not None:
            def fixture():
                scope, vault, outside = original()
                (vault / destination).write_text(replacement, encoding="utf-8")
                return scope, vault, outside
            run.prepared_fixture = fixture
        return run

    def assert_stopped(self, run):
        self.assertTrue(run.processes)
        self.assertTrue(all(process["stopped"] for process in run.processes), run.processes)

    def test_id_success_without_the_literal_note_edit_is_failed(self):
        code = ("import json\ndef main(args):\n"
                "    print(json.dumps({'changes':[{'path':'Inbox/Add.md','old_id':'','new_id':'kos:concept:new-note-2','written':True}]}))\n"
                "    return 0\n")
        run = self.run_fixture("maintenance", code, "knowledgeos/__main__.py")
        run.run_case("ids_write")
        self.assertEqual(run.cases[0]["observed"]["exit_code"], 0)
        self.assertEqual(run.cases[0]["observed"]["literal_note_bytes_match"], False)
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assert_stopped(run)

    def test_destructive_hook_refusal_is_failed(self):
        code = ("from pathlib import Path\nimport sys\n"
                "Path('.git/hooks/pre-commit').write_bytes(b'damaged')\n"
                "print('Preserving existing hook', file=sys.stderr)\nraise SystemExit(1)\n")
        run = self.run_fixture("hooks", code, "scripts/setup_git_hooks.py")
        run.run_case("existing")
        self.assertEqual(run.cases[0]["observed"]["exit_code"], 1)
        self.assertEqual(run.cases[0]["observed"]["changed"], ["vault/.git/hooks/pre-commit"])
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assert_stopped(run)

    def test_hook_success_without_a_runnable_hook_is_failed(self):
        run = self.run_fixture("hooks", "print('Hook setup successfully!')\n", "scripts/setup_git_hooks.py")
        run.run_case("custom")
        self.assertEqual(run.cases[0]["observed"]["exit_code"], 0)
        self.assertEqual(run.cases[0]["observed"]["installed_hook_present"], False)
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assert_stopped(run)

    def test_validator_false_green_on_an_invalid_date_is_failed(self):
        code = ("def validate_vault(vault):\n"
                "    return {'notes_checked':7,'errors':[],'warnings':[],'summary':{'errors':0,'warnings':0}}\n")
        run = self.run_fixture("validation", code, "knowledgeos/validator.py")
        run.run_case("date")
        self.assertEqual([row["exit_code"] for row in run.cases[0]["observed"]["entrypoints"]], [0, 0])
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assert_stopped(run)

    def test_valid_readonly_observations_satisfy_the_literal_good_gate(self):
        code = ("def validate_vault(vault):\n"
                "    return {'notes_checked':7,'errors':[],'warnings':[],'summary':{'errors':0,'warnings':0}}\n")
        run = self.run_fixture("validation", code, "knowledgeos/validator.py")
        run.run_case("good")
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertEqual(run.cases[0]["observed"]["unchanged"], True)
        self.assertEqual([row["notes_checked"] for row in run.cases[0]["observed"]["entrypoints"]], [7, 7])
        self.assertEqual([row["errors"] for row in run.cases[0]["observed"]["entrypoints"]], [[], []])
        self.assert_stopped(run)

    def test_actual_link_replace_fault_runs_and_preserves_originals(self):
        run = self.run_fixture("maintenance")
        run.run_case("links_replace_fault")
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertEqual(run.cases[0]["observed"]["exit_code"], 1)
        self.assertEqual(run.cases[0]["observed"]["unchanged"], True)
        self.assertTrue(run.nested_process_tracking_complete)
        self.assert_stopped(run)


if __name__ == "__main__":
    unittest.main()
