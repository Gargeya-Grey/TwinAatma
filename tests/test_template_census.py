"""Personal search excludes root instruction templates and preserves user project notes."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knowledgeos.indexer import index_files, iter_markdown
from knowledgeos.memory import MemoryAPI


class TemplateCensusTests(unittest.TestCase):
    def setUp(self):
        self.scope = ROOT / "work/gc-artifacts/.knowledgeos/data-preservation-20261019/template-next" / uuid.uuid4().hex[:8]
        self.vault = self.scope / "vault"
        self.vault.mkdir(parents=True)
        environment = patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.scope / "state")})
        environment.start()
        self.addCleanup(environment.stop)
        self.api = MemoryAPI(self.vault)

    def write(self, relative, marker):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("---\ntype: concept\ntitle: " + marker + "\n---\n# " + marker + "\n").encode())
        return path

    def paths(self, query):
        return {row["path"] for row in self.api.search(query)["ranked"]}

    def test_root_templates_are_instructions_in_both_vault_shapes(self):
        path = self.write("Templates/t-belief.md", "RootTemplateExclusionMarker")
        for toolkit in (False, True):
            with self.subTest(toolkit=toolkit):
                if toolkit:
                    self.write("pyproject.toml", "Toolkit discriminator")
                    (self.vault / "knowledgeos").mkdir()
                self.assertNotIn(path, iter_markdown(self.vault))
                self.assertEqual(self.paths("RootTemplateExclusionMarker"), set())

    def test_nested_personal_template_folder_remains_searchable(self):
        path = self.write("Projects/Templates/Real.md", "NestedPersonalMarker")
        self.assertIn(path, iter_markdown(self.vault))
        self.assertEqual(self.paths("NestedPersonalMarker"), {"Projects/Templates/Real.md"})

    def test_incremental_index_cannot_add_a_root_template(self):
        self.api.search("warm")
        path = self.write("Templates/t-belief.md", "IncrementalTemplateMarker")
        self.assertEqual(index_files(self.vault, [path])["notes"], 0)
        self.assertEqual(self.paths("IncrementalTemplateMarker"), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
