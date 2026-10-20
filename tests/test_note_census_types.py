"""Special filesystem nodes cannot enter the note census or ID fallback."""
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import patch

from support import TempVaultCase
from knowledgeos.indexer import iter_markdown


class NoteCensusTypeTests(TempVaultCase):
    def setUp(self):
        super().setUp()
        self.candidate = self.write("Projects/special.md", "---\nid: special-note-id\n---\n# Special node\n")
        self.ordinary = self.write("Projects/ordinary.md", "---\nid: ordinary-note-id\n---\n# Ordinary note\n")

    def projected_type(self, kind):
        original = Path.lstat
        key = os.path.normcase(os.path.abspath(self.candidate))

        def lstat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if os.path.normcase(os.path.abspath(path)) != key:
                return result
            fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
            fields["st_mode"] = stat.S_IMODE(result.st_mode) | kind
            return SimpleNamespace(**fields)

        return patch.object(Path, "lstat", lstat)

    def test_census_excludes_nonregular_nodes_and_keeps_ordinary_notes(self):
        for kind in (stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR):
            with self.subTest(kind=kind), self.projected_type(kind):
                paths = iter_markdown(self.vault)
                self.assertNotIn(self.candidate, paths)
                self.assertIn(self.ordinary, paths)

    def test_id_fallback_never_opens_a_nonregular_candidate(self):
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            self.assertNotEqual(path, self.candidate, "ID fallback opened a special filesystem node")
            return original(path, *args, **kwargs)

        with self.projected_type(stat.S_IFIFO), patch.object(Path, "read_text", read_text):
            self.assertIn("error", self.api().get_note("absent-note-id"))
            self.assertEqual(self.api().get_note("ordinary-note-id")["path"], "Projects/ordinary.md")
