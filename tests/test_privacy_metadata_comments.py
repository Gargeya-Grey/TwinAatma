"""A privacy marker excludes a note in every spelling a person is likely to write."""
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
}
KEPT = {
    "public": "privacy: public # shared with the team",
    "off": "do_not_remember: false # fine to keep",
    "no": "sensitive: no",
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
                           ("sensitive", "unclear text"), ("do_not_remember", ["x"])):
            with self.subTest(key=key, value=value):
                self.assertEqual(policy.text_reason("", {key: value}), "explicit_exclusion")
        for key, value in (("privacy", "public # shared"), ("do_not_remember", "false # fine"),
                           ("sensitive", False), ("do_not_remember", "")):
            with self.subTest(key=key, value=value):
                self.assertIsNone(policy.text_reason("", {key: value}))


if __name__ == "__main__":
    unittest.main()
