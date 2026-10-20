"""Synthetic evaluation-scorer controls, separate from real product acceptance."""
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_identity_score import ObservationFixtures, ROOT, metric

SELF = ("# Self\n\nSynthetic fixture only. Personal identity is unknown.\n\n"
        "## Operating Heuristics & Rules of Thumb\n<!-- kos:section=heuristics -->\nUnknown.\n\n"
        "## Values Hierarchy\n<!-- kos:section=values -->\nUnknown.\n\n"
        "## Mental Models\n<!-- kos:section=mental_models -->\nUnknown.\n\n"
        "## Anti-Goals\n<!-- kos:section=anti_goals -->\nUnknown.\n\n"
        "## Active Bets\n<!-- kos:section=active_bets -->\nUnknown.\n\n"
        "## Drift Log\n<!-- kos:section=drift_log -->\nNo history.\n")


class QualityScoreTests(ObservationFixtures, unittest.TestCase):
    def quality_fixture(self):
        self.fixture_index += 1
        directory = self.directory / ("quality-" + str(self.fixture_index))
        data = self.base_report(directory, "verify-twinaatma.quality/v1", "quality.py", "evaluation source-only startup MCP retrieval synthetic scorer control")
        corpus, notes, summary = metric.quality_corpus()
        data.update(corpus_path="tests/fixtures/quality-v1.json", corpus_sha256="787de4674bb0a51fceee87acb7ee7e9b8872068e1fab8af24de3e729bcbac379",
                    corpus_summary=summary, cases=[], binding_checks=[], capture_policy_status="UNAPPROVED", execution_complete=True)
        fixtures = {}
        for case in corpus["cases"]:
            label = case["id"]
            fixture = directory / "fixtures" / label
            vault = fixture / "vault"
            vault.mkdir(parents=True)
            fixtures[label] = str(vault)
            inventory = {name: {"kind": "file", "links": 1, "sha256": digest} for name, digest in self.toolkit.items()}
            for note in corpus["notes"]:
                target = vault / note["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(note["content"].encode("utf-8"))
                inventory[note["path"]] = {"kind": "file", "links": 1, "size": target.stat().st_size, "sha256": metric.sha(target)}
            (vault / "People").mkdir(exist_ok=True)
            (vault / "People/Self.md").write_bytes(SELF.encode("utf-8"))
            inventory["People/Self.md"] = {"kind": "file", "links": 1, "size": len(SELF.encode("utf-8")), "sha256": metric.sha(vault / "People/Self.md")}
            for suffix in (".before.json", ".after.json"):
                self.save(directory / (label + suffix), inventory)
            for suffix in (".notes.before.json", ".notes.after.json"):
                self.save(directory / (label + suffix), notes)
            self.command(directory, data, label + "-doctor", [sys.executable, "-B", "-P", "-m", "knowledgeos", "doctor", "--vault", str(vault)],
                directory, state=fixture / "gate-state", vault=vault, stdout="ready\n")
            ranked = [{"path": source["path"], "excerpt": "\n".join(claim["quote"] for claim in source["claims"])} for source in case["expected_sources"]]
            payload = {"context": {"task_hint": case["task_hint"], "relevant": {"ranked": ranked}}, "session_id": "synthetic-session-" + label}
            self.rpc(directory, data, label + "-startup", fixture, [("memory_session_start", {"task_hint": case["task_hint"]})], [{"payload": payload, "is_error": False}], quality=True)
            self.save(directory / (label + ".context.json"), payload)
            sources = [{"path": source["path"], "critical": source["critical"], "rank": index, "in_first_eight": True,
                        "claims": [{"id": claim["id"], "quote": claim["quote"], "available_in_source_context": True} for claim in source["claims"]]}
                       for index, source in enumerate(case["expected_sources"], 1)]
            row = {"id": label, "split": case["split"], "categories": case["categories"], "task_hint": case["task_hint"],
                "verdict": "PASS" if sources else "NOT APPLICABLE", "expected": "All literal source labels occur in first eight",
                "ranked_paths": [source["path"] for source in sources], "returned_notes": len(sources), "sources": sources,
                "empty_source_case": not sources, "expected_answer_mode": case["expected_answer"]["mode"],
                "host_answer_verdict": "NOT CHECKED", "capture_verdict": "NOT CHECKED",
                "labeled_source_precision": {"numerator": len(sources), "denominator": len(sources), "ratio": 1.0 if sources else None},
                "evidence": [label + suffix for suffix in (".before.json", ".after.json", ".notes.before.json", ".notes.after.json",
                    "-doctor.command.json", "-doctor.stdout.txt", "-doctor.stderr.txt", "-startup.requests.json", "-startup.command.json",
                    "-startup.stdout.txt", "-startup.stderr.txt", ".context.json")],
                "observed": {"complete_inventory_preserved": True, "literal_hint_used": True, "session_id": payload["session_id"], "fresh_process_and_vault": True}}
            data["cases"].append(row)
            data["binding_checks"].append({"id": label, "copied_product_unchanged": True, "all_frozen_notes_unchanged": True, "synthetic_self_unchanged": True})
        manifest = {key: data[key] for key in ("producer", "producer_sha256", "support_sha256", "product_hashes", "corpus_path", "corpus_sha256", "corpus_summary")}
        manifest.update(frozen_at="2026-10-19T12:00:00+00:00", frozen_before_first_product_invocation=True, complete_note_inventory=notes,
            case_registry=[case["id"] for case in corpus["cases"]], fixtures=fixtures, held_out_status="Process held out; synthetic control only",
            capture_policy_status="UNAPPROVED", acceptance_credit_awarded=False)
        self.save(directory / "run-manifest.json", manifest)
        self.recompute(data)
        path = directory / "report.json"
        self.refresh(path, data)
        return path, data

    def recompute(self, data):
        data["metrics"] = metric.quality_metrics(data["cases"])
        passed = all(data["metrics"][split]["retrieval_target_met"] for split in ("development", "held_out", "combined"))
        data["checks"] = [{"id": "quality.fixed_corpus", "verdict": "PASS", "expected": "Frozen diverse pre-labeled corpus",
                           "observed": data["corpus_summary"], "evidence": ["run-manifest.json"]},
                          {"id": "quality.retrieval_target", "verdict": "PASS" if passed else "FAIL", "expected": "All critical and at least 90 percent noncritical sources",
                           "observed": data["metrics"], "evidence": [case["id"] + ".context.json" for case in data["cases"]]}]
        data["verdict"] = "PASS" if passed else "FAIL"

    def change_context(self, path, data, index, change):
        label = data["cases"][index]["id"]
        payload = metric.read_json(path.parent / (label + ".context.json"))
        change(payload)
        self.save(path.parent / (label + ".context.json"), payload)
        stdout_path = path.parent / (label + "-startup.stdout.txt")
        responses = [json.loads(line) for line in stdout_path.read_text(encoding="utf-8").splitlines()]
        responses[-1]["result"]["content"][0]["text"] = json.dumps(payload, ensure_ascii=False)
        stdout_path.write_text("".join(json.dumps(response, ensure_ascii=False) + "\n" for response in responses), encoding="utf-8")
        corpus = metric.read_json(ROOT / "tests/fixtures/quality-v1.json")
        data["cases"][index].update(metric.quality_case(corpus["cases"][index], payload))
        self.recompute(data)
        self.refresh(path, data)

    def test_complete_corpus_awards_only_two_existing_evaluation_outcomes(self):
        path, data = self.quality_fixture()
        report = metric.quality_report(path, self.current)
        passed = {item["id"] for item in metric.read_json(metric.RUBRIC)["outcomes"] if metric.outcome(item, [report])["verdict"] == "PASS"}
        self.assertEqual(passed, {"QUALITY.fixed_corpus", "QUALITY.retrieval_target"})
        self.assertEqual(data["metrics"]["combined"]["critical_sources"], {"numerator": 10, "denominator": 10, "ratio": 1.0})
        self.assertEqual(data["metrics"]["combined"]["critical_claims"], {"numerator": 16, "denominator": 16})
        self.assertEqual(data["metrics"]["combined"]["noncritical_sources"], {"numerator": 31, "denominator": 31, "ratio": 1.0})
        self.assertEqual(data["metrics"]["combined"]["empty_source_cases"], 6)

    def test_actual_critical_quote_failure_keeps_corpus_pass_and_retrieval_fail(self):
        path, data = self.quality_fixture()
        self.change_context(path, data, 3, lambda payload: payload["context"]["relevant"]["ranked"][0].update(excerpt="Unavailable exact critical evidence"))
        report = metric.quality_report(path, self.current)
        self.assertEqual(report["checks"]["quality.fixed_corpus"]["verdict"], "PASS")
        self.assertEqual(report["checks"]["quality.retrieval_target"]["verdict"], "FAIL")
        self.assertEqual(data["metrics"]["combined"]["critical_sources"]["numerator"], 10)
        self.assertEqual(data["metrics"]["combined"]["critical_claims"]["numerator"], 14)

    def test_rank_eight_counts_and_rank_nine_does_not(self):
        corpus = metric.read_json(ROOT / "tests/fixtures/quality-v1.json")
        case = corpus["cases"][3]
        source = case["expected_sources"][0]
        target = {"path": source["path"], "excerpt": "\n".join(claim["quote"] for claim in source["claims"])}
        filler = [{"path": "Other/" + str(index) + ".md"} for index in range(8)]
        payload = {"context": {"task_hint": case["task_hint"], "relevant": {"ranked": filler[:7] + [target]}}, "session_id": "synthetic"}
        result = metric.quality_case(case, payload)
        self.assertEqual(result["sources"][0]["rank"], 8)
        self.assertTrue(result["sources"][0]["in_first_eight"])
        payload["context"]["relevant"]["ranked"] = filler + [target]
        result = metric.quality_case(case, payload)
        self.assertFalse(result["sources"][0]["in_first_eight"])
        self.assertIsNone(result["sources"][0]["rank"])
        self.assertFalse(result["sources"][0]["claims"][0]["available_in_source_context"])

    def test_exact_ninety_percent_and_split_requirements_are_independent(self):
        rows = []
        for split in ("development", "held_out"):
            for index in range(11):
                critical = index == 0
                source = {"critical": critical, "in_first_eight": index != 10, "claims": [{"available_in_source_context": True}]}
                rows.append({"split": split, "sources": [source], "empty_source_case": False, "verdict": "PASS",
                             "returned_notes": 1, "labeled_source_precision": {"numerator": int(source["in_first_eight"])}})
        result = metric.quality_metrics(rows)
        self.assertTrue(result["combined"]["retrieval_target_met"])
        self.assertEqual(result["combined"]["noncritical_sources"]["ratio"], 0.9)
        rows[1]["sources"][0]["in_first_eight"] = False
        self.assertFalse(metric.quality_metrics(rows)["development"]["retrieval_target_met"])
        self.assertFalse(metric.quality_metrics(rows)["combined"]["retrieval_target_met"])
        self.assertFalse(metric.quality_metrics([])["combined"]["retrieval_target_met"])

    def test_partial_cases_or_changed_metrics_cannot_award_evaluation_credit(self):
        path, data = self.quality_fixture()
        for change in (lambda value: value["cases"].pop(), lambda value: value["cases"][0].update(split="held_out"),
                       lambda value: value["metrics"]["combined"]["critical_sources"].update(numerator=999),
                       lambda value: value.update(execution_complete=False), lambda value: value.update(corpus_sha256="0" * 64),
                       lambda value: value["checks"][0].update(expected="")):
            changed = copy.deepcopy(data)
            change(changed)
            self.save(path, changed)
            with self.assertRaises(ValueError):
                metric.quality_report(path, self.current)

    def test_freeze_manifest_and_full_note_labels_must_precede_observation(self):
        path, data = self.quality_fixture()
        manifest_path = path.parent / "run-manifest.json"
        original = metric.read_json(manifest_path)
        for change in (lambda value: value.update(frozen_before_first_product_invocation=False),
                       lambda value: value.update(frozen_at="not-a-date"), lambda value: value["complete_note_inventory"].popitem(),
                       lambda value: value["case_registry"].pop(), lambda value: value.update(capture_policy_status="APPROVED")):
            changed = copy.deepcopy(original)
            change(changed)
            self.save(manifest_path, changed)
            self.refresh(path, data)
            with self.assertRaises(ValueError):
                metric.quality_report(path, self.current)

    def test_actual_distractor_bytes_and_wrong_vault_or_noop_command_are_rejected(self):
        path, data = self.quality_fixture()
        record_path = path.parent / "quality-v1-001-startup.command.json"
        original = metric.read_json(record_path)
        for field, value in (("command", [sys.executable, "-c", "pass"]), ("vault", str(ROOT)), ("pythonpath", str(ROOT)), ("pid", True)):
            changed = copy.deepcopy(original)
            changed[field] = value
            self.save(record_path, changed)
            self.refresh(path, data)
            with self.assertRaises(ValueError):
                metric.quality_report(path, self.current)
        self.save(record_path, original)
        self.refresh(path, data)
        inventory_path = path.parent / "quality-v1-001.before.json"
        inventory = metric.read_json(inventory_path)
        changed = copy.deepcopy(inventory)
        changed["Extra/Tuned.md"] = {"kind": "file", "links": 1, "size": 1, "sha256": "a" * 64}
        self.save(inventory_path, changed)
        self.refresh(path, data)
        with self.assertRaisesRegex(ValueError, "unlabelled"):
            metric.quality_report(path, self.current)
        self.save(inventory_path, inventory)
        self.refresh(path, data)
        distractor = path.parent / "fixtures/quality-v1-001/vault/Clippings/Keyboard-Advertisement.md"
        distractor.write_text("Changed distractor after observation\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "actual retained note"):
            metric.quality_report(path, self.current)

    def test_payload_tamper_and_unstopped_process_do_not_inherit_corpus_pass(self):
        path, data = self.quality_fixture()
        for change in (lambda value: value["processes"][0].update(stopped=False),
                       lambda value: value["cases"][0]["sources"][0].update(in_first_eight=False)):
            changed = copy.deepcopy(data)
            change(changed)
            self.save(path, changed)
            with self.assertRaises(ValueError):
                metric.quality_report(path, self.current)
        self.save(path, data)
        payload_path = path.parent / "quality-v1-001.context.json"
        self.save(payload_path, {"context": {}, "session_id": "fabricated"})
        self.refresh(path, data)
        with self.assertRaisesRegex(ValueError, "actual startup MCP"):
            metric.quality_report(path, self.current)

    def test_empty_sources_never_become_positive_recall_or_human_grounding(self):
        corpus = metric.read_json(ROOT / "tests/fixtures/quality-v1.json")
        case = next(case for case in corpus["cases"] if not case["expected_sources"])
        payload = {"context": {"task_hint": case["task_hint"], "relevant": {"ranked": [{"path": "Unrelated.md"}]}}, "session_id": "synthetic"}
        row = metric.quality_case(case, payload)
        self.assertEqual(row["verdict"], "NOT APPLICABLE")
        self.assertEqual(row["host_answer_verdict"], "NOT CHECKED")
        self.assertEqual(row["capture_verdict"], "NOT CHECKED")
        metrics = metric.quality_metrics([row])["combined"]
        self.assertEqual(metrics["critical_sources"]["denominator"], 0)
        self.assertEqual(metrics["noncritical_sources"]["denominator"], 0)
        self.assertFalse(metrics["retrieval_target_met"])

    def test_corpus_label_tamper_is_rejected_independently_of_declared_digest(self):
        corpus = metric.read_json(ROOT / "tests/fixtures/quality-v1.json")
        for change in (lambda value: value.update(labels_observed_from_product=True),
                       lambda value: value["cases"][0]["expected_sources"][0]["claims"][0].update(quote="Unwritten evidence"),
                       lambda value: value["evaluation_contract"].update(noncritical_expected_source_target=0.8),
                       lambda value: value["splits"]["held_out"].pop()):
            changed = copy.deepcopy(corpus)
            change(changed)
            with patch.object(metric, "read_json", return_value=changed), self.assertRaises(ValueError):
                metric.quality_corpus()


if __name__ == "__main__":
    unittest.main()
