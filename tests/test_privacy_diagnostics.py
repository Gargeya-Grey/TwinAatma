"""Policy exclusions apply to public diagnostic output as well as recall."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from unittest import mock

from support import ROOT, TempVaultCase


class PrivacyDiagnosticTests(TempVaultCase):
    def cli(self, *arguments):
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", *arguments,
                   "--vault", str(self.vault)]
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate(timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        evidence = os.environ.get("TA_DIAGNOSTIC_TEST_EVIDENCE")
        if evidence:
            with Path(evidence).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"command": command, "pid": process.pid,
                    "stopped": process.poll() is not None, "exit_code": process.returncode,
                    "stdout": stdout, "stderr": stderr}) + "\n")
        return process.returncode, stdout, stderr

    def test_pending_omits_legacy_signed_sensitive_proposal_paths(self):
        from knowledgeos.gate import propose
        token = "sk-" + secrets.token_hex(16)
        # A pre-policy signed proposal is fixture input, never approval or a current
        # authorized path for sensitive capture.
        proposal = propose(self.vault, self.vault / "People/Self.md", self.vault / "People/Self-Proposals",
                           "Legacy " + token, "heuristics", "* Prefer concise project reviews.", mode="append")
        self.assertTrue(proposal.get("ok"), proposal)
        before = (self.vault / proposal["proposal_path"]).read_bytes()
        code, stdout, stderr = self.cli("self", "pending")
        self.assertEqual(code, 0, stderr)
        self.assertNotIn(token, stdout + stderr)
        self.assertNotIn(proposal["proposal_path"], stdout)
        self.assertEqual((self.vault / proposal["proposal_path"]).read_bytes(), before)

    def test_pending_retains_ordinary_proposals(self):
        proposal = self.api().propose_self_update("Review cadence", "heuristics", "* Prefer concise project reviews.", mode="append")
        self.assertTrue(proposal.get("ok"), proposal)
        code, stdout, stderr = self.cli("self", "pending")
        self.assertEqual(code, 0, stderr)
        self.assertIn(proposal["proposal_path"], stdout)

    def malformed_policy(self):
        path = self.vault / ".knowledgeos/remembering-policy.json"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'{"version":1,"forgotten":{},"forgotten":{},"superseded":{}}')
        return path.read_bytes()

    def test_pending_refuses_malformed_policy_without_rewriting_it(self):
        before = self.malformed_policy()
        code, stdout, stderr = self.cli("self", "pending")
        self.assertNotEqual(code, 0)
        self.assertIn("policy", (stdout + stderr).lower())
        self.assertEqual((self.vault / ".knowledgeos/remembering-policy.json").read_bytes(), before)

    def test_doctor_reports_obstructed_state_without_traceback_or_rewriting_sources(self):
        private = self.write("Concepts/private-doctor.md",
                             "---\nprivacy: exclude\n---\n\n# Private diagnostic fixture\n")
        state = self.vault / ".knowledgeos"
        retained = self.vault / "retained-state"
        state.rename(retained)
        state.write_bytes(b"Preserve this state-folder obstruction.\n")
        before = {path.relative_to(self.vault).as_posix(): path.read_bytes()
                  for path in self.vault.rglob("*") if path.is_file()}
        with self.guard() as identity:
            code, stdout, stderr = self.cli("doctor")
        identity.assert_unchanged(self)
        self.assertEqual(code, 1, stdout + stderr)
        self.assertIn(".knowledgeos exists but is not a folder", stdout)
        self.assertIn("[FAIL] Environment check FAILED", stdout)
        self.assertNotIn("Traceback", stdout + stderr)
        self.assertNotIn(private.name, stdout + stderr)
        self.assertEqual({path.relative_to(self.vault).as_posix(): path.read_bytes()
                          for path in self.vault.rglob("*") if path.is_file()}, before)

    def drift(self, history):
        spec = importlib.util.spec_from_file_location("privacy_drift_fixture", ROOT / "scripts/semantic_drift.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (self.vault / ".git").mkdir(exist_ok=True)
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(module, "VAULT_DIR", self.vault), \
             mock.patch.object(module, "run_git_command", return_value=history), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = module.main()
            except SystemExit as error:
                code = error.code
        return code or 0, stdout.getvalue(), stderr.getvalue()

    def test_drift_reports_only_permitted_current_personal_sources(self):
        token = "sk-" + secrets.token_hex(16)
        ordinary = self.vault / "Concepts/current.md"
        ordinary.parent.mkdir(exist_ok=True)
        ordinary.write_text("# Current\n\nUse concise project reviews.\n", encoding="utf-8")
        private = self.vault / ("Concepts/private-" + token + ".md")
        private.write_text("---\nprivacy: exclude\n---\n\n# Private source\n", encoding="utf-8")
        history = "Concepts/current.md\n" + private.relative_to(self.vault).as_posix() + "\nAGENTS.md\n"
        code, stdout, stderr = self.drift(history)
        self.assertEqual(code, 0, stderr)
        self.assertIn("Concepts/current.md", stdout)
        self.assertNotIn(token, stdout + stderr)
        self.assertNotIn("AGENTS.md", stdout)
        self.assertNotIn("suggest updates for my People/Self.md", stdout)

    def test_drift_refuses_unavailable_policy_before_releasing_activity(self):
        before = self.malformed_policy()
        code, stdout, stderr = self.drift("Concepts/private.md\n")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Concepts/private.md", stdout + stderr)
        self.assertEqual((self.vault / ".knowledgeos/remembering-policy.json").read_bytes(), before)
