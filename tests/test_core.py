"""Stdlib unit tests for KnowledgeOS core."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knowledgeos.ids import make_id, slugify
from knowledgeos.parser import parse_frontmatter, split_frontmatter
from knowledgeos.schema import REQUIRED_FIELDS, SCHEMA_V03
from knowledgeos.search import _fts_query, blended_search


class ParserTests(unittest.TestCase):
    def test_bool_and_list(self):
        fm = parse_frontmatter(
            "---\ntitle: Hi\npublish_to_notion: true\ntags: [a, b]\n---\nBody\n"
        )
        self.assertEqual(fm["title"], "Hi")
        self.assertIs(fm["publish_to_notion"], True)
        self.assertEqual(fm["tags"], ["a", "b"])

    def test_split(self):
        fm, body = split_frontmatter("---\ntitle: X\n---\nHello")
        self.assertEqual(fm["title"], "X")
        self.assertTrue(body.startswith("Hello"))


class SchemaTests(unittest.TestCase):
    def test_required_fields(self):
        self.assertIn("schema", REQUIRED_FIELDS)
        self.assertEqual(SCHEMA_V03, "knowledgeos-v0.3")


class IdsTests(unittest.TestCase):
    def test_make_id(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")
        self.assertTrue(make_id("decision", "Close Loop").startswith("kos:decision:"))


class SearchQueryTests(unittest.TestCase):
    def test_fts_query(self):
        q = _fts_query("Never silently rewrite")
        self.assertIn('"Never"', q)
        self.assertIn("AND", q)


class InitSmokeTests(unittest.TestCase):
    def test_init_creates_self(self):
        from knowledgeos.init_vault import init_vault

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "brain"
            result = init_vault(target, source_root=ROOT, owner_name="Test", non_interactive=True)
            self.assertTrue((target / "People" / "Self.md").exists())
            self.assertTrue((target / "knowledgeos" / "parser.py").exists())
            self.assertTrue((target / "AGENTS.md").exists())
            self.assertTrue((target / ".cursor" / "rules" / "knowledgeos-twin.mdc").exists())
            self.assertEqual(result["owner"], "Test")
            # post_init rebuild may succeed in temp vault
            self.assertIn("post_init", result)


class SessionRitualTests(unittest.TestCase):
    def test_session_start_and_ops(self):
        from knowledgeos.memory import MemoryAPI, dispatch

        api = MemoryAPI(ROOT)
        if not (ROOT / "knowledge_index.db").exists():
            self.skipTest("index not built")
        start = dispatch(api, "memory_session_start", {"task_hint": "KnowledgeOS", "limit": 5})
        self.assertEqual(start.get("ritual"), "breathe")
        self.assertIn("context", start)
        self.assertIn("ops", start)
        self.assertIn("agent_must", start)
        self.assertIn("actions_taken", start)
        ops = dispatch(api, "memory_ops_status", {})
        self.assertIn("plain_language", ops)
        self.assertIn("agent_instruction", ops)

    def test_autopilot_state_dir(self):
        from knowledgeos.autopilot import load_state, soft_prompt_for_human, state_dir

        d = state_dir(ROOT)
        self.assertTrue(d.exists())
        self.assertIsInstance(load_state(ROOT), dict)
        self.assertIsNone(soft_prompt_for_human({"open_proposals": [], "pending_outcomes": []}))
        self.assertIn(
            "remember",
            soft_prompt_for_human(
                {"open_proposals": [{"path": "x"}], "pending_outcomes": []}
            ).lower(),
        )


class BlendedSearchTests(unittest.TestCase):
    def test_search_against_repo_index(self):
        db = ROOT / "knowledge_index.db"
        if not db.exists():
            self.skipTest("index not built")
        result = blended_search(db, "KnowledgeOS", limit=5)
        self.assertTrue(result.get("fts_available"))
        self.assertGreaterEqual(len(result.get("ranked") or []), 1)


if __name__ == "__main__":
    unittest.main()
