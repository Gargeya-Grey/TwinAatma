"""Personal search distinguishes owned generated reports from the user's notes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knowledgeos.intelligence import learning_trajectory_report
from knowledgeos.indexer import index_files
from knowledgeos.memory import MemoryAPI


class GeneratedCensusTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "work/gc-artifacts/.knowledgeos/data-preservation-20261019/census-fix/fixtures" / uuid.uuid4().hex
        self.vault = self.root / "vault"
        self.vault.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.write("People/Self.md", "# Self\nSynthetic identity for an isolated search test.\n")
        self.api = MemoryAPI(self.vault)

    def write(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def paths(self, query):
        return {row["path"] for row in self.api.search(query)["ranked"]}

    def receipt(self, generated):
        relative = generated.relative_to(self.vault).as_posix()
        return self.vault / ".knowledgeos/generated" / (hashlib.sha256(relative.encode()).hexdigest() + ".sha256")

    def directory_link(self, path, target):
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(target)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            path.symlink_to(target, target_is_directory=True)

    def test_owned_trajectory_report_stays_out_of_personal_search(self):
        personal = self.write("MOCs/Learning Trajectory.md", "# Learning Trajectory\nMy personal account of learning.\n")
        self.assertIn(personal.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        generated = learning_trajectory_report(self.api)
        self.assertNotIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        self.assertIn(personal.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))

    def test_legacy_owned_report_stays_out_of_personal_search(self):
        generated = learning_trajectory_report(self.api)
        receipt = self.receipt(generated)
        intent = json.loads(receipt.read_text(encoding="ascii"))
        receipt.write_bytes(intent["after_sha256"].encode("ascii"))
        self.assertNotIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))

    def test_pending_receipt_keeps_unchanged_prior_report_out_of_search(self):
        generated = learning_trajectory_report(self.api)
        original = generated.read_bytes()
        self.write("Decisions/Changed.md", "---\ntype: decision\ntitle: New choice\n---\n# New choice\n")
        original_replace = os.replace

        def fail_report(source, destination):
            if Path(destination) == generated:
                raise OSError("injected report replacement failure")
            return original_replace(source, destination)

        with patch.object(os, "replace", fail_report):
            with self.assertRaisesRegex(OSError, "injected report replacement failure"):
                learning_trajectory_report(self.api)
        self.assertEqual(generated.read_bytes(), original)
        intent = json.loads(self.receipt(generated).read_text(encoding="ascii"))
        self.assertEqual(intent["before_sha256"], hashlib.sha256(original).hexdigest())
        self.assertNotEqual(intent["before_sha256"], intent["after_sha256"])
        self.assertNotIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        learning_trajectory_report(self.api)
        self.assertNotEqual(generated.read_bytes(), original)
        self.assertNotIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))

    def test_human_edits_to_owned_report_become_searchable(self):
        generated = learning_trajectory_report(self.api)
        self.assertNotIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        generated.write_bytes(generated.read_bytes() + b"\nMy personal cyanocoral recollection.\n")
        self.assertIn(generated.relative_to(self.vault).as_posix(), self.paths("cyanocoral"))

    def test_unowned_mocs_and_synthesis_notes_remain_searchable(self):
        personal = [
            self.write("MOCs/_MOC_Experiments.md", "---\ntype: synthesis\ntags: [intelligence]\n---\n# My cyanocoral experiments\n"),
            self.write("Research/Synthesis/2026-01-01-learning-trajectory.md", "# My cyanocoral learning\n"),
        ]
        self.assertEqual(self.paths("cyanocoral"), {p.relative_to(self.vault).as_posix() for p in personal})

    def test_malformed_and_unknown_receipts_do_not_hide_personal_notes(self):
        generated = learning_trajectory_report(self.api)
        receipt = self.receipt(generated)
        original_intent = json.loads(receipt.read_text(encoding="ascii"))
        invalid = [
            b"not a receipt", b"[]", b"\xff",
            json.dumps(dict(original_intent, schema="twinaatma.generated-write/v2")).encode(),
            json.dumps(dict(original_intent, before_sha256=[])).encode(),
            json.dumps(dict(original_intent, after_sha256=None)).encode(),
            json.dumps(dict(original_intent, extra=True)).encode(),
        ]
        for stored in invalid:
            with self.subTest(stored=stored):
                receipt.write_bytes(stored)
                self.assertIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
                self.assertEqual(receipt.read_bytes(), stored)

    def test_linked_metadata_cannot_hide_a_report(self):
        generated = learning_trajectory_report(self.api)
        receipts = self.vault / ".knowledgeos/generated"
        outside = self.root / "external-receipts"
        receipts.rename(outside)
        before = {p.name: p.read_bytes() for p in outside.iterdir()}
        self.directory_link(receipts, outside)
        self.assertIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        self.assertEqual({p.name: p.read_bytes() for p in outside.iterdir()}, before)

    def test_hardlinked_receipt_cannot_hide_a_report(self):
        generated = learning_trajectory_report(self.api)
        receipt = self.receipt(generated)
        outside = self.root / "external-receipt"
        receipt.rename(outside)
        os.link(outside, receipt)
        before = outside.read_bytes()
        self.assertIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        self.assertEqual(outside.read_bytes(), before)

    def test_repeating_generated_report_does_not_rewrite_personal_index(self):
        self.assertEqual(self.paths("Learning Trajectory"), set())
        state = [self.vault / "knowledge_index.db", self.vault / ".knowledgeos/index-manifest.json"]
        before = {p.name: p.read_bytes() for p in state}
        for _ in range(2):
            generated = learning_trajectory_report(self.api)
            self.assertNotIn(generated.relative_to(self.vault).as_posix(), self.paths("Learning Trajectory"))
        self.assertEqual({p.name: p.read_bytes() for p in state}, before)

    def test_incremental_index_does_not_add_an_owned_generated_report(self):
        self.assertEqual(self.paths("Learning Trajectory"), set())
        generated = learning_trajectory_report(self.api)
        state = [self.vault / "knowledge_index.db", self.vault / ".knowledgeos/index-manifest.json"]
        before = {p.name: p.read_bytes() for p in state}
        result = index_files(self.vault, [generated])
        self.assertEqual(result["notes"], 0)
        self.assertEqual(self.paths("Learning Trajectory"), set())
        self.assertEqual({p.name: p.read_bytes() for p in state}, before)


if __name__ == "__main__":
    unittest.main()
