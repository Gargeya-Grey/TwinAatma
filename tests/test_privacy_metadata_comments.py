"""The privacy rule fails closed.

A note with a privacy key is private unless the value clearly says it is not. A spelling
this code does not know withholds the note.
"""
from __future__ import annotations

import unittest

from support import TempVaultCase

from knowledgeos.remembering import RememberingPolicy

EXCLUDED = {
    "comment": "privacy: private # keep out",
    "quoted": 'privacy: "private"  # quoted, then a comment',
    "flag": "do_not_remember: true # opted out",
    "word": "sensitive: yes # family",
    "unclear": "do_not_remember: maybe",
    "policy": "memory_policy: exclude # not for assistants",
    "list": "privacy: [private] # a list with a note",
    "mixed": "privacy: [public, private]",
    "items": "privacy:\n  - private # an item with a note",
    "twice": "privacy: private\nprivacy: public",
    "quotedkey": '"privacy": private',
    "hyphen": "do-not-remember: true",
    "spaced": "Memory Privacy: secret",
    "unknown": "privacy: team-only",
    "level": "sensitivity: high",
    "yes": "privacy: yes",
    "nested": "privacy:\n  level: private",
    "nextline": "privacy:\n  private",
    "under": "meta:\n  privacy: private",
    "initem": "notes:\n  - privacy: private",
    "question": "? privacy\n: private",
    "flagnested": "do_not_remember:\n  value: true",
    # The forms a fifth review found. The reader does not look for a key in these; it
    # refuses a block that it does not take apart.
    "escaped": '"priv\\u0061cy": private',
    "tagged": "!!str privacy: private",
    "anchored": "&key privacy: private",
    "alias": "first: &key privacy\n*key: private",
    "folded": "privacy: public\n  private",
    "quotedfold": 'privacy: "public\n  private"',
    "flagfold": "do_not_remember: false\n  yes",
    "dashkey": "list:\n  - -privacy: private",
    "bracekey": "meta: [privacy: private]",
}
KEPT = {
    "public": "privacy: public # shared with the team",
    "off": "do_not_remember: false # fine to keep",
    "no": "sensitive: no",
    "ordinary": "privacy: ordinary",
    "openlist": "privacy: [public] # shared",
    "low": "sensitivity: low",
    "blank": "privacy:",
    "notprivate": "privacy: no",
    "falseword": "privacy: false",
    "zero": "privacy: 0",
    "nullword": "privacy: null",
    # Ordinary metadata in the forms that note tools write stays shared.
    "itemlist": "aliases:\n  - Copper\n  - 'Field: one'",
    "wrapped": "summary: a long text\n  that goes on",
    "bracket": "summary: [urgent] call the bank",
    "braces": "summary: Guide to {privacy:private} settings",
    "nestedblock": "relations:\n  - type: supersedes\n    target: Old plan\n  - type: extends",
    "textblock": "summary: |\n  a text block\n  with two lines",
}


