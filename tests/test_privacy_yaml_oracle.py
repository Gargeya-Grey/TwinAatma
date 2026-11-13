"""The privacy reader against a full YAML parser.

`knowledgeos` reads metadata without a YAML library. Its rule is to share a note only
when it understands the whole metadata block. This test asks one question of many
blocks: when the reader shares a note, does a full YAML parser agree that the block
holds no privacy key that says "keep this"?

The blocks come from three places: a list of known forms, documents written by the YAML
library in each of its styles, and known blocks changed at random (a token put in, a
piece cut out, a line moved or indented). The random part is what finds a form nobody
thought of. With the reader of commit a0171e0 it finds a fault in about one block of
seventy.

The oracle below does not import the reader's key names or labels. It states the rule
again from the documents. The YAML library is a tool of this test only, and the test is
skipped where it is absent, so install PyYAML before a release run. A block that the
library refuses to parse cannot be judged and is counted, not failed.
"""
from __future__ import annotations

import random
import unittest

try:
    import yaml
except ImportError:  # pragma: no cover - the toolkit itself has no dependencies
    yaml = None

from knowledgeos.remembering import marked_excluded

# The rule, as the documents state it.
PRIVACY = {"privacy", "memory_privacy", "sensitivity", "memory_policy"}
FLAGS = {"sensitive", "third_party_sensitive", "do_not_remember"}
SHARE = {"", "ordinary", "public", "shared", "open", "normal", "none", "low", "false", "no", "off", "0", "null", "~"}
UNSET = {"", "false", "no", "off", "0", "null", "none", "~"}


def name(key) -> str:
    """A key without case, where spaces, `-` and `_` are the same."""
    return "_".join(str(key).lower().replace("-", " ").replace("_", " ").split()) if isinstance(key, str) else ""


def says_no(value, words) -> bool:
    if isinstance(value, (list, tuple)):
        return all(says_no(item, words) for item in value)
    if value is None or value is False:
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return value == 0
    return isinstance(value, str) and value.strip().lower() in words


def must_be_private(document, seen=None) -> bool:
    """True when the parsed block holds, at any depth, a privacy key that does not say "share"."""
    seen = set() if seen is None else seen
    if id(document) in seen:
        return False
    seen.add(id(document))
    if isinstance(document, dict):
        for key, value in document.items():
            if name(key) in PRIVACY and not says_no(value, SHARE):
                return True
            if name(key) in FLAGS and not says_no(value, UNSET):
                return True
            if must_be_private(key, seen) or must_be_private(value, seen):
                return True
    if isinstance(document, (list, tuple, set, frozenset)):
        return any(must_be_private(item, seen) for item in document)
    return False


def note(block: str) -> str:
    return "---\n" + block + "\n---\n\nThe body.\n"


def verdict(block: str) -> str:
    """``"leak"``, ``"agree"``, ``"withheld"``, ``"no_parse"`` or ``"skip"`` for one block."""
    if any(line.startswith(("---", "...")) for line in block.split("\n")):
        return "skip"  # the line would end the block; the rest is the body
    if marked_excluded(note(block)):
        return "withheld"
    try:
        document = yaml.safe_load(block)
    except Exception:  # noqa: BLE001 - any refusal of the library means "cannot be judged"
        return "no_parse"
    return "leak" if must_be_private(document) else "agree"


