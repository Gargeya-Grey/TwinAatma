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

The library is given the whole text of the note, with its opening and closing lines,
and is asked for the first document. A sixth review found a fault in the opening line
(`--- # note`, then a line separator that only a full parser honours, then the key),
which an oracle that was handed the inside of the block could not see. So the opening
line, the closing line and the text after it are changed at random too. Metadata is
the block that opens with `---` on the first line that holds anything, which is where
note tools look for it. A text that opens another way is not judged.

The oracle below does not import the reader's key names or labels. It states the rule
again from the documents. The YAML library is a tool of this test only, and the test is
skipped where it is absent, so install PyYAML before a release run. A block that the
library refuses to parse cannot be judged and is counted, not failed.
"""
from __future__ import annotations

import random
import re
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


def opens_metadata(text: str) -> bool:
    """True when the first line that holds anything is a `---` line."""
    for line in re.split("\r\n|[\r\n\x85  ]", text.lstrip("﻿")):
        if line.strip():
            return line.startswith("---") and line[3:4] in ("", " ", "\t")
    return False


def first_document(text: str):
    """The first document of the text, as the library reads it."""
    return next(iter(yaml.safe_load_all(text)), None)


def verdict(text: str) -> str:
    """``"leak"``, ``"agree"``, ``"withheld"``, ``"no_parse"`` or ``"skip"`` for one whole text."""
    if not opens_metadata(text):
        return "skip"  # the text does not open with a metadata block
    if marked_excluded(text):
        return "withheld"
    try:
        document = first_document(text)
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
    # A no-break space is no space to a full parser, so the first colon ends no key.
    # The wider random hunt of the sixth review found this one.
    "list:\xa0: \n  - -privacy: private",
    "privacy\xa0: private",
    "meta:\u3000x:\n  privacy: private",
    # A value that is one JSON object or list is read with a JSON parser.
    'meta: {"privacy":"private"}',
    'meta: {"a":{"sensitive":true},"b":[1,2]}',
    'meta: [{"do_not_remember":"yes"}]',
    'outcome_recording: {"priv\\u0061cy":"team"}',
    'meta: {"privacy":["public","private"]}',
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
    'title: A note\noutcome_recording: {"request_sha256":"ab12","status":"confirmed","version":1}',
    'title: A note\nmeta: {"a": [1, 2], "b": null, "privacy": "public", "sensitive": false}',
]
# Whole texts that a full parser reads as marked. The marker depends on the opening
# line, the closing line or a line separator.
MARKED_TEXTS = [
    "--- # note\x85privacy: private\n---\nThe body.\n",
    "---\x85privacy: private\x85---\x85The body.\n",
    "--- privacy: private --- The body.\n",
    "--- privacy: private --- The body.\n",
    "--- {privacy: private}\n---\nThe body.\n",
    # A comment line ends at the same characters. The random hunt found this one.
    "---\n# c\x85privacy: private\n---\nThe body.\n",
    "--- \n    # c meta: {\"priv\\u0061cy\":\"team\"}\n---\nThe body.\n",
    "--- !!map\nprivacy: private\n---\nThe body.\n",
    "---\n!!map\nprivacy: private\n---\nThe body.\n",
    "---\n&a\nprivacy: private\n---\nThe body.\n",
    "﻿---\nprivacy: private\n---\nThe body.\n",
    "\n\n---\nprivacy: private\n---\nThe body.\n",
    "---\r\nprivacy: private\r\n---\r\nThe body.\r\n",
    "---\rprivacy: private\r---\rThe body.\r",
    "---\ntitle: x\n ---\nprivacy: private\n---\nThe body.\n",
    "---\ntitle:\n  ----\nprivacy: private\n---\nThe body.\n",
    "--- \nprivacy: private\n...\nThe body.\n",
]
# Whole texts with no marker. A rule line and words are ordinary writing.
ORDINARY_TEXTS = [
    "--- # a comment\ntitle: A note\n---\nThe body.\n",
    "---\r\ntitle: A note\r\ntags: [a, b]\r\n---\r\nThe body.\r\n",
    "﻿---\ntitle: A note\n---\nThe body.\n",
    "---\ntitle: A note\n...\nThe body.\n",
    "---\n[My project notes](https://example.org)\n---\nPlease remember the violet meeting.\n",
    "---\n**Note:** the desk is upstairs\n---\nMore words.\n",
    "---\n> a quoted line\n---\nMore words.\n",
    "---\nA line of words.\n---\nMore words.\n",
    "---\n---\nprivacy: private\n---\nThe second block is the body.\n",
]
OPENINGS = ["---\n"] * 6 + ["--- \n", "--- # note\n", "---\r\n", "---\r", "---\x85", "--- ", "--- ",
                           "﻿---\n", "\n\n---\n", "--- # c\x85", "--- # c ", "---\t\n", "--- >\n",
                           "--- |\n", "--- !!map\n", "--- &a\n", "--- {", "--- [", "--- \n# c\n", "---\n\n"]
CLOSINGS = ["\n---\n"] * 6 + ["\n...\n", "\n--- \n", "\n---\r\n", "\n--- # c\n", "\n", "\n ---\n", "\n---x\n",
                             "\n----\n", "\x85---\x85", " --- ", "\n---", "}\n---\n", "]\n---\n"]
TAILS = ["\nThe body.\n"] * 4 + ["privacy: private\n---\nThe body.\n", "\nprivacy: private\n",
                                 "  privacy: private\n---\n", ""]
TOKENS = ["&a ", "*a", "*a : ", "!!str ", "!!map ", "!x ", '"', "'", "\\u0061", "\\x70", "\\\n", "\n", "\n  ", "\n    ",
          "\n- ", "\n  - ", ": ", ":", " : ", "{", "}", "[", "]", ",", ", ", "? ", "\n? ", "\n: ", "|", ">", "|-", ">+",
          "|2", "#", " #", " # c\n", "<<: ", "<<: *a\n", "privacy", "private", "public", "do_not_remember", "true",
          "false", "sensitive", "yes", "no", "null", "~", " ", "  ", "\t", "\r\n", "\r", "-", "- ", "--", "%YAML 1.1\n",
          "privacy: private", "privacy: public", "\nprivacy: private", "\n  privacy: private", "{privacy: private}",
          "[privacy: private]", "a: ", "key: ", "\n\n", "''", '\\"', "\\", "@", "`", "!", "&", "*", "=", "\nprivacy:\n",
          "memory_policy: exclude", "sensitivity: high", "0", "1", "y", "\xa0", "\u2028", "\x85", "\ufeff",
          "\u2029", "\x0b", "\x0c", "\n---\n", "\n...\n", "---", "...", "\u3000", "\u2003", ":\xa0",
          "\xa0: ", "\n  - -", "- -", '{"privacy":"private"}', '{"a":1}', '":"', '","', '"privacy":',
          '"sensitive":true', "\\u0070", '{"', '"}', "null", "true,"]


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

    def test_the_oracle_calls_each_marked_text_marked(self):
        for text in MARKED_TEXTS:
            with self.subTest(text=text):
                self.assertTrue(opens_metadata(text))
                self.assertTrue(must_be_private(first_document(text)))

    def test_each_marked_text_keeps_the_note_private(self):
        for text in MARKED_TEXTS:
            with self.subTest(text=text):
                self.assertTrue(marked_excluded(text))

    def test_each_ordinary_text_is_shared(self):
        for text in ORDINARY_TEXTS:
            with self.subTest(text=text):
                self.assertFalse(marked_excluded(text))


@unittest.skipIf(yaml is None, "the YAML library is not installed")
class ChangedAtRandom(unittest.TestCase):
    ROUNDS = 12000

    def hunt(self, seed: int) -> None:
        rng = random.Random(seed)
        pool = MARKED + ORDINARY
        counts = {"leak": 0, "agree": 0, "withheld": 0, "no_parse": 0, "skip": 0}
        for _ in range(self.ROUNDS):
            block = changed(rng, rng.choice(pool))
            # Two texts in three keep the plain lines around the block. The third gets an
            # opening line, a closing line and a tail of its own, and one more change.
            if rng.random() < 0.66:
                text = note(block)
            else:
                text = rng.choice(OPENINGS) + block + rng.choice(CLOSINGS) + rng.choice(TAILS)
                if rng.random() < 0.3:
                    text = changed(rng, text)
            found = verdict(text)
            counts[found] += 1
            if found == "leak":
                self.fail(f"The reader shares a note that a full parser reads as marked:\n{text!r}\n"
                          f"parsed: {first_document(text)!r}")
            if found == "agree" and text == note(block) and len(pool) < 3000 and rng.random() < 0.05:
                pool.append(block)
        # The hunt means nothing when most texts are withheld or cannot be parsed.
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