class MarkedNotes(TempVaultCase):
    def setUp(self) -> None:
        super().setUp()
        for name, marker in {**EXCLUDED, **KEPT}.items():
            self.write(f"Inbox/{name}.md", f"---\ntitle: Copperfield {name}\ntype: note\n{marker}\n---\n\n"
                                           f"The copperfield {name} merger closes in March.\n")

    def offered(self) -> set[str]:
        found = self.api().search("copperfield merger")
        return {row["path"] for row in found.get("ranked", []) + found.get("possibly_related", [])}

    def test_a_marked_note_is_not_offered_by_search(self):
        offered = self.offered()
        self.assertEqual({f"Inbox/{name}.md" for name in EXCLUDED} & offered, set(), offered)
        self.assertEqual({f"Inbox/{name}.md" for name in KEPT} - offered, set(), offered)

    def test_a_marked_note_is_not_in_the_startup_context(self):
        context = repr(self.api().session_start(task_hint="copperfield merger")["context"])
        for name in EXCLUDED:
            with self.subTest(marker=EXCLUDED[name]):
                self.assertNotIn(f"copperfield {name} merger", context)

    def test_the_policy_names_the_exclusion(self):
        policy = RememberingPolicy(self.vault)
        for key, value in (("privacy", "private # keep out"), ("do_not_remember", "true # opted out"),
                           ("sensitive", "unclear text"), ("do_not_remember", ["x"]),
                           ("privacy", "[private] # x"), ("privacy", ["public", "private"]),
                           ("Privacy", "private"), ("privacy", True), ("privacy", {"level": "private"}),
                           ("privacy", "a word nobody listed")):
            with self.subTest(key=key, value=value):
                self.assertEqual(policy.text_reason("", {key: value}), "explicit_exclusion")
        for key, value in (("privacy", "public # shared"), ("do_not_remember", "false # fine"),
                           ("sensitive", False), ("do_not_remember", ""), ("privacy", "ordinary"),
                           ("privacy", None), ("privacy", False), ("privacy", ["public", "shared"])):
            with self.subTest(key=key, value=value):
                self.assertIsNone(policy.text_reason("", {key: value}))

    def test_the_doctor_counts_the_marked_notes_without_naming_them(self):
        import contextlib
        import io

        from knowledgeos import doctor

        self.assertEqual(doctor.count_privacy_marked(self.vault), len(EXCLUDED))
        marked, not_read = doctor.count_withheld_by_metadata(self.vault)
        self.assertEqual(marked + not_read, len(EXCLUDED))
        self.assertGreater(marked, 0)
        self.assertGreater(not_read, 0)
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            doctor._check_privacy_markers(self.vault)
        self.assertIn(f"{marked} note(s) carry a privacy marker", said.getvalue())
        self.assertIn(f"{not_read} note(s) have metadata in a form the toolkit does not read", said.getvalue())
        self.assertIn("ordinary", said.getvalue())
        self.assertNotIn("Inbox/", said.getvalue())
        self.assertNotIn("opperfield", said.getvalue())

    def test_the_block_is_read_in_forms_a_strict_reader_would_refuse(self):
        from knowledgeos.remembering import marked_excluded

        for name, text in (("blank line first", "\n---\nprivacy: private\n---\nBody."),
                           ("no closing line", "---\nprivacy: private\nBody."),
                           ("dots close it", "---\nprivacy: private\n...\nBody."),
                           ("windows line ends", "---\r\nprivacy: private # c\r\n---\r\nBody."),
                           ("byte order mark", "\ufeff---\nprivacy: private\n---\nBody.")):
            with self.subTest(form=name):
                self.assertTrue(marked_excluded(text))
        self.assertFalse(marked_excluded("A body line that says privacy: private is not metadata."))


WHOLE_BLOCKS = {
    "escapedkey": 'title: Larkspur escapedkey\ntype: note\n"priv\\u0061cy": private',
    "taggedkey": "title: Larkspur taggedkey\ntype: note\n!!str privacy: private",
    "foldedvalue": "title: Larkspur foldedvalue\ntype: note\nprivacy: public\n  private",
    "aliaskey": "title: Larkspur aliaskey\ntype: note\nfirst: &key privacy\n*key: private",
    "flow": "{title: Larkspur flow, type: note, privacy: private}",
    "flowlines": "{\n  title: Larkspur flowlines,\n  type: note,\n  \"privacy\": private\n}",
    "flowflag": "{title: Larkspur flowflag, type: note, do_not_remember: true}",
    "nestedflow": "title: Larkspur nestedflow\ntype: note\nmeta: {privacy: private}",
    "deep": "title: Larkspur deep\ntype: note\nmeta:\n  access:\n    privacy:\n      level: private",
}


