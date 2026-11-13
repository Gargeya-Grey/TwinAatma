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
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            doctor._check_privacy_markers(self.vault)
        self.assertIn(f"{len(EXCLUDED)} note(s) carry a privacy marker", said.getvalue())
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


if __name__ == "__main__":
    unittest.main()
