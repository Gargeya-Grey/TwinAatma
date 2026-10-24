"""Frozen quality proof rejects missing evidence and misleading recall totals."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("quality_proof", SCRIPTS / "quality.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)
CORPUS = json.loads((ROOT / "tests/fixtures/quality-v3.json").read_text(encoding="utf-8"))


def payload(case, sources, missing_quotes=()):
    by_path = {note["path"]: note["content"] for note in CORPUS["notes"]}
    ranked = [{"path": path, "snippet": "Unavailable excerpt" if path in missing_quotes else by_path[path]}
              for path in sources]
    return {"session_id": "synthetic-session", "context": {"task_hint": case["task_hint"],
                                                             "relevant": {"ranked": ranked}}}


class QualityVerifierTests(unittest.TestCase):
    def test_frozen_corpus_has_literal_diverse_split_inventory(self):
        observed = proof.validate_corpus(CORPUS)
        self.assertEqual((observed["cases"], observed["notes"], observed["roles"]),
                         (108, 126, {'relevant': 88, 'distractor': 38}))
        self.assertEqual(observed["splits"], {
            'development': {'cases': 72, 'empty_source_cases': 10, 'noncritical_sources': 75, 'critical_sources': 30, 'critical_claims': 36},
            'held_out': {'cases': 36, 'empty_source_cases': 4, 'critical_sources': 14, 'critical_claims': 42, 'noncritical_sources': 22}})

    def test_all_original_cases_and_notes_remain_immutable_regressions(self):
        original_path = ROOT / "tests/fixtures/quality-v1.json"
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(),
                         "787de4674bb0a51fceee87acb7ee7e9b8872068e1fab8af24de3e729bcbac379")
        prior_path = ROOT / "tests/fixtures/quality-v2.json"
        self.assertEqual(hashlib.sha256(prior_path.read_bytes()).hexdigest(),
                         "8ec5e0e902c7fbdac2e81288a25a5d0c380a99b820217a67f052da178b6567c6")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        self.assertEqual(CORPUS["notes"][:82], prior["notes"])
        self.assertEqual(CORPUS["cases"][:72], [dict(case, split="development") for case in prior["cases"]])
        self.assertEqual(CORPUS["splits"]["development"], [case["id"] for case in prior["cases"]])
        self.assertEqual(hashlib.sha256(proof.CORPUS.read_bytes()).hexdigest(), proof.CORPUS_SHA256)

    def test_changed_old_labels_and_missing_fresh_cases_are_rejected(self):
        mutations = [
            lambda data: data["cases"][0]["expected_sources"][0]["claims"][0].update(text="Changed legacy claim label"),
            lambda data: data["cases"][0].update(task_hint="Changed legacy prompt"),
            lambda data: data["notes"][0].update(title="Changed legacy note label"),
            lambda data: data["cases"][36].update(task_hint="Changed retired v2 prompt"),
            lambda data: data["notes"][38].update(title="Changed retired v2 note label"),
            lambda data: data["cases"].pop(0),
            lambda data: data["cases"].pop(),
            lambda data: data["splits"]["held_out"].pop(),
            lambda data: data["cases"][72].update(split="development"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = copy.deepcopy(CORPUS)
                mutate(data)
                with self.assertRaises(ValueError):
                    proof.validate_corpus(data)

    def test_invalid_labels_and_changed_contract_fail_before_product_use(self):
        mutations = [
            lambda data: data.update(cases=data["cases"][:29]),
            lambda data: data["splits"]["held_out"].append("quality-v1-001"),
            lambda data: data["cases"][0]["expected_sources"][0].update(path="Missing.md"),
            lambda data: data["cases"][0]["expected_sources"][0]["claims"][0].update(quote="No such original sentence"),
            lambda data: data["notes"][0].update(path="../outside.md"),
            lambda data: data["notes"][0].update(path="C:/outside.md"),
            lambda data: data.update(labels_observed_from_product=True),
            lambda data: data["evaluation_contract"].update(noncritical_expected_source_target=0.8),
            lambda data: data["evaluation_contract"]["capture_policy"].update(status="APPROVED"),
            lambda data: data["cases"][0].update(expected_capture={}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = copy.deepcopy(CORPUS)
                mutate(data)
                with self.assertRaises(ValueError):
                    proof.validate_corpus(data)

    def test_missing_expected_source_is_not_retrieval_success(self):
        case = CORPUS["cases"][0]
        value = payload(case, ["Clippings/Keyboard-Advertisement.md"])
        row = proof.grade_case(case, value)
        self.assertEqual(row["verdict"], "FAIL")
        self.assertEqual(row["sources"][0]["in_first_eight"], False)
        self.assertEqual(row["labeled_source_precision"], {"numerator": 0, "denominator": 1, "ratio": 0.0})

    def test_critical_source_without_each_literal_fact_fails(self):
        case = CORPUS["cases"][3]
        path = "Preferences/Food.md"
        value = payload(case, [path], missing_quotes=[path])
        row = proof.grade_case(case, value)
        self.assertEqual(row["verdict"], "FAIL")
        self.assertEqual(row["sources"][0]["in_first_eight"], True)
        self.assertEqual([claim["available_in_source_context"] for claim in row["sources"][0]["claims"]], [False, False])
        value["context"]["relevant"]["fulltext"] = [{"path": path, "snippet": "I eat vegan food. I am allergic to hazelnuts."}]
        self.assertEqual(proof.grade_case(case, value)["verdict"], "PASS")

    def test_ninth_rank_and_extra_search_payload_cannot_rescue_a_source(self):
        case = CORPUS["cases"][0]
        distractors = [note["path"] for note in CORPUS["notes"] if note["role"] == "distractor"][:8]
        value = payload(case, distractors + ["Preferences/Travel-Keyboard.md"])
        value["extra_search"] = payload(case, ["Preferences/Travel-Keyboard.md"])
        row = proof.grade_case(case, value)
        self.assertEqual(row["verdict"], "FAIL")
        self.assertEqual(row["returned_notes"], 8)
        self.assertEqual(row["sources"][0]["rank"], None)

    def test_exact_ninety_percent_threshold_and_critical_veto(self):
        critical = CORPUS["cases"][3]
        initial = proof.grade_case(critical, payload(critical, ["Preferences/Food.md"]))
        rows = [initial]
        case = CORPUS["cases"][0]
        for index in range(10):
            changed = copy.deepcopy(case)
            changed["id"] = "noncritical-" + str(index)
            sources = ["Preferences/Travel-Keyboard.md"] if index < 9 else []
            rows.append(proof.grade_case(changed, payload(changed, sources)))
        observed = proof.aggregate(rows)["development"]
        self.assertEqual(observed["noncritical_sources"], {"numerator": 9, "denominator": 10, "ratio": 0.9})
        self.assertEqual(observed["critical_claims"], {"numerator": 2, "denominator": 2})
        self.assertEqual(observed["retrieval_target_met"], True)
        rows[9] = proof.grade_case(case, payload(case, []))
        self.assertEqual(proof.aggregate(rows)["development"]["retrieval_target_met"], False)
        rows[9] = proof.grade_case(case, payload(case, ["Preferences/Travel-Keyboard.md"]))
        rows[0] = proof.grade_case(critical, payload(critical, ["Preferences/Food.md"], ["Preferences/Food.md"]))
        self.assertEqual(proof.aggregate(rows)["development"]["retrieval_target_met"], False)

    def test_development_and_held_out_metrics_are_separate(self):
        development = CORPUS["cases"][3]
        held_out = dict(development, id="synthetic-held-out", split="held_out")
        rows = [proof.grade_case(development, payload(development, ["Preferences/Food.md"])),
                proof.grade_case(held_out, payload(held_out, []))]
        metrics = proof.aggregate(rows)
        self.assertEqual(metrics["development"]["critical_sources"], {"numerator": 1, "denominator": 1, "ratio": 1.0})
        self.assertEqual(metrics["held_out"]["critical_sources"], {"numerator": 0, "denominator": 1, "ratio": 0.0})
        self.assertEqual(metrics["combined"]["critical_sources"], {"numerator": 1, "denominator": 2, "ratio": 0.5})
        self.assertEqual(metrics["combined"]["cases"], 2)

    def test_unknown_and_empty_cases_do_not_create_positive_recall_or_answer_credit(self):
        case = CORPUS["cases"][23]
        row = proof.grade_case(case, payload(case, ["Preferences/Travel-Keyboard.md"]))
        metrics = proof.aggregate([row])["development"]
        self.assertEqual(row["verdict"], "NOT APPLICABLE")
        self.assertEqual(row["host_answer_verdict"], "NOT CHECKED")
        self.assertEqual((metrics["source_cases"], metrics["empty_source_cases"]), (0, 1))
        self.assertEqual(metrics["noncritical_sources"], {"numerator": 0, "denominator": 0, "ratio": None})
        self.assertEqual(metrics["labeled_source_precision"]["denominator"], 0)
        self.assertEqual(metrics["retrieval_target_met"], False)

    def test_all_distractors_must_exist_before_any_startup_command(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/retrieval-20261023/quality-v3-proof/unit-fixtures"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            vault = Path(folder) / "vault"
            for note in CORPUS["notes"]:
                target = vault / note["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(note["content"].encode("utf-8"))
            (vault / "People/Self.md").write_bytes(proof.SELF.encode("utf-8"))
            run = object.__new__(proof.QualityRun)
            run.expected_notes = {note["path"]: {"sha256": hashlib.sha256(note["content"].encode("utf-8")).hexdigest(),
                "size": len(note["content"].encode("utf-8")), "role": note["role"]} for note in CORPUS["notes"]}
            self.assertEqual(len(run.verify_notes(vault)), 126)
            distractor = next(note for note in CORPUS["notes"] if note["role"] == "distractor")
            (vault / distractor["path"]).unlink()
            run.prepared = True
            run.fixtures = {CORPUS["cases"][0]["id"]: vault}
            with patch.object(run, "command") as command:
                with self.assertRaisesRegex(ValueError, "including all distractors"):
                    run.run_case(CORPUS["cases"][0])
                command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
