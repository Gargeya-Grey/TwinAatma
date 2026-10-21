"""Regression tests for nine product gaps found by the integrity, signing-state and
upgrade/divergence journeys.

Each test goes through the public surface (the CLI entry point, ``gate`` and ``doctor``
functions) and was written before the fix: it fails on the code that preceded it.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import secrets
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import support
from support import ROOT, TempVaultCase

# The recovery wording the journeys look for. Copies of the journey patterns, kept here so
# the product tests do not import the fixed journey scripts.
RECOVERY = re.compile(r"(?i)\b(?:restore|backup|re-?propos\w*|propose (?:it )?again|new proposal|create a new|signing key|key file|recover\w*)\b")
PROPOSE_AGAIN = re.compile(r"propos\w*[^.\n]{0,40}\bagain\b|\bagain\b[^.\n]{0,40}propos|new proposal", re.I)
OTHER_DEVICE = re.compile(r"\b(another|different|other)\b[^.\n]{0,24}\b(device|install|machine|computer)\b", re.I)

NOTE = (
    "---\ntype: project\ntitle: {title}\ndescription: Synthetic note\nstatus: active\n"
    "schema: knowledgeos-v0.3\ncreated: 2026-10-21\nupdated: 2026-10-21\ntags: [synthetic]\n"
    "id: {note_id}\n---\n# {title}\nSee [Self](../People/Self.md).\n"
)


def run_doctor(vault: Path) -> tuple[int, str]:
    from knowledgeos import doctor

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = doctor.run_doctor(vault)
    return code, buffer.getvalue()


def cli(argv: list[str], *, tty: bool = True) -> tuple[int, str, str]:
    from knowledgeos.__main__ import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch("sys.stdin") as fake_stdin, \
            mock.patch("builtins.input", side_effect=AssertionError("the approval prompt was reached")):
        fake_stdin.isatty.return_value = tty
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class GateRefusalTests(TempVaultCase):
    def propose(self, text="* Prefer short notes before long ones", section="heuristics"):
        api = self.api()
        result = api.propose_self_update("Synthetic proposal", section, text, mode="append")
        return api, result["proposal_path"]

    # D1 ----------------------------------------------------------------------------------
    def test_a_rejected_proposal_with_restored_bytes_is_refused_before_the_prompt(self):
        from knowledgeos import gate

        api, rel = self.propose()
        original = (self.vault / rel).read_bytes()
        self.assertTrue(api.reject_self_update(rel, "no").get("ok"))
        (self.vault / rel).write_bytes(original)

        with self.guard() as guard:
            described = gate.describe(api.vault, api.proposals_dir, rel)
            code, _, err = cli(["self", "approve", rel, "--vault", str(self.vault)])
        guard.assert_unchanged(self)
        self.assertIn("rejected", str(described.get("error")))
        self.assertNotIn("patch", described)
        self.assertEqual(code, 1)
        self.assertIn("rejected", err)

    def test_every_row_that_is_not_an_open_draft_is_refused_by_describe(self):
        from knowledgeos import gate

        for status in ("applied", "superseded", "withdrawn"):
            with self.subTest(status=status):
                api, rel = self.propose("* line for " + status)
                gate._set_status(api.vault, rel, status)
                described = gate.describe(api.vault, api.proposals_dir, rel)
                self.assertIn(status, str(described.get("error")))
                self.assertNotIn("patch", described)

    def test_an_open_draft_is_still_described(self):
        from knowledgeos import gate

        api, rel = self.propose()
        described = gate.describe(api.vault, api.proposals_dir, rel)
        self.assertNotIn("error", described)
        self.assertEqual(described["section"], "heuristics")

    # D2 ----------------------------------------------------------------------------------
    def copy_of(self, rel):
        target = self.vault / "People/Self-Proposals/copied-under-a-new-filename.md"
        target.write_bytes((self.vault / rel).read_bytes())
        return target.relative_to(self.vault).as_posix()

    def test_the_unregistered_refusal_says_how_to_recover(self):
        from knowledgeos import gate

        api, rel = self.propose()
        copy = self.copy_of(rel)
        described = gate.describe(api.vault, api.proposals_dir, copy)
        self.assertIn("not registered in this install's Self proposal ledger", described["error"])
        self.assertIsNotNone(RECOVERY.search(described["hint"]), described["hint"])
        self.assertIsNotNone(PROPOSE_AGAIN.search(described["hint"]), described["hint"])
        code, _, err = cli(["self", "approve", copy, "--vault", str(self.vault)])
        self.assertEqual(code, 1)
        self.assertIsNotNone(PROPOSE_AGAIN.search(err), err)

    def test_the_reject_refusal_says_how_to_recover(self):
        from knowledgeos import gate

        api, rel = self.propose()
        copy = self.copy_of(rel)
        refused = gate.reject(api.vault, api.proposals_dir, copy)
        self.assertIn("not a Self proposal registered in this install's ledger", refused["error"])
        self.assertIsNotNone(PROPOSE_AGAIN.search(refused["hint"]), refused["hint"])

    # D4 ----------------------------------------------------------------------------------
    def test_a_null_device_is_not_a_console(self):
        from knowledgeos import gate

        with open(os.devnull, "r") as null:
            self.assertFalse(gate.is_real_console(null))

    def test_approve_with_stdin_on_the_null_device_is_refused_before_the_prompt(self):
        api, rel = self.propose()
        env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(self.root / "state"), PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
        env.pop("KNOWLEDGEOS_GATE_KEY", None)
        with self.guard() as guard:
            done = subprocess.run(
                [sys.executable, "-m", "knowledgeos", "self", "approve", rel, "--vault", str(self.vault)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, env=env, cwd=str(self.root))
        guard.assert_unchanged(self)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("interactive terminal", done.stderr)
        self.assertNotIn("Apply this", done.stdout)
        self.assertNotIn("No answer possible", done.stdout + done.stderr)


class DoctorLedgerTests(TempVaultCase):
    def swap_key(self):
        (self.root / "state" / "gate.key").write_text(secrets.token_hex(32) + "\n", encoding="ascii")

    # D3 ----------------------------------------------------------------------------------
    def test_doctor_explains_rows_signed_by_a_different_key(self):
        api = self.api()
        api.propose_self_update("One", "heuristics", "* Prefer evidence one.", mode="append")
        api.propose_self_update("Two", "anti_goals", "* Avoid evidence two.", mode="append")
        self.swap_key()
        _, text = run_doctor(self.vault)
        self.assertRegex(text, r"2 ledger row\(s\) failed signature")
        self.assertRegex(text, r"2 Self proposal file\(s\) are not in the ledger")
        self.assertRegex(text, r"(?i)signing key was lost or replaced")
        self.assertIsNotNone(OTHER_DEVICE.search(text), text)
        self.assertRegex(text, r"(?i)cannot be approved here")
        self.assertRegex(text, r"(?i)restore the signing key backup, or propose")
        self.assertNotIn("[OK] Proposal ledger is signed", text)

    def test_doctor_stays_quiet_about_the_key_when_every_row_verifies(self):
        api = self.api()
        api.propose_self_update("One", "heuristics", "* Prefer evidence one.", mode="append")
        _, text = run_doctor(self.vault)
        self.assertIn("[OK] Proposal ledger is signed (1 entries", text)
        self.assertNotRegex(text, r"(?i)different key")

    def test_doctor_keeps_the_signed_line_while_some_rows_still_verify(self):
        api = self.api()
        api.propose_self_update("One", "heuristics", "* Prefer evidence one.", mode="append")
        self.swap_key()
        api.propose_self_update("Two", "anti_goals", "* Avoid evidence two.", mode="append")
        _, text = run_doctor(self.vault)
        self.assertIn("[OK] Proposal ledger is signed (1 entries", text)
        self.assertRegex(text, r"1 ledger row\(s\) failed signature")
        self.assertRegex(text, r"(?i)signing key was lost or replaced")

    def test_a_missing_key_is_still_created_for_a_new_install(self):
        from knowledgeos import gate

        key = self.root / "state" / "gate.key"
        if key.exists():
            key.unlink()
        self.assertIsNotNone(gate._signing_key())
        self.assertTrue(key.is_file())


class VersionAndSchemaTests(TempVaultCase):
    # G2 ----------------------------------------------------------------------------------
    def test_a_dev_version_sorts_before_its_release(self):
        from knowledgeos.vault_resolve import _version_tuple as v

        self.assertLess(v("0.4.0-dev"), v("0.4.0"))
        self.assertLess(v("0.4.0.dev0"), v("0.4.0"))
        self.assertLess(v("0.4.0rc1"), v("0.4.0"))
        self.assertLess(v("0.4.0.dev3"), v("0.4.0rc1"))
        self.assertLess(v("0.3.9"), v("0.4.0-dev"))
        self.assertEqual(v("0.4"), v("0.4.0"))
        self.assertLess(v("0.4.0"), v("0.4.1"))
        self.assertLess(v("0.4.0"), v("99.0.0"))

    def test_a_vault_from_the_dev_build_is_compatible_with_the_release(self):
        from knowledgeos import vault_resolve

        marker = self.vault / ".knowledgeos-vault.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["toolkit_min_version"] = "0.4.0-dev"
        marker.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch("knowledgeos.__version__", "0.4.0"):
            self.assertIsNone(vault_resolve.vault_version_check(self.vault))

    def test_a_newer_vault_still_warns(self):
        from knowledgeos import vault_resolve

        marker = self.vault / ".knowledgeos-vault.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["toolkit_min_version"] = "0.5.0"
        marker.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch("knowledgeos.__version__", "0.4.0"):
            self.assertIn("expects toolkit 0.5.0", vault_resolve.vault_version_check(self.vault) or "")

    def test_doctor_states_the_version_the_schema_and_the_verdict(self):
        import knowledgeos

        marker = json.loads((self.vault / ".knowledgeos-vault.json").read_text(encoding="utf-8"))
        _, text = run_doctor(self.vault)
        lines = [line for line in text.splitlines() if not line.startswith("Vault Root:")]
        body = "\n".join(lines)
        self.assertIn(knowledgeos.__version__, body)
        self.assertIn(marker["schema"], body)
        self.assertRegex(body, r"(?i)compatible")

    def test_doctor_warns_when_the_vault_needs_a_newer_toolkit(self):
        marker = self.vault / ".knowledgeos-vault.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["toolkit_min_version"] = "99.0.0"
        marker.write_text(json.dumps(data), encoding="utf-8")
        code, text = run_doctor(self.vault)
        self.assertRegex(text, r"\[WARNING\][^\n]*expects toolkit 99\.0\.0")
        self.assertNotRegex(text, r"(?m)^\s*\[OK\][^\n]*compatible")

    def test_doctor_warns_about_a_schema_it_does_not_know(self):
        marker = self.vault / ".knowledgeos-vault.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["schema"] = "knowledgeos-v9"
        marker.write_text(json.dumps(data), encoding="utf-8")
        _, text = run_doctor(self.vault)
        self.assertRegex(text, r"\[WARNING\][^\n]*knowledgeos-v9")


class ValidatorRootGuideTests(TempVaultCase):
    # G3 ----------------------------------------------------------------------------------
    def test_a_root_readme_without_frontmatter_is_not_a_note(self):
        from knowledgeos.validator import validate_vault

        self.write("README.md", "# Vault guide\n\nThis folder is a TwinAatma vault.\n")
        report = validate_vault(self.vault)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["supported_schemas"], ["knowledgeos-v0.2", "knowledgeos-v0.3"])

    def test_a_readme_inside_a_note_folder_is_still_a_note(self):
        from knowledgeos.validator import validate_vault

        self.write("Projects/README.md", "# No frontmatter here\n")
        report = validate_vault(self.vault)
        self.assertIn({"path": "Projects/README.md", "issue": "missing_frontmatter"}, report["errors"])

    def test_the_validate_command_exits_zero_for_a_vault_with_a_root_guide(self):
        self.write("README.md", "# Vault guide\n")
        code, out, _ = cli(["validate", "--vault", str(self.vault)])
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["errors"], [])


class ConflictCopyDoctorTests(TempVaultCase):
    # G4 ----------------------------------------------------------------------------------
    def make_note(self, rel, note_id="kos:project:shared-plan", title="Shared plan"):
        self.write(rel, NOTE.format(title=title, note_id=note_id))
        return rel

    def test_doctor_names_a_syncthing_conflict_copy(self):
        self.make_note("Projects/Shared-Plan.md")
        copy = self.make_note("Projects/Shared-Plan.sync-conflict-20261021-101500-ABC1234.md")
        before = {p: (self.vault / p).read_bytes() for p in ("Projects/Shared-Plan.md", copy)}
        code, text = run_doctor(self.vault)
        self.assertEqual(code, 0, text)
        self.assertIn(copy, text)
        self.assertRegex(text, r"(?i)conflict")
        self.assertRegex(text, r"\[WARNING\][^\n]*conflict")
        self.assertEqual(before, {p: (self.vault / p).read_bytes() for p in before})
        self.assertTrue((self.vault / "Projects/Shared-Plan.md").is_file())

    def test_doctor_names_dropbox_and_nextcloud_conflicted_copies(self):
        names = ["Projects/Plan (Gargeya's conflicted copy 2026-10-21).md",
                 "Projects/Plan (conflicted copy 2026-10-21 101500).md"]
        for index, name in enumerate(names):
            self.make_note(name, note_id="kos:project:plan-%d" % index, title="Plan %d" % index)
        _, text = run_doctor(self.vault)
        for name in names:
            self.assertIn(name, text)
        self.assertRegex(text, r"\[WARNING\][^\n]*conflict")

    def test_doctor_names_notes_that_share_an_id(self):
        self.make_note("Projects/Alpha.md")
        self.make_note("Projects/Beta.md")
        _, text = run_doctor(self.vault)
        self.assertIn("kos:project:shared-plan", text)
        self.assertIn("Projects/Alpha.md", text)
        self.assertIn("Projects/Beta.md", text)
        self.assertRegex(text, r"(?i)conflict")

    def test_doctor_is_quiet_when_there_is_no_conflict(self):
        self.make_note("Projects/Alpha.md", note_id="kos:project:alpha", title="Alpha")
        self.make_note("Projects/Beta.md", note_id="kos:project:beta", title="Beta")
        code, text = run_doctor(self.vault)
        self.assertEqual(code, 0)
        self.assertNotRegex(text, r"\[(WARNING|ERROR)\][^\n]*conflict")
        self.assertIn("No sync conflict copies found", text)

    def test_a_conflict_copy_is_a_warning_not_an_error(self):
        self.make_note("Projects/Shared-Plan.md")
        self.make_note("Projects/Shared-Plan.sync-conflict-20261021-101500-ABC1234.md")
        code, text = run_doctor(self.vault)
        self.assertEqual(code, 0)
        self.assertIn("Environment check PASSED", text)
        self.assertNotRegex(text, r"\[ERROR\][^\n]*conflict")


if __name__ == "__main__":
    unittest.main()
