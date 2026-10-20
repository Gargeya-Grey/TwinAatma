"""Public graph payloads disclose ambiguity without inventing neighbors."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get("TWIN_GRAPH_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from knowledgeos.memory import MemoryAPI


class GraphAmbiguityTests(unittest.TestCase):
    def setUp(self):
        output = ROOT / "work/gc-artifacts/.knowledgeos/graph-ambiguity-controls"
        output.mkdir(parents=True, exist_ok=True)
        self.run = Path(tempfile.mkdtemp(prefix="case-", dir=output))
        self.vault = self.run / "vault"
        self.vault.mkdir()
        state = patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.run / "gate-state")})
        state.start()
        self.addCleanup(state.stop)

    def note(self, relative, body):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntype: concept\ntitle: " + path.stem +
                        "\nstatus: active\nschema: knowledgeos-v0.3\n---\n" + body,
                        encoding="utf-8")
        return path

    def twins(self):
        self.note("Concepts/Twin.md", "First candidate")
        self.note("Projects/B/Twin.md", "Second candidate")

    def test_ambiguous_reference_discloses_both_candidates_and_preserves_real_neighbors(self):
        self.twins()
        self.note("Concepts/Known.md", "A resolved neighbor")
        self.note("Projects/A/Source.md", "[[Twin]]\n[[Concepts/Known]]")
        payload = MemoryAPI(self.vault).related("Projects/A/Source.md")
        self.assertEqual([row["path"] for row in payload["related"]], ["Concepts/Known.md"])
        self.assertEqual(payload.get("warnings"), [{
            "issue": "ambiguous_link", "source": "Projects/A/Source.md", "target": "Twin",
            "candidates": ["Concepts/Twin.md", "Projects/B/Twin.md"],
        }])

    def test_unrelated_ambiguity_fenced_examples_and_missing_targets_do_not_warn(self):
        self.twins()
        self.note("Projects/B/Other.md", "[[Twin]]")
        self.note("Concepts/Known.md", "A resolved neighbor")
        self.note("Projects/A/Source.md", "[[Concepts/Known]]\n[[Missing]]\n```md\n[[Twin]]\n```")
        payload = MemoryAPI(self.vault).related("Projects/A/Source.md")
        self.assertEqual([row["path"] for row in payload["related"]], ["Concepts/Known.md"])
        self.assertEqual(payload.get("warnings", []), [])

    def test_warnings_follow_expanded_hops_and_refresh_after_source_edit(self):
        self.twins()
        self.note("Concepts/Seed.md", "[[Concepts/Middle]]")
        middle = self.note("Concepts/Middle.md", "[[Twin]]\n[[Concepts/Leaf]]")
        self.note("Concepts/Leaf.md", "Last neighbor")
        api = MemoryAPI(self.vault)
        first = api.related("Concepts/Seed.md", hops=1)
        self.assertEqual([row["path"] for row in first["related"]], ["Concepts/Middle.md"])
        self.assertEqual(first.get("warnings", []), [])
        second = api.related("Concepts/Seed.md", hops=2)
        self.assertEqual([row["path"] for row in second["related"]], ["Concepts/Leaf.md", "Concepts/Middle.md"])
        self.assertEqual(second.get("warnings"), [{
            "issue": "ambiguous_link", "source": "Concepts/Middle.md", "target": "Twin",
            "candidates": ["Concepts/Twin.md", "Projects/B/Twin.md"],
        }])
        middle.write_text("---\ntype: concept\ntitle: Middle\n---\n[[Concepts/Leaf]]", encoding="utf-8")
        edited = api.related("Concepts/Seed.md", hops=2)
        self.assertEqual([row["path"] for row in edited["related"]], ["Concepts/Leaf.md", "Concepts/Middle.md"])
        self.assertEqual(edited.get("warnings", []), [])


if __name__ == "__main__":
    unittest.main()
