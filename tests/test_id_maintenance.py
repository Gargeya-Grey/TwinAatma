"""ID maintenance preserves source bytes and protected identity in contained vaults."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knowledgeos.ids import assign_ids_for_vault


class IdMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.scope = ROOT / "work/gc-artifacts/.knowledgeos/maintenance-20261019/root-tests" / uuid.uuid4().hex[:8]
        self.vault = self.scope / "vault"
        self.vault.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.scope / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write(self, relative, raw):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def test_contained_vault_assignment_preserves_mixed_endings_and_fenced_yaml(self):
        raw = (b"---\r\ntype: concept\r\ntitle: Kept example\r\ndescription: Keep\r\nschema: knowledgeos-v0.2\r\n---\r\n\r\n"
               b"# Kept example\n\n```yaml\nid: example-only\nschema: example-only\n```\n")
        target = self.write("Concepts/Example.md", raw)
        changes = assign_ids_for_vault(self.vault, write=True)
        self.assertEqual(changes, [{"path": "Concepts/Example.md", "old_id": "", "new_id": "kos:concept:kept-example", "written": True}])
        expected = raw.replace(b"type: concept\r\n", b"type: concept\r\nid: kos:concept:kept-example\r\n", 1)
        self.assertEqual(target.read_bytes(), expected)

    def test_protected_identity_ids_still_reserve_their_names(self):
        identity = self.write("People/Self.md", b"---\ntype: person\ntitle: Reserved\nid: kos:person:reserved\n---\n# Protected\n")
        before = identity.read_bytes()
        target = self.write("Inbox/Reserved.md", b"---\ntype: person\ntitle: Reserved\n---\n# Candidate\n")
        changes = assign_ids_for_vault(self.vault, write=True)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["new_id"], "kos:person:reserved-2")
        self.assertIn(b"id: kos:person:reserved-2\n", target.read_bytes())
        self.assertEqual(identity.read_bytes(), before)

    def test_failed_atomic_replace_preserves_the_entire_note(self):
        target = self.write("Inbox/Original.md", b"---\ntype: concept\ntitle: Original\n---\n\nNever truncate this.\n")
        before = target.read_bytes()
        with patch("os.replace", side_effect=OSError("injected ID replace failure")):
            with self.assertRaisesRegex(OSError, "injected ID replace failure"):
                assign_ids_for_vault(self.vault, write=True)
        self.assertEqual(target.read_bytes(), before)

    def test_hardlinked_identity_and_proposal_aliases_are_refused(self):
        for index, relative in enumerate(("People/Self.md", "People/Self-Proposals/pending.md")):
            with self.subTest(relative=relative):
                protected = self.write(relative, b"---\ntype: person\ntitle: Protected\n---\n# Original evidence\n")
                alias = self.vault / ("Alias" + str(index) + ".md")
                os.link(protected, alias)
                before = protected.read_bytes()
                with self.assertRaisesRegex(ValueError, "hardlinked"):
                    assign_ids_for_vault(self.vault, write=True)
                self.assertEqual(protected.read_bytes(), before)
                self.assertEqual(alias.read_bytes(), before)
                alias.rename(alias.with_suffix(".retained"))

    def test_invalid_utf8_cannot_be_lossily_rewritten(self):
        target = self.write("Inbox/Invalid.md", b"---\ntype: concept\ntitle: Invalid\n---\n\xffKeep this exact byte.\n")
        before = target.read_bytes()
        with self.assertRaises(UnicodeDecodeError):
            assign_ids_for_vault(self.vault, write=True)
        self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
