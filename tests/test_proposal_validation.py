"""Public validation compatibility for retained Self-proposal metadata."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProposalValidationTests(unittest.TestCase):
    def setUp(self):
        evidence = os.environ.get("PROPOSAL_VALIDATION_EVIDENCE")
        base = Path(evidence) if evidence else ROOT / "work/gc-artifacts/.knowledgeos/proposal-validation-regression"
        self.scope = base / (hashlib.sha256(self._testMethodName.encode()).hexdigest()[:6] + "-" + uuid.uuid4().hex[:6])
        self.scope.mkdir(parents=True)
        (self.scope / "case.json").write_text(json.dumps({"test": self._testMethodName}), encoding="utf-8")
        self.vault = self.scope / "vault"
        self.state = self.scope / "state"
        self.environment = os.environ.copy()
        self.environment.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                                PYTHONIOENCODING="utf-8", KNOWLEDGEOS_STATE_DIR=str(self.state))
        self.initialize()

    def run_process(self, argv):
        process = subprocess.Popen(argv, cwd=ROOT, env=self.environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
        record = {"argv": list(map(str, argv)), "cwd": str(ROOT), "pid": process.pid,
                  "exit_code": process.returncode, "stopped": process.poll() is not None,
                  "timed_out": timed_out, "stdout": stdout, "stderr": stderr,
                  "vault": str(self.vault), "state": str(self.state), "import_root": str(ROOT)}
        with (self.scope / "processes.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
        self.assertFalse(timed_out, record)
        return record

    def cli(self, *args):
        return self.run_process([sys.executable, "-B", "-P", "-m", "knowledgeos", *map(str, args)])

    def initialize(self, force=False):
        args = ["init", self.vault, "--name", "Synthetic proposal validation", "--non-interactive"]
        if force:
            args.append("--force")
        result = self.cli(*args)
        self.assertEqual(result["exit_code"], 0, result)
        report = json.loads(result["stdout"])
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["post_init"]["validate"]["ok"], report)
        return report

    def propose(self):
        result = self.cli("memory", "memory_propose_self_update", "--vault", self.vault,
                          "--summary", "Synthetic retained history", "--section", "heuristics",
                          "--proposed-markdown", "* Check the original evidence.", "--mode", "append")
        self.assertEqual(result["exit_code"], 0, result)
        report = json.loads(result["stdout"])
        self.assertTrue(report["ok"], report)
        self.assertFalse(report["mutated_self"], report)
        return self.vault / report["proposal_path"]

    def protected(self):
        paths = [self.vault / "People/Self.md", self.vault / ".knowledgeos-vault.json"]
        paths += sorted((self.vault / "People/Self-Proposals").glob("*.md"))
        paths += sorted(path for path in self.state.rglob("*") if path.is_file())
        return {str(path.relative_to(self.scope)): sha(path) for path in paths}

    def validations(self, expected_invalid=None):
        expected_invalid = expected_invalid or []
        before = self.protected()
        commands = [
            [sys.executable, "-B", "-P", "-m", "knowledgeos", "validate", "--vault", str(self.vault)],
            [sys.executable, "-B", str(ROOT / "scripts/validate_schema.py"), "--vault", str(self.vault)],
        ]
        for argv in commands:
            result = self.run_process(argv)
            report = json.loads(result["stdout"])
            self.assertEqual(result["exit_code"], 1 if expected_invalid else 0, result)
            self.assertEqual(report["summary"]["errors"], len(expected_invalid), report)
            self.assertEqual(sorted((entry["path"], entry.get("status")) for entry in report["errors"]),
                             sorted(expected_invalid), report)
            self.assertTrue(all(entry["issue"] == "invalid_status" for entry in report["errors"]), report)
            self.assertEqual(self.protected(), before)

    def write_status_fixture(self, relative, status, metadata="", kind="research"):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntype: " + kind + "\ntitle: Synthetic status fixture\n"
                        "description: Metadata compatibility only, no identity approval.\n"
                        "schema: knowledgeos-v0.3\ncreated: 2026-10-20\nupdated: 2026-10-20\n"
                        "tags: [synthetic]\nstatus: " + status + "\n" + metadata +
                        "---\n# Synthetic metadata fixture\n", encoding="utf-8")
        return path

    def test_public_rejection_remains_valid_and_force_init_preserves_history(self):
        before_self = sha(self.vault / "People/Self.md")
        proposal = self.propose()
        self.validations()
        result = self.cli("memory", "memory_reject_self_update", "--vault", self.vault,
                          "--path", proposal.relative_to(self.vault),
                          "--args", json.dumps({"reason": "Synthetic public rejection control"}))
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue(json.loads(result["stdout"])["ok"], result)
        self.assertIn("status: rejected\n", proposal.read_text(encoding="utf-8"))
        self.assertEqual(sha(self.vault / "People/Self.md"), before_self)
        history = self.protected()
        (self.scope / "before-validation-history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        failures = []
        try:
            self.validations()
        except AssertionError as error:
            failures.append(str(error))
        try:
            self.initialize(force=True)
        except AssertionError as error:
            failures.append(str(error))
        after = self.protected()
        (self.scope / "after-init-history.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
        self.assertEqual(after, history)
        self.assertEqual(sha(self.vault / "People/Self.md"), before_self)
        self.assertEqual(failures, [], "\n".join(failures))

    def test_terminal_metadata_statuses_are_compatible_without_approval(self):
        before_self = sha(self.vault / "People/Self.md")
        metadata = "proposal_target: People/Self.md\nproposal_origin: memory_propose_self_update\n"
        for status in ("accepted", "rejected", "superseded"):
            self.write_status_fixture("People/Self-Proposals/metadata-" + status + ".md", status, metadata)
        history = self.protected()
        self.validations()
        self.initialize(force=True)
        self.assertEqual(self.protected(), history)
        self.assertEqual(sha(self.vault / "People/Self.md"), before_self)

    def test_terminal_statuses_refuse_outside_canonical_proposal_domain(self):
        metadata = "proposal_target: People/Self.md\nproposal_origin: memory_propose_self_update\n"
        expected = []
        for status in ("accepted", "rejected", "superseded"):
            for folder in ("Concepts", "Projects/People/Self-Proposals", "People/Self-Proposals/Nested"):
                relative = folder + "/" + status + ".md"
                self.write_status_fixture(relative, status, metadata)
                expected.append((relative, status))
        self.validations(expected)

    def test_proposal_directory_alone_or_partial_metadata_does_not_expand_statuses(self):
        variants = {"unmarked": "", "target-only": "proposal_target: People/Self.md\n",
                    "origin-only": "proposal_origin: memory_propose_self_update\n",
                    "other-target": "proposal_target: People/Other.md\nproposal_origin: memory_propose_self_update\n",
                    "other-origin": "proposal_target: People/Self.md\nproposal_origin: other_writer\n"}
        expected = []
        for name, metadata in variants.items():
            relative = "People/Self-Proposals/" + name + ".md"
            self.write_status_fixture(relative, "rejected", metadata)
            expected.append((relative, "rejected"))
        relative = "People/Self-Proposals/wrong-type.md"
        self.write_status_fixture(relative, "rejected",
                                  "proposal_target: People/Self.md\nproposal_origin: memory_propose_self_update\n",
                                  kind="decision")
        expected.append((relative, "rejected"))
        self.validations(expected)

    def test_regular_statuses_remain_valid_and_unknown_proposal_statuses_refuse(self):
        for status in ("draft", "active", "refined", "archived", "completed"):
            self.write_status_fixture("Concepts/" + status + ".md", status)
        self.validations()
        metadata = "proposal_target: People/Self.md\nproposal_origin: memory_propose_self_update\n"
        expected = []
        for status in ("applied", "approved", "invalid"):
            relative = "People/Self-Proposals/" + status + ".md"
            self.write_status_fixture(relative, status, metadata)
            expected.append((relative, status))
        self.validations(expected)


if __name__ == "__main__":
    unittest.main()
