"""Local remembering rules shared by storage, readers and derived output.

Metadata is authoritative exclusion input. Conservative content checks combine
third-person relationships with sensitive detail categories, including indirect
clinical statements. These finite checks are not a general semantic classifier.
Forgetting matches reviewed sources and normalized literal passages, including
copies, but cannot recognize arbitrary paraphrases.
"""
from __future__ import annotations

import contextlib
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
import unicodedata
from pathlib import Path, PurePosixPath

from knowledgeos.data_ops import plain_vault_path
from knowledgeos.locking import file_lock
from knowledgeos.parser import split_frontmatter
from knowledgeos.textio import atomic_create_bytes, atomic_write_bytes

POLICY = "twinaatma-remembering-policy-v1"
UNAVAILABLE = "Remembering policy state is unavailable; no memory was released or saved."
EXCLUDED = "This content is excluded by the approved remembering policy."
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
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    # Keep sentence/paragraph boundaries. A sensitive topic in another unrelated
    # paragraph must not make a normal collaboration statement private.
    for paragraph in re.split(r"(?<=[.!?])\s+|\n\s*\n", normalized):
        if _SENSITIVE_DETAIL.search(paragraph) and (
                _RELATED_PERSON.search(paragraph) or _NAMED_PERSON.search(paragraph)):
            return True
    return False


_EXCLUDED_LABELS = {"exclude", "excluded", "private", "secret", "credential", "credentials",
                    "sensitive", "sensitive-third-party", "third-party-sensitive", "do-not-remember"}


class PolicyError(ValueError):
    """A refusal whose message never includes the excluded input or unsafe path."""


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
        fm = metadata if metadata is not None else split_frontmatter(text)[0]
        for key in ("privacy", "memory_privacy", "sensitivity", "memory_policy"):
            value = fm.get(key)
            labels = value if isinstance(value, list) else [value]
            for label in labels:
                if label and (not isinstance(label, str)
                              or label.strip().casefold() in _EXCLUDED_LABELS):
                    return "explicit_exclusion"
        if any(fm.get(key) is True for key in ("sensitive", "third_party_sensitive", "do_not_remember")):
            return "explicit_exclusion"
        if _CREDENTIALS.search(text):
            return "credential_pattern"
        if _THIRD_PARTY.search(text) or _sensitive_third_party(text):
            return "third_party_pattern"
        words = _words(text)
        expected = {}
        for record in self.state["forgotten"].values():
            for fp in record["fingerprints"]:
                expected.setdefault(fp["words"], set()).add(fp["sha256"])
        for width, digests in expected.items():
            for offset in range(len(words) - width + 1):
                if hashlib.sha256(" ".join(words[offset:offset + width]).encode()).hexdigest() in digests:
                    return "forgotten_literal"
        return None

    def require_text(self, text, metadata=None):
        if self.text_reason(text, metadata):
            raise PolicyError(EXCLUDED)

    def read(self, path, *, historical=True):
        try:
            path = plain_vault_path(self.vault, Path(path))
            relative = path.relative_to(self.vault).as_posix()
            if relative in self.state["forgotten"]:
                return None
            if not historical and relative in self.state["superseded"]:
                return None
            raw = self._read_plain(path)
            if raw is None:
                return None
            if any(hashlib.sha256(raw).hexdigest() == record["sha256"]
                   for record in self.state["forgotten"].values()):
                return None
            text = raw.decode("utf-8", errors="strict")
        except (OSError, ValueError, UnicodeError):
            return None
        if self.text_reason(text) or self.text_reason(relative):
            return None
        return text

    def attribution(self, path):
        relative = Path(path).relative_to(self.vault).as_posix()
        record = self.state["superseded"].get(relative)
        if record:
            return {"memory_status": "historical", "superseded_by": record["replacement"],
                    "reviewed_sha256": record["sha256"]}
        return {"memory_status": "current"}

    def scrub(self, value):
        if isinstance(value, str):
            if value in self.state["forgotten"] or self.text_reason(value):
                return "[Excluded by remembering policy]"
            return value
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, dict):
            if self.text_reason("", value):
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
        from knowledgeos.indexer import iter_markdown, _process_file, _SCHEMA_SQL, _INSERT_NOTE_SQL
        from knowledgeos.links import build_note_lookup

        files = [path for path in iter_markdown(self.vault) if self.read(path, historical=False) is not None]
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
                note, links, _fts = parsed
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
