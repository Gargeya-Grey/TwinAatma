"""Decision project filters preserve exact scalar and YAML-list membership."""
import unittest

from support import TempVaultCase


class DecisionProjectPrecisionTests(TempVaultCase):
    def setUp(self):
        super().setUp()
        for name, project in (
            ("Nova", "project: Nova"),
            ("Supernova", "project: Supernova"),
            ("Inline", "project: [Nova, Orion]"),
            ("Block", "project:\n  - Nova\n  - Lyra"),
            ("Unicode", "project: Straße"),
            ("Semicolon", 'project: "Nova; Orion"'),
            ("Comma", 'project: "Nova, Orion"'),
            ("Unset", "project:"),
            ("EmptyList", "project: []"),
        ):
            self.write("Decisions/" + name + ".md", "---\ntype: decision\ntitle: " + name + "\nstatus: active\n" + project + "\n---\n# " + name + "\n")

    def paths(self, **arguments):
        payload = self.api().decisions(**arguments)
        paths = sorted(row["path"] for row in payload["decisions"])
        self.assertEqual(payload["count"], len(paths))
        return paths

    def test_exact_labels_and_list_members_are_distinct(self):
        self.assertEqual(self.paths(project="nOvA"), ["Decisions/Block.md", "Decisions/Inline.md", "Decisions/Nova.md"])
        self.assertEqual(self.paths(project="SUPERNOVA"), ["Decisions/Supernova.md"])
        self.assertEqual(self.paths(project="oRiOn"), ["Decisions/Inline.md"])
        self.assertEqual(self.paths(project="nOvA; oRiOn"), ["Decisions/Semicolon.md"])
        self.assertEqual(self.paths(project="nOvA, oRiOn"), ["Decisions/Comma.md"])

    def test_unicode_project_names_use_casefold(self):
        self.assertEqual(self.paths(project="STRASSE"), ["Decisions/Unicode.md"])

    def test_empty_and_omitted_filters_preserve_unassigned_decisions(self):
        expected = ["Decisions/Block.md", "Decisions/Comma.md", "Decisions/EmptyList.md", "Decisions/Inline.md", "Decisions/Nova.md", "Decisions/Semicolon.md", "Decisions/Supernova.md", "Decisions/Unicode.md", "Decisions/Unset.md"]
        self.assertEqual(self.paths(project=""), expected)
        self.assertEqual(self.paths(), expected)
        self.assertEqual(self.paths(project="missing-precision-731"), [])


if __name__ == "__main__":
    unittest.main()
