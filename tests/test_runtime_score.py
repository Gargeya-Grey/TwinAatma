"""Runtime matrix outcomes cannot be credited by partial or mislabeled evidence."""
import importlib.util
from pathlib import Path
import unittest
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_score", ROOT / ".agents/skills/verify-twinaatma/scripts/acceptance.py")
metric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metric)

class RuntimeScoreTests(unittest.TestCase):
    def installation(self, platform=None):
        base = ROOT / "work/gc-artifacts/.knowledgeos/runtime-hooks-20261019/scorer-location-tests"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        environment = Path(temporary.name)
        origin = environment / "site-packages/knowledgeos/__init__.py"
        origin.parent.mkdir(parents=True); origin.write_text("")
        platform = platform or ("Windows" if os.name == "nt" else "Linux")
        python = environment / ("Scripts/python.exe" if platform == "Windows" else "bin/python")
        python.parent.mkdir(); python.write_bytes(b"interpreter path fixture")
        observed = {"prefix": str(environment), "origin": str(origin), "executable": str(python)}
        installed = {"environment": str(environment), "import_origin": str(origin), "python": str(python)}
        return observed, installed, platform, python

    def test_runtime_interpreter_must_stay_lexically_in_the_retained_environment(self):
        observed, installed, platform, python = self.installation()
        metric.checked_runtime_location(observed, installed, platform)
        observed["executable"] = installed["python"] = sys.executable
        with self.assertRaisesRegex(ValueError, "recorded venv"):
            metric.checked_runtime_location(observed, installed, platform)

    def test_windows_origin_case_alias_identifies_the_same_physical_package(self):
        observed, installed, platform, python = self.installation("Windows")
        alias = Path(observed["origin"].replace("site-packages", "SITE-PACKAGES"))
        if not alias.is_file():
            self.skipTest("Case-sensitive storage does not represent a Windows origin alias")
        self.assertTrue(alias.samefile(Path(installed["import_origin"])))
        observed["origin"] = str(alias)
        metric.checked_runtime_location(observed, installed, platform)

    def test_another_origin_path_cannot_pass_only_because_it_is_a_hardlink(self):
        observed, installed, platform, python = self.installation()
        other = python.parent / "other-origin.py"
        try:
            os.link(installed["import_origin"], other)
        except OSError as error:
            self.skipTest("Hardlinks unavailable: " + str(error))
        self.assertTrue(other.samefile(Path(installed["import_origin"])))
        observed["origin"] = str(other)
        with self.assertRaisesRegex(ValueError, "retained installation"):
            metric.checked_runtime_location(observed, installed, platform)

    @unittest.skipIf(os.name == "nt", "Standard POSIX venv system-interpreter link")
    def test_real_system_interpreter_link_is_a_valid_venv_executable(self):
        observed, installed, platform, python = self.installation()
        python.unlink(); python.symlink_to("/usr/bin/python3")
        self.assertTrue(python.is_symlink())
        with self.assertRaisesRegex(ValueError, "escapes"):
            metric.retained_path(str(python))
        metric.checked_runtime_location(observed, installed, platform)

    def reports(self):
        return [{"cell": list(cell), "checks": {key: {"id": key, "verdict": "PASS", "observed": True}
                                                  for key in metric.HOOK_IDS}}
                for cell in sorted(metric.RUNTIME_MATRIX)]

    def test_partial_matrix_earns_no_runtime_outcome(self):
        aggregate = metric.runtime_hook_matrix(self.reports()[:-1])
        item = next(row for row in metric.read_json(metric.RUBRIC)["outcomes"] if row["id"] == "SETUP.runtime_hooks")
        self.assertEqual(metric.outcome(item, [aggregate])["verdict"], "NOT CHECKED")

    def test_complete_actual_matrix_awards_exactly_one_fixed_outcome(self):
        aggregate = metric.runtime_hook_matrix(self.reports())
        outcomes = metric.read_json(metric.RUBRIC)["outcomes"]
        passed = [row["id"] for row in outcomes if metric.outcome(row, [aggregate])["verdict"] == "PASS"]
        self.assertEqual(passed, ["SETUP.runtime_hooks"])
        self.assertEqual(len(outcomes), 54)
        self.assertEqual(metric.sha(metric.RUBRIC), "744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91")

    def test_duplicate_cell_is_refused(self):
        rows = self.reports()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            metric.runtime_hook_matrix(rows + rows[:1])

    def test_missing_case_cannot_count_as_complete_usable_matrix(self):
        rows = self.reports()
        rows[0]["checks"].pop("hook.prewarm_runs")
        aggregate = metric.runtime_hook_matrix(rows)
        self.assertEqual(aggregate["checks"]["hook.runtime_matrix_usable"]["verdict"], "FAIL")

    def test_any_failed_runtime_vetoes_the_outcome(self):
        rows = self.reports()
        rows[0]["checks"]["hook.vault_code_not_executed"]["verdict"] = "FAIL"
        aggregate = metric.runtime_hook_matrix(rows)
        item = next(row for row in metric.read_json(metric.RUBRIC)["outcomes"] if row["id"] == "SETUP.runtime_hooks")
        self.assertEqual(metric.outcome(item, [aggregate])["verdict"], "FAIL")

if __name__ == "__main__":
    unittest.main()
