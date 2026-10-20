"""Tamper controls for the independent longitudinal source grader."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
LOCAL = Path(__file__).resolve().parent
ROOT = next(path for path in Path(__file__).resolve().parents if (path / "knowledgeos/memory.py").is_file())
sys.path.insert(0, str(LOCAL if (LOCAL / "longitudinal_adapter.py").is_file() else ROOT / ".agents/skills/verify-twinaatma/scripts"))
import longitudinal_adapter as grader

REPORT = Path(os.environ["TWIN_LONGITUDINAL_REPORT"]).absolute() if os.environ.get("TWIN_LONGITUDINAL_REPORT") else None


class LongitudinalAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPORT is None:
            raise unittest.SkipTest("An original public-process report is required")
        cls.observed = grader.Observations(REPORT)
        cls.scored = grader.score(REPORT)

    def test_original_observations_cover_both_fixed_outcomes(self):
        self.assertEqual({key: row["verdict"] for key, row in self.scored["checks"].items()}, {
            "longitudinal.semantic_drift.complete": "PASS", "longitudinal.rejection_recurrence.complete": "PASS"})
        self.assertEqual(set(self.scored["case_results"]), set(grader.CASE_IDS))

    def mutated_report(self, name, mutate):
        data = copy.deepcopy(self.observed.data)
        mutate(data)
        target = REPORT.parent / ("tamper-" + name + ".json")
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return target

    def test_top_level_tamper_controls_refuse(self):
        mutations = {
            "stale-product": lambda data: data["product_hashes"].update({"knowledgeos/evolution.py": "0" * 64}),
            "deleted-product": lambda data: data["product_hashes"].pop("knowledgeos/evolution.py"),
            "stale-producer": lambda data: data.update(producer_sha256="0" * 64),
            "stale-support": lambda data: data["support_sha256"].update({"case-plan.json": "0" * 64}),
            "scope-laundering": lambda data: data.update(scope="host"),
            "incomplete-case-list": lambda data: data["expected_case_ids"].pop(),
            "missing-source-snapshot": lambda data: data["evidence_files"].pop("snapshots/uncertain_attributed-before.json"),
            "tampered-wire-digest": lambda data: data["evidence_files"].update({"uncertain_attributed.stdout.txt": "0" * 64}),
            "untracked-process": lambda data: data["processes"].pop(),
            "wrong-process-role": lambda data: data["processes"][0].update(role="other-init"),
            "wrong-process-pid": lambda data: data["processes"][0].update(pid=data["processes"][0]["pid"] + 1),
            "reused-instance": lambda data: data["processes"][1].update(instance=data["processes"][0]["instance"]),
            "missing-shutdown": lambda data: data["processes"][0].update(stopped=False),
            "claimed-identity-mutation": lambda data: data["isolation"]["after"].update({next(iter(data["isolation"]["after"])): "0" * 64}),
            "post-output-freeze": lambda data: data["frozen"].update(frozen_at="2999-01-01T00:00:00+00:00"),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                grader.score(self.mutated_report(name, mutation))

    def proposal_material(self):
        results = [json.loads(line) for line in self.observed.text("uncertain_attributed.stdout.txt").splitlines()]
        payloads = [json.loads(row["result"]["content"][0]["text"]) for row in results[1:]]
        snapshot = self.observed.snapshot("uncertain_attributed-after")
        payload, opened = payloads
        return payload, opened, snapshot["markdown"][payload["proposal_path"]], grader.decision_texts(snapshot)

    def test_recompute_proposal_sources_and_uncertainty(self):
        payload, opened, text, sources = self.proposal_material()
        self.assertTrue(grader.proposal_valid(payload, opened, text, sources))
        for fragment in (grader.BEFORE, grader.AFTER, "this suggestion is uncertain and needs your review.", "not independent verification", grader.NARRATIVES["mail"], "Decisions/calendar.md"):
            with self.subTest(fragment=fragment):
                self.assertFalse(grader.proposal_valid(payload, opened, text.replace(fragment, "Invented replacement"), sources))
        wrong = dict(sources)
        wrong["Decisions/mail.md"] = wrong["Decisions/mail.md"].replace(grader.NARRATIVES["mail"], "An invented supporting outcome.")
        self.assertFalse(grader.proposal_valid(payload, opened, text, wrong))
        copied = dict(sources)
        copied["Decisions/calendar.md"] = copied["Decisions/calendar.md"].replace(grader.NARRATIVES["calendar"], grader.NARRATIVES["mail"])
        self.assertFalse(grader.proposal_valid(payload, opened, text, copied))
        self.assertFalse(grader.proposal_valid(payload, opened, text + "\nI know the current owner now believes this.\n", sources))
        self.assertFalse(grader.proposal_valid(payload, opened, text, {"Decisions/mail.md": sources["Decisions/mail.md"]}))
        forged = copy.deepcopy(payload)
        forged.update(mutated_self=True)
        self.assertFalse(grader.proposal_valid(forged, opened, text, sources))

    def test_before_after_or_receipt_tampering_refuses(self):
        before = self.observed.snapshot("record-mail-before")["markdown"]["Decisions/mail.md"]
        after = self.observed.snapshot("record-mail-after")["markdown"]["Decisions/mail.md"]
        requests = [json.loads(line) for line in self.observed.text("record-mail.requests.jsonl").splitlines()]
        request = requests[-1]["params"]["arguments"]
        responses = [json.loads(line) for line in self.observed.text("record-mail.stdout.txt").splitlines()]
        payload = json.loads(responses[-1]["result"]["content"][0]["text"])
        started = self.observed.records["record-mail"]["started_at"]
        self.assertTrue(grader.recorded_valid(before, after, request, payload, started))
        for bad in (after.replace(grader.BEFORE, "An invented old belief"), after.replace(grader.AFTER, "An invented new belief"), after.replace('"version":1', '"version":2')):
            self.assertNotEqual(bad, after)
            self.assertFalse(grader.recorded_valid(before, bad, request, payload, started))
        wrong = dict(request, expected_sha256="0" * 64)
        self.assertFalse(grader.recorded_valid(before, after, wrong, payload, started))
        self.assertIsInstance(grader.frontmatter(after)["outcome_recording"], dict)
        self.assertIsInstance(grader.public_metadata(after)["outcome_recording"], str)

    def test_public_wire_cannot_be_rebound_to_a_different_source(self):
        with self.assertRaisesRegex(ValueError, "Wrong-source"):
            self.observed.rpc("recorded_pair", [("memory_get_note", {"path_or_id": "Decisions/storage.md"}),
                ("memory_get_note", {"path_or_id": "Decisions/calendar.md"}), ("memory_pending_outcomes", {})])

    def test_pid_reuse_is_allowed_only_with_distinct_nonoverlapping_instances(self):
        records = copy.deepcopy(self.observed.records)
        traces = {self.observed.json(name)["instance"]: self.observed.json(name) for name in self.observed.data["trace_files"]}
        processes = copy.deepcopy(self.observed.data["processes"])
        roles = grader.process_roles()
        reused = records[roles[0]]["pid"]
        records[roles[1]]["pid"] = reused
        traces["direct-002"]["pid"] = reused
        processes[1]["pid"] = reused
        grader.validate_lifetimes(records, traces, processes)
        for name in ("overlap", "wrong-parent", "wrong-instance", "nested-untracked"):
            r, t, p = copy.deepcopy(records), copy.deepcopy(traces), copy.deepcopy(processes)
            if name == "overlap":
                r[roles[1]]["started_ns"] = r[roles[0]]["started_ns"]
            elif name == "wrong-parent":
                t["direct-002"]["parent_pid"] += 1
            elif name == "wrong-instance":
                t["direct-002"]["instance"] = "direct-001"
            else:
                t["direct-002"]["children"] = [{"pid": 999, "stopped": False}]
            with self.subTest(name=name), self.assertRaises(ValueError):
                grader.validate_lifetimes(r, t, p)

    def test_producer_pass_claims_do_not_award_credit(self):
        target = self.mutated_report("fake-green-claims", lambda data: data.update(verdict="PASS", cases=[{"id": "made-up", "verdict": "PASS"}], fixed_outcome_candidates={"HOST.grounded": "PASS"}))
        result = grader.score(target)
        self.assertEqual(result["checks"], self.scored["checks"])
        self.assertEqual(result["scope"], "longitudinal")
        self.assertNotIn("HOST.grounded", result["checks"])


def main():
    global REPORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args, remaining = parser.parse_known_args()
    REPORT = args.report.absolute()
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False)
    if args.output:
        args.output.write_text(json.dumps({"tests_run": program.result.testsRun, "failures": [(str(test), detail) for test, detail in program.result.failures],
            "errors": [(str(test), detail) for test, detail in program.result.errors], "skipped": [(str(test), reason) for test, reason in program.result.skipped],
            "success": program.result.wasSuccessful(), "report": str(REPORT), "report_sha256": grader.sha(REPORT),
            "grader_sha256": grader.sha(grader.__file__), "tests_sha256": grader.sha(__file__)}, indent=2) + "\n", encoding="utf-8")
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
