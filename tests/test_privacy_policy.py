"""Behavioral checks for the approved local remembering policy."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import sqlite3
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI


class RememberingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1] / "work/gc-artifacts/.knowledgeos"
                     / "privacy-policy-controls" / secrets.token_hex(8))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        (self.vault / "People/Self.md").write_text("# Self\n\n## Heuristics\n\n_Unknown._\n", encoding="utf-8")
        self.before_self = (self.vault / "People/Self.md").read_bytes()
        self.saved_env = os.environ.get("KNOWLEDGEOS_STATE_DIR")
        os.environ["KNOWLEDGEOS_STATE_DIR"] = str(self.root / "gate-state")
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        if self.saved_env is None:
            os.environ.pop("KNOWLEDGEOS_STATE_DIR", None)
        else:
            os.environ["KNOWLEDGEOS_STATE_DIR"] = self.saved_env
        self.assertTrue(self.before_self == (self.vault / "People/Self.md").read_bytes(), "identity bytes changed")

    def test_allowed_capture_and_credential_refusal(self):
        allowed = self.api.capture("Project Rill", "For Rill, prefer short weekly review notes.")
        self.assertTrue(allowed.get("ok"))
        self.assertTrue("short weekly" in MemoryAPI(self.vault).get_note(allowed["path"])["body"])
        token = "sk-" + secrets.token_hex(24)
        refused = self.api.capture("Private service", "API key: " + token)
        self.assertFalse(refused.get("ok"), "credential capture must refuse before persistence")
        self.assertTrue(token not in json.dumps(refused), "refusal exposed excluded material")
        self.assertTrue(all(token.encode() not in path.read_bytes() for path in self.vault.rglob("*") if path.is_file()), "capture persisted excluded material")

    def test_forgetting_preserves_source_and_blocks_literal_copies_and_retries(self):
        fact = "Rill review meetings happen every second Thursday morning."
        captured = self.api.capture("Rill review cadence", fact, request_id="rill-cadence")
        source = self.vault / captured["path"]
        original = source.read_bytes()
        duplicate = self.vault / "Projects/copied-cadence.md"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        duplicate.write_bytes(original)
        self.api.session_start(task_hint=fact, session_id="forget-session")
        result = self.api.forget(captured["path"], hashlib.sha256(original).hexdigest())
        self.assertTrue(result.get("ok"), "forgetting must durably complete")
        self.assertTrue(source.read_bytes() == original, "forgetting changed source bytes")
        self.assertTrue(duplicate.read_bytes() == original, "forgetting changed a duplicate source")
        self.assertTrue(self.api.get_note(captured["path"]).get("error"), "forgotten direct read was released")
        self.assertTrue(self.api.get_note("Projects/copied-cadence.md").get("error"), "literal copy was released")
        self.assertFalse(self.api.capture("Different title", fact).get("ok"), "forgotten material was recaptured")
        state = (self.vault / ".knowledgeos/autopilot.json").read_text(encoding="utf-8")
        self.assertTrue(fact not in state, "forgotten material remained in session state")

    def test_source_export_omits_excluded_legacy_notes_and_preserves_sources(self):
        toolkit = self.root / "toolkit"
        candidate = Path(__file__).resolve().parents[1]
        for name in ("knowledgeos", "scripts"):
            shutil.copytree(candidate / name, toolkit / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(candidate / "pyproject.toml", toolkit / "pyproject.toml")
        project = toolkit / "Projects"
        project.mkdir()
        token = "sk-" + secrets.token_hex(24)
        (project / "legacy.md").write_text("# Legacy service\n\nAPI key: " + token + "\n", encoding="utf-8")
        (project / "allowed.md").write_text("# Rill\n\nPrefer a weekly review for Rill.\n", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in project.iterdir()}
        proc = subprocess.run([sys.executable, "-B", "scripts/export_bundle.py", "--paths", "Projects", "--out", "Bundles/review"], cwd=toolkit, capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, "export did not complete")
        bundle = toolkit / "Bundles/review"
        self.assertTrue((bundle / "Projects/allowed.md").exists(), "export lost an ordinary project note")
        self.assertTrue(not (bundle / "Projects/legacy.md").exists(), "export copied an excluded source")
        self.assertTrue(all(token.encode() not in p.read_bytes() for p in bundle.rglob("*") if p.is_file()), "export exposed excluded material")
        self.assertTrue(before == {p.name: p.read_bytes() for p in project.iterdir()}, "export changed sources")

    def test_derived_intelligence_does_not_release_forged_cache_fields(self):
        from knowledgeos.intelligence import emerging_themes, orphan_notes

        captured = self.api.capture("Rill collaboration", "Mira and I review the project each Monday.", tags=["rill"])
        self.assertTrue(captured.get("ok"))
        token = "sk-" + secrets.token_hex(24)
        conn = sqlite3.connect(self.vault / "knowledge_index.db")
        conn.execute("UPDATE notes SET title=?, tags=? WHERE path=?", (token, token, captured["path"]))
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            observed = {"themes": emerging_themes(self.api), "orphans": orphan_notes(self.api)}
        finally:
            conn.rollback()
            conn.close()
        self.assertTrue(token not in json.dumps(observed), "derived intelligence trusted excluded cache fields")

    def test_sensitive_sources_remain_in_raw_inventory_and_validation(self):
        from knowledgeos.indexer import iter_markdown, iter_memory_markdown
        from knowledgeos.validator import validate_vault

        path = self.vault / "Projects/private-invalid.md"
        path.parent.mkdir()
        path.write_text("---\ntype: project\nprivacy: exclude\nstatus: invalid-state\n---\n\n# Private source\n", encoding="utf-8")
        original = path.read_bytes()
        self.assertTrue(path in iter_markdown(self.vault), "raw source inventory hid a private source")
        self.assertTrue(path not in iter_memory_markdown(self.vault), "memory admission accepted an excluded source")
        report = validate_vault(self.vault)
        self.assertTrue(report["summary"]["errors"] > 0, "validation silently treated an invalid private source as valid")
        self.assertTrue(path.read_bytes() == original, "validation changed a private source")

    def test_ordinary_direct_read_preserves_original_text_bytes(self):
        path = self.vault / "Projects/ordinary.md"
        path.parent.mkdir()
        original = "# Rill café review\r\n\r\nPrefer concise project notes.\n".encode("utf-8")
        path.write_bytes(original)
        read = self.api.get_note("Projects/ordinary.md")
        self.assertTrue(read["body"].encode("utf-8") == original, "ordinary direct read changed text bytes")
        self.assertEqual(read["sha256"], hashlib.sha256(original).hexdigest())

    def test_linked_policy_directory_is_refused_without_touching_target(self):
        target = self.root / "outside-state"
        target.mkdir()
        sentinel = target / "unchanged"
        sentinel.write_bytes(b"protected state sentinel")
        folder = self.vault / ".knowledgeos"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(folder))
        else:
            folder.symlink_to(target, target_is_directory=True)
        result = self.api.capture("Rill", "Rill uses a weekly project review.")
        self.assertFalse(result.get("ok"), "linked policy directory was followed")
        self.assertTrue({path.name for path in target.iterdir()} == {"unchanged"}, "linked state target was written")
        self.assertTrue(sentinel.read_bytes() == b"protected state sentinel", "linked state target changed")

    def test_explicit_and_finite_third_party_exclusions_preserve_benign_collaboration(self):
        self.assertTrue(self.api.capture("Rill collaboration", "Mira reviews Rill release plans with me.").get("ok"))
        for body in ("Mira was diagnosed with diabetes.", "Mira's bank account is reserved for her medical care.",
                     "Mira's private phone is available only to her family."):
            result = self.api.capture("Third-party detail", body)
            self.assertFalse(result.get("ok"), "documented third-party pattern was captured")
            self.assertTrue(body not in json.dumps(result), "refusal repeated a third-party detail")
        self.assertFalse(self.api.capture("Private note", "An opaque private detail.", privacy="sensitive-third-party").get("ok"))

    def test_guarded_correction_retains_reviewed_historical_attribution(self):
        old = self.api.capture("Rill old cadence", "Rill release reviews happen on Tuesday.")
        new = self.api.capture("Rill current cadence", "Rill release reviews happen on Friday.")
        old_source, new_source = self.vault / old["path"], self.vault / new["path"]
        old_bytes, new_bytes = old_source.read_bytes(), new_source.read_bytes()
        result = self.api.supersede(old["path"], hashlib.sha256(old_bytes).hexdigest(),
                                    new["path"], hashlib.sha256(new_bytes).hexdigest())
        self.assertTrue(result.get("ok"))
        historical = MemoryAPI(self.vault).get_note(old["path"])
        self.assertEqual(historical.get("memory_status"), "historical")
        self.assertEqual(historical.get("superseded_by"), new["path"])
        current = MemoryAPI(self.vault).search("Rill")
        self.assertTrue(all(row["path"] != old["path"] for row in current.get("ranked", [])), "historical fact was current recall")
        self.assertTrue(any(row["path"] == new["path"] for row in current.get("ranked", [])), "correction lost its current replacement")
        self.assertTrue((old_source.read_bytes(), new_source.read_bytes()) == (old_bytes, new_bytes), "correction rewrote source notes")
        self.assertFalse(self.api.forget("People/Self.md", hashlib.sha256(self.before_self).hexdigest()).get("ok"))

    def test_malformed_and_hardlinked_policy_state_fail_closed(self):
        allowed = self.api.capture("Rill", "Rill uses one weekly release review.")
        state = self.vault / ".knowledgeos/remembering-policy.json"
        sentinel = self.root / "ledger-sentinel"
        sentinel.write_bytes(b"unchanged sentinel")
        state.hardlink_to(sentinel)
        result = self.api.get_note(allowed["path"])
        self.assertTrue(result.get("error"), "hardlinked policy state did not fail closed")
        self.assertTrue(sentinel.read_bytes() == b"unchanged sentinel", "linked state changed its protected source")
        state.unlink()
        malformed = b'{"version":1,"forgotten":{},"forgotten":{},"superseded":{}}'
        state.write_bytes(malformed)
        result = self.api.get_note(allowed["path"])
        self.assertTrue(result.get("error"), "duplicate-key policy state was accepted")
        self.assertTrue(state.read_bytes() == malformed, "malformed policy state was replaced")

    def test_failed_ledger_publication_preserves_exclusions_and_retry_converges(self):
        first = self.api.capture("Rill first", "Rill weekly planning uses Wednesday mornings.")
        second = self.api.capture("Rill second", "Rill release decisions use Friday afternoons.")
        first_raw = (self.vault / first["path"]).read_bytes()
        second_raw = (self.vault / second["path"]).read_bytes()
        self.assertTrue(self.api.forget(first["path"], hashlib.sha256(first_raw).hexdigest()).get("ok"))
        state = self.vault / ".knowledgeos/remembering-policy.json"
        original = state.read_bytes()
        with mock.patch("knowledgeos.remembering.atomic_write_bytes", side_effect=OSError("synthetic publication failure")):
            failed = self.api.forget(second["path"], hashlib.sha256(second_raw).hexdigest())
        self.assertFalse(failed.get("ok"), "failed policy publication claimed success")
        self.assertTrue(state.read_bytes() == original, "failed policy publication lost prior exclusions")
        self.assertTrue(self.api.get_note(first["path"]).get("error"), "prior exclusion was lost")
        self.assertTrue(self.api.forget(second["path"], hashlib.sha256(second_raw).hexdigest()).get("ok"), "honest retry did not converge")


if __name__ == "__main__":
    unittest.main()
