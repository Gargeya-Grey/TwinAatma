"""The privacy reader against a full YAML parser, on generated metadata blocks.

`knowledgeos` reads metadata without a YAML library, so it cannot know every form. Its
rule is to keep a note private when a privacy key is present in a form it does not take
apart. This test writes many documents with a real YAML library, in every style that
library offers, and asks one question of each: when the parsed document holds a privacy
key that does not clearly say "share", does the reader keep the note private?

The YAML library is a tool of the test only. The test is skipped where it is absent.
"""
from __future__ import annotations

import random
import unittest

try:
    import yaml
except ImportError:  # pragma: no cover - the toolkit itself has no dependencies
    yaml = None

from knowledgeos.remembering import _FLAG_KEYS, _OPEN_LABELS, _PRIVACY_KEYS, _metadata_key, marked_excluded

PLAIN_KEYS = ["title", "type", "tags", "status", "project", "meta", "notes", "links", "created"]
PLAIN_VALUES = ["A note", "draft", "Privacy: a guide", "what sensitive means", ["privacy", "security"],
                3, None, True, "2026-11-13", "do not remember the milk: buy it"]
PRIVACY_NAMES = ["privacy", "Privacy", "PRIVACY", "memory_privacy", "sensitivity", "memory_policy",
                 "memory-privacy", "Memory Privacy"]
FLAG_NAMES = ["do_not_remember", "sensitive", "third_party_sensitive", "do-not-remember", "Do Not Remember"]
PRIVATE_VALUES = ["private", "secret", "exclude", "Private", "team-only", "high", True, ["private"],
                  ["public", "private"], {"level": "private"}, {"level": "public"}, "private # not a comment"]
OPEN_VALUES = ["public", "ordinary", "shared", "open", "normal", "none", "low", None, False, ["public", "shared"]]
SET_FLAGS = [True, "yes", "true", "always", 1, ["x"], {"value": True}]
UNSET_FLAGS = [False, None, "no", "false", "off"]
STYLES = [dict(default_flow_style=False), dict(default_flow_style=True), dict(default_flow_style=None),
          dict(default_flow_style=False, default_style='"'), dict(default_flow_style=False, default_style="'"),
          dict(default_flow_style=False, indent=4), dict(default_flow_style=True, width=30),
          dict(default_flow_style=False, canonical=True)]


def labels(value) -> list:
    if isinstance(value, (list, tuple)):
        return [label for item in value for label in labels(item)]
    return [value]


def says_share(value) -> bool:
    """The oracle's reading of a parsed privacy value."""
    for label in labels(value):
        if label is None or label is False:
            continue
        if not isinstance(label, str) or label.casefold() not in _OPEN_LABELS:
            return False
    return True


def flag_unset(value) -> bool:
    return value is None or value is False or (isinstance(value, str)
                                               and value.casefold() in {"", "false", "no", "off", "0", "null", "none", "~"})


def must_be_private(document) -> bool:
    """True when the parsed document holds a privacy key, at any depth, that does not say "share"."""
    if isinstance(document, dict):
        for key, value in document.items():
            name = _metadata_key(key)
            if name in _PRIVACY_KEYS and not says_share(value):
                return True
            if name in _FLAG_KEYS and not flag_unset(value):
                return True
            if must_be_private(value):
                return True
    if isinstance(document, list):
        return any(must_be_private(item) for item in document)
    return False


def plain_document(rng: random.Random, depth: int = 0) -> dict:
    document = {}
    for key in rng.sample(PLAIN_KEYS, rng.randint(1, 5)):
        roll = rng.random()
        if roll < 0.2 and depth < 2:
            document[key] = plain_document(rng, depth + 1)
        elif roll < 0.3 and depth < 2:
            document[key] = [plain_document(rng, depth + 1) for _ in range(rng.randint(1, 2))]
        else:
            document[key] = rng.choice(PLAIN_VALUES)
    return document


def place(rng: random.Random, document: dict, key: str, value, *, top: bool) -> None:
    """Put ``key: value`` into the document: at the top, or at a random depth."""
    target = document
    while not top and rng.random() < 0.6:
        inner = [v for v in target.values() if isinstance(v, dict)]
        inner += [item for v in target.values() if isinstance(v, list) for item in v if isinstance(item, dict)]
        if not inner:
            break
        target = rng.choice(inner)
    items = list(target.items())
    items.insert(rng.randint(0, len(items)), (key, value))
    target.clear()
    target.update(items)


def note(document: dict, style: dict) -> str:
    return "---\n" + yaml.dump(document, sort_keys=False, allow_unicode=True, **style) + "---\n\nThe body.\n"


@unittest.skipIf(yaml is None, "the YAML library is not installed")
class AgainstAFullParser(unittest.TestCase):
    def check_private(self, rng: random.Random, names: list[str], values: list, rounds: int) -> None:
        for number in range(rounds):
            document = plain_document(rng)
            place(rng, document, rng.choice(names), rng.choice(values), top=False)
            for style in STYLES:
                text = note(document, style)
                # The oracle reads the text back, so the claim is about the text as written.
                parsed = yaml.safe_load(text.split("---\n")[1])
                if not must_be_private(parsed):
                    continue
                self.assertTrue(marked_excluded(text), f"case {number}, style {style}:\n{text}")

    def test_a_privacy_key_that_does_not_say_share_keeps_the_note_private(self):
        self.check_private(random.Random(20261113), PRIVACY_NAMES, PRIVATE_VALUES, 400)

    def test_a_flag_that_is_set_keeps_the_note_private(self):
        self.check_private(random.Random(7), FLAG_NAMES, SET_FLAGS, 300)

    def test_a_document_with_no_privacy_key_is_shared_in_block_style(self):
        rng = random.Random(11)
        for number in range(400):
            document = plain_document(rng)
            for style in (STYLES[0], STYLES[3], STYLES[4], STYLES[5]):
                text = note(document, style)
                self.assertFalse(marked_excluded(text), f"case {number}, style {style}:\n{text}")

    def test_a_top_level_key_that_says_share_is_shared_in_block_style(self):
        rng = random.Random(13)
        for number in range(300):
            document = {key: value for key, value in plain_document(rng).items() if not isinstance(value, (dict, list))}
            if rng.random() < 0.5:
                place(rng, document, rng.choice(PRIVACY_NAMES), rng.choice(OPEN_VALUES), top=True)
            else:
                place(rng, document, rng.choice(FLAG_NAMES), rng.choice(UNSET_FLAGS), top=True)
            text = note(document, STYLES[0])
            self.assertFalse(marked_excluded(text), f"case {number}:\n{text}")

    def test_a_repeated_key_counts_wherever_it_stands(self):
        for first, second in (("private", "public"), ("public", "private")):
            text = f"---\ntitle: x\nprivacy: {first}\nprivacy: {second}\n---\nBody.\n"
            self.assertTrue(marked_excluded(text), text)


if __name__ == "__main__":
    unittest.main()
