"""Record one reviewed decision outcome without a second transaction or identity edit."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from knowledgeos.data_ops import personal_note_paths, plain_vault_path
from knowledgeos.indexer import iter_markdown
from knowledgeos.parser import parse_frontmatter
from knowledgeos.remembering import EXCLUDED, PolicyError, RememberingPolicy
from knowledgeos.textio import atomic_write_bytes, dominant_newline

_RECEIPT = "outcome_recording"
_COMPLETED = {"confirmed", "invalidated", "superseded"}
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_KEY = re.compile(rb"([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _refuse(message: str) -> None:
    raise PolicyError(message + "; no outcome changed.")


def _scalar(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _refuse("Outcome and lesson values must be nonempty text")
    if any(ord(char) < 32 or 127 <= ord(char) < 160 or char in "\u2028\u2029" for char in value):
        _refuse("Outcome values must be single-line text without control characters")
    if "'" not in value:
        encoded = "'" + value + "'"
    elif '"' not in value and "\\" not in value:
        encoded = json.dumps(value, ensure_ascii=False)
    else:
        _refuse("This value cannot be stored losslessly in the supported note format")
    if parse_frontmatter("---\nvalue: " + encoded + "\n---\n").get("value") != value:
        _refuse("This value cannot be stored losslessly in the supported note format")
    return encoded


@dataclass(frozen=True)
class OutcomeReview:
    path: str
    expected_sha256: str
    outcome_status: str
    actual_outcome: str
    lesson: str
    belief_before: str | None = None
    belief_after: str | None = None

    def fields(self) -> dict[str, str]:
        if not isinstance(self.path, str) or not self.path:
            _refuse("Use the exact vault-relative path returned by memory_get_note")
        parts = PurePosixPath(self.path)
        if (parts.is_absolute() or str(parts) != self.path or "\\" in self.path or ":" in self.path
                or any(part in (".", "..") for part in parts.parts) or parts.suffix.lower() != ".md"):
            _refuse("Use the exact vault-relative path returned by memory_get_note")
        if not isinstance(self.expected_sha256, str) or not _HEX.fullmatch(self.expected_sha256):
            _refuse("The reviewed source SHA-256 from memory_get_note is required")
        if not isinstance(self.outcome_status, str) or self.outcome_status not in _COMPLETED:
            _refuse("Outcome status must be confirmed, invalidated or superseded")
        if (self.belief_before is None) != (self.belief_after is None):
            _refuse("Explicit belief evidence needs both before and after statements")
        values = {"outcome_status": self.outcome_status, "actual_outcome": self.actual_outcome, "lesson": self.lesson}
        if self.belief_before is not None:
            values.update(belief_before=self.belief_before, belief_after=self.belief_after)
        return {key: _scalar(value) for key, value in values.items()}

    def digest(self) -> str:
        return _sha(json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _source(vault: Path, relative: str) -> Path:
    try:
        path = plain_vault_path(vault, vault / relative)
        protected = relative.casefold()
        if protected == "people/self.md" or protected.startswith("people/self-proposals/"):
            raise ValueError("protected identity")
        if not path.is_file() or path not in iter_markdown(vault) or not personal_note_paths(vault, [path]):
            raise ValueError("not an ordinary source")
        return path
    except (OSError, ValueError):
        _refuse("The reviewed source is unavailable, linked, generated or protected")


def _frontmatter(raw: bytes) -> tuple[list[bytes], int, dict[str, int]]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n").removeprefix(b"\xef\xbb\xbf").strip() != b"---":
        _refuse("The decision needs an existing supported frontmatter block")
    entries = {}
    current = None
    editable = {"outcome_status", "actual_outcome", "lesson", "belief_before", "belief_after", "updated", "outcome_recorded_at", _RECEIPT}
    for index, line in enumerate(lines[1:], 1):
        logical = line.rstrip(b"\r\n")
        if logical.strip() == b"---":
            return lines, index, entries
        if not logical.strip() or logical.lstrip().startswith(b"#"):
            continue
        match = _KEY.match(logical)
        if match:
            current = match[1].decode("ascii").lower()
            if current in entries:
                _refuse("Duplicate frontmatter keys need source review before recording")
            entries[current] = index
        elif current in editable:
            _refuse("Outcome fields must use supported single-line frontmatter")
    _refuse("The decision needs a complete supported frontmatter block")


def _receipt(lines: list[bytes], entries: dict[str, int]) -> dict | None:
    if _RECEIPT not in entries:
        return None
    try:
        value = lines[entries[_RECEIPT]].decode("utf-8").partition(":")[2].strip()
        result = json.loads(value)
        if (not isinstance(result, dict) or set(result) != {"version", "before_sha256", "request_sha256", "content_sha256"}
                or type(result["version"]) is not int or result["version"] != 1
                or any(not isinstance(result[key], str) or not _HEX.fullmatch(result[key])
                       for key in ("before_sha256", "request_sha256", "content_sha256"))):
            raise ValueError("receipt shape")
        content = b"".join(line for index, line in enumerate(lines) if index != entries[_RECEIPT])
        if _sha(content) != result["content_sha256"]:
            raise ValueError("changed completed source")
        expected_marker = (_RECEIPT + ": " + json.dumps(result, sort_keys=True, separators=(",", ":"))).encode("ascii")
        if lines[entries[_RECEIPT]] != expected_marker + dominant_newline(content).encode("ascii"):
            raise ValueError("changed outcome receipt")
        return result
    except (ValueError, KeyError, UnicodeError):
        _refuse("The completed source changed or its outcome receipt is invalid")


def _payload(raw: bytes, review: OutcomeReview, fields: dict[str, str], lines: list[bytes], end: int,
             entries: dict[str, int]) -> tuple[bytes, dict]:
    ending = dominant_newline(raw).encode("ascii")
    expected = {key: getattr(review, key) for key in fields}
    expected.update(updated=datetime.date.today().isoformat(), outcome_recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    fields = dict(fields, updated=_scalar(expected["updated"]), outcome_recorded_at=_scalar(expected["outcome_recorded_at"]))
    added = []
    for key, encoded in fields.items():
        replacement = (key + ": " + encoded).encode("utf-8")
        if key in entries:
            index = entries[key]
            old = lines[index]
            tail = old[len(old.rstrip(b"\r\n")):]
            lines[index] = replacement + tail
        else:
            added.append(replacement + ending)
    content = b"".join(lines[:end] + added + lines[end:])
    receipt = {"version": 1, "before_sha256": review.expected_sha256, "request_sha256": review.digest(), "content_sha256": _sha(content)}
    marker = (_RECEIPT + ": " + json.dumps(receipt, sort_keys=True, separators=(",", ":"))).encode("ascii") + ending
    payload = b"".join(lines[:end] + added + [marker] + lines[end:])
    parsed = parse_frontmatter(payload.decode("utf-8"))
    for key in fields:
        if parsed.get(key) != expected[key]:
            _refuse("The requested values cannot roundtrip through this source format")
    return payload, receipt


def record_outcome(vault: Path, review: OutcomeReview) -> dict:
    fields = review.fields()
    with RememberingPolicy(vault).lock() as policy:
        path = _source(vault, review.path)
        text = policy.read(path, historical=False)
        if text is None:
            raise PolicyError(EXCLUDED)
        raw = text.encode("utf-8")
        metadata = parse_frontmatter(text)
        if metadata.get("type") != "decision":
            _refuse("Only a reviewed decision source can acquire an outcome")
        lines, end, entries = _frontmatter(raw)
        receipt = _receipt(lines, entries)
        if receipt is not None:
            if (receipt["before_sha256"] != review.expected_sha256 or receipt["request_sha256"] != review.digest()
                    or any(metadata.get(key) != getattr(review, key) for key in fields)):
                _refuse("This source already has a different completed outcome or review")
            payload = raw
        else:
            if _sha(raw) != review.expected_sha256:
                _refuse("The source changed since review")
            if metadata.get("outcome_status") not in (None, "", "pending"):
                _refuse("The reviewed decision already has a completed outcome")
            payload, receipt = _payload(raw, review, fields, lines, end, entries)
        complete_text = payload.decode("utf-8")
        policy.require_text(complete_text)
        if payload != raw:
            try:
                if policy.read(_source(vault, review.path), historical=False) != text:
                    _refuse("The source changed since review")
                atomic_write_bytes(path, payload)
            except OSError:
                _refuse("The outcome could not be published; retry the reviewed request")
        return {"ok": True, "recorded": True, "path": review.path, "outcome_status": review.outcome_status,
                "reviewed_sha256": receipt["before_sha256"], "sha256": _sha(payload),
                "mutated_self": False}