class MarkersInOtherShapes(TempVaultCase):
    """A marker inside braces or below another key keeps the note out of every route."""

    def setUp(self) -> None:
        super().setUp()
        for name, block in WHOLE_BLOCKS.items():
            self.write(f"Inbox/{name}.md", f"---\n{block}\n---\n\nThe larkspur {name} audit ends in April.\n")
        self.write("Inbox/plain.md", "---\ntitle: Larkspur plain\ntype: note\n---\n\n"
                                     "The larkspur plain audit ends in April.\n")

    def test_search_does_not_offer_them(self):
        found = self.api().search("larkspur audit")
        offered = {row["path"] for row in found.get("ranked", []) + found.get("possibly_related", [])}
        self.assertEqual(offered & {f"Inbox/{name}.md" for name in WHOLE_BLOCKS}, set())
        self.assertIn("Inbox/plain.md", offered)

    def test_no_read_tool_returns_their_text(self):
        import json

        from knowledgeos.memory import MemoryAPI, dispatch

        for tool, arguments in (("memory_search", {"query": "larkspur audit April"}),
                                ("memory_session_start", {"task_hint": "larkspur audit April"}),
                                ("memory_bootstrap_context", {"task_hint": "larkspur audit April"}),
                                ("memory_timeline", {"days": 30}),
                                ("memory_related", {"path_or_id": "Inbox/plain.md", "hops": 2})):
            answer = json.dumps(dispatch(MemoryAPI(self.vault), tool, arguments), ensure_ascii=False)
            for name in WHOLE_BLOCKS:
                with self.subTest(tool=tool, block=name):
                    self.assertNotIn(f"larkspur {name}", answer.casefold())

    def test_a_read_by_path_is_refused(self):
        from knowledgeos.memory import MemoryAPI, dispatch

        for name in WHOLE_BLOCKS:
            with self.subTest(block=name):
                try:
                    answer = repr(dispatch(MemoryAPI(self.vault), "memory_get_note",
                                           {"path_or_id": f"Inbox/{name}.md"}))
                except Exception as error:  # a refusal may be raised or returned
                    answer = repr(error)
                self.assertNotIn("audit ends in April", answer)

    def test_the_hook_does_not_show_them(self):
        import io
        import json

        from knowledgeos import claude_hook

        out = io.StringIO()
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "when does the larkspur audit end?"}
        claude_hook.main(["--vault", str(self.vault)], stdin=io.StringIO(json.dumps(event)), stdout=out)
        said = out.getvalue().casefold()
        self.assertIn("larkspur plain", said)
        for name in WHOLE_BLOCKS:
            with self.subTest(block=name):
                self.assertNotIn(f"larkspur {name}", said)

    def test_the_doctor_counts_them(self):
        from knowledgeos import doctor

        self.assertEqual(doctor.count_privacy_marked(self.vault), len(WHOLE_BLOCKS))


