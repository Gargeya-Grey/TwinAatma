"""Indirect third-party disclosures must not depend on proper-name templates."""
from __future__ import annotations

import json
import unittest

from support import TempVaultCase
from knowledgeos.memory import dispatch


class SensitiveRelationTests(TempVaultCase):
    def test_indirect_sensitive_statements_are_refused_without_echo_or_persistence(self):
        statements = (
            "My coworker has a malignant finding in her clinical test results.",
            "The specimen report for our neighbour describes a tumour.",
            "A colleague told me their biopsy needs further treatment.",
            "Her pathology report includes a positive finding from the hospital.",
            "Our teammate is undergoing chemotherapy after a recent scan.",
            "My friend's prenatal test results should stay between us.",
            "Their psychiatric assessment describes symptoms and treatment.",
            "My cousin's take-home pay and outstanding loan balance are private.",
            "His routing number and account balance were shared in confidence.",
            "Our client's personal email and home address are confidential.",
            "Her private mobile number is reserved for her family.",
            "My colleague's clinical findings are confidential.",
        )
        for ordinal, text in enumerate(statements):
            with self.subTest(case=ordinal):
                result = dispatch(self.api(), "memory_capture", {"title": "Private third-party detail", "content": text})
                self.assertFalse(result.get("ok"), "sensitive third-party capture was accepted")
                self.assertIn("error", result)
                self.assertNotIn(text, json.dumps(result), "refusal echoed sensitive content")
                self.assertTrue(all(text.encode() not in path.read_bytes() for path in self.vault.rglob("*") if path.is_file()),
                                "excluded content was persisted")

    def test_ordinary_collaboration_and_sensitive_domain_project_work_remain_available(self):
        statements = (
            "My colleague reviews Rill release plans with me every Monday.",
            "Our clinical software project will ship its next release on Friday.",
            "I prefer short project notes and quiet review sessions.",
            "The banking integration project uses a three-stage release process.",
            "Our team's private repository contains the project's build scripts.",
        )
        for ordinal, text in enumerate(statements):
            with self.subTest(case=ordinal):
                result = dispatch(self.api(), "memory_capture", {"title": "Project preference", "content": text})
                self.assertTrue(result.get("ok"), "ordinary project memory was refused")
                self.assertEqual(self.api().get_note(result["path"])["path"], result["path"])

    def test_legacy_indirect_clinical_note_is_not_released_or_admitted_to_context(self):
        path = self.vault / "Projects/legacy-private.md"
        path.parent.mkdir(exist_ok=True)
        text = "My colleague's biopsy finding was malignant and her care plan is confidential."
        path.write_text("---\ntype: project\ntitle: Legacy clinical detail\nstatus: active\n---\n\n" + text + "\n", encoding="utf-8")
        before = path.read_bytes()
        direct = self.api().get_note("Projects/legacy-private.md")
        self.assertTrue("error" in direct, "legacy source was released")
        context = self.api().bootstrap_context("clinical biopsy colleague")
        self.assertNotIn(text, json.dumps(context), "legacy source entered context")
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
