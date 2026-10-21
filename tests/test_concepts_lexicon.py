"""The concept lexicon keeps its own rules: shape, spelling, tokens, size and coverage.

Every rule that a machine can check is checked here. Three rules need a human:
that each entry is specific evidence of its concept, that polysemous words sit in
their dominant sense, and that no entry is a proper noun.
"""
from pathlib import Path
import sys
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knowledgeos import concepts, search  # noqa: E402

MIN_CLUSTERS, MAX_CLUSTERS = 200, 350
MIN_ENTRIES, MAX_ENTRIES = 4, 40
MAX_FILE_BYTES = 150 * 1000
MIN_SCRIPT_SHARE = 0.60
# Empty words: a match on one of these says nothing about the concept.
GENERIC_WORDS = frozenset("""
thing stuff make get take go put good bad new old time day way use like want need help
people person place work do see look say tell ask give keep let try come know think feel
really lot much many other same next last first
""".split())


def _clusters():
    return concepts.CLUSTERS


def _entries(clusters):
    for index, cluster in enumerate(clusters):
        for entry in cluster:
            yield index, cluster, entry


def _label(index, cluster):
    return f"cluster {index} ({cluster[0] if cluster else 'empty'})"


def _scaffolding():
    """The words `_context_query` drops from a task description.

    A later change may name the set at module level; use it if it exists. Until then it
    is a literal inside the function, so read it back from the compiled constants.
    """
    for name in ("_CONTEXT_SCAFFOLDING", "_SCAFFOLDING", "_CONTEXT_STOP_WORDS"):
        named = getattr(search, name, None)
        if named:
            return frozenset(named) | frozenset(search._QUESTION_STOP_WORDS)
    found = set(search._QUESTION_STOP_WORDS)
    for const in search._context_query.__code__.co_consts:
        if isinstance(const, frozenset) and const and all(isinstance(x, str) for x in const):
            found |= const
    return frozenset(found)


def problems_shape(clusters):
    out = []
    if not isinstance(clusters, tuple):
        out.append("CLUSTERS is not a tuple")
    for index, cluster in enumerate(clusters):
        if not isinstance(cluster, tuple):
            out.append(f"cluster {index} is not a tuple")
            continue
        for entry in cluster:
            if not isinstance(entry, str):
                out.append(f"{_label(index, cluster)}: {entry!r} is not a str")
    return out


def problems_spelling(clusters):
    out = []
    for index, cluster, entry in _entries(clusters):
        if not isinstance(entry, str):
            continue
        # casefold turns ß into ss; the lexicon keeps ß as written and lists the ss form beside it.
        if entry != entry.lower() or entry.casefold() != entry.replace("ß", "ss"):
            out.append(f"{_label(index, cluster)}: {entry!r} is not lowercase/casefolded")
        if unicodedata.normalize("NFC", entry) != entry:
            out.append(f"{_label(index, cluster)}: {entry!r} is not NFC")
        if entry != entry.strip() or "  " in entry or not entry:
            out.append(f"{_label(index, cluster)}: {entry!r} has stray or empty whitespace")
    return out


def problems_characters(clusters):
    """Letters and marks only, with one plain space inside a phrase: no hyphen, apostrophe, digit or underscore."""
    out = []
    for index, cluster, entry in _entries(clusters):
        for ch in entry:
            if ch == " ":
                continue
            if unicodedata.category(ch)[0] not in {"L", "M"}:
                out.append(f"{_label(index, cluster)}: {entry!r} holds {ch!r} ({unicodedata.name(ch, '?')})")
                break
    return out


def problems_tokens(clusters):
    out = []
    for index, cluster, entry in _entries(clusters):
        tokens = search._tokens(entry)
        if " ".join(tokens) != entry:
            out.append(f"{_label(index, cluster)}: {entry!r} becomes {tokens!r} in _tokens()")
    return out


def problems_phrase_length(clusters):
    return [f"{_label(i, c)}: {e!r} has more than two words"
            for i, c, e in _entries(clusters) if len(e.split()) > 2]


