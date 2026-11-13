"""A profile draft the person has not decided is not a note. No read tool returns it."""
from __future__ import annotations

import json
import re
import unittest

from support import TempVaultCase

from knowledgeos.memory import MemoryAPI, dispatch

RULE = "Never deploys the quokka ledger on a Friday afternoon; the code word is zanzibar."
MARK = "zanzibar"
WORDS = "quokka ledger"

# Each tool that returns notes, with arguments that would match the draft. A new read tool
# belongs in this table, or in REACHES_A_DRAFT with the reason.
RETURNS_NOTES = {
    "memory_search": [{"query": "Friday afternoon"}, {"query": WORDS}, {"query": "Self proposal"},
                      {"query": "what do I do with the quokka ledger on a Friday"},
                      {"query": "heuristics"}, {"query": "Quokka rule"}],
    "memory_related": [{"path_or_id": "People/Self.md", "hops": 2}],
    "memory_decisions": [{}],
    "memory_drift": [{"days": 30}],
    "memory_timeline": [{"days": 30}],
    "memory_bootstrap_context": [{"task_hint": "deploy the quokka ledger on Friday afternoon"}],
    "memory_pending_outcomes": [{}],
    "memory_session_start": [{"task_hint": "deploy the quokka ledger on Friday afternoon"}],
    "memory_breathe": [{"task_hint": "Quokka rule heuristics"}],
    "memory_self_get": [{}],
    "memory_ops_status": [{}],
}
# These reach a draft on purpose: the list of drafts, and a read by the draft's own path.
REACHES_A_DRAFT = {"memory_list_self_proposals", "memory_get_note"}
# These write, or decide a draft. They are not read routes.
WRITES = {"memory_capture", "memory_record_outcome", "memory_forget", "memory_supersede",
          "memory_propose_self_update", "memory_accept_self_update", "memory_propose_note_update",
          "memory_reject_self_update", "memory_propose_from_drift", "memory_propose_from_lesson",
          "memory_session_end"}


class DraftCase(TempVaultCase):
    def setUp(self) -> None:
        super().setUp()
        self.api().capture("Quokka ledger owner", "The quokka ledger is owned by the finance team.")
        drafted = self.api().propose_self_update("Quokka rule", "heuristics", f"* {RULE}", "Said so.", "append")
        self.draft = drafted["proposal_path"]

    def ask(self, tool: str, arguments: dict) -> str:
        return json.dumps(dispatch(MemoryAPI(self.vault), tool, arguments), ensure_ascii=False)


class EveryReadTool(DraftCase):
    def test_the_table_names_every_tool(self):
        from knowledgeos.memory import TOOL_SPECS

        named = {tool["name"] for tool in TOOL_SPECS}
        self.assertEqual(named - set(RETURNS_NOTES) - REACHES_A_DRAFT - WRITES, set())

    def test_no_tool_that_returns_notes_returns_the_draft_text(self):
        for tool, calls in RETURNS_NOTES.items():
            for arguments in calls:
                with self.subTest(tool=tool, arguments=arguments):
                    self.assertNotIn(MARK, self.ask(tool, arguments))

    def test_no_note_row_names_the_draft(self):
        for tool in ("memory_search", "memory_related", "memory_decisions", "memory_drift",
                     "memory_timeline", "memory_bootstrap_context", "memory_pending_outcomes"):
            for arguments in RETURNS_NOTES[tool]:
                with self.subTest(tool=tool, arguments=arguments):
                    self.assertNotIn("Self-Proposals/", self.ask(tool, arguments))

    def test_the_draft_in_any_shape_stays_out(self):
        path = self.vault / self.draft
        text = path.read_text(encoding="utf-8")
        for kind in ("decision", "project", "note", "moc"):
            path.write_text(re.sub(r"^type: .*$", f"type: {kind}", text, count=1, flags=re.M), encoding="utf-8")
            for tool in ("memory_search", "memory_decisions", "memory_timeline", "memory_bootstrap_context"):
                for arguments in RETURNS_NOTES[tool]:
                    with self.subTest(kind=kind, tool=tool, arguments=arguments):
                        self.assertNotIn(MARK, self.ask(tool, arguments))

    def test_a_decided_draft_stays_out_too(self):
        self.assertTrue(self.api().reject_self_update(self.draft, "Not mine.").get("ok"))
        for arguments in RETURNS_NOTES["memory_search"]:
            with self.subTest(arguments=arguments):
                self.assertNotIn(MARK, self.ask("memory_search", arguments))

    def test_the_real_note_is_still_found(self):
        self.assertIn("Quokka-ledger-owner", self.ask("memory_search", {"query": WORDS}))


class OnPurpose(DraftCase):
    def test_the_list_of_drafts_names_it(self):
        self.assertIn(self.draft, self.ask("memory_list_self_proposals", {}))

    def test_a_read_by_its_own_path_returns_it(self):
        self.assertIn(MARK, self.ask("memory_get_note", {"path_or_id": self.draft}))

    def test_an_approved_rule_is_in_the_profile(self):
        self.assertTrue(self.approve(self.draft).get("ok"))
        self.assertIn(MARK, self.ask("memory_self_get", {}))


class APersonsOwnMap(TempVaultCase):
    """A map the person wrote is memory. A starter page under a `_` name is not."""

    def setUp(self) -> None:
        super().setUp()
        self.write("MOCs/Family.md", "---\ntitle: Family map\ntype: moc\n---\n\n"
                                     "Mira loves chess and collects coins.\n")

    def test_a_plain_question_is_offered_the_map(self):
        found = self.api().search("what games does Mira like")
        offered = [row["path"] for row in found.get("ranked", []) + found.get("possibly_related", [])]
        self.assertIn("MOCs/Family.md", offered)

    def test_the_startup_context_holds_the_map(self):
        relevant = self.api().bootstrap_context(task_hint="Mira chess coins")["relevant"]
        self.assertIn("MOCs/Family.md", repr(relevant))

    def test_a_starter_page_is_still_not_offered(self):
        relevant = self.api().bootstrap_context(task_hint="Master MOC index")["relevant"]
        self.assertNotIn("_MOC_Master", repr(relevant))
        self.assertNotIn("_Index.md", repr(relevant))

    def test_the_map_counts_as_a_note_of_the_person(self):
        from knowledgeos.autopilot import has_own_notes
        from knowledgeos.init_vault import init_vault
        from support import ROOT

        fresh = self.root / "fresh"
        init_vault(fresh, source_root=ROOT, owner_name="New Person", non_interactive=True)
        self.assertFalse(has_own_notes(MemoryAPI(fresh)))
        (fresh / "MOCs" / "Family.md").write_text("---\ntitle: Family map\ntype: moc\n---\n\nMira loves chess.\n",
                                                  encoding="utf-8")
        self.assertTrue(has_own_notes(MemoryAPI(fresh)))


if __name__ == "__main__":
    unittest.main()