# Blocks that a full parser reads as marked. Each one was a fault of an earlier reader,
# or is a neighbour of one.
MARKED = [
    "title: A note\ntype: note\nprivacy: private",
    "privacy:\n  level: private",
    "privacy:\n  private",
    "meta:\n  privacy: private\n  other: x",
    "notes:\n  - privacy: private\n    name: y\n  - name: z",
    "{title: x, privacy: private}",
    "title: x\nmeta: {privacy: private}",
    '"priv\\u0061cy": private',
    '{"priv\\u0061cy": private}',
    "!!str privacy: private",
    "&key privacy: private",
    "first: &key privacy\n*key: private",
    "privacy: public\n  private",
    'privacy: "public\n  private"',
    "do_not_remember: false\n  yes",
    "? privacy\n: private",
    "title: x\ndo_not_remember: true",
    "title: x\nsensitive: [yes]",
    "aliases:\n- one\n- two\nprivacy: [public, private]",
    "base: &b\n  privacy: private\nmeta:\n  <<: *b",
    "list:\n  - - privacy: private",
    "list:\n  -\n    privacy: private",
    "list:\n  - -privacy: private",
    "title: 'single'\n'privacy': 'private'",
    "tags: [a,\n  b]\nprivacy: private",
    "meta: [privacy: private]",
    "meta: [{privacy: private}]",
    "title: text # comment\nprivacy: secret # comment",
    "memory-privacy: secret\nDo Not Remember: yes",
    "title: x\nthird_party_sensitive: on",
    "privacy : private",
    "  privacy: private\n  title: x",
]
# Blocks with no marker, in the forms that note tools write. The reader shares these.
ORDINARY = [
    "title: A note\ntype: note\ntags: [a, b]",
    "title: A note\nprivacy: public\ntags: [a, b]",
    "title: 'Privacy: a guide'\naliases:\n  - One\n  - 'Two: three'",
    "title: A note\ndescription: a long text\n  that goes on\n  for three lines\ntype: note",
    "title: A note\nsummary: |\n  a block of text\n  with: a colon\ntype: note",
    "title: A note\nsummary: >-\n  folded text\n\n  second paragraph\ntype: note",
    "title: A note\nrelations:\n  - type: supersedes\n    target: Old plan\n  - type: extends\n    target: Other",
    "title: Guide to {privacy:private} settings\ntype: note",
    "title: [urgent] call the bank\ntype: note",
    "title: A note\ncreated: 2026-11-13\nupdated: 2026-11-13T00:00:00Z\ncount: 3\ndone: true\nproject:",
    "title: A note\ntags:\n- one\n- two\nsensitive: no\nprivacy:",
    "title: A note # with a comment\n# a comment line\ntype: note",
    '"title": "A note"\n"type": "note"',
]
TOKENS = ["&a ", "*a", "*a : ", "!!str ", "!!map ", "!x ", '"', "'", "\\u0061", "\\x70", "\\\n", "\n", "\n  ", "\n    ",
          "\n- ", "\n  - ", ": ", ":", " : ", "{", "}", "[", "]", ",", ", ", "? ", "\n? ", "\n: ", "|", ">", "|-", ">+",
          "|2", "#", " #", " # c\n", "<<: ", "<<: *a\n", "privacy", "private", "public", "do_not_remember", "true",
          "false", "sensitive", "yes", "no", "null", "~", " ", "  ", "\t", "\r\n", "\r", "-", "- ", "--", "%YAML 1.1\n",
          "privacy: private", "privacy: public", "\nprivacy: private", "\n  privacy: private", "{privacy: private}",
          "[privacy: private]", "a: ", "key: ", "\n\n", "''", '\\"', "\\", "@", "`", "!", "&", "*", "=", "\nprivacy:\n",
          "memory_policy: exclude", "sensitivity: high", "0", "1", "y", " ", " ", "\x85", "﻿"]


def changed(rng: random.Random, block: str) -> str:
    """The block after one to four random changes."""
    for _ in range(rng.randint(1, 4)):
        roll = rng.random()
        at = rng.randint(0, len(block))
        lines = block.split("\n")
        if roll < 0.45:
            block = block[:at] + rng.choice(TOKENS) + block[at:]
        elif roll < 0.60:
            block = block[:at] + block[min(len(block), at + rng.randint(1, 4)):]
        elif roll < 0.72:
            index = rng.randrange(len(lines))
            lines[index] = " " * rng.randint(0, 6) + lines[index].lstrip(" ")
            block = "\n".join(lines)
        elif roll < 0.82:
            lines.insert(rng.randint(0, len(lines)), rng.choice(lines))
            block = "\n".join(lines)
        elif roll < 0.92:
            rng.shuffle(lines)
            block = "\n".join(lines)
        else:
            other = rng.choice(MARKED)
            block = block[:at] + other[rng.randint(0, len(other)):] + block[at:]
    return block


@unittest.skipIf(yaml is None, "the YAML library is not installed")
class KnownForms(unittest.TestCase):
    def test_the_oracle_calls_each_marked_block_marked(self):
        for block in MARKED:
            with self.subTest(block=block):
                self.assertTrue(must_be_private(yaml.safe_load(block)))

    def test_each_marked_block_keeps_the_note_private(self):
        for block in MARKED:
            with self.subTest(block=block):
                self.assertTrue(marked_excluded(note(block)))

    def test_a_repeated_key_counts_wherever_it_stands(self):
        # A full parser keeps the last value. The reader counts each one.
        for first, second in (("private", "public"), ("public", "private")):
            self.assertTrue(marked_excluded(note(f"title: x\nprivacy: {first}\nprivacy: {second}")))

    def test_each_ordinary_block_is_shared(self):
        for block in ORDINARY:
            with self.subTest(block=block):
                self.assertFalse(marked_excluded(note(block)))


