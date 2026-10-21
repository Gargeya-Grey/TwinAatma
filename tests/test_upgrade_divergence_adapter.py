"""Tamper controls for the independent upgrade and device-divergence grader.

Set TWIN_UPGRADE_DIVERGENCE_REPORT to a retained report.json from upgrade_divergence.py.
Without it, the newest report under work/gc-artifacts/.knowledgeos/upgrade/report is used.
The tests skip when no report exists.
"""
import copy
import hashlib
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
sys.path.insert(0, str(SCRIPTS))
import upgrade_divergence_adapter as grader

REPORT_DIR = ROOT / "work/gc-artifacts/.knowledgeos/upgrade/report"


def find_report():
    if os.environ.get("TWIN_UPGRADE_DIVERGENCE_REPORT"):
        return Path(os.environ["TWIN_UPGRADE_DIVERGENCE_REPORT"]).absolute()
    reports = sorted(REPORT_DIR.glob("*/report.json")) if REPORT_DIR.is_dir() else []
    return reports[-1] if reports else None


REPORT = find_report()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class UpgradeDivergenceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPORT is None:
            raise unittest.SkipTest("A retained upgrade-divergence report is required")
        spec = importlib.util.spec_from_file_location("acceptance_under_test", SCRIPTS / "acceptance.py")
        cls.api = importlib.util.module_from_spec(spec)
        sys.modules["acceptance_under_test"] = cls.api
        spec.loader.exec_module(cls.api)
        original = cls.api.retained_path

        def contained(value):
            # In a git worktree the scorer maps a path below its own ROOT onto a doubled path
            # and refuses it. Accept an absolute path already below ROOT; all other checks are the scorer's.
            if isinstance(value, str) and value and Path(value).is_absolute():
                path = Path(value)
                try:
                    path.absolute().relative_to(cls.api.ROOT.absolute())
                    path.resolve(strict=True).relative_to(cls.api.ROOT.resolve())
                    return path
                except (ValueError, OSError):
                    pass
            return original(value)

        cls.api.retained_path = contained
        cls.current = cls.api.product_hashes()
        cls.original = json.loads(REPORT.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("acceptance_under_test", None)

    def data(self):
        return copy.deepcopy(self.original)

    def grade(self, data=None, report=None):
        return grader.grade_report(self.api, report or REPORT, self.current, data=data)

    def refuses(self, name, mutate, pattern=None):
        data = self.data()
        mutate(data)
        with self.subTest(name=name):
            if pattern:
                with self.assertRaisesRegex(ValueError, pattern):
                    self.grade(data)
            else:
                with self.assertRaises(ValueError):
                    self.grade(data)

    def first_row(self, verdict):
        return next(index for index, row in enumerate(self.original["cases"]) if row["verdict"] == verdict)

    def test_real_report_keeps_its_truthful_verdict(self):
        graded = self.grade()
        check = graded["checks"][grader.CHECK]
        failed = sorted(row["id"] for row in self.original["cases"] if row["verdict"] != "PASS")
        self.assertEqual(graded["scope"], "artifact")
        self.assertEqual(set(graded["case_results"]), set(grader.CASE_IDS))
        self.assertEqual(check["observed"]["failed"], failed)
        self.assertEqual(check["verdict"], "PASS" if not failed else "FAIL")
        self.assertEqual(check["observed"]["passed"], len(grader.CASE_IDS) - len(failed))
        self.assertEqual(self.original["verdict"], check["verdict"])

    def test_grade_entry_point_accepts_the_report_path(self):
        self.assertEqual(grader.grade(self.api, [REPORT], self.current)[0]["report_sha256"], self.api.sha(REPORT))

    def test_every_case_is_recomputed_from_retained_evidence(self):
        evidence = grader.Evidence(REPORT.parent, self.original)
        for row in self.original["cases"]:
            with self.subTest(case=row["id"]):
                self.assertEqual(grader.case_row(evidence, row["id"]), row)
                self.assertTrue(row["evidence"], "a case must cite retained evidence")

    def test_a_missing_call_fails_the_case_instead_of_passing(self):
        data = self.data()
        data["calls"] = [row for row in data["calls"] if row["label"] != "dv-b-approve-pa"]
        evidence = grader.Evidence(REPORT.parent, data)
        for case in ("divergence.foreign_proposal_refused", "divergence.refusal_hints_propose_again"):
            with self.subTest(case=case):
                self.assertEqual(grader.case_row(evidence, case)["verdict"], "FAIL")
                self.assertIn("missing call", grader.case_row(evidence, case)["observed"]["error"])

    def test_missing_extra_and_reordered_cases_are_refused(self):
        self.refuses("missing", lambda d: d["cases"].pop(3), "Missing, extra or reordered")
        self.refuses("last-missing", lambda d: d["cases"].pop(), "Missing, extra or reordered")
        self.refuses("extra", lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])), "Missing, extra or reordered")
        self.refuses("reordered", lambda d: d["cases"].reverse(), "Missing, extra or reordered")
        self.refuses("plan-shortened", lambda d: d["expected_case_ids"].pop(), "Case plan")

    def test_stale_or_edited_hashes_are_refused(self):
        self.refuses("stale-product", lambda d: d["product_hashes"].update({"knowledgeos/gate.py": "0" * 64}), "product")
        self.refuses("deleted-product", lambda d: d["product_hashes"].pop("knowledgeos/gate.py"), "product")
        self.refuses("stale-producer", lambda d: d.update(producer_sha256="0" * 64), "producer hash")
        self.refuses("stale-support", lambda d: d["support"].update({grader.SUPPORT_NAME: "0" * 64}), "support hash")
        self.refuses("wrong-producer", lambda d: d.update(producer="verify-twinaatma.other/v1"), "Unsupported")
        self.refuses("scope-laundering", lambda d: d.update(scope="real_host"), "scope")

    def test_altered_evidence_is_refused(self):
        name = next(n for n in self.original["transcript_files"] if n.endswith("dv-b-approve-pa.stderr.txt"))
        self.refuses("transcript-hash", lambda d: d["transcript_files"].update({name: "0" * 64}), "Evidence changed")
        self.refuses("observer-hash", lambda d: d["transcript_files"].update({grader.OBSERVER_NAME: "0" * 64}), "Evidence changed")
        self.refuses("dropped-evidence", lambda d: d["transcript_files"].pop(name), "Unhashed")
        self.refuses("plan-hash", lambda d: d["transcript_files"].update({"case-plan.json": "0" * 64}), "Evidence changed")
        self.refuses("tree-hash", lambda d: d["final_trees"]["device-b/vault"].update({"People/Self.md": "0" * 64}), "Retained state changed")
        self.refuses("dropped-tree", lambda d: d["final_trees"].pop("device-a/state"), "trees are incomplete")

    def test_escaped_or_linked_evidence_names_are_refused(self):
        self.refuses("parent-traversal", lambda d: d["transcript_files"].update({"..\\outside.txt": "0" * 64}), "flat")
        self.refuses("nested", lambda d: d["transcript_files"].update({"device-a/vault/People/Self.md": "0" * 64}), "flat")
        self.refuses("absolute", lambda d: d["transcript_files"].update({str(REPORT): "0" * 64}), "flat")
        self.refuses("missing-file", lambda d: d["transcript_files"].update({"never-written.txt": "0" * 64}), "evidence")

    def test_unstopped_processes_and_changed_sentinels_are_refused(self):
        self.refuses("unstopped-process", lambda d: d["processes"][0].update(stopped=False), "shutdown")
        self.refuses("flag-cleared", lambda d: d.update(all_started_processes_stopped=False), "Stability")
        self.refuses("unstopped-call", lambda d: d["calls"][0].update(stopped=False), "shutdown|not stopped")
        self.refuses("unrecorded-process", lambda d: d["processes"].pop(0), "not recorded")
        self.refuses("sentinel-changed", lambda d: d["isolation"]["after"].update({next(iter(d["isolation"]["after"])): "0" * 64}), "sentinels")
        self.refuses("sentinel-flag", lambda d: d["isolation"].update(unchanged=False), "sentinels")
        self.refuses("artifact-flag", lambda d: d.update(artifacts_unchanged=False), "Stability")
        self.refuses("product-flag", lambda d: d.update(product_unchanged=False), "Stability")

    def test_artifact_bytes_that_differ_from_their_reports_are_refused(self):
        self.refuses("wheel-hash", lambda d: d["artifacts"]["wheel"].update(artifact_sha256="0" * 64), "Artifact bytes")
        self.refuses("binary-hash", lambda d: d["artifacts"]["binary"].update(artifact_sha256="0" * 64), "Artifact bytes")
        self.refuses("executable-hash", lambda d: d["artifacts"]["wheel"].update(executable_sha256="0" * 64), "Executable bytes")
        self.refuses("report-hash", lambda d: d["artifacts"]["binary"].update(report_sha256="0" * 64), "Artifact report changed")
        self.refuses("wheel-version", lambda d: d["artifacts"]["wheel"].update(version="9.9.9"), "version")
        self.refuses("binary-dropped", lambda d: d["artifacts"].pop("binary"), "artifact references")
        self.refuses("swapped-reports", lambda d: d["artifacts"].update(wheel=d["artifacts"]["binary"], binary=d["artifacts"]["wheel"]), "")

    def test_previous_revision_identity_is_checked(self):
        self.refuses("old-hash", lambda d: d["old_wheel"].update(sha256="0" * 64), "Previous-revision wheel bytes")
        self.refuses("old-members", lambda d: d["old_wheel"]["members"].append("knowledgeos/gate.py"), "contents differ")
        self.refuses("old-version", lambda d: d["old_wheel"].update(version="0.4.0"), "contents differ")
        self.refuses("old-revision", lambda d: d["old_wheel"].update(revision="0" * 40), "revision")

    def test_a_report_cannot_claim_what_its_evidence_does_not_show(self):
        failing, passing = self.first_row("FAIL"), self.first_row("PASS")
        self.refuses("fail-claimed-as-pass", lambda d: d["cases"][failing].update(verdict="PASS"), "contradicts")
        self.refuses("pass-claimed-as-fail", lambda d: d["cases"][passing].update(verdict="FAIL"), "contradicts")
        self.refuses("observed-edited", lambda d: d["cases"][failing]["observed"].update(invented=True), "contradicts")
        self.refuses("expected-edited", lambda d: d["cases"][passing].update(expected="Anything"), "contradicts")
        self.refuses("report-verdict-raised", lambda d: d.update(verdict="PASS"), "verdict contradicts")
        if self.original["verdict"] == "PASS":
            self.refuses("report-verdict-lowered", lambda d: d.update(verdict="FAIL"), "verdict contradicts")
        self.refuses("call-removed", lambda d: d["calls"].pop(next(i for i, r in enumerate(d["calls"]) if r["label"] == "dv-a-init")), "contradicts|Duplicate|processes")
        self.refuses("exit-code-edited", lambda d: d["calls"][1].update(exit_code=99), "differs from its retained")

    def test_console_observation_must_come_from_the_reviewed_observer(self):
        console = next(row for row in self.original["calls"] if row["kind"] == "console")
        self.refuses("child-pid", lambda d: next(r for r in d["calls"] if r["label"] == console["label"]).update(child_pid=1), "Console")
        self.refuses("child-unrecorded", lambda d: d["processes"].remove(next(p for p in d["processes"] if p["role"] == console["label"] + "-child")), "child")
        record = json.loads((REPORT.parent / console["record"]).read_text(encoding="utf-8"))
        self.assertIs(record["input_written"], False)
        self.assertEqual(sha(grader.OBSERVER_SOURCE.encode("utf-8")), self.original["transcript_files"][grader.OBSERVER_NAME])
        for banned in ("stdin.write", "input(", "communicate(", "stdin=subprocess.PIPE"):
            self.assertNotIn(banned, grader.OBSERVER_SOURCE, "the observer must have no way to answer a prompt")