class ANoteAboutPrivacy(TempVaultCase):
    """A note that explains privacy markers in its body is an ordinary note."""

    def setUp(self) -> None:
        super().setUp()
        self.write("Concepts/Marker-guide.md",
                   "---\ntitle: Marker guide\ntype: concept\n---\n"
                   "---\nprivacy: private\n---\n\n"
                   "The harbour guide says: write the lines above at the top of a note to keep it private.\n")

    def test_it_can_be_read(self):
        from knowledgeos.memory import MemoryAPI, dispatch

        note = dispatch(MemoryAPI(self.vault), "memory_get_note", {"path_or_id": "Concepts/Marker-guide.md"})
        self.assertNotIn("error", note, note)
        self.assertIn("harbour guide", note["body"])

    def test_it_reaches_the_startup_context(self):
        from knowledgeos.memory import MemoryAPI, dispatch

        started = dispatch(MemoryAPI(self.vault), "memory_session_start", {"task_hint": "harbour guide marker"})
        self.assertIn("Concepts/Marker-guide.md", repr(started["context"]["relevant"]))

    def test_a_private_note_that_is_pasted_in_is_not_saved_as_an_ordinary_note(self):
        from knowledgeos.memory import MemoryAPI, dispatch

        pasted = "---\nprivacy: private\n---\nThe topaz beacon secret is hidden here.\n"
        self.write("Concepts/Target.md", "---\ntitle: Target\ntype: concept\n---\n\nA plain target note.\n")
        for tool, arguments in (
                ("memory_capture", {"title": "Copy of marked note", "content": pasted}),
                ("memory_capture", {"title": "Copy with a form nobody reads",
                                    "content": pasted.replace("privacy: private", "{privacy: private}")}),
                ("memory_propose_note_update", {"path_or_id": "Concepts/Target.md", "summary": "Add this",
                                                "patch_markdown": pasted})):
            with self.subTest(tool=tool, title=arguments.get("title")):
                answer = dispatch(MemoryAPI(self.vault), tool, arguments)
                self.assertIsNot(answer.get("ok"), True, answer)
                self.assertNotIn("topaz", repr(answer))
        # The command line and the importer call the method, not the tool.
        try:
            direct = self.api().capture("Copy by the method", pasted)
        except Exception as error:  # noqa: BLE001 - a refusal may be raised or returned
            direct = {"refused": repr(error)}
        self.assertIsNot(direct.get("ok"), True, direct)
        try:
            direct = self.api().propose_note_update("Concepts/Target.md", "Add this", pasted)
        except Exception as error:  # noqa: BLE001
            direct = {"refused": repr(error)}
        self.assertIsNot(direct.get("ok"), True, direct)
        from knowledgeos.indexer import iter_markdown

        saved = [path.name for path in iter_markdown(self.vault)
                 if "topaz beacon" in path.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual(saved, [])

    def test_a_mapping_on_its_way_out_is_still_judged(self):
        policy = RememberingPolicy(self.vault)
        self.assertEqual(policy.scrub({"privacy": "private", "body": "x"}), "[Excluded by remembering policy]")
        self.assertEqual(policy.scrub({"privacy": "ordinary", "body": "x"}), {"privacy": "ordinary", "body": "x"})


class WhatTheToolkitWrites(TempVaultCase):
    """The reader understands each file the toolkit writes. A saved fact can be read back."""

    TITLES = {
        "indigo": "Guide to {privacy:private} settings",
        "walnut": "[urgent] call: the bank",
        "saffron": '"Quoted" title',
        "pewter": "&co news",
        "cobalt": "!important: read this",
        "russet": "- a dash at the start",
        "ochre": "? a question mark at the start",
        "umber": "*star* note",
        "sienna": "{x: y}",
        "mauve": "privacy: private",
        "teal": "It's a 'quoted' thing",
        "fawn": "[a, b]",
        "ebony": "> an arrow, | a bar and # a hash",
    }

    def test_a_fact_saved_under_any_title_is_read_back(self):
        from knowledgeos.memory import MemoryAPI, dispatch

        for word, title in self.TITLES.items():
            with self.subTest(title=title):
                saved = dispatch(MemoryAPI(self.vault), "memory_capture",
                                 {"title": title, "content": f"The {word} otter fact is Wednesday."})
                self.assertIs(saved.get("ok"), True, saved)
                note = dispatch(MemoryAPI(self.vault), "memory_get_note", {"path_or_id": saved["path"]})
                self.assertIn(f"{word} otter", str(note.get("body")), note)
                found = dispatch(MemoryAPI(self.vault), "memory_search", {"query": f"{word} otter Wednesday"})
                self.assertIn(saved["path"], repr(found))

    def test_every_file_the_toolkit_writes_is_understood(self):
        from knowledgeos.indexer import iter_markdown
        from knowledgeos.memory import MemoryAPI, dispatch
        from knowledgeos.remembering import metadata_reason

        api = MemoryAPI(self.vault)
        for word, title in self.TITLES.items():
            dispatch(api, "memory_capture", {"title": title, "content": f"The {word} otter fact is Wednesday."})
            dispatch(api, "memory_propose_self_update",
                     {"summary": title, "section": "heuristics", "proposed_markdown": f"* Keeps the {word} rule.",
                      "rationale": "Said so.", "mode": "append"})
        started = dispatch(api, "memory_session_start", {"task_hint": "otter facts"})
        dispatch(api, "memory_session_end", {"session_id": started.get("session_id"),
                                             "summary": "[done] talked: about {otters} & more"})
        files = iter_markdown(self.vault)
        self.assertGreater(len(files), 2 * len(self.TITLES))
        withheld = {path.relative_to(self.vault).as_posix(): metadata_reason(path.read_text(encoding="utf-8"))
                    for path in files}
        self.assertEqual({path: reason for path, reason in withheld.items() if reason}, {})

    def test_the_starter_templates_are_understood(self):
        from knowledgeos.remembering import metadata_reason
        from support import ROOT

        templates = sorted((ROOT / "Templates").glob("*.md"))
        self.assertTrue(templates)
        for path in templates:
            with self.subTest(template=path.name):
                self.assertIsNone(metadata_reason(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