@unittest.skipIf(yaml is None, "the YAML library is not installed")
class ChangedAtRandom(unittest.TestCase):
    ROUNDS = 12000

    def hunt(self, seed: int) -> None:
        rng = random.Random(seed)
        pool = MARKED + ORDINARY
        counts = {"leak": 0, "agree": 0, "withheld": 0, "no_parse": 0, "skip": 0}
        for _ in range(self.ROUNDS):
            block = changed(rng, rng.choice(pool))
            found = verdict(block)
            counts[found] += 1
            if found == "leak":
                self.fail(f"The reader shares a note that a full parser reads as marked:\n{block!r}\n"
                          f"parsed: {yaml.safe_load(block)!r}")
            if found == "agree" and len(pool) < 3000 and rng.random() < 0.05:
                pool.append(block)
        # The hunt means nothing when most blocks are withheld or cannot be parsed.
        self.assertGreater(counts["agree"], self.ROUNDS // 5, counts)
        self.assertGreater(counts["withheld"], self.ROUNDS // 10, counts)

    def test_no_changed_block_is_shared_against_the_full_parser_seed_one(self):
        self.hunt(20261113)

    def test_no_changed_block_is_shared_against_the_full_parser_seed_two(self):
        self.hunt(7)


PLAIN_KEYS = ["title", "type", "tags", "status", "project", "meta", "notes", "links", "created"]
PLAIN_VALUES = ["A note", "draft", "Privacy: a guide", "what sensitive means", ["privacy", "security"],
                3, None, True, "2026-11-13", "do not remember the milk: buy it"]
PRIVACY_NAMES = ["privacy", "Privacy", "PRIVACY", "memory_privacy", "sensitivity", "memory_policy",
                 "memory-privacy", "Memory Privacy"]
FLAG_NAMES = ["do_not_remember", "sensitive", "third_party_sensitive", "do-not-remember", "Do Not Remember"]
PRIVATE_VALUES = ["private", "secret", "exclude", "Private", "team-only", "high", True, ["private"],
                  ["public", "private"], {"level": "private"}, {"level": "public"}, "private # not a comment"]
SET_FLAGS = [True, "yes", "true", "always", 1, ["x"], {"value": True}]
STYLES = [dict(default_flow_style=False), dict(default_flow_style=True), dict(default_flow_style=None),
          dict(default_flow_style=False, default_style='"'), dict(default_flow_style=False, default_style="'"),
          dict(default_flow_style=False, indent=4), dict(default_flow_style=True, width=30),
          dict(default_flow_style=False, canonical=True), dict(default_flow_style=False, width=20)]
BLOCK_STYLES = [dict(default_flow_style=False), dict(default_flow_style=False, indent=4)]


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


def place(rng: random.Random, document: dict, key: str, value) -> None:
    """Put ``key: value`` into the document at a random depth."""
    target = document
    while rng.random() < 0.6:
        inner = [v for v in target.values() if isinstance(v, dict)]
        inner += [item for v in target.values() if isinstance(v, list) for item in v if isinstance(item, dict)]
        if not inner:
            break
        target = rng.choice(inner)
    items = list(target.items())
    items.insert(rng.randint(0, len(items)), (key, value))
    target.clear()
    target.update(items)


def written(document: dict, style: dict) -> str:
    """The document as the library writes it, without the library's own first `---` line.

    The generator uses one list object in several places. A tool that writes a note does
    not, so the writer is told not to turn that into an anchor and an alias.
    """
    class Writer(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True

    block = yaml.dump(document, Dumper=Writer, sort_keys=False, allow_unicode=True, **style).rstrip("\n")
    return block[4:] if block.startswith("---\n") else block


@unittest.skipIf(yaml is None, "the YAML library is not installed")
class WrittenByTheLibrary(unittest.TestCase):
    def check_private(self, rng: random.Random, names: list[str], values: list, rounds: int) -> None:
        judged = 0
        for number in range(rounds):
            document = plain_document(rng)
            place(rng, document, rng.choice(names), rng.choice(values))
            for style in STYLES:
                block = written(document, style)
                # The oracle reads the text back, so the claim is about the text as written.
                if not must_be_private(yaml.safe_load(block)):
                    continue
                judged += 1
                self.assertTrue(marked_excluded(note(block)), f"case {number}, style {style}:\n{block}")
        self.assertGreater(judged, rounds)

    def test_a_privacy_key_that_does_not_say_share_keeps_the_note_private(self):
        self.check_private(random.Random(20261113), PRIVACY_NAMES, PRIVATE_VALUES, 300)

    def test_a_flag_that_is_set_keeps_the_note_private(self):
        self.check_private(random.Random(7), FLAG_NAMES, SET_FLAGS, 200)

    def test_a_document_with_no_privacy_key_is_shared_in_block_style(self):
        rng = random.Random(11)
        for number in range(400):
            document = plain_document(rng)
            for style in BLOCK_STYLES:
                block = written(document, style)
                self.assertFalse(marked_excluded(note(block)), f"case {number}, style {style}:\n{block}")


if __name__ == "__main__":
    unittest.main()
