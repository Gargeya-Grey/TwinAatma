"""Public preview must reject edited proposals before a human sees a diff."""
import json
import os
import unittest

from preview_authenticity_support import BASE, PATCH, SUMMARY, Fixture, load_gate

gate = load_gate("current-root")


class PreviewIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(gate, self._testMethodName)

    def tearDown(self):
        self.fixture.close()

    def test_edited_body_is_refused_before_restore(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = original.replace(PATCH.encode(), b"* Change a different synthetic preference.")
        path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertEqual(result.get("error"), "proposal content was edited after it was created")
            self.assertNotIn("patch", result)
            self.assertEqual(path.read_bytes(), changed)
        finally:
            path.write_bytes(original)
            fixture.preserve(path, original)
        self.assertEqual(fixture.describe(path).get("patch"), PATCH)

    def test_edited_summary_is_refused_before_restore(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = original.replace(SUMMARY.encode(), b"A harmless synthetic wording adjustment.")
        path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertEqual(result.get("error"), "proposal file was edited after it was created")
            self.assertNotIn("patch", result)
            self.assertEqual(path.read_bytes(), changed)
        finally:
            path.write_bytes(original)
            fixture.preserve(path, original)
        self.assertEqual(fixture.describe(path).get("patch"), PATCH)

    def test_edited_display_metadata_is_refused(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = original.replace(b"proposal_section: heuristics", b"proposal_section: values")
        path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertEqual(result.get("error"), "proposal file was edited after it was created")
            self.assertNotIn("section", result)
        finally:
            path.write_bytes(original)
            fixture.preserve(path, original)

    def test_stale_target_base_is_refused_before_restore(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = BASE.replace(b"* Keep careful notes", b"* Keep manually revised notes")
        fixture.self_path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertEqual(result.get("error"), "Self.md changed since this proposal was created")
            self.assertNotIn("patch", result)
            self.assertEqual(fixture.self_path.read_bytes(), changed)
            self.assertEqual(path.read_bytes(), original)
        finally:
            fixture.self_path.write_bytes(BASE)
            fixture.preserve(path, original)
        self.assertEqual(fixture.describe(path).get("patch"), PATCH)

    def test_invalid_terminal_patch_is_refused_before_preview(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = original.replace(PATCH.encode(), b"* \x1b[8mHidden synthetic preference.")
        path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertIn("control characters", result.get("error", ""))
            self.assertNotIn("patch", result)
            self.assertEqual(path.read_bytes(), changed)
        finally:
            path.write_bytes(original)
            fixture.preserve(path, original)

    def test_ambiguous_fenced_patch_is_refused(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = original + b"\n```markdown\n* A second synthetic patch.\n```\n"
        path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertEqual(result.get("error"), "proposal must contain exactly one ```markdown block")
            self.assertNotIn("patch", result)
        finally:
            path.write_bytes(original)
            fixture.preserve(path, original)

    def test_authentic_append_and_replace_preview_without_mutation(self):
        fixture = self.fixture
        for mode in ("append", "replace"):
            with self.subTest(mode=mode):
                path, original = fixture.propose(mode=mode)
                result = fixture.describe(path)
                self.assertNotIn("error", result)
                self.assertEqual(result.get("patch"), PATCH)
                self.assertEqual(result.get("section"), "heuristics")
                self.assertEqual(result.get("mode"), mode)
                self.assertEqual(result.get("allow_destructive"), mode == "replace")
                self.assertNotIn("self_text", result)
                fixture.preserve(path, original)

    def test_windows_patch_line_endings_remain_acceptable(self):
        fixture = self.fixture
        patch = "* First synthetic rule.\r\n* Second synthetic rule.\r\n"
        path, original = fixture.propose(patch=patch)
        result = fixture.describe(path)
        self.assertEqual(result.get("patch"), "* First synthetic rule.\n* Second synthetic rule.")
        fixture.preserve(path, original)

    def test_unrelated_section_edit_keeps_target_base_valid(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = BASE.replace(b"* Preserve independently", b"* Honor independently")
        fixture.self_path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertEqual(result.get("patch"), PATCH)
            self.assertEqual(fixture.self_path.read_bytes(), changed)
        finally:
            fixture.self_path.write_bytes(BASE)
            fixture.preserve(path, original)

    def test_duplicate_canonical_target_is_refused(self):
        fixture = self.fixture
        path, original = fixture.propose()
        changed = BASE + b"\n## Another Heuristics\n<!-- kos:section=heuristics -->\n* Duplicate.\n"
        fixture.self_path.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertIn("2 headings marked kos:section=heuristics", result.get("error", ""))
            self.assertNotIn("patch", result)
            self.assertEqual(fixture.self_path.read_bytes(), changed)
        finally:
            fixture.self_path.write_bytes(BASE)
            fixture.preserve(path, original)

    def test_native_hardlinked_self_is_refused_without_touching_either_name(self):
        fixture = self.fixture
        path, original = fixture.propose()
        alias = fixture.scope / "linked-self.md"
        os.link(fixture.self_path, alias)
        result = fixture.describe(path)
        self.assertIn("Self.md is hard-linked", result.get("error", ""))
        self.assertNotIn("patch", result)
        self.assertEqual(alias.read_bytes(), BASE)
        fixture.preserve(path, original)

    def test_native_hardlinked_proposal_is_refused_without_touching_either_name(self):
        fixture = self.fixture
        path, original = fixture.propose()
        alias = fixture.scope / "linked-proposal.md"
        os.link(path, alias)
        result = fixture.describe(path)
        self.assertIn("proposal is hard-linked", result.get("error", ""))
        self.assertNotIn("patch", result)
        self.assertEqual(alias.read_bytes(), original)
        fixture.preserve(path, original)

    def test_edited_signed_ledger_is_not_trusted_or_rewritten(self):
        fixture = self.fixture
        path, original = fixture.propose()
        ledger = gate.ledger_path(fixture.vault)
        self.assertFalse(ledger.is_relative_to(fixture.vault))
        recorded = ledger.read_bytes()
        (fixture.scope / "originals" / "signed-ledger.jsonl").write_bytes(recorded)
        row = json.loads(recorded)
        row["body_sha256"] = "0" * 64
        changed = (json.dumps(row) + "\n").encode()
        ledger.write_bytes(changed)
        try:
            result = fixture.describe(path)
            self.assertIn("not registered", result.get("error", ""))
            self.assertNotIn("patch", result)
            self.assertEqual(ledger.read_bytes(), changed)
        finally:
            ledger.write_bytes(recorded)
            fixture.preserve(path, original)
        self.assertEqual(fixture.describe(path).get("patch"), PATCH)

    def test_duplicate_authentic_ledger_rows_are_refused(self):
        fixture = self.fixture
        path, original = fixture.propose()
        ledger = gate.ledger_path(fixture.vault)
        recorded = ledger.read_bytes()
        (fixture.scope / "originals" / "signed-ledger.jsonl").write_bytes(recorded)
        ledger.write_bytes(recorded + recorded)
        try:
            result = fixture.describe(path)
            self.assertIn("duplicate rows", result.get("error", ""))
            self.assertNotIn("patch", result)
            self.assertEqual(ledger.read_bytes(), recorded + recorded)
        finally:
            ledger.write_bytes(recorded)
            fixture.preserve(path, original)

    def test_authentic_bytes_at_an_unregistered_path_are_refused(self):
        fixture = self.fixture
        path, original = fixture.propose()
        copied = fixture.proposals / "unregistered-copy.md"
        copied.write_bytes(original)
        result = fixture.describe(copied)
        self.assertIn("not registered", result.get("error", ""))
        self.assertNotIn("patch", result)
        self.assertEqual(copied.read_bytes(), original)
        fixture.preserve(path, original)

    def test_authentic_bytes_outside_proposal_directory_are_refused(self):
        fixture = self.fixture
        path, original = fixture.propose()
        copied = fixture.scope / "outside-proposal.md"
        copied.write_bytes(original)
        result = fixture.describe(copied)
        self.assertEqual(result.get("error"), "not a Self proposal in People/Self-Proposals")
        self.assertNotIn("patch", result)
        self.assertEqual(copied.read_bytes(), original)
        fixture.preserve(path, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