class FixedProductTests(unittest.TestCase):
    """Edit retained evidence to what a repaired product would print; the verdict must follow the evidence."""

    FIXES = (
        "upgrade.pre_ledger_draft_refused_with_hint",
        "upgrade.version_schema_reported",
        "upgrade.validate_clean",
        "divergence.doctor_flags_conflict_copy",
        "divergence.refusal_hints_propose_again",
        "divergence.doctor_explains_foreign_ledger",
    )

    @classmethod
    def setUpClass(cls):
        UpgradeDivergenceAdapterTests.setUpClass.__func__(cls)
        cls.failing = [row["id"] for row in cls.original["cases"] if row["verdict"] != "PASS"]

    @classmethod
    def tearDownClass(cls):
        UpgradeDivergenceAdapterTests.tearDownClass.__func__(cls)

    def workspace(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/upgrade/tests"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name)
        source = REPORT.parent
        for item in source.iterdir():
            if item.is_file() and item.name != "report.json":
                shutil.copy2(item, target / item.name)
        for tree in grader.FINAL_TREES:
            shutil.copytree(source / tree, target / tree)
        return target

    def read(self, folder, name):
        return (folder / name).read_text(encoding="utf-8")

    def write(self, folder, name, text):
        (folder / name).write_bytes(text.encode("utf-8"))

    def call(self, data, label):
        return next(row for row in data["calls"] if row["label"] == label)

    def set_exit(self, folder, data, label, code):
        row = self.call(data, label)
        row["exit_code"] = code
        retained = json.loads(self.read(folder, row["record"]))
        retained["exit_code"] = code
        self.write(folder, row["record"], json.dumps(retained, indent=2))

    def repair(self, folder, data, case):
        stdout = lambda label: self.call(data, label)["stdout"]
        stderr = lambda label: self.call(data, label)["stderr"]
        if case == "upgrade.pre_ledger_draft_refused_with_hint":
            refusal = self.read(folder, stderr("up-approve"))
            self.write(folder, stderr("up-approve"), refusal.rstrip("\n") + "\nIf it came from another device, propose it again on this device.\n")
        elif case == "upgrade.version_schema_reported":
            pre = json.loads(self.read(folder, "up-pre.json"))
            note = "\n[OK] Vault schema %s is supported by toolkit %s.\n" % (pre["marker"]["schema"], data["artifacts"]["wheel"]["version"])
            self.write(folder, stdout("up-doctor-after"), self.read(folder, stdout("up-doctor-after")) + note)
            self.write(folder, stdout("up-version-check"), "None\n")
        elif case == "upgrade.validate_clean":
            report = json.loads(self.read(folder, stdout("up-validate")))
            report["errors"] = []
            report["summary"]["errors"] = 0
            self.write(folder, stdout("up-validate"), json.dumps(report, indent=2))
            self.set_exit(folder, data, "up-validate", 0)
        elif case == "divergence.doctor_flags_conflict_copy":
            copy_name = next(rel for rel in json.loads(self.read(folder, "dv-synced-a.json"))["files"] if grader.CONFLICT_PATTERN.match(rel))
            for label in ("dv-a-doctor", "dv-b-doctor"):
                self.write(folder, stdout(label), self.read(folder, stdout(label)) + "\n[WARNING] Sync conflict copy kept as a separate source: %s\n" % copy_name)
        elif case == "divergence.refusal_hints_propose_again":
            self.write(folder, stderr("dv-b-approve-pa"), self.read(folder, stderr("dv-b-approve-pa")) + "Propose it again on this device.\n")
        elif case == "divergence.doctor_explains_foreign_ledger":
            label = "dv-b-doctor-ledger"
            self.write(folder, stdout(label), self.read(folder, stdout(label)) + "\n[WARNING] This ledger came from another device and cannot be trusted here.\n")
        else:
            self.fail("No repair is defined for " + case)

    def rebuilt(self, folder, data):
        data["transcript_files"] = {p.name: sha(p.read_bytes()) for p in sorted(folder.iterdir()) if p.is_file() and p.name != "report.json"}
        evidence = grader.Evidence(folder, data)
        data["cases"] = [grader.case_row(evidence, case) for case in grader.CASE_IDS]
        failed = [row["id"] for row in data["cases"] if row["verdict"] != "PASS"]
        data["verdict"] = "FAIL" if failed else "PASS"
        (folder / "report.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return grader.grade(self.api, [folder / "report.json"], self.current)[0]

    def regrade(self, repaired):
        folder = self.workspace()
        data = copy.deepcopy(self.original)
        for case in repaired:
            self.repair(folder, data, case)
        return self.rebuilt(folder, data)

    def test_only_unrepaired_cases_fail(self):
        for skipped in self.failing:
            with self.subTest(still_broken=skipped):
                graded = self.regrade([case for case in self.failing if case != skipped])
                check = graded["checks"][grader.CHECK]
                self.assertEqual(check["verdict"], "FAIL")
                self.assertEqual(check["observed"]["failed"], [skipped])

    def test_every_repair_together_passes_the_outcome(self):
        self.assertTrue(set(self.failing) <= set(self.FIXES), "a new failing case needs its own repair in this test")
        graded = self.regrade(self.failing)
        check = graded["checks"][grader.CHECK]
        self.assertEqual(check["verdict"], "PASS")
        self.assertEqual(check["observed"], {"cases": len(grader.CASE_IDS), "passed": len(grader.CASE_IDS), "failed": []})

    def test_edited_evidence_without_a_new_hash_is_refused(self):
        folder = self.workspace()
        data = copy.deepcopy(self.original)
        self.repair(folder, data, "divergence.refusal_hints_propose_again")
        (folder / "report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Evidence changed"):
            grader.grade(self.api, [folder / "report.json"], self.current)


class CaseLogicTests(unittest.TestCase):
    """Small synthetic evidence sets that exercise one predicate in both directions."""

    def evidence(self, calls, files, data=None):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        rows = []
        for label, (code, out, err, extra) in calls.items():
            (base / (label + ".out")).write_text(out, encoding="utf-8")
            (base / (label + ".err")).write_text(err, encoding="utf-8")
            (base / (label + ".rec")).write_text(json.dumps(extra.get("record", {})), encoding="utf-8")
            rows.append({"label": label, "kind": extra.get("kind", "command"), "command": extra.get("command", [label]), "exit_code": code,
                         "stdout": label + ".out", "stderr": label + ".err", "record": label + ".rec"})
        for name, value in files.items():
            (base / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
        return grader.Evidence(base, dict(data or {}, calls=rows))

    def test_refusal_hint_needs_the_words_and_a_refusal_before_the_prompt(self):
        record = {"stdin_isatty": True, "reason": "exited", "input_written": False}
        for hint, expected in (("Only proposals created by this install can be approved.", False), ("Propose it again on this device.", True),
                               ("Create a new proposal here.", True), ("Ask for approval again.", False)):
            with self.subTest(hint=hint):
                ev = self.evidence({"dv-b-approve-pa": (1, "", "not registered\n" + hint + "\n", {"kind": "console", "record": record})}, {})
                self.assertEqual(grader.evaluate(ev, "divergence.refusal_hints_propose_again")[0], expected)
        record["reason"] = "prompt_reached"
        ev = self.evidence({"dv-b-approve-pa": (1, "Apply [y/N]", "Propose again\n", {"kind": "console", "record": record})}, {})
        self.assertFalse(grader.evaluate(ev, "divergence.refusal_hints_propose_again")[0], "reaching the prompt is not a refusal")

    def test_doctor_explanation_must_name_another_device(self):
        for text, expected in (("[WARNING] 1 ledger row(s) failed signature verification and were ignored.", False),
                               ("[WARNING] The ledger came from another device.", True),
                               ("[WARNING] Signed by a different install; propose again here.", True)):
            with self.subTest(text=text):
                ev = self.evidence({"dv-b-doctor-ledger": (0, text, "", {})}, {})
                self.assertEqual(grader.evaluate(ev, "divergence.doctor_explains_foreign_ledger")[0], expected)

    def test_missing_evidence_is_a_failure_with_a_reason(self):
        passed, observed = grader.evaluate(self.evidence({}, {}), "upgrade.self_unchanged")
        self.assertFalse(passed)
        self.assertIn("missing", observed["error"])


if __name__ == "__main__":
    unittest.main()
