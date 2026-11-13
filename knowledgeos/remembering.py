"""Local remembering rules shared by storage, readers and derived output.

Metadata is authoritative exclusion input. Conservative content checks combine
third-person relationships with sensitive detail categories, including indirect
clinical statements. These finite checks are not a general semantic classifier.
Forgetting matches reviewed sources and normalized literal passages, including
copies, but cannot recognize arbitrary paraphrases.
"""
from __future__ import annotations

import contextlib
import builtins
import datetime
import functools
import hashlib
import hmac
import inspect
import json
import os
import re
import secrets
import stat
import sys
import threading
import types
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple, Union

from knowledgeos.data_ops import plain_vault_path
from knowledgeos.locking import file_lock
from knowledgeos.parser import split_frontmatter
from knowledgeos.textio import atomic_create_bytes, atomic_write_bytes

POLICY = "twinaatma-remembering-policy-v1"
UNAVAILABLE = "Remembering policy state is unavailable; no memory was released or saved."
EXCLUDED = "This content is excluded by the approved remembering policy."
UNREAD_BLOCK = ("This text opens with a metadata block in a form that is not read, so nothing was "
                "saved or looked up. If the block marks the text private, leave it out of memory. "
                "Otherwise send the words without the block.")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CREDENTIALS = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16})\b"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{12,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|\b(?:api[ _-]?key|access[ _-]?token|client[ _-]?secret|password|passwd|credential)"
    r"\s*[:=]\s*[\"']?[^\s\"',;]{4,}", re.I,
)
_THIRD_PARTY = re.compile(
    r"\b(?:third[ -]party|someone else's|their private)\b[^\n]{0,100}"
    r"\b(?:medical|diagnos\w*|bank account|financial|phone|email|address)\b"
    r"|\b[A-Z][a-z]+(?: [A-Z][a-z]+)?(?:'s|’s)\s+"
    r"(?:medical|diagnos\w*|bank account|private (?:phone|email|address|contact)|salary|debt)\b"
    r"|\b[A-Z][a-z]+(?: [A-Z][a-z]+)?\s+(?:has|was diagnosed with|is being treated for)\s+"
    r"(?:diabetes|cancer|HIV|depression|bipolar disorder|a medical condition)\b",
)
_RELATED_PERSON = re.compile(
    r"\b(?:he|she|they|him|her|his|their|theirs|someone|somebody|"
    r"third[ -]party|colleague|coworker|co-worker|co\s+worker|teammate|"
    r"neighbou?r|friend|spouse|partner|child|patient|client|customer|employee|"
    r"relative|cousin|sister|brother|mother|father|parent|family\s+member)s?\b", re.I,
)
_NAMED_PERSON = re.compile(
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:['’]s\b|\s+(?:has|is|was|takes|"
    r"underwent|receives|needs|attends|started|stopped|uses)\b)"
)
_SENSITIVE_DETAIL = re.compile(
    r"\b(?:biops\w*|malignan\w*|tumou?rs?|patholog\w*|chemotherap\w*|"
    r"radiotherap\w*|prenatal|psychiatr\w*|insulin|HIV|diabetes|cancer|"
    r"depression|bipolar(?:\s+disorder)?|mental\s+health|hospitali[sz]ed|"
    r"(?:clinical|medical)\s+(?:findings?|histor(?:y|ies)|records?|results?|"
    r"conditions?|diagnos\w*|treatments?|tests?|samples?|reports?|specimens?|care|details?)|"
    r"(?:test|scan|specimen)\s+(?:results?|findings?|reports?)|care\s+plan|"
    r"undergoing\s+(?:treatment|surgery)|"
    r"salary|debt|bank\s+account|net\s+worth|take[ -]home\s+pay|"
    r"(?:loan|account)\s+balance|routing\s+number|financial\s+(?:records?|details?)|"
    r"(?:private|personal)\s+(?:phone|email|address|contact|mobile)|"
    r"home\s+address|mobile\s+number)\b", re.I,
)


def _sensitive_third_party(text):
    normalized = unicodedata.normalize("NFKC", text)
    ignored = {ord(char): None for char in set(normalized) if unicodedata.category(char) == "Cf"}
    if ignored:
        normalized = normalized.translate(ignored)
    # Keep sentence/paragraph boundaries. A sensitive topic in another unrelated
    # paragraph must not make a normal collaboration statement private.
    for paragraph in re.split(r"(?<=[.!?])\s+|\n\s*\n", normalized):
        if _SENSITIVE_DETAIL.search(paragraph) and (
                _RELATED_PERSON.search(paragraph) or _NAMED_PERSON.search(paragraph)):
            return True
    return False


def _uncached_pattern_reason(text):
    if _CREDENTIALS.search(text):
        return "credential_pattern"
    if _THIRD_PARTY.search(text) or _sensitive_third_party(text):
        return "third_party_pattern"
    return None


_PATTERN_MISS = object()
_SENTENCE_PATTERN = r"(?<=[.!?])\s+|\n\s*\n"


def _function_builtins(function):
    namespace = getattr(function, "__builtins__", function.__globals__.get("__builtins__"))
    return vars(namespace) if type(namespace) is types.ModuleType else namespace


def _function_snapshot(function):
    return (function, function.__code__, function.__defaults__,
            tuple((function.__kwdefaults__ or {}).items()), function.__globals__,
            _function_builtins(function))


def _function_unchanged(function, snapshot):
    original, code, defaults, keywords, namespace, builtin_namespace = snapshot
    if (function is not original or function.__code__ is not code
            or function.__defaults__ is not defaults or function.__closure__ is not None
            or function.__globals__ is not namespace
            or _function_builtins(function) is not builtin_namespace):
        return False
    current = function.__kwdefaults__
    return ((current is None and not keywords) or
            (type(current) is dict and len(current) == len(keywords)
             and all(current.get(key) is value for key, value in keywords)))


def _fixed_pattern_bytes(roots, shared):
    seen = set(map(id, shared))

    def size(value):
        if id(value) in seen:
            return 0
        seen.add(id(value))
        total = sys.getsizeof(value)
        if type(value) in (tuple, list):
            total += sum(size(item) for item in value)
        elif type(value) is dict:
            total += sum(size(key) + size(item) for key, item in value.items())
        elif type(value) is types.SimpleNamespace:
            total += size(vars(value))
        elif type(value) is types.FunctionType:
            total += sum(size(item) for item in (value.__code__, value.__defaults__,
                         value.__kwdefaults__, value.__globals__, value.__closure__))
        elif type(value) is types.CodeType:
            total += sum(size(item) for item in (value.co_code, value.co_consts,
                         value.co_names, value.co_varnames, value.co_freevars,
                         value.co_cellvars, value.co_filename, value.co_name))
        elif type(value) is types.CellType:
            total += size(value.cell_contents)
        elif type(value) is types.BuiltinMethodType:
            total += size(value.__self__)
        return total

    return size(roots)


class _PatternResults:
    __slots__ = ("entries", "lock", "eligible", "evaluate", "fixed_bytes",
                 "key_bytes", "enabled", "sizeof", "hasher")
    capacity = 65536
    budget = 16 * 1024 * 1024

    def __init__(self, eligible, evaluate, fixed_bytes):
        self.entries = OrderedDict()
        self.lock = threading.Lock()
        self.eligible = eligible
        self.evaluate = evaluate
        self.fixed_bytes = fixed_bytes
        self.key_bytes = sys.getsizeof(bytes(32))
        self.sizeof = sys.getsizeof
        self.hasher = hashlib.sha256
        self.enabled = True

    def retained_bound(self):
        return self.sizeof(self.entries) + len(self.entries) * self.key_bytes + self.fixed_bytes

    def lookup(self, digest):
        with self.lock:
            if not self.enabled:
                return _PATTERN_MISS
            result = self.entries.get(digest, _PATTERN_MISS)
            if result is not _PATTERN_MISS:
                self.entries.move_to_end(digest)
            return result

    def publish(self, digest, result):
        with self.lock:
            if not self.enabled:
                return
            try:
                if digest in self.entries:
                    self.entries.move_to_end(digest)
                else:
                    if len(self.entries) == self.capacity:
                        self.entries.popitem(last=False)
                    self.entries[digest] = result
                # OrderedDict's actual size includes its dictionary high-water allocation.
                if self.retained_bound() > self.budget:
                    self.entries.clear()
                    self.enabled = False
            except (MemoryError, OverflowError):
                self.entries.clear()
                self.enabled = False
                raise


def _make_pattern_results():
    if sys.implementation.name != "cpython":
        return None
    fingerprints = {
        (3, 9): ("3ee0bb58a1a65d49c5e778e295c62fb02fa3e97dfb49e591bceebefff12caceb",
                 "3bd8063ae7cd90aaf6e2a64043d61a6f8b40fc5e035ca93c67e213c5dd58e4b2", "_cache"),
        (3, 13): ("6e60a0cda23f660746d96a7703a7085d70a567ccf9b21370b7164d7454fb2496",
                  "1c0b8142dfcfb28f5eb9d395e6988eee845077e0edd369e440ce18cc2e159258", "_cache2"),
    }
    expected = fingerprints.get(sys.version_info[:2])
    if expected is None:
        return None
    split, compiler = getattr(re, "split", None), getattr(re, "_compile", None)
    for function, fingerprint in zip((split, compiler), expected[:2]):
        if type(function) is not types.FunctionType or function.__closure__ is not None:
            return None
        code = function.__code__
        shape = (code.co_code, code.co_names, code.co_consts, code.co_argcount,
                 code.co_kwonlyargcount, code.co_flags)
        if hashlib.sha256(repr(shape).encode()).hexdigest() != fingerprint:
            return None
    if (split.__globals__ is not vars(re) or compiler.__globals__ is not vars(re)
            or _function_builtins(split) is not vars(builtins)
            or _function_builtins(compiler) is not vars(builtins)):
        return None
    if expected[2] == "_cache2":
        defaults = split.__kwdefaults__
        if (split.__defaults__ is not None or type(defaults) is not dict
                or set(defaults) != {"maxsplit", "flags"}
                or any(value is not re._zero_sentinel for value in defaults.values())):
            return None
        zero_type = type(re._zero_sentinel)
        if zero_type.__bases__ != (int,) or int(re._zero_sentinel) != 0:
            return None
        zero_attributes = tuple(vars(zero_type).items())
        zero_mro = zero_type.__mro__
    else:
        if split.__defaults__ != (0, 0) or split.__kwdefaults__ is not None:
            return None
        zero_type, zero_attributes, zero_mro = None, (), None
    regex_flag = re.RegexFlag
    flag_meta = type(regex_flag)
    instancecheck = flag_meta.__instancecheck__
    if instancecheck is not type.__instancecheck__:
        return None
    splitter = compiler(_SENTENCE_PATTERN, 0)
    pattern_type = type(_CREDENTIALS)
    patterns = (_CREDENTIALS, _THIRD_PARTY, _SENSITIVE_DETAIL, _RELATED_PERSON, _NAMED_PERSON)
    if (type(splitter) is not pattern_type or splitter.pattern != _SENTENCE_PATTERN
            or splitter.flags != 32 or any(type(pattern) is not pattern_type for pattern in patterns)):
        return None
    unicode_module, regex_module = unicodedata, re
    normalize, category = unicodedata.normalize, unicodedata.category
    if (type(normalize) is not types.BuiltinFunctionType
            or type(category) is not types.BuiltinFunctionType
            or type(hashlib.sha256) is not types.BuiltinFunctionType):
        return None
    for function in (_uncached_pattern_reason, _sensitive_third_party):
        if (type(function) is not types.FunctionType or function.__closure__ is not None
                or function.__defaults__ is not None or function.__kwdefaults__ is not None):
            return None
    if not set(_uncached_pattern_reason.__code__.co_names) <= {
            "_CREDENTIALS", "search", "_THIRD_PARTY", "_sensitive_third_party"}:
        return None
    pure_snapshot = _function_snapshot(_uncached_pattern_reason)
    sensitive_snapshot = _function_snapshot(_sensitive_third_party)
    split_snapshot, compiler_snapshot = _function_snapshot(split), _function_snapshot(compiler)
    allowed = {"unicodedata", "normalize", "join", "re", "split", "search",
               "_SENSITIVE_DETAIL", "_RELATED_PERSON", "_NAMED_PERSON", "category"}
    allowed |= {"set", "ord", "translate"}
    code_stack = [_sensitive_third_party.__code__]
    while code_stack:
        code = code_stack.pop()
        if code.co_freevars or not set(code.co_names) <= allowed:
            return None
        code_stack.extend(item for item in code.co_consts if type(item) is types.CodeType)
    frozen_globals = {
        "__builtins__": {"set": set, "ord": ord},
        "unicodedata": types.SimpleNamespace(normalize=normalize, category=category),
        "re": types.SimpleNamespace(split=lambda pattern, value, operation=splitter.split: operation(value)),
        "_SENSITIVE_DETAIL": _SENSITIVE_DETAIL, "_RELATED_PERSON": _RELATED_PERSON,
        "_NAMED_PERSON": _NAMED_PERSON,
    }
    canonical_sensitive = types.FunctionType(_sensitive_third_party.__code__, frozen_globals)
    canonical_globals = {"__builtins__": {}, "_CREDENTIALS": _CREDENTIALS,
                         "_THIRD_PARTY": _THIRD_PARTY, "_sensitive_third_party": canonical_sensitive}
    canonical = types.FunctionType(_uncached_pattern_reason.__code__, canonical_globals)
    effective_cache_name = expected[2]
    cache_key = (str, _SENTENCE_PATTERN, 0)
    core_isinstance, core_type = builtins.isinstance, builtins.type
    core_set, core_ord = set, ord

    def eligible():
        if (globals().get("re") is not regex_module or globals().get("unicodedata") is not unicode_module
                or not _function_unchanged(globals().get("_uncached_pattern_reason"), pure_snapshot)
                or not _function_unchanged(globals().get("_sensitive_third_party"), sensitive_snapshot)
                or not _function_unchanged(getattr(regex_module, "split", None), split_snapshot)
                or not _function_unchanged(getattr(regex_module, "_compile", None), compiler_snapshot)
                or getattr(unicode_module, "normalize", None) is not normalize
                or getattr(unicode_module, "category", None) is not category
                or (globals().get("_CREDENTIALS") is not patterns[0]
                    or globals().get("_THIRD_PARTY") is not patterns[1]
                    or globals().get("_SENSITIVE_DETAIL") is not patterns[2]
                    or globals().get("_RELATED_PERSON") is not patterns[3]
                    or globals().get("_NAMED_PERSON") is not patterns[4])
                or getattr(regex_module, "RegexFlag", None) is not regex_flag
                or flag_meta.__instancecheck__ is not instancecheck):
            return False
        if (pure_snapshot[4].get("set", pure_snapshot[5].get("set")) is not core_set
                or pure_snapshot[4].get("ord", pure_snapshot[5].get("ord")) is not core_ord):
            return False
        namespace = compiler_snapshot[4]
        if (namespace.get("isinstance", compiler_snapshot[5].get("isinstance")) is not core_isinstance
                or namespace.get("type", compiler_snapshot[5].get("type")) is not core_type):
            return False
        if zero_type is not None:
            attributes = vars(zero_type)
            if (zero_type.__mro__ is not zero_mro or len(attributes) != len(zero_attributes)
                    or any(attributes.get(key) is not value for key, value in zero_attributes)):
                return False
        provider_cache = getattr(regex_module, effective_cache_name, None)
        return type(provider_cache) is dict and provider_cache.get(cache_key) is splitter

    if not eligible():
        return None
    fixed_roots = (canonical, eligible, pure_snapshot, sensitive_snapshot, split_snapshot,
                   compiler_snapshot, patterns, zero_attributes, _PatternResults.__dict__)
    measured_fixed = _fixed_pattern_bytes(fixed_roots, (globals(), vars(re), vars(builtins)))
    fixed_reserve = 1024 * 1024
    if (measured_fixed + sys.getsizeof(threading.Lock()) + sys.getsizeof(_PatternResults)
            > fixed_reserve or sys.getsizeof(bytes(32)) < 32):
        return None
    return _PatternResults(eligible, canonical, fixed_reserve)


try:
    _PATTERN_RESULTS = _make_pattern_results()
except (MemoryError, OverflowError):
    _PATTERN_RESULTS = None


def _pattern_reason(text):
    cache = _PATTERN_RESULTS
    try:
        eligible = cache is not None and cache.enabled and cache.eligible()
    except (MemoryError, OverflowError):
        eligible = False
    if not eligible:
        return _uncached_pattern_reason(text)
    try:
        digest = cache.hasher(b"twinaatma-pure-pattern-v1\0")
        for offset in range(0, len(text), 16384):
            digest.update(text[offset:offset + 16384].encode("utf-8", "surrogatepass"))
        key = digest.digest()
        result = cache.lookup(key)
    except (MemoryError, OverflowError):
        return _uncached_pattern_reason(text)
    if result is not _PATTERN_MISS:
        try:
            eligible = cache.eligible()
        except (MemoryError, OverflowError):
            eligible = False
        return result if eligible else _uncached_pattern_reason(text)
    # Classification exceptions propagate. Only bookkeeping may bypass reuse.
    result = cache.evaluate(text)
    try:
        if cache.eligible():
            cache.publish(key, result)
            if cache.eligible():
                return result
    except (MemoryError, OverflowError):
        pass
    return _uncached_pattern_reason(text)


# The privacy rule fails closed, twice.
#
# 1. A note that carries a privacy key is private unless every value is a word from the
#    short list that means "not private".
# 2. A note is shared only when its whole metadata block is understood. The reader below
#    takes a small grammar apart: plain `key: value` lines, lists, nested blocks and text
#    values. In a block of that grammar every key is known exactly, at every depth. A
#    block in any other form (a `{...}` mapping, a tag, an anchor, a `? key`, an escaped
#    key) is not searched for a privacy key. It keeps the note private.
#
# Five reviews found a spelling of a privacy key that an earlier reader did not see. Each
# earlier reader looked for the key in text that it did not parse. This one refuses the
# text it does not parse. `tests/test_privacy_yaml_oracle.py` changes blocks at random and
# compares the answer with a full YAML parser. A sixth review found the same fault one
# level up, in the opening line of the block. That line is now read by the same rule, and
# the test changes it too.
_PRIVACY_KEYS = {"privacy", "memory_privacy", "sensitivity", "memory_policy"}
_FLAG_KEYS = {"sensitive", "third_party_sensitive", "do_not_remember"}
_OPEN_LABELS = {"", "ordinary", "public", "shared", "open", "normal", "none", "low",
                "false", "no", "off", "0", "null", "~"}
_FLAG_NOT_SET = {"", "false", "no", "off", "0", "null", "none", "~"}
_WIDE_BREAKS = "\r\n\x85\u2028\u2029"  # where a full parser ends a line
_BLOCK_START = re.compile(r"\A\ufeff?\s*---(?=[ \t" + _WIDE_BREAKS + r"]|\Z)")
_RULE_LINE = re.compile(r"[ \t]*---[ \t]*(?:#.*)?\Z")
_BLOCK_CLOSING = re.compile(r"(?:---|\.\.\.)(?:[ \t].*)?\Z")
_KEY_END = re.compile(r":(?=\s|\Z)")
_YAML_COMMENT = re.compile(r"(?:\A|\s)#.*\Z", re.S)
_DASH = re.compile(r"-(?:\s|\Z)")
_ODD_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85\u2028\u2029\ufeff]")
# A full parser knows two spaces: the space and the tab. Every other space character
# is an ordinary character to it, so `key:` followed by a no-break space is no key.
# Python calls these characters white space. The reader sees each one as `_`, which
# is an ordinary character here and a word break in a key name.
_ODD_SPACE = re.compile("[\xa0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_KEY_STARTS = frozenset("-?:,[]{}#&*!|>'\"%@`")
_TEXT = object()        # a text value: its words are not read, and it holds no key
_MANY_LINES = object()  # a value written over several lines


class _NotUnderstood(Exception):
    """The metadata block has a form this reader does not take apart."""


class _Mapping(list):
    """The ``(key, value)`` pairs of one mapping, in the order written."""


def _metadata_key(raw) -> str:
    """A key as it is compared: no quotes, no case; spaces, `-` and `_` are one `_`."""
    return "_".join(part for part in re.split(r"[\s\-_]+", str(raw).strip().strip("\"'").casefold()) if part)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _no_content(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _metadata_lines(text: str):
    """``(lines, plain)`` of the first metadata block, or ``None`` when the text has none.

    The block opens with `---` on the first line that holds anything. A full parser
    ends a line at more characters than a line feed, so the opening line is cut at any
    of them. Inside the block such a character is odd, and the block is not understood.
    ``plain`` is false when the opening line holds more than a comment: a full parser
    reads that as the start of the content (`--- {privacy: private}`).
    """
    opening = _BLOCK_START.match(text)
    if not opening:
        return None
    rest = text[opening.end():]
    cut = re.search("\r\n|[" + _WIDE_BREAKS + "]", rest)
    first, rest = (rest[:cut.start()], rest[cut.end():]) if cut else (rest, "")
    lines = re.split(r"\r\n|\r|\n", rest)
    for number, line in enumerate(lines):
        if _BLOCK_CLOSING.match(line):
            lines = lines[:number]
            break
    return lines, not first.strip() or first.strip().startswith("#")


def _starts_as_prose(first: str) -> bool:
    """True when the first line of a block cannot open a mapping.

    A rule line and words are ordinary writing, not metadata. No key separator stands
    on the line, and the line does not start a form that can hold a key on a later line
    (`{`, `?`, a tag, an anchor, a list). An alias, a text block and a closed bracket of
    plain words hold no key.
    """
    if _KEY_END.search(first):
        return False
    head = first[0]
    if head not in _KEY_STARTS or head in "*|>":
        return True
    if head == "[":
        close = first.find("]")
        return (close > 0 and not any(mark in first[1:close] for mark in ":{}[\"'")
                and not first[close + 1:].lstrip(" ").startswith(":"))
    return False


class _BlockReader:
    """Reads a block mapping line by line. A line outside the grammar raises."""

    def __init__(self, lines: list[str]):
        self.lines = lines
        self.at = 0

    def peek(self):
        """The next line that holds something, or ``None``."""
        while self.at < len(self.lines) and _no_content(self.lines[self.at]):
            self.at += 1
        return self.lines[self.at] if self.at < len(self.lines) else None

    def take_text_below(self, parent: int) -> bool:
        """Pass the lines of a text value of a key at column ``parent``.

        After a value has started as text, a deeper line is more of that text or an
        error to a full parser. It is never a key.
        """
        taken = False
        while self.at < len(self.lines):
            line = self.lines[self.at]
            if line.strip() and _indent(line) <= parent:
                break
            taken = taken or bool(line.strip())
            self.at += 1
        return taken

    def mapping(self, column: int, first: tuple | None = None) -> _Mapping:
        pairs = _Mapping()
        if first is not None:
            pairs.append((first[0], self.value(first[1], column)))
        while True:
            line = self.peek()
            if line is None or _indent(line) < column:
                return pairs
            if _indent(line) > column:
                raise _NotUnderstood("a line stands deeper than its neighbours")
            key, rest = _key_line(line[column:])
            self.at += 1
            pairs.append((key, self.value(rest, column)))

    def sequence(self, column: int) -> list:
        items: list = []
        while True:
            line = self.peek()
            if line is None or _indent(line) != column or not _DASH.match(line[column:]):
                if line is not None and _indent(line) > column:
                    raise _NotUnderstood("a line stands deeper than the list it follows")
                return items
            content = line[column + 1:]
            lead = content[:len(content) - len(content.lstrip(" \t"))]
            if "\t" in lead:
                raise _NotUnderstood("a tab after a list dash")
            inner = column + 1 + len(lead)
            content = content.strip()
            self.at += 1
            if not content or content.startswith("#"):
                following = self.peek()
                if following is not None and _indent(following) > column:
                    raise _NotUnderstood("a list item that starts on the next line")
                items.append(None)
            elif re.match(r"[-?](?:\s|\Z)", content):
                raise _NotUnderstood("a list or a `?` key inside a list item")
            else:
                entry = _entry(content)
                items.append(self.mapping(inner, first=entry) if entry else self.value(content, column))

    def value(self, rest: str, parent: int):
        """The value of a key at column ``parent``; ``rest`` is the text after its colon."""
        rest = rest.strip()
        if not rest or rest.startswith("#"):
            line = self.peek()
            if line is None:
                return None
            depth = _indent(line)
            content = line[depth:]
            if depth >= parent and _DASH.match(content):
                return self.sequence(depth)
            if depth <= parent:
                return None
            if _entry(content):
                return self.mapping(depth)
            if content[0] in _KEY_STARTS:
                raise _NotUnderstood("a value on the next line that is not plain text")
            self.take_text_below(parent)
            return _MANY_LINES
        first = rest[0]
        if first in "&!" or re.match(r"[-?](?:\s|\Z)", rest):
            raise _NotUnderstood("a value with a tag, an anchor or a nested start")
        if first in "[{":
            items = _flow_value(rest)
            line = self.peek()
            if line is not None and _indent(line) > parent:
                raise _NotUnderstood("a `[` or `{` value over several lines")
            return items
        if first in "\"'":
            closed = _quoted(rest)
            more = self.take_text_below(parent)
            return _MANY_LINES if more or closed is None else closed
        if first in "|>":
            self.take_text_below(parent)
            return _TEXT
        more = self.take_text_below(parent)
        return _MANY_LINES if more else _YAML_COMMENT.sub("", rest).strip()


def _entry(content: str):
    """``(key, rest)`` when the content is a `key: rest` entry, ``None`` when it holds no key.

    Content that holds a key separator and is not a plain entry raises. It is never passed
    on as text: a full parser can read a key where this reader sees words.
    """
    first = content[:1]
    if first in "\"'":
        return None if _quoted(content) is not None else _key_line(content)
    if first in "[{|>":
        return None
    return _key_line(content) if _KEY_END.search(_YAML_COMMENT.sub("", content)) else None


def _key_line(content: str) -> tuple[str, str]:
    """``(key, rest)`` of a `key: rest` line. Any other line raises."""
    first = content[:1]
    if first in "\"'":
        end = content.find(first, 1)
        key = content[1:end]
        after = content[end + 1:].lstrip(" ")
        if end < 0 or "\\" in key or after[:1] == first or not _KEY_END.match(after):
            raise _NotUnderstood("a quoted key that is not plain")
        return key, after[1:]
    if not first or first in _KEY_STARTS:
        raise _NotUnderstood("a line that does not start with a plain key")
    found = _KEY_END.search(content)
    if not found:
        raise _NotUnderstood("a line with no key")
    key = content[:found.start()].rstrip()
    if not key or re.search(r"\s#", key) or key == "<<":
        raise _NotUnderstood("a key that is not plain")
    return key, content[found.end():]


def _quoted(rest: str):
    """The text of a quoted value that ends on its line, or ``None`` when it does not."""
    quote = rest[0]
    at = 1
    while at < len(rest):
        char = rest[at]
        if quote == '"' and char == "\\":
            at += 2
            continue
        if char == quote:
            if quote == "'" and rest[at + 1:at + 2] == "'":
                at += 2
                continue
            tail = rest[at + 1:]
            return None if tail.strip() and not re.match(r"\s+#", tail) else rest[1:at]
        at += 1
    return None


def _simple_list(rest: str):
    """The labels of `[a, "b", 'c']` on one line, or ``None`` when it is not that form."""
    at, items, size = 1, [], len(rest)
    while True:
        while at < size and rest[at] == " ":
            at += 1
        if at >= size:
            return None
        char = rest[at]
        if char == "]":
            tail = rest[at + 1:]
            return None if tail.strip() and not re.match(r"\s+#", tail) else items
        if char in "\"'":
            end = at + 1
            while end < size and rest[end] != char:
                end += 2 if (char == '"' and rest[end] == "\\") else 1
            if end >= size or (char == "'" and rest[end + 1:end + 2] == "'"):
                return None
            items.append(rest[at + 1:end])
            at = end + 1
        else:
            end = at
            while end < size and rest[end] not in ",]":
                end += 1
            label = rest[at:end].strip()
            if (not label or label[0] in "&*!|>%@`?#" or _DASH.match(label)
                    or _KEY_END.search(label) or re.search(r"\s#", label)
                    or any(mark in label for mark in "{}[\"'")):
                return None
            items.append(label)
            at = end
        while at < size and rest[at] == " ":
            at += 1
        if at < size and rest[at] == ",":
            at += 1
        elif at >= size or rest[at] != "]":
            return None


def _not_json(_name):
    raise ValueError("not a JSON value")


def _json_node(node):
    """A parsed JSON value in the shapes the block reader gives: pairs, lists, labels."""
    if isinstance(node, _Mapping):
        return _Mapping((key, _json_node(value)) for key, value in node)
    if isinstance(node, list):
        return [_json_node(item) for item in node]
    return node


def _flow_value(rest: str):
    """A value that starts with `[` or `{`.

    A plain one-line list gives its labels. A value that is, whole, one JSON object or
    list is read by the JSON parser of the standard library, which reads an escaped key
    too; the toolkit writes the record of an outcome in that form. A bracket that
    closes on its line with no colon and no quote inside holds no key that has a value,
    so it is text. Any other form raises.
    """
    if rest[0] == "[":
        items = _simple_list(rest)
        if items is not None:
            return items
    try:
        return _json_node(json.loads(rest, object_pairs_hook=_Mapping, parse_int=str, parse_float=str,
                                     parse_constant=_not_json))
    except (ValueError, RecursionError):
        pass
    depth = 0
    for at, char in enumerate(rest):
        if char in "\"'":
            break
        depth += char in "[{"
        depth -= char in "]}"
        if depth == 0:
            if ":" in rest[:at + 1] or rest[at + 1:].lstrip(" ").startswith(":"):
                break
            return _TEXT
    raise _NotUnderstood("a `[` or `{` value that is not a plain list")


def _label_is_open(label) -> bool:
    if label is None or label is False:
        return True
    return isinstance(label, str) and label.isascii() and label.strip().lower() in _OPEN_LABELS


def _flag_is_set(value) -> bool:
    """True unless a privacy flag clearly says no. Text nobody can read as a no is a yes."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return not (value.isascii() and value.strip().lower() in _FLAG_NOT_SET)
    return True


def _every_label(value, test) -> bool:
    labels = value if isinstance(value, (list, tuple, set)) and not isinstance(value, _Mapping) else [value]
    return all((label is None or isinstance(label, (str, bool))) and test(label) for label in labels)


def _pair_excludes(raw_key, value) -> bool:
    key = _metadata_key(raw_key)
    if key in _PRIVACY_KEYS:
        return not _every_label(value, _label_is_open)
    if key in _FLAG_KEYS:
        return not _every_label(value, lambda label: not _flag_is_set(label))
    return False


def _tree_excludes(node) -> bool:
    """True when a key at any depth says "do not remember"."""
    if isinstance(node, _Mapping):
        return any(_pair_excludes(key, value) or _tree_excludes(value) for key, value in node)
    if isinstance(node, list):
        return any(_tree_excludes(item) for item in node)
    return False


def _plain_scalar(value):
    """A value as one label: no trailing comment, no quotes."""
    if not isinstance(value, str):
        return value
    return _YAML_COMMENT.sub("", value).strip().strip("\"'").strip()


def _pairs_exclude(pairs) -> bool:
    """The question for a mapping that is already parsed (a tool argument, a result row)."""
    for raw_key, value in pairs:
        if isinstance(value, str):
            value = _plain_scalar(value)
            if value.startswith("[") and value.endswith("]"):
                value = [_plain_scalar(part) for part in value[1:-1].split(",")]
        elif isinstance(value, dict):
            value = _Mapping(value.items())
        elif isinstance(value, (list, tuple, set)):
            value = [_plain_scalar(item) if isinstance(item, str) else item for item in value]
        elif value is not None and not isinstance(value, bool):
            value = str(value)
        if _pair_excludes(raw_key, value):
            return True
    return False


def _flat_reading_excludes(lines: list[str]) -> bool:
    """True when the toolkit's own flat parser reads a privacy key that does not share.

    That parser makes the `frontmatter` mapping the tools return, and it reads each
    `key: value` line alone. A note it would call private is private here too, even
    where the line stands inside a text value. So the two readings never disagree.
    """
    from knowledgeos.parser import parse_frontmatter_block

    return _pairs_exclude(parse_frontmatter_block("\n".join(lines)).items())


def metadata_reason(text: str = ""):
    """Why the text's own metadata keeps it private, or ``None`` when it does not.

    ``"marked"``: a privacy key says so. ``"not_understood"``: the block has a form this
    reader does not take apart, so nobody can say that it holds no privacy key.
    """
    block = _metadata_lines(str(text or ""))
    if block is None:
        return None
    lines, plain = block
    if _flat_reading_excludes(lines):
        return "marked"
    if not plain:
        return "not_understood"
    # Before the comment lines are set aside: a full parser ends a comment at a
    # character that is odd here, and reads a key after it.
    if _ODD_CONTROL.search("\n".join(lines)):
        return "not_understood"
    lines = [_ODD_SPACE.sub("_", line) for line in lines]
    content = [line for line in lines if not _no_content(line)]
    if not content:
        return None
    if any("\t" in line[:len(line) - len(line.lstrip(" \t"))] for line in lines):
        return "not_understood"
    if _starts_as_prose(content[0].strip()):
        return None
    reader = _BlockReader(lines)
    try:
        start = reader.peek()
        if _DASH.match(start.strip()):
            raise _NotUnderstood("a list where the keys should be")
        pairs = reader.mapping(_indent(start))
        if reader.peek() is not None:
            raise _NotUnderstood("a line that stands outside the block")
    except _NotUnderstood:
        return "not_understood"
    return "marked" if _tree_excludes(pairs) else None


def marked_excluded(text: str = "", metadata=None) -> bool:
    """True when the text's own metadata, or the given mapping, keeps it private."""
    if isinstance(metadata, dict) and _pairs_exclude(metadata.items()):
        return True
    return metadata_reason(text) is not None


def metadata_excludes(metadata) -> bool:
    """The same question for a mapping alone, with no text to read."""
    return isinstance(metadata, dict) and _pairs_exclude(metadata.items())


def holds_marked_block(text: str = "") -> bool:
    """True when a metadata block that says "do not remember" opens on any line.

    For a text that comes in. A note that is pasted after a line of introduction, in a
    code fence or with a margin still holds its own block between two `---` lines. Only
    a block that is marked counts here: two rule lines around other words are ordinary
    writing. A note that is typed again in another shape is not recognised; the policy
    does not judge meaning.
    """
    lines = re.split("\r\n|[" + _WIDE_BREAKS + "]", str(text or ""))
    rules = [number for number, line in enumerate(lines) if _RULE_LINE.match(line)]
    for start, end in zip(rules, rules[1:]):
        margin = lines[start][:len(lines[start]) - len(lines[start].lstrip(" \t"))]
        block = [line[len(margin):] if line.startswith(margin) else line for line in lines[start:end + 1]]
        if metadata_reason("\n".join(block)) == "marked":
            return True
    return False


def metadata_text(value) -> str:
    """One line of text as a metadata value that this reader and a full parser read as text.

    A writer of note metadata passes a title through here. Text that a parser would
    read as something else (a list, a tag, an anchor, a key such as `Decision: use
    this`, a comment after ` #`) is put in quotes, so the note that is written can be
    read back here and in a note tool. A character that metadata cannot hold (a control
    character, a byte order mark) becomes a space.
    """
    text = " ".join(_ODD_CONTROL.sub(" ", str(value or "")).split())
    if not text:
        return ""
    try:
        understood = _BlockReader([]).value(text, 0)
    except _NotUnderstood:
        understood = None
    # `<<` and `=` are words of their own to a full parser.
    if (understood == text and text[0] not in _KEY_STARTS and not _KEY_END.search(text)
            and text not in ("<<", "=")):
        return text
    if '"' not in text and "\\" not in text:
        return '"' + text + '"'
    return "'" + text.replace("'", "''") + "'"


class PolicyError(ValueError):
    """A refusal whose message never includes the excluded input or unsafe path."""


class _SourceSignature(NamedTuple):
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class _AdmittedSource:
    text: str
    signature: _SourceSignature


@dataclass(frozen=True)
class _ExcludedSource:
    pass


@dataclass(frozen=True)
class _UnavailableSource:
    pass


_SourceObservation = Union[_AdmittedSource, _ExcludedSource, _UnavailableSource]


def refusal(error: PolicyError) -> dict:
    return {"ok": False, "error": str(error), "policy": POLICY}


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate policy field")
        out[key] = value
    return out


def _relative(value):
    return (isinstance(value, str) and value and "\\" not in value
            and not PurePosixPath(value).is_absolute() and ":" not in value
            and all(part not in {"", ".", ".."} for part in value.split("/"))
            and value.endswith(".md"))


def _digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _words(text):
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def _passages(text):
    _, body = split_frontmatter(text)
    body = body.split("\n## Links", 1)[0]
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "<!--", "_Captured via")):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        for sentence in re.split(r"[.!?](?:\s|$)", line):
            words = _words(sentence)
            if len(words) >= 2:
                yield words


