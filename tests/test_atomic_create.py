"""Exclusive publication never exposes a partial file or replaces another writer."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knowledgeos.textio import atomic_create_bytes


class AtomicCreateTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / "work/gc-artifacts/.knowledgeos/maintenance-20261019/atomic-tests" / uuid.uuid4().hex[:8]
        self.directory.mkdir(parents=True)
        self.target = self.directory / "pre-commit"

    def test_complete_publication_refuses_even_an_identical_existing_file(self):
        atomic_create_bytes(self.target, b"complete hook\n")
        self.assertEqual(self.target.read_bytes(), b"complete hook\n")
        with self.assertRaises(FileExistsError):
            atomic_create_bytes(self.target, b"complete hook\n")
        self.assertEqual(self.target.read_bytes(), b"complete hook\n")
        self.assertEqual(self.target.stat().st_nlink, 1)
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_an_intervening_writer_keeps_its_original_hook(self):
        real_link = os.link

        def competing_write(source, destination, *args, **kwargs):
            self.assertEqual(Path(destination), self.target)
            self.target.write_bytes(b"another writer's hook\n")
            return real_link(source, destination, *args, **kwargs)

        with patch("knowledgeos.textio.os.link", side_effect=competing_write):
            with self.assertRaises(FileExistsError):
                atomic_create_bytes(self.target, b"new generated hook\n")
        self.assertEqual(self.target.read_bytes(), b"another writer's hook\n")
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_permission_failure_does_not_publish_a_hook(self):
        with patch("knowledgeos.textio.os.chmod", side_effect=OSError("injected chmod failure")):
            with self.assertRaisesRegex(OSError, "injected chmod failure"):
                atomic_create_bytes(self.target, b"complete hook\n", mode=0o700)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
