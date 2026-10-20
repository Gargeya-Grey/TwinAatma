"""Synthetic score-adapter controls; these fixtures are never product acceptance evidence."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/acceptance.py"
SPEC = importlib.util.spec_from_file_location("data_acceptance_controls", SCRIPT)
metric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metric)


class DataScoreTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/data-preservation-20261019/data-scoring/unit-fixtures"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.current = {"knowledgeos/fake.py": "a" * 64, "AGENTS.md": "b" * 64}
        self.toolkit = dict(self.current, **{"scripts/export_bundle.py": "c" * 64})
        self.producers = self.directory / "test-producers"
        self.producers.mkdir()
        for name in ("acceptance.py", "data_preservation.py", "generated_writers.py", "memory_census.py"):
            (self.producers / name).write_text("# Synthetic adapter unit fixture only.\n", encoding="utf-8")
        for replacement in (
                patch.object(metric, "__file__", str(self.producers / "acceptance.py")),
                patch.object(metric, "data_toolkit_hashes", return_value=self.toolkit),
                patch.object(metric, "product_hashes", return_value=self.current)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def save(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def report(self, producer="verify-twinaatma.data-preservation/v1"):
        spec = metric.DATA_PRODUCERS[producer]
        directory = self.directory / spec["file"].removesuffix(".py")
        directory.mkdir(exist_ok=True)
        vault = directory / "fixtures/probe/vault"
        vault.mkdir(parents=True, exist_ok=True)
        command = {"pid": 1234, "exit_code": 0, "stopped": True, "shell": False,
                   "command": [sys.executable, "-c", "print('synthetic unit fixture')"],
                   "cwd": str(vault), "vault": str(vault), "state_dir": str(directory / "gate-state"),
                   "seconds": 0.01, "error": None}
        self.save(directory / "probe.command.json", command)
        (directory / "probe.stdout.txt").write_text("Synthetic unit fixture only.\n", encoding="utf-8")
        (directory / "probe.stderr.txt").write_text("", encoding="utf-8")
        cases = []
        copied = {"vault/" + name: {"kind": "file", "links": 1, "sha256": digest}
                  for name, digest in self.toolkit.items()}
        for identifier in sorted(spec["cases"]):
            references = ["probe.command.json", "probe.stdout.txt", "probe.stderr.txt"]
            if spec["file"] != "memory_census.py":
                name = identifier.split(".", 2)[2] + ".before.json"
                self.save(directory / name, copied)
                references.append(name)
            cases.append({"id": identifier, "verdict": "PASS", "expected": "Synthetic expected observation",
                          "observed": {"literal": "unit control"}, "evidence": references})
        sentinels = {str(ROOT / name): "d" * 64 for name in
                     ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}
        data = {"producer": producer, "producer_sha256": metric.sha(self.producers / spec["file"]),
                "support_sha256": {name: metric.sha(self.producers / name) for name in spec["support"]},
                "scope": "source-only synthetic adapter unit fixture", "platform": "synthetic", "python": sys.version,
                "product_hashes": self.toolkit, "product_hashes_after": self.toolkit,
                "product_and_producer_unchanged": True, "cases": cases, "verdict": "PASS", "error": None,
                "processes": [{"pid": 1234, "role": "probe", "stopped": True, "exit_code": 0}],
                "all_started_processes_stopped": True,
                "isolation": {"before": sentinels, "after": copy.deepcopy(sentinels), "selected_sentinels_unchanged": True}}
        if spec["file"] == "memory_census.py":
            data["toolkit_copy_evidence"] = "toolkit-copy.before.json"
            self.save(directory / "toolkit-copy.before.json", copied)
        data["evidence_files"] = {path.name: metric.sha(path) for path in directory.iterdir() if path.is_file() and path.name != "report.json"}
        path = directory / "report.json"
        self.save(path, data)
        return path, data

    def parse(self, path):
        return metric.data_report(path, self.current)

    def assert_rejected(self, path, data, pattern):
        self.save(path, data)
        with self.assertRaisesRegex(ValueError, pattern):
            self.parse(path)

    def aggregate(self, path):
        result = self.parse(path)
        identifier = metric.DATA_PRODUCERS[result["producer"]]["aggregate"]
        return result["checks"][identifier]["verdict"]

    def test_complete_source_reports_award_exactly_three_fixed_outcomes(self):
        reports = [self.parse(self.report(producer)[0]) for producer in metric.DATA_PRODUCERS]
        rubric = metric.read_json(metric.RUBRIC)
        passed = {item["id"] for item in rubric["outcomes"] if metric.outcome(item, reports)["verdict"] == "PASS"}
        self.assertEqual(passed, {"DATA.safe_export", "DATA.atomic_generated", "DATA.memory_census"})
        self.assertEqual(len(rubric["outcomes"]), 54)
        self.assertEqual(metric.sha(metric.RUBRIC), "744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91")
        self.assertTrue(all(report["scope"] == "source" for report in reports))

    def test_cli_accepts_repeatable_data_reports_without_scope_leakage(self):
        paths = [self.report(producer)[0] for producer in metric.DATA_PRODUCERS]
        output = self.directory / "synthetic-score.json"
        arguments = [str(SCRIPT), "--output", str(output)]
        for path in paths:
            arguments += ["--data-report", str(path)]
        with patch.object(sys, "argv", arguments), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(metric.main(), 0)
        result = metric.read_json(output)
        self.assertEqual(result["counts"]["PASS"], 3)
        self.assertEqual(result["denominator"], 54)
        self.assertEqual(result["readiness_verdict"], "NOT ACCEPTED")
        self.assertEqual(result["adapter_requirements"]["version"], "verify-twinaatma.adapters/v12")
        self.assertTrue(all(result["outcomes"][name]["verdict"] == "NOT CHECKED" for name in
                            ("SETUP.artifact_install", "SETUP.host_discovery", "IDENTITY.owner_exact_approval")))

    def test_missing_cases_and_nonpassing_cases_never_receive_partial_credit(self):
        for producer in metric.DATA_PRODUCERS:
            path, data = self.report(producer)
            missing = data["cases"].pop()
            self.save(path, data)
            self.assertEqual(self.aggregate(path), "NOT CHECKED")
            data["cases"].append(missing)
            for status in ("FAIL", "BLOCKED", "NOT CHECKED"):
                with self.subTest(producer=producer, status=status):
                    data["cases"][0]["verdict"] = status
                    self.save(path, data)
                    self.assertEqual(self.aggregate(path), status)

    def test_partial_reports_cannot_be_merged_into_complete_proof(self):
        path, data = self.report()
        half = len(data["cases"]) // 2
        other = copy.deepcopy(data)
        data["cases"] = data["cases"][:half]
        other["cases"] = other["cases"][half:]
        self.save(path, data)
        first = self.parse(path)
        self.save(path, other)
        second = self.parse(path)
        item = next(item for item in metric.read_json(metric.RUBRIC)["outcomes"] if item["id"] == "DATA.safe_export")
        self.assertEqual(metric.outcome(item, [first, second])["verdict"], "NOT CHECKED")

    def test_unknown_manual_duplicate_and_unobserved_claims_are_rejected(self):
        for change, pattern in (
                (lambda data: data.update(producer="manual/data-pass"), "producer"),
                (lambda data: data["cases"][0].update(id="data.export.human_approved"), "Unknown producer"),
                (lambda data: data["cases"].append(copy.deepcopy(data["cases"][0])), "duplicate"),
                (lambda data: data["cases"][0].update(observed=None), "literal observed"),
                (lambda data: data["cases"][0].update(expected=""), "expected result"),
                (lambda data: data["cases"][0].update(evidence=[]), "retained evidence")):
            with self.subTest(pattern=pattern):
                path, data = self.report()
                change(data)
                self.assert_rejected(path, data, pattern)

    def test_stale_producer_support_product_or_toolkit_inputs_are_rejected(self):
        for change, pattern in (
                (lambda data: data.update(producer_sha256="0" * 64), "producer hash"),
                (lambda data: data.update(support_sha256={}), "support producer"),
                (lambda data: data["product_hashes"].update({"knowledgeos/fake.py": "0" * 64}), "exact current product"),
                (lambda data: data["product_hashes"].update({"scripts/export_bundle.py": "0" * 64}), "copied-toolkit input"),
                (lambda data: data.update(product_hashes_after={}), "copied-toolkit input"),
                (lambda data: data.update(product_and_producer_unchanged=False), "changed during")):
            with self.subTest(pattern=pattern):
                path, data = self.report("verify-twinaatma.generated-writers/v2")
                data["product_hashes"] = dict(data["product_hashes"])
                change(data)
                self.assert_rejected(path, data, pattern)

    def test_tampered_transcript_missing_file_and_unhashed_reference_are_rejected(self):
        path, data = self.report()
        (path.parent / "probe.stdout.txt").write_text("Tampered unit fixture", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.parse(path)
        path, data = self.report()
        (path.parent / "probe.stderr.txt").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or linked"):
            self.parse(path)
        path, data = self.report()
        data["cases"][0]["evidence"].append("not-hashed.txt")
        self.assert_rejected(path, data, "hashed retained evidence")

    def test_escaped_and_hardlinked_evidence_is_rejected(self):
        path, data = self.report()
        data["evidence_files"]["../escape.txt"] = "0" * 64
        self.assert_rejected(path, data, "contained retained file")
        path, data = self.report()
        target = path.parent / "probe.stdout.txt"
        try:
            os.link(target, path.parent / "hardlink.txt")
        except OSError as error:
            self.skipTest("Native hardlinks unavailable: " + str(error))
        with self.assertRaisesRegex(ValueError, "hardlinked"):
            self.parse(path)

    def test_report_path_rejects_lexical_parent_components(self):
        path, data = self.report()
        alias = path.parent / ".." / path.parent.name / path.name
        self.assertTrue(alias.is_file())
        with self.assertRaisesRegex(ValueError, "lexical parent"):
            self.parse(alias)

    def test_linked_evidence_parent_is_rejected(self):
        path, data = self.report()
        alias = self.directory / "linked-report"
        try:
            alias.symlink_to(path.parent, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest("Native directory links unavailable: " + str(error))
            junction = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(path.parent)],
                                      capture_output=True, text=True, timeout=10)
            if junction.returncode:
                self.skipTest("Native directory link and junction unavailable: " + junction.stderr)
        with self.assertRaisesRegex(ValueError, "linked|reparse"):
            self.parse(alias / path.name)

    def test_shutdown_claim_requires_retained_owned_command_pid_and_exit_records(self):
        for field, value in (("stopped", False), ("exit_code", None), ("pid", True), ("role", "unknown")):
            with self.subTest(field=field):
                path, data = self.report()
                data["processes"][0][field] = value
                self.assert_rejected(path, data, "shutdown|command and output")
        path, data = self.report()
        command_path = path.parent / "probe.command.json"
        record = metric.read_json(command_path)
        record["pid"] += 1
        self.save(command_path, record)
        data["evidence_files"][command_path.name] = metric.sha(command_path)
        self.assert_rejected(path, data, "disagrees")
        path, data = self.report()
        data["all_started_processes_stopped"] = False
        self.assert_rejected(path, data, "shutdown")

    def test_command_targeting_real_vault_or_external_state_cannot_earn_credit(self):
        for field, value in (("cwd", str(ROOT)), ("vault", str(ROOT)), ("state_dir", str(ROOT / ".knowledgeos"))):
            with self.subTest(field=field):
                path, data = self.report()
                record_path = path.parent / "probe.command.json"
                record = metric.read_json(record_path)
                record[field] = value
                self.save(record_path, record)
                data["evidence_files"][record_path.name] = metric.sha(record_path)
                self.assert_rejected(path, data, "synthetic vault|isolated state")

    def test_isolation_requires_exact_unchanged_selected_sentinels(self):
        for change in (
                lambda data: data["isolation"]["after"].update({str(ROOT / "People/Self.md"): "0" * 64}),
                lambda data: data["isolation"].update(selected_sentinels_unchanged=False),
                lambda data: data["isolation"].update(before={"fake": "0" * 64}, after={"fake": "0" * 64}),
                lambda data: data["isolation"].update(before={}, after={})):
            path, data = self.report()
            change(data)
            self.assert_rejected(path, data, "isolation|outside the retained repository")

    def test_copied_toolkit_is_checked_independently_of_hash_and_boolean_claims(self):
        path, data = self.report()
        before_path = path.parent / data["cases"][0]["evidence"][-1]
        copied = metric.read_json(before_path)
        copied["vault/scripts/export_bundle.py"]["sha256"] = "0" * 64
        self.save(before_path, copied)
        data["evidence_files"][before_path.name] = metric.sha(before_path)
        self.assert_rejected(path, data, "copied-toolkit bytes")

    def test_census_uses_pre_probe_copy_binding_instead_of_changed_instruction_probe_bytes(self):
        path, data = self.report("verify-twinaatma.memory-census/v2")
        self.assertEqual(self.aggregate(path), "PASS")
        data.pop("toolkit_copy_evidence")
        self.assert_rejected(path, data, "pre-probe copied-toolkit")
        data["toolkit_copy_evidence"] = "toolkit-copy.before.json"
        copied_path = path.parent / data["toolkit_copy_evidence"]
        self.save(copied_path, {})
        data["evidence_files"][copied_path.name] = metric.sha(copied_path)
        self.assert_rejected(path, data, "copied-toolkit bytes")

    def test_execution_error_remains_a_failed_outcome(self):
        path, data = self.report()
        data["error"] = "Synthetic command execution failure"
        self.save(path, data)
        self.assertEqual(self.aggregate(path), "FAIL")


if __name__ == "__main__":
    unittest.main()