def _fingerprints(text):
    found = set()
    passages = list(_passages(text))
    if not passages:
        frontmatter, body = split_frontmatter(text)
        title = frontmatter.get("title") or next((line[2:] for line in body.splitlines() if line.startswith("# ")), "")
        words = _words(str(title))
        if len(words) >= 2:
            passages.append(words)
    for words in passages:
        width = min(8, len(words))
        for offset in range(len(words) - width + 1):
            digest = hashlib.sha256(" ".join(words[offset:offset + width]).encode()).hexdigest()
            found.add((width, digest))
    return [{"words": width, "sha256": digest} for width, digest in sorted(found)]


class RememberingPolicy:
    def __init__(self, vault):
        self.vault = Path(vault).absolute()
        self.path = self.vault / ".knowledgeos/remembering-policy.json"
        self.state = self._load()

    def _checked(self):
        try:
            plain_vault_path(self.vault, self.path)
            folder = self.path.parent
            if folder.exists() and not folder.is_dir():
                raise ValueError("state parent is not a directory")
            if self.path.exists() and not self.path.is_file():
                raise ValueError("policy state is not a file")
            return self.path
        except (OSError, ValueError):
            raise PolicyError(UNAVAILABLE) from None

    def _state(self, state):
        try:
            if (not isinstance(state, dict) or set(state) != {"version", "forgotten", "superseded"}
                    or type(state["version"]) is not int or state["version"] != 1):
                raise ValueError("policy schema")
            for collection in ("forgotten", "superseded"):
                if not isinstance(state[collection], dict):
                    raise ValueError("policy collection")
                for path, record in state[collection].items():
                    if not _relative(path) or not isinstance(record, dict):
                        raise ValueError("policy source")
                    required = {"sha256", "recorded_at", "fingerprints"} if collection == "forgotten" else {
                        "sha256", "recorded_at", "replacement", "replacement_sha256"}
                    if set(record) != required or not _digest(record["sha256"]):
                        raise ValueError("policy record")
                    when = record["recorded_at"]
                    if not isinstance(when, str) or datetime.datetime.fromisoformat(when).tzinfo is None:
                        raise ValueError("policy date")
                    if collection == "forgotten":
                        if not isinstance(record["fingerprints"], list):
                            raise ValueError("policy fingerprints")
                        for fp in record["fingerprints"]:
                            if (not isinstance(fp, dict) or set(fp) != {"words", "sha256"}
                                    or type(fp["words"]) is not int or not 2 <= fp["words"] <= 8
                                    or not _digest(fp["sha256"])):
                                raise ValueError("policy fingerprint")
                    elif (not _relative(record["replacement"]) or path == record["replacement"]
                          or not _digest(record["replacement_sha256"])):
                        raise ValueError("policy replacement")
            return state
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise PolicyError(UNAVAILABLE) from None

    def _authority(self):
        from knowledgeos import gate

        home = gate._state_home().absolute()
        try:
            home.resolve().relative_to(self.vault.resolve())
        except ValueError:
            pass
        else:
            raise PolicyError(UNAVAILABLE)
        path = home / "vaults" / gate.vault_key(self.vault) / "remembering-policy.json"
        gate._binding_file(path)
        return path

    @staticmethod
    def _read_plain(path):
        from knowledgeos import gate

        expected = gate._binding_file(path)
        if expected is None:
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            actual = os.fstat(handle.fileno())
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)
                    or actual.st_nlink != 1):
                raise OSError("policy state changed while opening")
            return handle.read()

    def _key(self, *, create=False):
        from knowledgeos import gate

        override = os.environ.get("KNOWLEDGEOS_GATE_KEY")
        if override:
            return override.encode("utf-8")
        path = gate._key_path()
        raw = self._read_plain(path)
        if raw is None and create:
            path.parent.mkdir(parents=True, exist_ok=True)
            gate._binding_file(path)
            try:
                atomic_create_bytes(path, secrets.token_bytes(32).hex().encode("ascii"), mode=0o600)
            except FileExistsError:
                pass
            raw = self._read_plain(path)
        if raw is None:
            raise PolicyError(UNAVAILABLE)
        text = raw.decode("ascii").strip()
        if len(text) < 32:
            raise PolicyError(UNAVAILABLE)
        try:
            return bytes.fromhex(text)
        except ValueError:
            return text.encode("ascii")

    @staticmethod
    def _mac(key, envelope):
        body = json.dumps({k: v for k, v in envelope.items() if k != "mac"},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(key, b"twinaatma.remembering/v2\0" + body, hashlib.sha256).hexdigest()

    def _open(self, raw, authority):
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if (not isinstance(envelope, dict)
                or set(envelope) != {"version", "policy", "vault_key", "state", "previous_sha256", "mac"}
                or type(envelope["version"]) is not int or envelope["version"] != 2
                or envelope["policy"] != POLICY or envelope["vault_key"] != authority.parent.name
                or not _digest(envelope["mac"])
                or envelope["previous_sha256"] is not None and not _digest(envelope["previous_sha256"])
                or not hmac.compare_digest(envelope["mac"], self._mac(self._key(), envelope))):
            raise PolicyError(UNAVAILABLE)
        self._state(envelope["state"])
        return envelope

    def _load(self):
        try:
            return self._load_once()
        except PolicyError:
            # The mirror and authority are separate atomic publications. A reader
            # may overlap multiple legitimate commits; recheck under their locks.
            # Persistent tampering or missing signing state still refuses.
            try:
                with self._locks():
                    return self._load_once()
            except (OSError, ValueError, TypeError, KeyError, UnicodeError, TimeoutError):
                raise PolicyError(UNAVAILABLE) from None

    def _load_once(self):
        try:
            raw = self._read_plain(self._checked())
            authority = self._authority()
            authenticated = self._read_plain(authority)
            self._authority_bytes = authenticated
            self._mirror_pending = False
            if authenticated is not None:
                envelope = self._open(authenticated, authority)
                if raw != authenticated:
                    if raw is not None and hashlib.sha256(raw).hexdigest() != envelope["previous_sha256"]:
                        raise PolicyError(UNAVAILABLE)
                    self._mirror_pending = True
                return envelope["state"]
            if raw is None:
                return {"version": 1, "forgotten": {}, "superseded": {}}
            self._state(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
            # A legacy unsigned ledger is preserved in full at its first trusted read.
            # Once signed, a missing authority cannot fall back to that local mirror.
            with self._locks():
                if self._read_plain(authority) is not None:
                    return self._load()
                if self._read_plain(self._checked()) != raw:
                    raise PolicyError(UNAVAILABLE)
                self.state = self._state(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
                self._publish()
                return self.state
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, TimeoutError):
            raise PolicyError(UNAVAILABLE) from None

    @contextlib.contextmanager
    def _locks(self):
        from knowledgeos import gate

        self._checked().parent.mkdir(parents=True, exist_ok=True)
        local = self.path.parent / "remembering-policy.lock"
        plain_vault_path(self.vault, local)
        authority = self._authority()
        authority.parent.mkdir(parents=True, exist_ok=True)
        trusted = authority.with_suffix(".lock")
        gate._binding_file(trusted)
        gate._binding_file(trusted.with_name(trusted.name + ".guard"))
        with file_lock(local, timeout=10), file_lock(trusted, timeout=10):
            yield

    @contextlib.contextmanager
    def lock(self):
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(self._locks())
                self.state = self._load()
                if self._mirror_pending:
                    atomic_write_bytes(self._checked(), self._authority_bytes)
                    self._mirror_pending = False
            except PolicyError:
                raise
            except (OSError, ValueError, TimeoutError):
                raise PolicyError(UNAVAILABLE) from None
            yield self

    def _publish(self):
        try:
            authority = self._authority()
            raw = self._read_plain(self._checked())
            envelope = {"version": 2, "policy": POLICY, "vault_key": authority.parent.name,
                        "state": self._state(self.state),
                        "previous_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None}
            envelope["mac"] = self._mac(self._key(create=self._authority_bytes is None), envelope)
            authenticated = json.dumps(envelope, sort_keys=True).encode("utf-8")
            # Commit restrictions outside the vault before publishing their mirror.
            atomic_write_bytes(authority, authenticated)
            self._authority_bytes = authenticated
            atomic_write_bytes(self._checked(), authenticated)
            self._mirror_pending = False
        except (OSError, ValueError, TypeError, UnicodeError):
            raise PolicyError(UNAVAILABLE) from None

    def text_reason(self, text, metadata=None):
        text = str(text or "")
        if marked_excluded(text, metadata):
            return "explicit_exclusion"
        return self.content_reason(text)

    def content_reason(self, text):
        """Why the words themselves are withheld: a credential, or forgotten text."""
        text = str(text or "")
        pattern_reason = _pattern_reason(text)
        if pattern_reason:
            return pattern_reason
        expected = {}
        for record in self.state["forgotten"].values():
            for fp in record["fingerprints"]:
                expected.setdefault(fp["words"], set()).add(fp["sha256"])
        words = _words(text) if expected else []
        for width, digests in expected.items():
            for offset in range(len(words) - width + 1):
                if hashlib.sha256(" ".join(words[offset:offset + width]).encode()).hexdigest() in digests:
                    return "forgotten_literal"
        return None

    def require_text(self, text, metadata=None):
        if self.text_reason(text, metadata):
            raise PolicyError(EXCLUDED)

    def _observe_source(self, path, *, historical=True) -> _SourceObservation:
        from knowledgeos import gate

        def revision(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                    info.st_nlink)

        try:
            path = Path(os.path.abspath(Path(path)))
            relative = path.relative_to(self.vault).as_posix()
            if relative in self.state["forgotten"]:
                plain_vault_path(self.vault, path)
                return _ExcludedSource()
            if not historical and relative in self.state["superseded"]:
                plain_vault_path(self.vault, path)
                return _ExcludedSource()
            expected = gate._binding_file(path)
            if expected is None:
                return _UnavailableSource()
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or revision(before) != revision(expected)):
                    return _UnavailableSource()
                raw = handle.read()
                after = os.fstat(handle.fileno())
                if (revision(before) != revision(after)
                        or before.st_ctime_ns != after.st_ctime_ns or len(raw) != after.st_size):
                    return _UnavailableSource()
                current = gate._binding_file(path)
                if (current is None or revision(current) != revision(after)
                        or current.st_ctime_ns != expected.st_ctime_ns):
                    return _UnavailableSource()
            signature = _SourceSignature(after.st_size, after.st_mtime_ns,
                                         hashlib.sha256(raw).hexdigest())
            if any(signature.sha256 == record["sha256"]
                   for record in self.state["forgotten"].values()):
                return _ExcludedSource()
            text = raw.decode("utf-8", errors="strict")
        except (OSError, ValueError, UnicodeError):
            return _UnavailableSource()
        if self.text_reason(text) or self.text_reason(relative):
            return _ExcludedSource()
        return _AdmittedSource(text, signature)

    def read(self, path, *, historical=True):
        observed = self._observe_source(path, historical=historical)
        return observed.text if isinstance(observed, _AdmittedSource) else None

    def attribution(self, path):
        relative = Path(path).relative_to(self.vault).as_posix()
        record = self.state["superseded"].get(relative)
        if record:
            return {"memory_status": "historical", "superseded_by": record["replacement"],
                    "reviewed_sha256": record["sha256"]}
        return {"memory_status": "current"}

    def admit(self, value):
        """Refuse a value on its way in.

        A string that comes in is a whole text: a note to save, a patch, a question. It
        is judged with its own metadata block, and with a marked block that opens on a
        later line, so a private note that is pasted in is not saved as an ordinary one.
        A block that is not read gets its own message, because the text may be ordinary.
        """
        if isinstance(value, str):
            if value in self.state["forgotten"]:
                raise PolicyError(EXCLUDED)
            reason = metadata_reason(value)
            if reason == "not_understood":
                raise PolicyError(UNREAD_BLOCK)
            if reason or holds_marked_block(value) or self.content_reason(value):
                raise PolicyError(EXCLUDED)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.admit(item)
        elif isinstance(value, dict):
            if metadata_excludes(value):
                raise PolicyError(EXCLUDED)
            for key, item in value.items():
                self.admit(key)
                self.admit(item)
        return value

    def scrub(self, value):
        if isinstance(value, str):
            # A string on its way out is a piece of a note: a body, a snippet, a title.
            # Whether the note is private was decided when the whole file was read, from
            # its own metadata block. A body that begins with a YAML example is not a
            # metadata block, so only the content checks apply here. A value on its way
            # in goes through `admit`.
            if value in self.state["forgotten"] or self.content_reason(value):
                return "[Excluded by remembering policy]"
            return value
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, dict):
            if metadata_excludes(value):
                return "[Excluded by remembering policy]"
            return {str(self.scrub(key)): self.scrub(item) for key, item in value.items()}
        return value

    def release(self, value):
        if self.scrub(value) != value:
            raise PolicyError(EXCLUDED)
        return value

    def current_connection(self):
        """A disposable relational view of permitted current sources, never cache claims."""
        import sqlite3
        from knowledgeos.indexer import iter_notes, _process_file, _SCHEMA_SQL, _INSERT_NOTE_SQL
        from knowledgeos.links import build_note_lookup

        files = [path for path in iter_notes(self.vault) if self.read(path, historical=False) is not None]
        lookup = build_note_lookup(files, self.vault)
        allowed = {path.relative_to(self.vault).as_posix() for path in files}
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(_SCHEMA_SQL)
            for path in files:
                relative, parsed = _process_file((path, self.vault, lookup))
                if isinstance(parsed, Exception):
                    raise PolicyError(UNAVAILABLE)
                note, links, _fts, _signature = parsed
                conn.execute(_INSERT_NOTE_SQL, note)
                for destination, raw in links:
                    if destination in allowed and not self.text_reason(raw):
                        conn.execute("INSERT INTO links(source,destination,raw_destination) VALUES (?,?,?)",
                                     (relative, destination, raw))
            self.release([dict(row) for row in conn.execute("SELECT * FROM notes")])
            return conn
        except BaseException:
            conn.close()
            raise

    def _reviewed(self, path, expected):
        if not _digest(expected):
            raise PolicyError("A reviewed source SHA-256 is required; no memory changed.")
        try:
            path = plain_vault_path(self.vault, Path(path))
            relative = path.relative_to(self.vault).as_posix()
            if not _relative(relative) or relative.casefold() == "people/self.md":
                raise ValueError("protected or invalid source")
            raw = self._read_plain(path)
            if raw is None:
                raise OSError("missing reviewed source")
        except (OSError, ValueError):
            raise PolicyError("The reviewed source is unavailable or protected; no memory changed.") from None
        if hashlib.sha256(raw).hexdigest() != expected:
            raise PolicyError("The source changed since review; no memory changed.")
        try:
            return relative, raw.decode("utf-8", errors="strict")
        except UnicodeError:
            raise PolicyError("The reviewed source cannot be read safely; no memory changed.") from None

    def forget(self, path, expected):
        with self.lock():
            relative, text = self._reviewed(path, expected)
            record = self.state["forgotten"].get(relative)
            if record is not None:
                if record["sha256"] != expected:
                    raise PolicyError("A different source version was already forgotten; no memory changed.")
                return
            self.state["forgotten"][relative] = {
                "sha256": expected, "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "fingerprints": _fingerprints(text),
            }
            self._publish()

    def supersede(self, path, expected, replacement, replacement_expected):
        with self.lock():
            relative, text = self._reviewed(path, expected)
            current, current_text = self._reviewed(replacement, replacement_expected)
            if (relative == current or current in self.state["superseded"]
                    or self.read(path, historical=True) is None or self.read(replacement, historical=False) is None):
                raise PolicyError("Correction needs two permitted, distinct reviewed sources; no memory changed.")
            self.require_text(text)
            self.require_text(current_text)
            existing = self.state["superseded"].get(relative)
            if existing:
                if (existing["sha256"], existing["replacement"], existing["replacement_sha256"]) != (
                        expected, current, replacement_expected):
                    raise PolicyError("This source already has a different correction; no memory changed.")
                return
            self.state["superseded"][relative] = {
                "sha256": expected, "replacement": current, "replacement_sha256": replacement_expected,
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self._publish()


def current_database(db_path, **_options):
    """Report adapter with the existing connection shape and current source authority."""
    from knowledgeos.database import checked_database_path

    checked = checked_database_path(db_path)
    return RememberingPolicy(checked.parent).current_connection()


def policy_boundary(method):
    """Apply the same refusal to direct APIs, CLI adapters and protocol callers."""
    signature = inspect.signature(method)

    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            policy = RememberingPolicy(self.vault)
            supplied = signature.bind(self, *args, **kwargs).arguments
            if method.__name__ not in {"forget", "supersede"}:
                for key, value in supplied.items():
                    if key != "self":
                        policy.release(value)
            result = method(self, *args, **kwargs)
            return RememberingPolicy(self.vault).release(result)
        except PolicyError as error:
            return refusal(error)
    return guarded
