"""Tamper and recomputation controls for the signing-state extension grader.

The controls need the retained Windows wheel and executable reports from
``signing_state.py``. Point TWIN_SIGNING_WHEEL_REPORT and TWIN_SIGNING_BINARY_REPORT at
them, or leave the newest retained pair beneath work/gc-artifacts/.knowledgeos/signing.
Without reports the tests skip.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
SIGNING = ROOT / "work/gc-artifacts/.knowledgeos/signing"
sys.path.insert(0, str(SCRIPTS))
import signing_state as producer  # noqa: E402
import signing_state_adapter as grader  # noqa: E402

DOCTOR_FIX = "  [WARNING] The signing key was missing; a new one was created, so older approvals cannot be verified.\n"
REFUSAL_FIX = "Restore your signing key backup, or ask for a new proposal.\n"


def retained(kind):
    configured = os.environ.get("TWIN_SIGNING_" + kind.upper() + "_REPORT")
    if configured:
        return Path(configured).absolute()
    found = sorted(SIGNING.glob("run-" + kind + "/*/report.json"))
    return found[-1] if found else None


def sha(path):
    return producer.sha(path)


class SigningStateAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = {kind: retained(kind) for kind in ("wheel", "binary")}
        if not all(cls.reports.values()):
            raise unittest.SkipTest("Retained Windows wheel and executable signing-state reports are required")
        spec = importlib.util.spec_from_file_location("acceptance", SCRIPTS / "acceptance.py")
        cls.metric = importlib.util.module_from_spec(spec)
        sys.modules["acceptance"] = cls.metric
        spec.loader.exec_module(cls.metric)
        cls.current = cls.metric.product_hashes()
        SIGNING.joinpath("test-tmp").mkdir(exist_ok=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=SIGNING / "test-tmp")
        self.addCleanup(self.temporary.cleanup)

    def copy_run(self, kind):
        source = self.reports[kind].parent
        target = Path(self.temporary.name) / (kind + "-" + str(len(list(Path(self.temporary.name).iterdir()))))
        target.mkdir()
        for entry in source.iterdir():
            if entry.is_file():
                shutil.copyfile(entry, target / entry.name)
        return target / "report.json"

    def edit(self, report, mutate):
        data = json.loads(report.read_text(encoding="utf-8"))
        mutate(data)
        report.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return report

    def reseal(self, report):
        """Rehash the evidence and recompute the cases, as a producer that observed these files would."""
        def mutate(data):
            data["evidence_files"] = {p.name: sha(p) for p in sorted(report.parent.iterdir()) if p.is_file() and p.name != "report.json"}
            data["cases"] = json.loads(json.dumps(producer.evaluate(report.parent)))
            data["verdict"] = "PASS" if all(row["verdict"] == "PASS" for row in data["cases"]) else "FAIL"
        return self.edit(report, mutate)

    def append(self, report, name, text):
        with (report.parent / name).open("a", encoding="utf-8", newline="") as stream:
            stream.write(text)

    def fixed(self, kind):
        report = self.copy_run(kind)
        self.append(report, "doctor-lost.stdout.txt", DOCTOR_FIX)
        self.append(report, "approve-lost-A.stderr.txt", REFUSAL_FIX)
        return self.reseal(report)

    def grade(self, *reports, current=None):
        return grader.grade(self.metric, [Path(p) for p in reports], current or self.current)

    def verdicts(self, reports):
        return {tuple(row["cell"]): row["checks"][grader.CHECK]["verdict"] for row in reports}

    def test_real_reports_are_recomputed_not_copied(self):
        reports = self.grade(self.reports["wheel"], self.reports["binary"])
        claimed = {}
        for kind, path in self.reports.items():
            data = json.loads(path.read_text(encoding="utf-8"))
            claimed[("Windows", kind)] = ("PASS" if all(row["verdict"] == "PASS" for row in data["cases"]) else "FAIL",
                                          sorted(row["id"] for row in data["cases"] if row["verdict"] != "PASS"))
        for row in reports:
            check = row["checks"][grader.CHECK]
            expected_verdict, expected_failed = claimed[tuple(row["cell"])]
            self.assertEqual(check["observed"]["failed_cases"], expected_failed)
            self.assertEqual(check["observed"]["cell_verdict"], expected_verdict)
            self.assertEqual(row["scope"], "artifact")
            self.assertEqual(set(row["checks"]), {grader.CHECK})
        self.assertIs(self.metric.retained_path.__module__, self.metric.__name__)

    def test_valid_complete_evidence_passes_both_cells_and_scores_one_outcome(self):
        wheel, binary = self.fixed("wheel"), self.fixed("binary")
        self.assertEqual(self.verdicts(self.grade(wheel, binary)), {("Windows", "wheel"): "PASS", ("Windows", "binary"): "PASS"})
        score = self.metric.snapshot([], [], extension_paths={"signing-state": [wheel.absolute(), binary.absolute()]})
        self.assertEqual(score["outcomes"]["PORT.missing_signing_state"]["verdict"], "PASS")
        self.assertEqual(score["counts"]["PASS"], 1)
        self.assertEqual([key for key, row in score["outcomes"].items() if row["verdict"] != "NOT CHECKED"], ["PORT.missing_signing_state"])
        spec = self.metric.EXTENSION_ADAPTERS["signing-state"]
        self.assertEqual((spec["module"], spec["scope"], spec["outcomes"]),
                         ("signing_state_adapter", "artifact", {"PORT.missing_signing_state": [grader.CHECK]}))
        self.assertEqual(self.metric.ADAPTER_REQUIREMENTS["extensions"]["signing-state"]["module_sha256"], sha(grader.__file__))

    def test_one_cell_only_is_not_a_pass(self):
        wheel = self.fixed("wheel")
        self.assertEqual(self.verdicts(self.grade(wheel)), {("Windows", "wheel"): "NOT CHECKED"})
        score = self.metric.snapshot([], [], extension_paths={"signing-state": [wheel.absolute()]})
        self.assertNotEqual(score["outcomes"]["PORT.missing_signing_state"]["verdict"], "PASS")
        self.assertEqual(score["counts"]["PASS"], 0)
        broken = self.fixed("binary")
        (broken.parent / "list-restored.stdout.txt").write_text("", encoding="utf-8")
        self.reseal(broken)
        self.assertEqual(self.verdicts(self.grade(broken)), {("Windows", "binary"): "FAIL"})

    def test_truthful_failure_in_one_cell_survives_a_passing_cell(self):
        wheel, binary = self.fixed("wheel"), self.fixed("binary")
        (binary.parent / "list-restored.stdout.txt").write_text("", encoding="utf-8")
        self.reseal(binary)
        reports = self.grade(wheel, binary)
        self.assertEqual(self.verdicts(reports), {("Windows", "wheel"): "PASS", ("Windows", "binary"): "FAIL"})
        failed = [row for row in reports if tuple(row["cell"]) == ("Windows", "binary")][0]["checks"][grader.CHECK]["observed"]["failed_cases"]
        self.assertEqual(failed, ["signing.restore_old_valid_again"])
        score = self.metric.snapshot([], [], extension_paths={"signing-state": [wheel.absolute(), binary.absolute()]})
        self.assertEqual(score["outcomes"]["PORT.missing_signing_state"]["verdict"], "FAIL")

    def test_missing_recovery_hint_or_cause_is_a_failure_not_an_exception(self):
        report = self.copy_run("wheel")
        (report.parent / "approve-lost-A.stderr.txt").write_text("proposal is not registered in this install's Self proposal ledger\n", encoding="utf-8")
        (report.parent / "doctor-lost.stdout.txt").write_text("  [OK] Proposal ledger is signed (0 entries, outside the vault).\n", encoding="utf-8")
        self.reseal(report)
        row = self.grade(report)[0]["checks"][grader.CHECK]["observed"]
        self.assertEqual(row["cell_verdict"], "FAIL")
        self.assertIn("signing.lost_old_approval_refused", row["failed_cases"])
        self.assertIn("signing.lost_doctor_honest", row["failed_cases"])

    def test_a_prompt_reached_by_the_hidden_console_fails(self):
        report = self.fixed("wheel")
        path = report.parent / "approve-lost-A.command.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(timed_out=True, exit_code=1)
        path.write_text(json.dumps(record), encoding="utf-8")
        data = json.loads(report.read_text(encoding="utf-8"))
        for row in data["processes"]:
            if row["role"] == "approve-lost-A":
                row["timed_out"] = True
        report.write_text(json.dumps(data), encoding="utf-8")
        self.reseal(report)
        observed = self.grade(report)[0]["checks"][grader.CHECK]["observed"]
        self.assertEqual(observed["cell_verdict"], "FAIL")
        self.assertIn("signing.lost_old_approval_refused", observed["failed_cases"])

    def test_tampered_reports_are_refused(self):
        def stale_product(data):
            data["product_hashes"]["knowledgeos/gate.py"] = "0" * 64

        def stale_after(data):
            data["product_hashes_after"]["knowledgeos/gate.py"] = "0" * 64

        def flip_first_case(data):
            data["cases"][0]["verdict"] = "FAIL" if data["cases"][0]["verdict"] == "PASS" else "PASS"

        def flip_verdict(data):
            data["verdict"] = "PASS" if data["verdict"] == "FAIL" else "FAIL"

        def fake_observation(data):
            data["cases"][2]["observed"]["capture_ok"] = not data["cases"][2]["observed"]["capture_ok"]

        mutations = {
            "stale-product": stale_product,
            "stale-product-after": stale_after,
            "deleted-product-entry": lambda data: data["product_hashes"].pop("knowledgeos/gate.py"),
            "stale-producer": lambda data: data.update(producer_sha256="0" * 64),
            "stale-support": lambda data: data["support_sha256"].update({"artifact.py": "0" * 64}),
            "wrong-producer": lambda data: data.update(producer="verify-twinaatma.other/v1"),
            "scope-laundering": lambda data: data.update(scope="real_host"),
            "wrong-cell": lambda data: data.update(cell=["Windows", "binary"]),
            "linux-cell": lambda data: data.update(cell=["Linux", "wheel"]),
            "forged-case-verdict": flip_first_case,
            "forged-observation": fake_observation,
            "forged-report-verdict": flip_verdict,
            "missing-case": lambda data: data["cases"].pop(),
            "extra-case": lambda data: data["cases"].append({"id": "signing.invented", "verdict": "PASS"}),
            "duplicate-case": lambda data: data["cases"].append(copy.deepcopy(data["cases"][0])),
            "reordered-cases": lambda data: data["cases"].reverse(),
            "shortened-frozen-list": lambda data: data["expected_case_ids"].pop(),
            "unstopped-process": lambda data: data["processes"][0].update(stopped=False),
            "unstopped-flag": lambda data: data.update(all_started_processes_stopped=False),
            "missing-process": lambda data: data["processes"].pop(),
            "wrong-process-pid": lambda data: data["processes"][0].update(pid=data["processes"][0]["pid"] + 1),
            "wrong-process-role": lambda data: data["processes"][0].update(role="other"),
            "console-misdeclared": lambda data: [row.update(console=not row["console"]) for row in data["processes"] if row["role"] == "approve-notty"],
            "changed-sentinel": lambda data: data["isolation"]["after"].update({next(iter(data["isolation"]["after"])): "0" * 64}),
            "unchanged-claim-removed": lambda data: data["isolation"].update(selected_sentinels_unchanged=False),
            "unchanged-product-claim": lambda data: data.update(product_and_producer_unchanged=False),
            "artifact-changed-claim": lambda data: data.update(artifact_unchanged=False),
            "execution-error": lambda data: data.update(error="RuntimeError: stopped early"),
            "wrong-artifact-bytes": lambda data: data["artifact"].update(sha256="0" * 64),
            "wrong-launcher-bytes": lambda data: data["artifact"].update(executable_sha256="0" * 64),
            "wrong-artifact-report-hash": lambda data: data["artifact"].update(report_sha256="0" * 64),
            "other-artifact-kind": lambda data: data["artifact"].update(kind="binary"),
            "other-artifact-file": lambda data: data["artifact"].update(path=str(producer.__file__), sha256=sha(producer.__file__)),
            "evidence-name-escape": lambda data: data["evidence_files"].update({"../plan.json": "0" * 64}),
            "evidence-hash": lambda data: data["evidence_files"].update({"snap-1.json": "0" * 64}),
            "evidence-dropped": lambda data: data["evidence_files"].pop("snap-1.json"),
            "windows-platform-removed": lambda data: data.update(platform="Linux-6.0"),
        }
        for name, mutation in mutations.items():
            report = self.edit(self.copy_run("wheel"), mutation)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.grade(report)
            self.assertIs(self.metric.retained_path.__module__, self.metric.__name__)

    def test_altered_missing_extra_or_linked_evidence_is_refused(self):
        report = self.copy_run("wheel")
        self.append(report, "list-0.stdout.txt", "\n")
        with self.subTest(name="altered"), self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.grade(report)
        report = self.copy_run("wheel")
        (report.parent / "snap-1.json").unlink()
        with self.subTest(name="missing"), self.assertRaises(ValueError):
            self.grade(report)
        report = self.copy_run("wheel")
        (report.parent / "unhashed.txt").write_text("extra", encoding="utf-8")
        with self.subTest(name="extra"), self.assertRaisesRegex(ValueError, "inventory"):
            self.grade(report)
        report = self.copy_run("wheel")
        target = report.parent / "snap-1.json"
        original = target.read_bytes()
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_bytes(original)
        target.unlink()
        try:
            os.symlink(outside, target)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are not available")
        with self.subTest(name="linked"), self.assertRaises(ValueError):
            self.grade(report)

    def test_a_frozen_list_written_after_the_first_product_call_is_refused(self):
        report = self.copy_run("wheel")
        plan = report.parent / "plan.json"
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["frozen_at_ns"] = 2 ** 62
        plan.write_text(json.dumps(data), encoding="utf-8")
        self.reseal(report)
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.grade(report)

    def test_stale_current_product_or_changed_producer_file_is_refused(self):
        stale = dict(self.current, **{"knowledgeos/gate.py": "0" * 64})
        with self.assertRaises(ValueError):
            self.grade(self.reports["wheel"], current=stale)
        removed = {key: value for key, value in self.current.items() if key != "knowledgeos/gate.py"}
        with self.assertRaises(ValueError):
            self.grade(self.reports["wheel"], current=removed)

    def test_duplicate_cells_are_refused(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.grade(self.reports["wheel"], self.reports["wheel"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.grade(self.reports["binary"], self.copy_run("binary"))


if __name__ == "__main__":
    unittest.main()