def problems_stop_words(clusters):
    blocked = _scaffolding()
    out = []
    for index, cluster, entry in _entries(clusters):
        for token in search._tokens(entry):
            if token.lower() in blocked:
                out.append(f"{_label(index, cluster)}: {entry!r} holds the stop word {token!r}")
    return out


def problems_generic_words(clusters):
    out = []
    for index, cluster, entry in _entries(clusters):
        for token in search._tokens(entry):
            if token.lower() in GENERIC_WORDS:
                out.append(f"{_label(index, cluster)}: {entry!r} holds the generic word {token!r}")
    return out


def problems_cluster_size(clusters):
    return [f"{_label(i, c)}: {len(c)} entries, want {MIN_ENTRIES} to {MAX_ENTRIES}"
            for i, c in enumerate(clusters) if not MIN_ENTRIES <= len(c) <= MAX_ENTRIES]


def problems_duplicates(clusters):
    out = []
    for index, cluster in enumerate(clusters):
        seen = set()
        for entry in cluster:
            if entry in seen:
                out.append(f"{_label(index, cluster)}: {entry!r} appears twice")
            seen.add(entry)
    return out


def problems_reuse(clusters):
    homes = {}
    for index, cluster in enumerate(clusters):
        for entry in set(cluster):
            homes.setdefault(entry, []).append(index)
    return [f"{entry!r} is in {len(where)} clusters {where}" for entry, where in homes.items() if len(where) > 2]


def _has(entry, ranges):
    return any(lo <= ord(ch) <= hi for ch in entry for lo, hi in ranges)


SCRIPTS = {
    "Devanagari": ((0x0900, 0x097F),),
    "kana": ((0x3040, 0x30FF),),
    "kanji/hanzi": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF)),
}


def script_shares(clusters):
    total = len(clusters) or 1
    return {name: sum(1 for c in clusters if any(_has(e, ranges) for e in c)) / total
            for name, ranges in SCRIPTS.items()}


def problems_script_coverage(clusters):
    return [f"{name} appears in {share:.0%} of clusters, want at least {MIN_SCRIPT_SHARE:.0%}"
            for name, share in script_shares(clusters).items() if share < MIN_SCRIPT_SHARE]


def _report(problems):
    shown = "\n  ".join(problems[:15])
    more = f"\n  ... and {len(problems) - 15} more" if len(problems) > 15 else ""
    return f"{len(problems)} problem(s):\n  {shown}{more}"


class ConceptLexiconTests(unittest.TestCase):
    def check(self, function):
        problems = function(_clusters())
        self.assertEqual(problems, [], _report(problems))

    def test_shape_is_a_tuple_of_tuples_of_strings(self):
        self.check(problems_shape)

    def test_every_entry_is_lowercase_nfc(self):
        self.check(problems_spelling)

    def test_entries_hold_only_letters_marks_and_one_space(self):
        self.check(problems_characters)

    def test_entries_survive_the_search_tokenizer_unchanged(self):
        self.check(problems_tokens)

    def test_phrases_are_at_most_two_words(self):
        self.check(problems_phrase_length)

    def test_no_stop_word_or_scaffolding_word(self):
        self.assertTrue({"also", "just", "the", "about"} <= _scaffolding(), "scaffolding words not found in search.py")
        self.check(problems_stop_words)

    def test_no_generic_word(self):
        self.check(problems_generic_words)

    def test_cluster_sizes_are_four_to_forty(self):
        self.check(problems_cluster_size)

    def test_no_duplicate_inside_a_cluster(self):
        self.check(problems_duplicates)

    def test_no_entry_sits_in_more_than_two_clusters(self):
        self.check(problems_reuse)

    def test_cluster_count_is_in_range(self):
        count = len(_clusters())
        self.assertTrue(MIN_CLUSTERS <= count <= MAX_CLUSTERS, f"{count} clusters, want {MIN_CLUSTERS} to {MAX_CLUSTERS}")

    def test_file_stays_small(self):
        size = Path(concepts.__file__).stat().st_size
        self.assertLessEqual(size, MAX_FILE_BYTES, f"concepts.py is {size} bytes")

    def test_each_non_latin_script_reaches_sixty_percent_of_clusters(self):
        self.check(problems_script_coverage)


if __name__ == "__main__":
    unittest.main(verbosity=2)
