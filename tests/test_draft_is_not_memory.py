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
    "memory_related": [{"path_or_id": "People/Self.md", "hops": 2},
                       {"path_or_id": "Concepts/Linker.md", "hops": 1},
                       {"path_or_id": "Concepts/Linker.md", "hops": 2},
                       {"path_or_id": "Concepts/Linked.md", "hops": 2}],
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
# The rule is about notes and text: no tool above returns a draft as a note, and none
# returns its text. Three status answers name the path of a draft that waits, because the
# person must be told that it waits: `memory_ops_status`, the weekly report, and the
# freshness reason of a session start.
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
        self.write("Concepts/Linked.md", "---\ntitle: Linked\ntype: concept\n---\n\nA note the draft names.\n")
        # The draft links to a note, and two notes link to the draft. Either way round,
        # the draft is no neighbour of a note.
        drafted = self.api().propose_self_update("Quokka rule", "heuristics",
                                                 f"* {RULE} See [[Linked]]. It contradicts: [[Linked]].",
                                                 "Said so.", "append")
        self.draft = drafted["proposal_path"]
        name = self.draft.rsplit("/", 1)[-1]
        self.write("Concepts/Linker.md", "---\ntitle: Linker\ntype: concept\n---\n\n"
                                         f"See [the draft](../People/Self-Proposals/{name}) and [[{name[:-3]}]].\n")
        self.write("Concepts/Second.md", "---\ntitle: Second\ntype: concept\n---\n\n"
                                         f"Also [the draft](../People/Self-Proposals/{name}).\n")

    def ask(self, tool: str, arguments: dict) -> str:
        return json.dumps(dispatch(MemoryAPI(self.vault), tool, arguments), ensure_ascii=False)

    def draft_rows(self, tool: str, arguments: dict) -> list[str]:
        """Each value in the answer that is the path of a draft.

        A note the person wrote can name a draft in its own text; that text is the note's.
        What may not happen is a row, a link target or a candidate that *is* a draft.
        """
        found: list[str] = []

        def walk(value) -> None:
            if isinstance(value, dict):
                for key, inner in value.items():
                    walk(key)
                    walk(inner)
            elif isinstance(value, (list, tuple)):
                for inner in value:
                    walk(inner)
            elif isinstance(value, str):
                shown = value.replace("\\", "/").strip().lstrip("./")
                if shown.casefold().startswith("people/self-proposals/"):
                    found.append(value)

        walk(dispatch(MemoryAPI(self.vault), tool, arguments))
        return found


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
                    self.assertEqual(self.draft_rows(tool, arguments), [])

    def test_a_note_that_links_to_the_draft_does_not_make_it_a_neighbour(self):
        for start in ("Concepts/Linker.md", "Concepts/Linked.md", "Concepts/Second.md"):
            for hops in (1, 2, 3):
                with self.subTest(start=start, hops=hops):
                    arguments = {"path_or_id": start, "hops": hops}
                    self.assertEqual(self.draft_rows("memory_related", arguments), [])
                    self.assertNotIn(MARK, self.ask("memory_related", arguments))

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
        for arguments in RETURNS_NOTES["memory_related"]:
            with self.subTest(arguments=arguments):
                self.assertEqual(self.draft_rows("memory_related", arguments), [])
                self.assertNotIn(MARK, self.ask("memory_related", arguments))

    def test_the_real_note_is_still_found(self):
        self.assertIn("Quokka-ledger-owner", self.ask("memory_search", {"query": WORDS}))


class ADraftIsNoStart(DraftCase):
    def test_neighbours_of_a_draft_are_not_given(self):
        name = self.draft.rsplit("/", 1)[-1]
        for start in (self.draft, name, name[:-3], self.draft.upper()):
            for hops in (1, 2):
                with self.subTest(start=start, hops=hops):
                    arguments = {"path_or_id": start, "hops": hops}
                    answer = dispatch(MemoryAPI(self.vault), "memory_related", arguments)
                    self.assertIn("error", answer, answer)
                    self.assertEqual(self.draft_rows("memory_related", arguments), [])


class EveryReport(DraftCase):
    """The reports read the files, not the index. A draft is no row of theirs either."""

    def test_the_view_the_reports_read_holds_no_draft(self):
        from knowledgeos.remembering import RememberingPolicy

        connection = RememberingPolicy(self.vault).current_connection()
        try:
            paths = [row[0] for row in connection.execute("SELECT path FROM notes")]
            links = [value for row in connection.execute("SELECT source, destination FROM links") for value in row]
        finally:
            connection.close()
        self.assertIn("Concepts/Linker.md", paths)
        self.assertEqual([path for path in paths + links if "self-proposals/" in path.casefold()], [])

    def test_no_report_finding_names_the_draft(self):
        from knowledgeos import intelligence

        api = MemoryAPI(self.vault)
        found = {"tensions": intelligence.find_tensions(api), "orphans": intelligence.orphan_notes(api),
                 "gaps": intelligence.knowledge_gaps(api)}
        self.assertNotIn("self-proposals/", json.dumps(found, default=str).casefold())


class EveryFileList(unittest.TestCase):
    """A route that lists the vault's files itself says here why it may see a draft."""

    # File name -> the number of calls of the plain list, and the reason each is allowed.
    MAY_SEE_DRAFTS = {
        "indexer.py": (0, "defines both lists; the index keeps one row per file, drafts included"),
        "validator.py": (1, "checks the form of every file"),
        "doctor.py": (2, "counts files and conflict copies; it returns no note text"),
        "ids.py": (1, "gives every file an id"),
        "vault.py": (1, "the plain file iterator of the Vault class"),
        "outcomes.py": (1, "confirms one given path; it refuses the draft folder on the line before"),
        "memory.py": (1, "a read by id, which reaches a draft on purpose like a read by path"),
    }

    def test_each_call_of_the_plain_file_list_is_named(self):
        from support import ROOT

        calls = {}
        for file in sorted((ROOT / "knowledgeos").glob("*.py")):
            source = file.read_text(encoding="utf-8")
            count = len(re.findall(r"(?<!def )(?<![\w.])iter_markdown\(", source))
            if count:
                calls[file.name] = count
        expected = {name: count for name, (count, _reason) in self.MAY_SEE_DRAFTS.items() if count}
        self.assertEqual(calls, expected,
                         "A route that returns notes uses `indexer.iter_notes`, which leaves profile drafts out. "
                         "A route that must see drafts is added to MAY_SEE_DRAFTS with its reason.")


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
