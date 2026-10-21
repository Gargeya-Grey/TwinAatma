"""Tamper and recomputation controls for the clean-device restore grader.

The controls need a retained real bundle: the attested ``clean-restore.json`` that
``.github/workflows/clean-device-restore.yml`` produced for this repository. Point
TWIN_CLEAN_RESTORE_BUNDLE at it, or leave the newest ``ci-*`` download beneath
work/gc-artifacts/.knowledgeos/clean-restore. Without a bundle those tests skip. The gh boundary and the
local binding are replaced; the grader, the scorer's snapshot() and the producer's wording rules run for real.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
RETAINED = ROOT / "work/gc-artifacts/.knowledgeos/clean-restore"
sys.path.insert(0, str(SCRIPTS))
import ci_graded as ci  # noqa: E402
import clean_restore as producer  # noqa: E402
import clean_restore_adapter as grader  # noqa: E402


def retained_bundle():
    configured = os.environ.get("TWIN_CLEAN_RESTORE_BUNDLE")
    if configured:
        return Path(configured).absolute()
    found = sorted(RETAINED.glob("ci-*/clean-restore.json"), key=lambda p: p.stat().st_mtime) if RETAINED.is_dir() else []
    return found[-1] if found else None


def good_flags(observed):
    return {key: (False if key in grader.FALSE_IS_GOOD else True) if isinstance(value, bool) else value for key, value in observed.items()}


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = retained_bundle()
        if cls.path is None:
            raise unittest.SkipTest("A retained real clean-restore bundle is required")
        spec = importlib.util.spec_from_file_location("acceptance_under_test", SCRIPTS / "acceptance.py")
        cls.metric = importlib.util.module_from_spec(spec)
        sys.modules["acceptance_under_test"] = cls.metric
        spec.loader.exec_module(cls.metric)
        cls.real = json.loads(cls.path.read_text(encoding="utf-8"))
        binding = cls.real["binding"]
        cls.local = {key: binding[key] for key in ("commit", "product_hashes_lf", "toolkit_hashes_lf", "scorer_sha256_lf",
                                                  "adapter_requirements_sha256_lf", "rubric_sha256")}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    # ------------------------------------------------------------------ builders
    def claims(self, bundle, **changes):
        binding = bundle["binding"]
        claim = {"sourceRepositoryDigest": binding["commit"], "sourceRepositoryURI": "https://github.com/" + grader.REPOSITORY,
                 "runInvocationURI": "https://github.com/{}/actions/runs/{}/attempts/{}".format(grader.REPOSITORY, binding["run_id"], binding["run_attempt"]),
                 "buildSignerURI": "https://github.com/{}/{}@refs/heads/acceptance/clean-restore".format(grader.REPOSITORY, grader.WORKFLOW),
                 "sourceRepositoryRef": "refs/heads/acceptance/clean-restore", "runnerEnvironment": "github-hosted"}
        claim.update(changes)
        return [claim]

    def reseal(self, bundle):
        bundle["graded_sha256"] = ci.sha256_bytes(ci.canonical(bundle["graded"]).encode())
        return bundle

    def aligned(self):
        """The real bundle, with the hashes of this checkout's producer, adapter and support scripts.

        At the commit the bundle was produced for they already equal these values. At a later commit the
        retained bundle would otherwise be refused for a stale producer, which another test proves.
        """
        bundle = copy.deepcopy(self.real)
        bundle["binding"].update(producer_sha256_lf=ci.lf_sha(producer.__file__), adapter_sha256_lf=ci.lf_sha(grader.__file__),
                                 support_sha256_lf={name: ci.lf_sha(SCRIPTS / name) for name in producer.SUPPORT})
        return bundle

    def passing(self):
        """The real bundle with every case made to pass by its own observed values. Only used to test PASS handling."""
        bundle = self.aligned()
        for cell in bundle["graded"]["cells"].values():
            for row in cell["cases"]:
                row["observed"] = good_flags(row["observed"])
                row["verdict"] = "PASS"
            cell.update(verdict="PASS", error=None, origin_error=None)
        return self.reseal(bundle)

    def grade(self, bundle, *, local=None, claims=None, verify=None, api=None):
        path = self.directory / "clean-restore.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        stub = verify or (lambda p, r: claims if claims is not None else self.claims(bundle))
        with mock.patch.object(ci, "local_binding", return_value=local or self.local):
            return grader.grade(api or self.metric, [path], self.metric.product_hashes(), verify=stub)

    def check(self, reports):
        self.assertEqual(len(reports), 1)
        self.assertEqual(set(reports[0]["checks"]), {grader.CHECK})
        self.assertEqual(reports[0]["scope"], "clean_device")
        return reports[0]["checks"][grader.CHECK]

    def refused(self, bundle, pattern, **kwargs):
        with self.assertRaisesRegex(ValueError, pattern):
            self.grade(bundle, **kwargs)

    # ------------------------------------------------------------------ the real bundle
    def test_real_verdict_follows_its_own_rows(self):
        check = self.check(self.grade(self.aligned()))
        failed = {kind: sorted(row["id"] for row in cell["cases"] if row["verdict"] != "PASS")
                  for kind, cell in self.real["graded"]["cells"].items()}
        self.assertEqual(check["observed"]["failed_cases"], failed)
        self.assertEqual(check["verdict"], "PASS" if not any(failed.values()) else "FAIL")
        self.assertRegex(check["observed"]["bundle_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(check["expected"], grader.EXPECTED)

    def test_real_binding_matches_this_checkout_when_it_is_the_ci_commit(self):
        if ci.git_head(ROOT) != self.real["binding"]["commit"]:
            self.skipTest("HEAD is not the commit the retained bundle was produced for")
        if ci.lf_sha(Path(producer.__file__)) != self.real["binding"]["producer_sha256_lf"]:
            self.skipTest("The producer in this checkout has uncommitted changes since the retained bundle")
        path =self.directory / "clean-restore.json"
        path.write_bytes(self.path.read_bytes())
        reports = grader.grade(self.metric, [path], self.metric.product_hashes(), verify=lambda p, r: self.claims(self.real))
        self.assertEqual(self.check(reports)["observed"]["commit"], ci.git_head(ROOT))

    def test_pass_needs_every_case_in_both_cells(self):
        self.assertEqual(self.check(self.grade(self.passing()))["verdict"], "PASS")
        for kind in producer.KINDS:
            for index in range(len(producer.CASE_IDS)):
                bundle = self.passing()
                row = bundle["graded"]["cells"][kind]["cases"][index]
                key = next(k for k, v in row["observed"].items() if isinstance(v, bool))
                row["observed"][key] = not row["observed"][key]
                row["verdict"] = "FAIL"
                bundle["graded"]["cells"][kind]["verdict"] = "FAIL"
                check = self.check(self.grade(self.reseal(bundle)))
                self.assertEqual(check["verdict"], "FAIL", (kind, index))
                self.assertEqual(check["observed"]["failed_cases"][kind], [row["id"]])

    def test_scorer_awards_exactly_the_one_outcome(self):
        with mock.patch.object(grader, "verify_attestation", lambda p, r: self.claims(self.passing())), \
                mock.patch.object(ci, "local_binding", return_value=self.local):
            path = self.directory / "clean-restore.json"
            path.write_text(json.dumps(self.passing()), encoding="utf-8")
            score = self.metric.snapshot([], [], extension_paths={"clean-restore": [path]})
        self.assertEqual(score["outcomes"]["PORT.clean_device_restore"]["verdict"], "PASS")
        self.assertEqual(score["counts"]["PASS"], 1)
        self.assertEqual([k for k, row in score["outcomes"].items() if row["verdict"] != "NOT CHECKED"], ["PORT.clean_device_restore"])
        spec = self.metric.EXTENSION_ADAPTERS["clean-restore"]
        self.assertEqual((spec["module"], spec["scope"], spec["outcomes"]),
                         ("clean_restore_adapter", "clean_device", {"PORT.clean_device_restore": [grader.CHECK]}))
        self.assertEqual(self.metric.ADAPTER_REQUIREMENTS["extensions"]["clean-restore"]["module_sha256"], self.metric.sha(grader.__file__))

    def test_a_failing_bundle_scores_fail_not_an_exception(self):
        bundle = self.passing()
        row = bundle["graded"]["cells"]["wheel"]["cases"][0]
        row["observed"]["error"] = "ValueError: forced"
        row["verdict"] = "FAIL"
        bundle["graded"]["cells"]["wheel"]["verdict"] = "FAIL"
        with mock.patch.object(grader, "verify_attestation", lambda p, r: self.claims(bundle)), \
                mock.patch.object(ci, "local_binding", return_value=self.local):
            path = self.directory / "clean-restore.json"
            path.write_text(json.dumps(self.reseal(bundle)), encoding="utf-8")
            score = self.metric.snapshot([], [], extension_paths={"clean-restore": [path]})
        self.assertEqual(score["outcomes"]["PORT.clean_device_restore"]["verdict"], "FAIL")
        self.assertEqual(score["counts"]["PASS"], 0)

    # ------------------------------------------------------------------ tampered copies of the real bundle
    def test_wrong_commit_or_stale_hash_is_refused(self):
        self.refused(self.passing(), "commit differs", local=dict(self.local, commit="1" * 40))
        for key, pattern in (("product_hashes_lf", "product hashes differ"), ("toolkit_hashes_lf", "product hashes differ")):
            self.refused(self.passing(), pattern, local=dict(self.local, **{key: {"x": "0" * 64}}))
        for key in ("scorer_sha256_lf", "adapter_requirements_sha256_lf", "rubric_sha256"):
            self.refused(self.passing(), "different scorer, adapter or rubric", local=dict(self.local, **{key: "0" * 64}))

    def test_bundle_fields_must_equal_the_local_producer_and_adapter(self):
        for key, pattern in (("producer_sha256_lf", "different clean-restore producer"), ("adapter_sha256_lf", "different clean-restore adapter")):
            bundle = self.passing()
            bundle["binding"][key] = "0" * 64
            self.refused(bundle, pattern)
        bundle = self.passing()
        bundle["binding"]["support_sha256_lf"]["signing_state.py"] = "0" * 64
        self.refused(bundle, "support scripts")
        for key, value, pattern in (("repository", "someone/else", "another repository"), ("run_id", "x", "run_id"),
                                    ("runner_environment", "self-hosted", "not GitHub-hosted")):
            bundle = self.passing()
            bundle["binding"][key] = value
            self.refused(bundle, pattern)
        bundle = self.passing()
        bundle["binding"]["platform"]["system"] = "Linux"
        self.refused(bundle, "not a Windows machine")

    def test_failed_or_mismatched_attestation_is_refused(self):
        def failing(path, repository):
            raise ValueError("Attestation verification failed: no match")
        self.refused(self.passing(), "Attestation verification failed", verify=failing)
        bundle = self.passing()
        for change in ({"sourceRepositoryDigest": "2" * 40}, {"runInvocationURI": "https://github.com/x/y/actions/runs/1/attempts/1"},
                       {"buildSignerURI": "https://github.com/x/y/.github/workflows/acceptance-evidence.yml@refs/heads/x"},
                       {"runnerEnvironment": "self-hosted"}, {"sourceRepositoryURI": "https://github.com/someone/else"}):
            self.refused(bundle, "Signed attestation does not match", claims=self.claims(bundle, **change))
        self.refused(bundle, "Signed attestation does not match", claims=[])

    def test_altered_rows_after_grading_are_refused(self):
        bundle = self.passing()
        bundle["graded"]["cells"]["wheel"]["cases"][0]["observed"]["extra"] = 1
        self.refused(bundle, "altered after grading")
        bundle = self.passing()
        bundle["graded_sha256"] = "0" * 64
        self.refused(bundle, "altered after grading")

    def test_a_verdict_must_follow_the_observed_values(self):
        for kind in producer.KINDS:
            bundle = self.passing()
            row = bundle["graded"]["cells"][kind]["cases"][3]
            key = next(k for k, v in row["observed"].items() if isinstance(v, bool))
            row["observed"][key] = False
            self.refused(self.reseal(bundle), "does not follow from its observed values")
        bundle = self.passing()
        bundle["graded"]["cells"]["binary"]["cases"][1]["verdict"] = "FAIL"
        self.refused(self.reseal(bundle), "does not follow from its observed values")
        bundle = self.passing()
        bundle["graded"]["cells"]["wheel"]["cases"][2]["observed"] = {"note": "no flags"}
        self.refused(self.reseal(bundle), "does not follow from its observed values")

    def test_missing_extra_or_reordered_cases_are_refused(self):
        bundle = self.passing()
        del bundle["graded"]["cells"]["wheel"]["cases"][4]
        self.refused(self.reseal(bundle), "missing, extra, duplicated or reordered")
        bundle = self.passing()
        bundle["graded"]["cells"]["binary"]["cases"].append(copy.deepcopy(bundle["graded"]["cells"]["binary"]["cases"][0]))
        self.refused(self.reseal(bundle), "missing, extra, duplicated or reordered")
        bundle = self.passing()
        cases = bundle["graded"]["cells"]["wheel"]["cases"]
        cases[0], cases[1] = cases[1], cases[0]
        self.refused(self.reseal(bundle), "missing, extra, duplicated or reordered")
        bundle = self.passing()
        del bundle["graded"]["cells"]["binary"]
        self.refused(self.reseal(bundle), "Both the wheel and the executable cell")

    def test_case_wording_and_row_shape_are_frozen(self):
        bundle = self.passing()
        bundle["graded"]["cells"]["wheel"]["cases"][5]["expected"] = "Something easier to satisfy"
        self.refused(self.reseal(bundle), "frozen text")
        bundle = self.passing()
        bundle["graded"]["cells"]["wheel"]["cases"][5]["unexpected"] = True
        self.refused(self.reseal(bundle), "unexpected fields")
        bundle = self.passing()
        bundle["graded"]["cells"]["wheel"]["cases"][5]["observed"] = {}
        self.refused(self.reseal(bundle), "no observed result")

    def test_devices_must_be_two_different_github_hosted_machines(self):
        for field, value, pattern in (("hostname", None, "two different machines"), ("runner_name", None, "two different machines"),
                                      ("github_job", None, "two different machines"), ("github_actions", "false", "GitHub-hosted Windows"),
                                      ("runner_environment", "self-hosted", "GitHub-hosted Windows"), ("run_id", "1", "GitHub-hosted Windows"),
                                      ("platform", "Linux-6.0", "GitHub-hosted Windows")):
            bundle = self.passing()
            devices = bundle["graded"]["cells"]["wheel"]["devices"]
            devices["restore"][field] = devices["origin"][field] if value is None else value
            self.refused(self.reseal(bundle), pattern)
        bundle = self.passing()
        del bundle["graded"]["cells"]["binary"]["devices"]["origin"]
        self.refused(self.reseal(bundle), "Both devices must be described")

    def test_install_freeze_and_shutdown_are_required(self):
        for field, value, pattern in (("frozen_before_first_command", False, "frozen before the first command"),
                                      ("origin_processes_stopped", False, "processes were not all stopped"),
                                      ("restore_processes_stopped", False, "processes were not all stopped"),
                                      ("report_sha256", "short", "report hash")):
            bundle = self.passing()
            bundle["graded"]["cells"]["wheel"][field] = value
            self.refused(self.reseal(bundle), pattern)
        bundle = self.passing()
        bundle["graded"]["cells"]["binary"]["install"]["restore"]["product_hashes"] = {"x": "0" * 64}
        self.refused(self.reseal(bundle), "install this commit")
        bundle = self.passing()
        bundle["graded"]["cells"]["binary"]["install"]["origin"]["kind"] = "wheel"
        self.refused(self.reseal(bundle), "install this commit")
        bundle = self.passing()
        bundle["graded"]["cells"]["wheel"]["verdict"] = "FAIL"
        self.refused(self.reseal(bundle), "differs from its recomputed cases")

    def test_one_bundle_exactly_and_it_must_be_json_with_the_right_schema(self):
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            grader.grade(self.metric, [], self.metric.product_hashes())
        path = self.directory / "not.json"
        path.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not JSON"):
            grader.grade(self.metric, [path], self.metric.product_hashes(), verify=lambda p, r: [])
        bundle = self.passing()
        bundle["schema"] = "twinaatma.ci-graded/v1"
        self.refused(bundle, "schema is unknown")


class FrozenContractTests(unittest.TestCase):
    """These need no retained bundle."""

    def test_case_list_is_the_frozen_literal(self):
        self.assertEqual(len(producer.CASE_IDS), 10)
        self.assertEqual(len(set(producer.CASE_IDS)), 10)
        self.assertEqual(set(producer.EXPECTED), set(producer.CASE_NAMES))
        self.assertEqual(set(producer.EVALUATORS), set(producer.CASE_NAMES))
        self.assertEqual(producer.CHECK, grader.CHECK)
        self.assertEqual(grader.CHECK, "port.clean_device_restore")

    def test_workflow_is_the_one_the_grader_verifies(self):
        text = (ROOT / grader.WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("windows-latest", text)
        self.assertNotIn("self-hosted", text)
        self.assertIn("needs: origin", text)
        self.assertIn("actions/attest-build-provenance", text)
        self.assertIn('branches: ["acceptance/**"]', text)
        self.assertIn("workflow_dispatch", text)

    def test_attestation_boundary_names_this_workflow_and_hides_the_token(self):
        seen = {}

        def fake_gh(command, env):
            seen["command"], seen["token"] = command, env.get("GH_TOKEN")
            payload = [{"verificationResult": {"signature": {"certificate": {"sourceRepositoryDigest": "a" * 40, "runnerEnvironment": "github-hosted"}}}}]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with mock.patch.dict(os.environ, {"GH_TOKEN": "not-a-real-token"}), mock.patch.object(ci, "run_gh", fake_gh):
            claims = grader.verify_attestation(Path("bundle.json"))
        self.assertEqual(claims[0]["sourceRepositoryDigest"], "a" * 40)
        self.assertIn(grader.REPOSITORY + "/" + grader.WORKFLOW, seen["command"])

        def failing(command, env):
            return subprocess.CompletedProcess(command, 1, "", "error with not-a-real-token inside")

        with mock.patch.dict(os.environ, {"GH_TOKEN": "not-a-real-token"}), mock.patch.object(ci, "run_gh", failing):
            with self.assertRaises(ValueError) as caught:
                grader.verify_attestation(Path("bundle.json"))
        self.assertNotIn("not-a-real-token", str(caught.exception))

    def test_row_verdict_treats_every_boolean_as_a_condition(self):
        self.assertEqual(grader.row_verdict({"observed": {"a": True, "timed_out": False, "text": "x"}}), "PASS")
        self.assertEqual(grader.row_verdict({"observed": {"a": True, "timed_out": True}}), "FAIL")
        self.assertEqual(grader.row_verdict({"observed": {"a": False}}), "FAIL")
        self.assertEqual(grader.row_verdict({"observed": {"a": True, "error": "boom"}}), "FAIL")
        self.assertEqual(grader.row_verdict({"observed": {"text": "no flags"}}), "FAIL")

    def test_product_wording_rules_ignore_file_paths(self):
        path_only = r"Vault Root: D:\a\TwinAatma\work\clean-restore\restore\wheel-data\vault" + "\n"
        self.assertEqual(producer.wording(path_only).strip(), "Vault Root:")
        self.assertIsNone(producer.ACTION.search(producer.wording(path_only)))
        self.assertIsNotNone(producer.ACTION.search(producer.wording("Restore your signing key backup, or ask for a new proposal.")))
        self.assertIsNone(producer.PROPOSE_AGAIN.search("Only proposals created by this install can be approved."))
        self.assertIsNotNone(producer.PROPOSE_AGAIN.search("This device did not make it. Propose the change again here."))

    def test_dependency_case_needs_a_cause_and_an_action_from_the_product(self):
        def device(doctor, setup="", stderr=""):
            directory = Path(tempfile.mkdtemp())
            self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
            for label, text in (("doctor-1.stdout.txt", doctor), ("setup-host.stdout.txt", setup), ("setup-host.stderr.txt", stderr)):
                (directory / label).write_text(text, encoding="utf-8")
            (directory / "doctor-1.command.json").write_text(json.dumps({"exit_code": 0, "stopped": True, "timed_out": False, "console": False}), encoding="utf-8")
            return producer.Ev(directory)

        today = "  [WARNING] 1 Self proposal file(s) are not in the ledger, so they cannot be approved:\n            People/Self-Proposals/x.md\n"
        passed, observed = producer.case_dependency(None, device(today), {})
        self.assertFalse(passed)
        self.assertFalse(observed["cause_named"])
        fixed = ("  [WARNING] The signing key from your other device is missing, so older approvals cannot be verified.\n"
                 "            Restore your signing key backup, or ask for a new proposal.\n")
        passed, observed = producer.case_dependency(None, device(fixed), {})
        self.assertTrue(passed, observed)
        passed, observed = producer.case_dependency(None, device("", setup=fixed), {})
        self.assertTrue(passed, observed)
        passed, observed = producer.case_dependency(None, device("  [WARNING] The signing key is missing.\n"), {})
        self.assertFalse(passed)
        self.assertTrue(observed["cause_named"])
        self.assertFalse(observed["action_named"])


if __name__ == "__main__":
    unittest.main()
