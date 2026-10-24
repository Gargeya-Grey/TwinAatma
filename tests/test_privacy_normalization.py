"""Public capture and reads preserve ASCII and Unicode privacy decisions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI, dispatch


class PrivacyNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/privacy-normalization-controls"
                     / secrets.token_hex(6))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\n## Heuristics\n\nUnknown.\n")
        self.self_before = self.identity.read_bytes()
        self.environment = mock.patch.dict(os.environ, {
            "KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.key = os.environ.pop("KNOWLEDGEOS_GATE_KEY", None)
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        if self.key is not None:
            os.environ["KNOWLEDGEOS_GATE_KEY"] = self.key
        self.environment.stop()
        self.assertEqual(self.identity.read_bytes(), self.self_before)

    def assert_refused(self, text):
        result = dispatch(self.api, "memory_capture", {
            "title": "Synthetic privacy control", "content": text})
        self.assertFalse(result.get("ok"), result)
        self.assertNotIn(text, json.dumps(result, ensure_ascii=False))
        self.assertTrue(all(text.encode("utf-8") not in path.read_bytes()
                            for path in self.vault.rglob("*") if path.is_file()))

    def test_nfkc_and_format_characters_still_exclude_sensitive_disclosures(self):
        text = "My coworker has a malignant finding in her clinical test results."
        fullwidth = "".join(chr(ord(char) + 0xFEE0) if "!" <= char <= "~" else char
                            for char in text)
        for value in (fullwidth, text.replace("coworker", "co\u200bworker")
                      .replace("malignant", "malig\u200bnant")):
            with self.subTest(text=value):
                self.assert_refused(value)

    def test_ordinary_unicode_and_unrelated_paragraphs_preserve_exact_text(self):
        for ordinal, text in enumerate((
            "Café Orion préfère des notes de projet courtes.",
            "The Ｏｒｉｏｎ project uses short weekly review notes.",
            "My colleague reviews project plans.\n\nClinical findings are a software report category.",
        )):
            with self.subTest(text=text):
                captured = dispatch(self.api, "memory_capture", {
                    "title": "Ordinary control " + str(ordinal), "content": text})
                self.assertTrue(captured.get("ok"), captured)
                result = dispatch(self.api, "memory_get_note", {"path_or_id": captured["path"]})
                self.assertIn(text, result["body"])
                self.assertIn(text.encode("utf-8"), (self.vault / captured["path"]).read_bytes())

    def test_legacy_unicode_source_is_withheld_without_source_mutation(self):
        path = self.vault / "Projects/legacy.md"
        path.parent.mkdir()
        text = "My co\u200bworker has a malig\u200bnant finding in her clinical test results."
        path.write_text("---\ntype: project\ntitle: Legacy control\nstatus: active\n---\n\n" + text,
                        encoding="utf-8")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = dispatch(self.api, "memory_get_note", {"path_or_id": "Projects/legacy.md"})
        self.assertTrue(result.get("error"), result)
        self.assertNotIn(text, json.dumps(result, ensure_ascii=False))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
