import json
import os
from pathlib import Path
import sys
import unittest
import uuid

TOOLKIT = Path(os.environ.get("TWIN_RETRIEVAL_ROOT", Path(__file__).resolve().parents[1])).resolve()
TASK = Path(os.environ.get("TWIN_RETRIEVAL_EVIDENCE_ROOT", TOOLKIT / "work/gc-artifacts/.knowledgeos/concept-expansion-regressions"))
sys.path.insert(0, str(TOOLKIT))
from knowledgeos import search
from knowledgeos.memory import MemoryAPI


class ConceptExpansionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TASK / "controls" / uuid.uuid4().hex
        self.vault = self.directory / "vault"
        self.vault.mkdir(parents=True)
        self.old_state = os.environ.get("KNOWLEDGEOS_STATE_DIR")
        os.environ["KNOWLEDGEOS_STATE_DIR"] = str(self.directory / "state")
        (self.vault / "People").mkdir()
        (self.vault / "People/Self.md").write_text("# Self\n\nUnknown.\n", encoding="utf-8")
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        if self.old_state is None:
            os.environ.pop("KNOWLEDGEOS_STATE_DIR", None)
        else:
            os.environ["KNOWLEDGEOS_STATE_DIR"] = self.old_state

    def note(self, name, text):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def ranked(self, hint):
        return self.api.bootstrap_context(hint)["relevant"]["ranked"]

    def paths(self, hint):
        return [row["path"] for row in self.ranked(hint)]

    def test_a_note_in_another_language_is_found(self):
        self.note("Preferences/Kaffee.md", "# Kaffee\n\nMorgens nur Filterkaffee, schwarz. Nach 14 Uhr keinen Kaffee mehr.\n")
        self.note("Notes/Garden.md", "# Garden\n\nWater the tomatoes.\n")
        rows = self.ranked("Order me a coffee for the afternoon, how do I take it?")
        self.assertEqual("Preferences/Kaffee.md", rows[0]["path"])
        self.assertIn("Nach 14 Uhr keinen Kaffee mehr.", json.dumps(rows[0], ensure_ascii=False))

    def test_a_synonym_finds_a_note_without_the_task_word(self):
        self.note("Preferences/Evenings.md", "# Evenings\n\nSupper is at seven, never later.\n")
        self.note("Notes/Garden.md", "# Garden\n\nWater the tomatoes.\n")
        self.assertIn("Preferences/Evenings.md", self.paths("When should I book dinner tonight?"))

    def test_a_cjk_expansion_is_found_by_substring_and_quoted(self):
        # The fact sits deep in a long note, so the excerpt must focus on it.
        self.note("Events/Fair.md", "# 展示会のメモ\n\n" + "準備のメモ。" * 300 + "\n\n来月の陶芸展は11月22日に港町ギャラリーで開催されます。\n")
        rows = self.ranked("When is the pottery show next month?")
        row = next(row for row in rows if row["path"] == "Events/Fair.md")
        self.assertIn("11月22日に港町ギャラリー", json.dumps(row, ensure_ascii=False))

    def test_a_long_word_finds_its_shorter_form(self):
        self.note("Preferences/Answers.md", "# Answers\n\nExplain the reasoning before the result.\n")
        self.assertIn("Preferences/Answers.md", self.paths("Which explanation suits me?"))

    def test_an_exact_rare_word_outranks_an_expansion(self):
        self.note("Projects/Glacier.md", "# Glacier\n\nThe glacier dinner budget is fixed.\n")
        self.note("Preferences/Food.md", "# Food\n\nMeal, food, cuisine, lunch, breakfast and supper notes.\n")
        self.assertEqual("Projects/Glacier.md", self.paths("Plan the glacier dinner.")[0])

    def test_an_excluded_note_stays_excluded_through_an_expansion(self):
        self.note("Preferences/Kaffee.md", "---\nprivacy: private\n---\n# Kaffee\n\nNur Filterkaffee.\n")
        self.note("Notes/Coffee.md", "# Coffee\n\nThe office coffee machine is on floor two.\n")
        paths = self.paths("Where can I get a coffee?")
        self.assertIn("Notes/Coffee.md", paths)
        self.assertNotIn("Preferences/Kaffee.md", paths)

    def test_direct_search_does_not_expand(self):
        self.note("Preferences/Kaffee.md", "# Kaffee\n\nNur Filterkaffee.\n")
        self.assertEqual(self.api.search("coffee")["ranked"], [])

    def test_a_task_without_concept_words_keeps_plain_word_matching(self):
        self.assertEqual(search._concept_expansions("Zyxt qwerv plonk"), [])
        lexical, expansion, substrings = search._context_parts("Zyxt qwerv plonk")
        self.assertEqual((expansion, substrings), ([], []))
        self.assertEqual(search._context_query("Zyxt qwerv plonk"), " OR ".join(lexical))

    def test_lookup_folds_accents_and_regular_plurals(self):
        self.assertEqual(search._fold("Japonés"), "japones")
        self.assertIn("dinner", search._lookup_keys("dinners"))
        self.assertEqual(search._fold("नमस्ते"), "नमस्ते")


if __name__ == "__main__":
    unittest.main()
