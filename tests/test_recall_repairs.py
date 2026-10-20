"""Public recall, graph and validation regressions using retained synthetic vaults."""
from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knowledgeos.memory import MemoryAPI
from knowledgeos.vault import Vault


class RecallRepairs(unittest.TestCase):
    def setUp(self):
        artifact_root = ROOT / "work/gc-artifacts/.knowledgeos/repair-20261019/recall"
        artifact_root.mkdir(parents=True, exist_ok=True)
        self.run = Path(tempfile.mkdtemp(prefix="case-", dir=artifact_root))
        self.vault = self.run / "vault"
        self.vault.mkdir()
        self.state = patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.run / "gate-state")})
        self.state.start()
        self.addCleanup(self.state.stop)

    def note(self, rel, body, **fields):
        metadata = dict(type="concept", title=Path(rel).stem, description="Synthetic recall case",
                        status="active", schema="knowledgeos-v0.3", created="2026-10-19",
                        updated="2026-10-19", tags="[verification]")
        metadata.update(fields)
        text = "---\n" + "\n".join(f"{k}: {v}" for k, v in metadata.items()) + "\n---\n" + body + "\n"
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_toolkit_census_keeps_personal_notes_and_excludes_tooling_and_synthetic_self(self):
        (self.vault / "pyproject.toml").write_text("[project]\nname='synthetic'\n", encoding="utf-8")
        (self.vault / "knowledgeos").mkdir()
        self.note("People/Self.md", "Actual retained synthetic identity", type="person", id="kos:person:self")
        self.note("Concepts/Actual.md", "censustoken useful personal evidence")
        excluded = [".agents/skills/demo/SKILL.md", ".cursor/rules/agent.md", "work/fixture/People/Self.md",
                    "outputs/fixture/People/Self.md", "tests/fixtures/People/Self.md", "fixtures/People/Self.md",
                    "Projects/A/AGENTS.md", "Projects/A/CLAUDE.md"]
        for rel in excluded:
            self.note(rel, "censustoken synthetic persona", type="person", id="kos:person:self")
        api = MemoryAPI(self.vault)
        self.assertEqual([r["path"] for r in api.search("censustoken")["ranked"]], ["Concepts/Actual.md"])
        self.assertEqual(api.get_note("kos:person:self")["path"], "People/Self.md")
        self.assertEqual({p.relative_to(self.vault).as_posix() for p in Vault(self.vault).iter_markdown()},
                         {"People/Self.md", "Concepts/Actual.md"})

    def test_graph_resolves_markdown_locally_and_refuses_ambiguous_wikilinks_and_examples(self):
        self.note("Target.md", "Root sibling")
        self.note("Projects/A/Target.md", "Project sibling")
        self.note("Projects/A/Source.md", "[Local](Target.md)\n[Explicit](/Shared.md)\n[Parent](../../Shared.md)")
        self.note("Shared.md", "Explicit root target")
        self.note("Projects/A/Ambiguous.md", "[[Target]]\n[[Target|Alias]]")
        self.note("Projects/A/Example.md", "```markdown\n[Fake](Target.md)\n```\n~~~text\n[[Target]]\n~~~")
        self.note("Projects/A/Mixed.md", "[[Target.md]]\n[Local](Target.md)")
        api = MemoryAPI(self.vault)
        self.assertEqual([r["path"] for r in api.related("Projects/A/Source.md")["related"]],
                         ["Projects/A/Target.md", "Shared.md"])
        self.assertEqual(api.related("Projects/A/Ambiguous.md")["related"], [])
        self.assertEqual(api.related("Projects/A/Example.md")["related"], [])
        self.assertEqual([r["path"] for r in api.related("Projects/A/Mixed.md")["related"]], ["Projects/A/Target.md"])

    def test_personal_readme_and_nested_project_docs_remain_searchable(self):
        self.note("README.md", "personalreadmetoken")
        self.note("Projects/A/docs/Plan.md", "personalreadmetoken")
        self.assertEqual({r["path"] for r in MemoryAPI(self.vault).search("personalreadmetoken")["ranked"]},
                         {"README.md", "Projects/A/docs/Plan.md"})
        self.assertEqual({p.relative_to(self.vault).as_posix() for p in Vault(self.vault).iter_markdown()},
                         {"README.md", "Projects/A/docs/Plan.md"})

    def test_natural_question_recalls_travel_keyboard_and_abstains_for_unknown(self):
        self.note("Preferences/Keyboard.md", "For travel I need a lightweight compact keyboard.")
        self.note("Projects/Plants.md", "I water the garden every morning.")
        self.note("Rules/Edits.md", "Never silently rewrite")
        api = MemoryAPI(self.vault)
        self.assertEqual([r["path"] for r in api.search("Help me choose a keyboard for travel")["ranked"]],
                         ["Preferences/Keyboard.md"])
        self.assertEqual(api.search("What is my preferred submarine brand?")["ranked"], [])
        self.assertEqual(api.search("keyboard submarine")["ranked"], [])
        self.assertEqual([r["path"] for r in api.search("Never silently rewrite")["ranked"]], ["Rules/Edits.md"])
        self.assertEqual(api.search("Never loudly rewrite")["ranked"], [])

    def test_blended_order_preserves_strong_fts_relevance_before_alphabetical_titles(self):
        self.note("Concepts/ZStrong.md", "raresignal " * 18, title="Z strong evidence")
        self.note("Concepts/ADistractor.md", "raresignal " + "unrelated filler " * 120, title="A weak evidence")
        self.note("Concepts/BDistractor.md", "raresignal " + "filler noise " * 160, title="B weak evidence")
        api = MemoryAPI(self.vault)
        results = api.search("raresignal", limit=2)
        self.assertEqual(results["fts"][0]["path"], "Concepts/ZStrong.md")
        self.assertEqual(results["ranked"][0]["path"], "Concepts/ZStrong.md")
        self.assertEqual(len(results["ranked"]), 2)

    def test_validate_reports_precise_link_and_schema_errors_through_cli(self):
        self.note("People/Self.md", "Synthetic owner", type="person", id="kos:person:self")
        self.note("Projects/A/Target.md", "One target")
        self.note("Projects/B/Target.md", "Another target")
        self.note("Concepts/Broken.md", "[Absent](Missing.md)\n[[Target]]\n```md\n[[NotALink]]\n```",
                  status="banana", created="2026-02-30", updated="yesterday", tags="not-a-list")
        proc = subprocess.run([sys.executable, "-B", "-m", "knowledgeos", "validate", "--vault", str(self.vault)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
        report = json.loads(proc.stdout)
        errors = [row for row in report["errors"] if row["path"] == "Concepts/Broken.md"]
        self.assertEqual(proc.returncode, 1)
        self.assertEqual({row["issue"] for row in errors},
                         {"broken_link", "ambiguous_link", "invalid_status", "invalid_date", "invalid_tags"})
        self.assertEqual(next(row for row in errors if row["issue"] == "ambiguous_link")["candidates"],
                         ["Projects/A/Target.md", "Projects/B/Target.md"])
        self.assertEqual({row["field"] for row in errors if row["issue"] == "invalid_date"}, {"created", "updated"})
        self.assertEqual(next(row for row in errors if row["issue"] == "broken_link")["target"], "Missing.md")

    def test_fresh_starter_is_valid_with_templates_and_instruction_links(self):
        proc = subprocess.run([sys.executable, "-B", "-m", "knowledgeos", "init", str(self.vault),
                               "--name", "Synthetic Owner", "--non-interactive"],
                              cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        report = json.loads(subprocess.run([sys.executable, "-B", "-m", "knowledgeos", "validate",
                                           "--vault", str(self.vault)], cwd=ROOT, capture_output=True,
                                          text=True, timeout=30).stdout)
        self.assertEqual(report["errors"], [])

    def test_validate_handles_invalid_list_metadata_and_counts_every_examined_note(self):
        self.note("People/Self.md", "Synthetic owner", type="person", id="kos:person:self")
        self.note("Concepts/List.md", "Malformed fields", type="[concept]", status="[active]", created="[2026-10-19]")
        (self.vault / "Plain.md").write_text("No frontmatter", encoding="utf-8")
        proc = subprocess.run([sys.executable, "-B", "-m", "knowledgeos", "validate", "--vault", str(self.vault)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["notes_checked"], 3)
        self.assertEqual({row["issue"] for row in report["errors"]},
                         {"missing_frontmatter", "invalid_status", "invalid_date"})


if __name__ == "__main__":
    unittest.main()
