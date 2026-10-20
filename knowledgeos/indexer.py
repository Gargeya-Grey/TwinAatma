"""Build the SQLite search index for a vault: notes, links, and FTS5 body text.

Stdlib only. Incremental: a note whose content hash is unchanged is not re-parsed.
Runs in-process so the agent runtime and the binary never need scripts/.

Freshness is a manifest, not a folder whitelist: every markdown file in the vault
is compared by ``(size, mtime_ns)`` so edits in any folder and deletions/renames
are both detected.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from knowledgeos.data_ops import personal_note_paths
from knowledgeos.database import checked_database_path, connect_database
from knowledgeos.links import build_note_lookup, extract_raw_links, normalize_link
from knowledgeos.parser import parse_frontmatter, split_frontmatter

DB_NAME = "knowledge_index.db"
MANIFEST_REL = ".knowledgeos/index-manifest.json"
LOCK_REL = ".knowledgeos/index-rebuild.lock"
LOCK_STALE_SECONDS = 600.0
LOCK_WAIT_SECONDS = 30.0
MANIFEST_VERSION = 1

# Never indexed: tool state, editor state, vendor code, trash.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".knowledgeos",
    ".trash",
    ".obsidian",
    ".agents",
    ".claude",
    ".cursor",
    ".codex",
    ".grok",
    ".commandcode",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    # Generated copy of the starter kit; indexing it makes search return template
    # boilerplate and doubles every hit.
    "_assets",
}

MAX_HASH_BYTES = 8 * 1024 * 1024
# How long `index_state` waits for the write lock before calling the database locked.
# This is the tool's first call of a chat; two seconds is the whole patience budget.
LOCK_PROBE_SECONDS = 1.5
# Streaming read size for `_file_signature`. Notes are hashed in full; this only bounds
# peak memory for a pathologically large file.
HASH_CHUNK_BYTES = 1024 * 1024

# `AGENTS.md` is the operating contract the host agent reads directly. It is not a note
# and it is not written by the user, so it is never indexed in any vault. It is still
# readable by explicit path, which is how an agent uses it.
PRODUCT_FILES = {"agents.md", "claude.md"}

# Repository plumbing that only exists because this folder is the toolkit's own checkout.
# Skipped **only** when the vault is that checkout: in a user's vault `Changelog.md` or
# `README.md` is a normal note, and skipping it made it unsearchable while
# `memory_get_note` still read it — the search index and the reader disagreed about what
# a note is, and the README promised the root was searchable.
ROOT_SKIP_FILES = {
    "contributing.md",
    "security.md",
    "code_of_conduct.md",
    "changelog.md",
    "readme.md",
    "license",
    "license.md",
}

# Folders that exist only in the toolkit checkout. The validator used to keep its own,
# slightly different list, so `search` and `validate` disagreed about the note set in the
# project whose ADR says there is exactly one. They now both walk `iter_markdown`.
TOOLKIT_ONLY_DIRS = {"docs", "work", "outputs", "tests", "test", "fixtures", "scripts", "knowledgeos", "build", "dist"}


def _is_toolkit_repo(vault: Path) -> bool:
    """True when this vault *is* the toolkit checkout, not a user's vault."""
    return (vault / "pyproject.toml").is_file() and (vault / "knowledgeos").is_dir()


def _is_conflict_copy(path: Path) -> bool:
    """True for `init`'s unmerged duplicates: `Self.new.md` next to `Self.md`.

    `_Plan.write` names them ``stem + ".new" + suffix``, so a conflict copy only exists
    beside the file it refused to overwrite. Testing the *name* alone also matched a
    user's own note called `notes.new.md`, which then existed on disk but was never
    searchable. Requiring the original to be present tells the two apart exactly.
    """
    name = path.name
    if ".new." not in name.lower():
        return False
    stem, _, suffix = name.rpartition(".new.")
    if not stem:
        return False
    return path.with_name(f"{stem}.{suffix}").exists()


def _skip_root_name(vault: Path, name: str) -> bool:
    lowered = name.lower()
    if lowered in PRODUCT_FILES:
        return True
    return lowered in ROOT_SKIP_FILES and _is_toolkit_repo(vault)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  path TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL DEFAULT 'concept',
  tags TEXT,
  project TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created TEXT,
  updated TEXT,
  description TEXT,
  resource TEXT,
  timestamp TEXT,
  schema TEXT,
  file_hash TEXT,
  entity_id TEXT,
  confidence TEXT,
  last_reviewed TEXT,
  outcome_status TEXT,
  review_after TEXT,
  lesson TEXT
);
CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  destination TEXT NOT NULL,
  raw_destination TEXT,
  FOREIGN KEY (source) REFERENCES notes(path)
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
"""

_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  path UNINDEXED,
  title,
  body,
  tags,
  description,
  tokenize = 'porter unicode61'
)
"""

_ADDED_NOTE_COLUMNS = [
    "description", "resource", "timestamp", "schema", "file_hash",
    "entity_id", "confidence", "last_reviewed", "outcome_status",
    "review_after", "lesson",
]

_INSERT_NOTE_SQL = """INSERT OR REPLACE INTO notes
  (title, path, type, tags, project, status, created, updated, description, resource, timestamp, schema, file_hash,
   entity_id, confidence, last_reviewed, outcome_status, review_after, lesson)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


# --------------------------------------------------------------------------- #
# vault scanning and manifest
# --------------------------------------------------------------------------- #


def _skip_parts(parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIRS for part in parts)


def _contained(root: str, candidate: str) -> bool:
    """True when ``candidate`` is the root or below it (no ``C:\\vault2`` prefix trick)."""
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        return False


def _is_link(path: Path) -> bool:
    """Symlink, junction or other reparse point (Windows junctions are not symlinks)."""
    try:
        if path.is_symlink():
            return True
        real = os.lstat(path)
    except OSError:
        return True
    attributes = getattr(real, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def iter_markdown(vault: Path) -> list[Path]:
    """All indexable markdown files, confined to the real vault directory."""
    vault = vault.resolve()
    root = str(vault)
    out: list[Path] = []
    toolkit_repo = _is_toolkit_repo(vault)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            if name in SKIP_DIRS:
                continue
            # Root templates are instructions for authoring notes. A user's
            # nested project folder named Templates still contains normal notes.
            if current == vault and name == "Templates":
                continue
            if toolkit_repo and current == vault and name in TOOLKIT_ONLY_DIRS:
                continue
            child = current / name
            if _is_link(child):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if not name.lower().endswith(".md"):
                continue
            if name.lower() in PRODUCT_FILES:
                continue
            if current == vault and _skip_root_name(vault, name):
                continue
            # `init` writes `<stem>.new<suffix>` when it refuses to overwrite a user's
            # file. Those are unmerged duplicates: indexing them makes `kos:person:self`
            # resolve to `People/Self.new.md` and turns search into a coin flip. Match
            # the exact shape `init` produces — a plain substring test also hid
            # legitimate notes called `thing.new.md` from search entirely.
            if _is_conflict_copy(current / name):
                continue
            path = current / name
            if _is_link(path):
                continue
            try:
                if not stat.S_ISREG(path.lstat().st_mode):
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            if not _contained(root, str(resolved)):
                # A link inside the vault pointing outside: never index it.
                continue
            out.append(path)
    return personal_note_paths(vault, out)


def iter_memory_markdown(vault: Path) -> list[Path]:
    """Memory admission is narrower than the source inventory used by maintenance."""
    from knowledgeos.remembering import RememberingPolicy

    policy = RememberingPolicy(vault)
    return [path for path in iter_markdown(vault) if policy.read(path) is not None]


def manifest_path(vault: Path) -> Path:
    return vault / MANIFEST_REL


def _file_signature(path: Path) -> list[Any] | None:
    """``[size, mtime_ns, sha256]``, hashed over the whole file.

    The hash matters: a same-size edit inside the same filesystem timestamp tick (or a
    tool that preserves mtime) is invisible to ``(size, mtime)`` alone, and the whole
    point of the manifest is that search never serves stale text.

    This hashes everything, in chunks. An earlier version sampled the first and last
    4 MB of large notes to keep the cost bounded — which reintroduced exactly the bug it
    was meant to fix, one size class up: a mid-file edit with size and mtime preserved
    was reported as ``fresh`` forever. A digest that is right for small files and wrong
    for large ones is not a digest, it is a size threshold with extra steps. Personal
    notes are small; the cost of being correct here is a few milliseconds.
    """
    digest = hashlib.sha256()
    try:
        before = path.stat()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
        after = path.stat()
    except OSError:
        return None
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        # The file changed while we were reading it; let the next tick catch it.
        return None
    return [after.st_size, after.st_mtime_ns, digest.hexdigest()]


def build_manifest(
    vault: Path,
    files: list[Path] | None = None,
    skip: set[str] | None = None,
    index_digest: str | None = None,
) -> dict[str, Any]:
    vault = vault.resolve()
    files = files if files is not None else iter_memory_markdown(vault)
    skip = skip or set()
    entries: dict[str, list[Any]] = {}
    for path in files:
        try:
            rel = path.relative_to(vault).as_posix()
        except ValueError:
            continue
        if rel in skip:
            # Unparseable last time: leave it out so the next tick retries it.
            continue
        signature = _file_signature(path)
        if signature is not None:
            entries[rel] = signature
    manifest = {
        "version": MANIFEST_VERSION,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "files": entries,
    }
    if index_digest:
        manifest["index"] = index_digest
    return manifest


def _manifest_mac(payload: dict[str, Any]) -> str | None:
    """HMAC over the manifest body, using the install's gate key.

    The manifest is the *freshness authority*: `manifest_diff` compares the vault to it
    and, when they agree, `search` is not rebuilt. It lives inside the vault, so an agent
    that can write notes can write it — and writing a manifest that claims the current
    files are already indexed silently disables the check. The reviewer did exactly that:
    edited a note, rewrote the manifest to match the file, and `search` went on quoting
    "human reviewer must sign off" from a note that now said deploys were automated, with
    `index_locked` False and `doctor` printing PASSED.

    An unsigned manifest is therefore not trusted. A missing or broken signature means
    "cannot vouch for this", which sends the caller down the rebuild path — the safe
    direction, because a rebuild always produces the truth.
    """
    try:
        from knowledgeos.gate import _signing_key

        key = _signing_key()
    except Exception:
        return None
    if not key:
        return None
    import hashlib
    import hmac

    body = {k: v for k, v in payload.items() if k != "mac"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def index_digest(conn: sqlite3.Connection) -> str | None:
    """A digest over every value the index holds.

    Signing only the *file* signatures left the database inside the vault unwatched, and
    the first attempt to fix that covered only `notes_fts.body`. The reviewer forged a
    `notes_fts.title` and two `notes` columns instead: one UPDATE, one ordinary capture,
    and `memory_decisions` served a note as a decision whose own frontmatter said
    `type: project`, with `doctor` green and `manifest_diff` reporting `fresh`. Covering
    `body` and nothing else just moved the hole.

    So this hashes all of it: every column of `notes`, every column of `notes_fts`, and
    the link edges. Reading the rows back costs ~4 ms at 800 notes, which is nothing next
    to the ~70 ms of file hashing already done on the same call.
    """
    import hashlib

    digest = hashlib.sha256()

    def feed(values: Any) -> None:
        for value in values:
            # Tagged and length-prefixed, because `str(value)` alone is not injective.
            # ``NULL`` and the four characters ``None`` hashed to the same bytes, so a
            # one-word `UPDATE notes SET description = 'None'` was invisible to
            # `manifest_diff` — the digest that exists to notice exactly that. The tag
            # also keeps a number from impersonating its own text.
            if value is None:
                digest.update(b"N")
            else:
                if isinstance(value, bytes):
                    tag, payload = b"B", value
                elif isinstance(value, int):
                    tag, payload = b"I", str(value).encode("utf-8", "replace")
                elif isinstance(value, float):
                    tag, payload = b"F", value.hex().encode("ascii")
                else:
                    tag, payload = b"S", str(value).encode("utf-8", "replace")
                digest.update(tag)
                digest.update(str(len(payload)).encode())
                digest.update(b":")
                digest.update(payload)
            digest.update(b"\x00")
        digest.update(b"\x1e")

    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(notes)")]
        if not columns:
            return None
        feed(("notes", *columns))
        quoted = ["\"" + name.replace("\"", "\"\"") + "\"" for name in columns]
        for row in conn.execute("SELECT " + ", ".join(quoted) + " FROM notes ORDER BY path"):
            feed(row)
        feed(("notes_fts", "path", "title", "body", "tags", "description"))
        for row in conn.execute(
            "SELECT path, title, body, tags, description FROM notes_fts ORDER BY path"
        ):
            feed(row)
        feed(("links", "source", "destination", "raw_destination"))
        for row in conn.execute(
            "SELECT source, destination, raw_destination FROM links "
            "ORDER BY source, destination, IFNULL(raw_destination, '')"
        ):
            feed(row)
    except sqlite3.Error:
        return None
    return digest.hexdigest()


def load_manifest(vault: Path) -> dict[str, Any] | None:
    path = manifest_path(vault)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        return None
    if not isinstance(data.get("files"), dict):
        return None
    stored = data.get("mac")
    expected = _manifest_mac(data)
    if not stored or not expected:
        # No key, or a manifest written before signing: re-derive rather than trust.
        return None
    import hmac

    if not hmac.compare_digest(str(stored), expected):
        return None
    return data


def _state_dir(vault: Path) -> Path:
    """``<vault>/.knowledgeos`` with the shared containment check."""
    from knowledgeos.vaultstate import state_dir

    return state_dir(vault)


def save_manifest(vault: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest through the shared atomic writer.

    It used to stage at ``<name>.tmp`` — a name an agent can compute — so a hardlink
    planted there made an ordinary index refresh replace the linked file with manifest
    JSON. The writer in ``knowledgeos.textio`` picks an unpredictable name and refuses
    anything that is not a single-link regular file.
    """
    from knowledgeos.textio import atomic_write

    path = manifest_path(vault)
    _state_dir(vault)
    manifest = dict(manifest)
    mac = _manifest_mac(manifest)
    if mac:
        manifest["mac"] = mac
    atomic_write(path, json.dumps(manifest, indent=0, sort_keys=True) + "\n", "\n")


def manifest_diff(
    vault: Path, *, hash_contents: bool = True, hash_budget_bytes: int = 64 * 1024 * 1024
) -> tuple[bool, str]:
    """``(changed, reason)`` comparing the on-disk markdown set to the manifest.

    ``hash_budget_bytes`` used to *silently* downgrade verification: once the budget was
    spent, the remaining files were compared on ``(size, mtime)`` only and the function
    returned ``fresh`` as though it had checked them. A note edited to the same length
    with its mtime restored — a deliberate act, and the threat model here includes an
    agent that can write vault files — was then reported fresh forever, and search went
    on quoting the replaced sentence with nothing anywhere saying so.

    The budget is now a *diagnostic*: every file with a stored digest is hashed, and
    exceeding the budget is reported in the reason (``fresh_over_budget:<bytes>``) so a
    slow vault is visible instead of the comparison being quietly weakened. Hashing a
    personal vault costs well under a second; correctness on the user's own notes is
    worth more than that.
    """
    stored = load_manifest(vault)
    if stored is None:
        return True, "manifest_missing"
    disk = iter_memory_markdown(vault)
    stored_files = stored.get("files") or {}
    disk_paths = {p.relative_to(vault).as_posix() for p in disk}

    added = sorted(disk_paths - set(stored_files))
    if added:
        return True, f"added:{added[0]}"
    removed = sorted(set(stored_files) - disk_paths)
    if removed:
        return True, f"removed:{removed[0]}"

    hashed = 0
    for path in disk:
        rel = path.relative_to(vault).as_posix()
        old = stored_files.get(rel) or []
        if len(old) < 2:
            return True, f"modified:{rel}"
        try:
            info = path.stat()
        except OSError:
            return True, f"unreadable:{rel}"
        if list(old[:2]) != [info.st_size, info.st_mtime_ns]:
            return True, f"modified:{rel}"
        if hash_contents and len(old) >= 3 and old[2]:
            # No `continue` on the budget any more. Skipping the hash here meant
            # returning `fresh` for a file that was never looked at.
            hashed += info.st_size
            signature = _file_signature(path)
            if signature is None or signature[2] != old[2]:
                return True, f"modified:{rel}"
    # The files agree with the manifest. Do the index's rows?
    #
    # They are not the same question. A rewritten `notes_fts.body` leaves every file
    # untouched, so the checks above say fresh while `search` quotes text that exists
    # nowhere and, in the other direction, hides the words the note really contains.
    # The digest is inside the manifest HMAC (keyed from outside the vault), so this
    # comparison cannot be satisfied by editing the vault.
    expected_index = stored.get("index")
    if not expected_index:
        return True, "index_digest_missing"
    db_path = vault / DB_NAME
    if expected_index and index_state(db_path) == "ok":
        actual_index = None
        try:
            conn = connect_database(db_path, timeout=2.0)
            try:
                actual_index = index_digest(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            actual_index = None
        if actual_index != expected_index:
            return True, "index_tampered"

    if hashed > hash_budget_bytes:
        return False, f"fresh_over_budget:{hashed}"
    return False, "fresh"


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #


_REQUIRED_NOTE_COLUMNS = (
    "path",
    "title",
    "type",
    "tags",
    "project",
    "status",
    "created",
    "updated",
    "description",
    "outcome_status",
    "review_after",
    "lesson",
    "entity_id",
)
_REQUIRED_FTS_COLUMNS = ("path", "title", "body", "tags", "description")
_REQUIRED_LINK_COLUMNS = ("source", "destination", "raw_destination")


def index_coverage_problem(vault: Path | str) -> str | None:
    """``None`` when every markdown note on disk has a row, else what is missing.

    The schema check answers "can this database be queried"; it says nothing about
    whether it holds the vault. An index that is *shaped* right and empty answers every
    search with an empty list — which reads as "no note matches", the most confidently
    wrong answer the product can give. `doctor` called exactly that
    ``[OK] Index healthy`` and exited 0 in a 42-note vault.

    Rebuilding repairs it, so this is reported as a warning with the count, and
    `doctor` says which. It is deliberately not part of `index_state`: a read must not
    trigger a full vault walk, and the read path already repairs the index when the
    manifest says it disagrees.
    """
    vault = Path(vault)
    db_path = vault / DB_NAME
    on_disk = {p.relative_to(vault).as_posix() for p in iter_memory_markdown(vault)}
    try:
        conn = connect_database(db_path, timeout=2.0)
    except sqlite3.Error:
        return None  # the schema check reports this case better
    try:
        indexed = {row[0] for row in conn.execute("SELECT path FROM notes")}
        fulltext = {row[0] for row in conn.execute("SELECT path FROM notes_fts")}
    except sqlite3.Error as exc:
        return f"coverage could not be checked ({exc})"
    finally:
        conn.close()
    missing = sorted(on_disk - indexed)
    if indexed != fulltext:
        return "the metadata and full-text tables disagree about the note set"
    if indexed - on_disk:
        return f"{len(indexed - on_disk)} indexed notes are no longer on disk"
    if not missing:
        return None
    if len(missing) == len(on_disk):
        return f"it is empty, but the vault has {len(on_disk)} notes"
    return f"{len(missing)} of {len(on_disk)} notes are missing (for example {missing[0]})"


def index_schema_problem(db_path: Path | str) -> str | None:
    """Why this database cannot answer a search, or ``None`` when it can.

    Checking that the *tables exist* is not enough, which round thirteen proved twice:
    a database with `notes` and `notes_fts` but no `links` reported "healthy", and so did
    one whose `notes_fts` was an ordinary table rather than an FTS5 one. In the second
    case `doctor` printed `[OK] Index healthy`, `search` silently returned nothing for a
    note that was right there, and `decisions()` raised
    `OperationalError: no such column: type` straight out of the tool surface.

    Column *types* are deliberately not checked: SQLite's are advisory and a vault that
    works must not be quarantined for `title TEXT` vs `title VARCHAR`. What matters is
    that every column a query names is there, and that `notes_fts` is really full-text —
    otherwise the queries that use `MATCH` fail at read time.
    """
    db_path = checked_database_path(db_path)
    try:
        conn = connect_database(db_path, timeout=2.0)
    except sqlite3.Error:
        return "it cannot be opened"
    try:
        rows = conn.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name IN "
            "('notes', 'notes_fts', 'links')"
        ).fetchall()
        found = {name: (kind, (sql or "")) for name, kind, sql in rows}
        for table in ("notes", "notes_fts", "links"):
            if table not in found:
                return f"it has no `{table}` table"
        fts_kind, fts_sql = found["notes_fts"]
        if fts_kind != "table" or not re.search(r"\bUSING\s+fts5\s*\(", fts_sql, re.I):
            # An ordinary table named `notes_fts` accepts writes and answers nothing, so
            # every search comes back empty and the emptiness looks like a real answer.
            return "`notes_fts` is not an FTS5 table"
        # Prove MATCH is executable; the text 'fts5' in an ordinary table's comment
        # or column name is not evidence that this is a virtual full-text table.
        conn.execute("SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1", ("schema_probe",)).fetchone()
        required = {
            "notes": _REQUIRED_NOTE_COLUMNS,
            "notes_fts": _REQUIRED_FTS_COLUMNS,
            "links": _REQUIRED_LINK_COLUMNS,
        }
        for table, wanted in required.items():
            have = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing = [name for name in wanted if name not in have]
            if missing:
                return f"`{table}` is missing {', '.join(missing)}"
        return None
    except sqlite3.Error as exc:
        return f"it cannot be read ({exc})"
    finally:
        conn.close()


def index_state(db_path: Path | str) -> str:
    """One of ``ok``, ``missing``, ``corrupt``, ``locked``.

    Unsafe filesystem paths raise ValueError and are never quarantined.

    ``locked`` is not corruption: another process is using the database and we
    must not move it aside.

    Detecting it needs a *write* probe. Reading two counts under WAL succeeds while a
    writer holds the database, because readers do not block on the writer — so the
    old ``SELECT count(*)`` returned ``ok``, the caller went on to rebuild, and the
    rebuild blocked for the whole busy timeout and then surfaced
    ``OperationalError: database is locked`` as the answer to the user's first
    message of the chat. ``BEGIN IMMEDIATE`` asks for the write lock, which is the
    thing that is actually contended.
    """
    db_path = checked_database_path(db_path)
    try:
        if not db_path.exists():
            return "missing"
        if db_path.stat().st_size == 0:
            return "missing"
    except OSError:
        return "missing"
    try:
        conn = connect_database(db_path, timeout=LOCK_PROBE_SECONDS)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            conn.execute("SELECT count(*) FROM notes").fetchone()
            conn.execute("SELECT count(*) FROM notes_fts").fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            return "locked"
        return "corrupt"
    except sqlite3.DatabaseError:
        return "corrupt"
    # Locked is decided by the probe above; everything else must also be *shaped* like an
    # index. `BEGIN IMMEDIATE` succeeds on a database with the wrong tables, and `doctor`
    # then reported it healthy while `decisions()` raised `no such column: type`.
    return "ok" if index_schema_problem(db_path) is None else "corrupt"


def index_is_healthy(db_path: Path | str) -> bool:
    return index_state(db_path) == "ok"


# --------------------------------------------------------------------------- #
# quarantine + locking
# --------------------------------------------------------------------------- #


def _quarantine(db_path: Path) -> Path | None:
    """Move an unusable index aside so a rebuild can start clean. Never deletes data."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for attempt in range(1000):
        suffix = f"{stamp}-{os.getpid()}" if attempt == 0 else f"{stamp}-{os.getpid()}-{attempt}"
        backup = db_path.with_name(f"{db_path.name}.corrupt-{suffix}")
        if backup.exists():
            continue
        try:
            db_path.replace(backup)
            # WAL sidecars belonging to the quarantined database would otherwise be
            # replayed into the fresh one, resurrecting the corruption.
            for sidecar_suffix in ("-wal", "-shm"):
                sidecar = db_path.with_name(db_path.name + sidecar_suffix)
                if sidecar.exists():
                    try:
                        sidecar.replace(backup.with_name(backup.name + sidecar_suffix))
                    except OSError:
                        pass
            return backup
        except OSError:
            return None
    return None


class IndexBusyError(TimeoutError):
    """Another process holds the rebuild lock or the database write lock.

    A subclass of ``TimeoutError`` so every existing handler keeps working, while the
    name says what happened. Callers that turn exceptions into tool responses should
    catch this rather than the builtin, which reads like a crash.
    """


class IndexLockUnusable(OSError):
    """The lock path exists but is not a lock we can use.

    Raised instead of blocking. The previous code treated *any* failure to create the
    lock file as "someone else is rebuilding", so a single ``mkdir`` at
    ``.knowledgeos/index-rebuild.lock`` — one ordinary write to the vault — made every
    rebuild fail forever: new notes stayed unsearchable, `breathe` swallowed the error,
    and `doctor` went on reporting a healthy index. A lock that cannot be taken is an
    environment fault the human has to be told about, not a normal busy state.
    """


@contextlib.contextmanager
def _rebuild_lock(vault: Path) -> Iterator[None]:
    from knowledgeos.locking import file_lock

    _state_dir(vault)
    try:
        with file_lock(vault / LOCK_REL, timeout=LOCK_WAIT_SECONDS,
                       message="the note index is being rebuilt by another process; try again in a moment"):
            yield
    except TimeoutError as exc:
        raise IndexBusyError(str(exc)) from exc
    except OSError as exc:
        raise IndexLockUnusable(f"could not take {LOCK_REL}: {exc}") from exc


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #


def _title_from_note(path: Path, text: str, fm: dict) -> str:
    if fm.get("title"):
        return str(fm["title"])
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return "" if value is None else str(value)


def _process_file(args: tuple[Path, Path, dict[str, str]]):
    """Extract one note. Never consults the database: the file is the only authority.

    Round thirteen's critical defect was a cache here — `if rel in db_notes and
    db_notes[rel] == file_hash: return cached`. The comparison was against a column in
    the same writable database as the rows it vouched for, so writing the row and the
    hash together made the rebuild skip the file. The parameter is gone rather than left
    empty, because an empty parameter is an invitation to fill it in again.
    """
    path, vault, lookup = args
    try:
        rel = path.relative_to(vault).as_posix()
        from knowledgeos.remembering import RememberingPolicy, PolicyError, EXCLUDED
        text = RememberingPolicy(vault).read(path)
        if text is None:
            raise PolicyError(EXCLUDED)
        file_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

        fm = parse_frontmatter(text)
        _, body_only = split_frontmatter(text)
        title = _title_from_note(path, text, fm)
        # *Every* field goes through `_as_text`. YAML does not only produce strings: a
        # frontmatter value written as a block list
        #
        #     description:
        #       - cost
        #       - risk
        #
        # is a Python `list`, and `parser.py` advertises that shape as supported. Handing
        # it to `sqlite3` raises `ProgrammingError: Error binding parameter 9: type 'list'
        # is not supported`, which `_try_rebuild` could only report as "degraded" — so ONE
        # ordinary note in a 42-note vault left `notes` and `notes_fts` with zero rows, no
        # manifest written, and every later search answered "Another process is using the
        # note index" while `doctor` printed `[OK] Index healthy` and passed. The
        # coercion used to cover only `tags`, `project` and `lesson`, which is exactly the
        # set of fields the author happened to think of.
        note_data = (
            title,
            rel,
            _as_text(fm.get("type") or "concept"),
            _as_text(fm.get("tags") or ""),
            _as_text(fm.get("project") or ""),
            _as_text(fm.get("status") or "draft"),
            _as_text(fm.get("created") or ""),
            _as_text(fm.get("updated") or ""),
            _as_text(fm.get("description") or ""),
            _as_text(fm.get("resource") or ""),
            _as_text(fm.get("timestamp") or ""),
            _as_text(fm.get("schema") or ""),
            file_hash,
            _as_text(fm.get("id") or ""),
            _as_text(fm.get("confidence") or ""),
            _as_text(fm.get("last_reviewed") or ""),
            _as_text(fm.get("outcome_status") or ""),
            _as_text(fm.get("review_after") or ""),
            _as_text(fm.get("lesson") or "")[:2000],
        )
        resolved_links = [
            (normalize_link(raw, rel, lookup), raw)
            for raw in extract_raw_links(body_only)
        ]
        fts_row = (
            rel,
            title,
            # Index the whole body. Truncating at 1 MB made the tail of a long note
            # silently unsearchable while `get_note` happily returned it.
            body_only,
            _as_text(fm.get("tags") or ""),
            _as_text(fm.get("description") or ""),
        )
        return (rel, (note_data, resolved_links, fts_row))
    except Exception as e:
        try:
            rel = str(path.relative_to(vault).as_posix())
        except ValueError:
            rel = str(path)
        return (rel, e)


def _indexed_paths(cur: sqlite3.Cursor) -> set[str]:
    """Every path the index knows about, from both tables.

    The reconcile needs the *set*, and the union of `notes` and `notes_fts`: reconciling
    only `notes` left an orphan full-text row behind after a `DELETE FROM notes`, and the
    note was then invisible to every list that reads `notes` while `search` still found
    it — two contradictory answers about the same note.
    """
    paths = {row[0] for row in cur.execute("SELECT path FROM notes").fetchall()}
    paths.update(row[0] for row in cur.execute("SELECT path FROM notes_fts").fetchall())
    return paths


# --------------------------------------------------------------------------- #
# rebuild
# --------------------------------------------------------------------------- #


def index_files(vault: Path | str, paths: list[Path]) -> dict[str, Any]:
    """Index specific files in place, for writes that must be searchable at once."""
    vault = checked_database_path(Path(vault) / DB_NAME).parent
    db_path = vault / DB_NAME
    if not db_path.exists():
        return rebuild_index(vault)

    # Before touching anything, ask the signed manifest whether the index it describes
    # is still the index on disk. If it is not, the vault's own capture path would
    # recompute the digest over the tampered rows and sign it, turning a one-shot alarm
    # into a permanent blessing — the reviewer did exactly that: one UPDATE, one
    # `memory_capture`, and `manifest_diff` went from `index_tampered` to `fresh` while
    # the forged title was still served.
    #
    # A capture is not the place to adjudicate trust, so the answer is to hand the whole
    # thing to `rebuild_index`, which re-extracts every note and therefore produces a
    # state that can honestly be signed. Done before taking the rebuild lock, because
    # `rebuild_index` takes it too.
    stored = load_manifest(vault)
    expected_digest = (stored or {}).get("index")
    if not expected_digest:
        # No signed digest: an index written before this field existed, a rotated HMAC
        # key, or a vault copied to a machine whose state folder is new. There is nothing
        # to compare against, so the honest move is a full rebuild — it is the only way
        # to produce a digest that means anything.
        #
        # That costs O(vault): ~1.2 s at 800 notes, ~26 s at 5,000. It happens *once*,
        # because the rebuild writes a digest, and the next capture takes the fast path.
        # Said out loud in the result rather than being an unexplained pause, and named
        # so a caller can tell "the index was rebuilt" from "one file was indexed".
        counts = rebuild_index(vault)
        counts["rebuilt"] = "no_signed_digest"
        return counts
    try:
        probe = connect_database(db_path, timeout=2.0)
        try:
            current_digest = index_digest(probe)
        finally:
            probe.close()
    except sqlite3.Error:
        return rebuild_index(vault)
    if current_digest != expected_digest:
        return rebuild_index(vault)

    with _rebuild_lock(vault):
        md_files = iter_memory_markdown(vault)
        lookup = build_note_lookup(md_files, vault)
        indexable = set(md_files)
        targets = [p for p in paths if p in indexable]
        if not targets:
            return {"notes": 0, "links": 0, "fts_updates": 0, "removed": 0, "failed": []}
        conn = connect_database(db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            cur = conn.cursor()
            counts = _upsert_files(cur, vault, targets, lookup)
            # The fast path used to report `removed: 0` unconditionally and merge only the
            # target signatures into the saved manifest. A note deleted in the same second
            # as a capture therefore survived in the index *and* in the manifest, so the
            # next `manifest_diff` called the vault fresh and the dead row was served
            # indefinitely. Reconcile against the disk like a rebuild does.
            current_paths = {p.relative_to(vault).as_posix() for p in md_files}
            for path in _indexed_paths(cur):
                if path not in current_paths:
                    cur.execute("DELETE FROM notes WHERE path = ?", (path,))
                    cur.execute("DELETE FROM links WHERE source = ?", (path,))
                    cur.execute("DELETE FROM notes_fts WHERE path = ?", (path,))
                    counts["removed"] += 1
            digest = index_digest(conn) or ""
            conn.commit()
        finally:
            conn.close()
        manifest = load_manifest(vault) or {"version": MANIFEST_VERSION, "files": {}}
        files = {
            rel: sig
            for rel, sig in (manifest.get("files") or {}).items()
            if rel in current_paths
        }
        failed_paths = set(counts.get("failed") or [])
        for path in targets:
            rel = path.relative_to(vault).as_posix()
            if rel in failed_paths:
                files.pop(rel, None)
                continue
            signature = _file_signature(path)
            if signature is not None:
                files[rel] = signature
        save_manifest(
            vault,
            {
                "version": MANIFEST_VERSION,
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "files": files,
                "index": digest,
            },
        )
        return counts


def _upsert_files(
    cur: sqlite3.Cursor,
    vault: Path,
    targets: list[Path],
    lookup: dict[str, str],
) -> dict[str, Any]:
    note_count = link_count = fts_updates = 0
    failed: list[str] = []
    for path in targets:
        rel, payload = _process_file((path, vault, lookup))
        if isinstance(payload, Exception):
            failed.append(rel)
            continue
        note_data, resolved_links, fts_row = payload
        cur.execute("DELETE FROM links WHERE source = ?", (rel,))
        cur.execute(_INSERT_NOTE_SQL, note_data)
        cur.execute("DELETE FROM notes_fts WHERE path = ?", (rel,))
        cur.execute(
            "INSERT INTO notes_fts(path, title, body, tags, description) VALUES (?, ?, ?, ?, ?)",
            fts_row,
        )
        fts_updates += 1
        note_count += 1
        for dest, raw in resolved_links:
            cur.execute(
                "INSERT INTO links (source, destination, raw_destination) VALUES (?, ?, ?)",
                (rel, dest, raw),
            )
            link_count += 1
    return {
        "notes": note_count,
        "links": link_count,
        "fts_updates": fts_updates,
        "removed": 0,
        "failed": failed,
    }


def rebuild_index(vault: Path | str) -> dict[str, Any]:
    """Create or refresh ``<vault>/knowledge_index.db``. Returns counts."""
    vault = checked_database_path(Path(vault) / DB_NAME).parent
    with _rebuild_lock(vault):
        md_files = iter_memory_markdown(vault)
        lookup = build_note_lookup(md_files, vault)
        db_path = vault / DB_NAME
        state = index_state(db_path)
        if state == "corrupt":
            backup = _quarantine(db_path)
            if backup is None:
                raise OSError("The unusable note index could not be moved aside; it may still be open")
            print(f"Moved unusable index to {backup.name}", file=sys.stderr)

        conn = connect_database(db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            counts = _write_index(conn, vault, md_files, lookup)
        finally:
            conn.close()
        final_state = index_state(db_path)
        if final_state != "ok":
            raise OSError(f"The rebuilt note index is not usable ({final_state})")
        failed = set(counts.get("failed", []) or [])
        digest = counts.pop("index_digest", None)
        save_manifest(
            vault, build_manifest(vault, md_files, skip=failed, index_digest=digest)
        )
        counts["index_state"] = final_state
        return counts


def _write_index(
    conn: sqlite3.Connection,
    vault: Path,
    md_files: list[Path],
    lookup: dict[str, str],
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.executescript(_SCHEMA_SQL)
    cur.execute(_FTS_SQL)

    link_cols = [r[1] for r in cur.execute("PRAGMA table_info(links)")]
    added_raw_destination = "raw_destination" not in link_cols
    if added_raw_destination:
        cur.execute("ALTER TABLE links ADD COLUMN raw_destination TEXT")
        # Rows written before this column existed have no raw destination, so their
        # stored `destination` cannot be re-normalised when the note is cached — and
        # `normalize_link(None, …)` raised on the first such row, crashing the upgrade.
        # Without the source text there is nothing to recover, so reprocess every note
        # once; the new rows carry `raw_destination` and are re-normalisable from then on.
        cur.execute("UPDATE notes SET file_hash = NULL")
    note_cols = [r[1] for r in cur.execute("PRAGMA table_info(notes)")]
    for col in _ADDED_NOTE_COLUMNS:
        if col not in note_cols:
            cur.execute(f"ALTER TABLE notes ADD COLUMN {col} TEXT")

    try:
        empty_v03 = cur.execute(
            "SELECT COUNT(*) FROM notes WHERE IFNULL(entity_id,'')='' AND IFNULL(outcome_status,'')=''"
        ).fetchone()[0]
        total = cur.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        if total and empty_v03 == total:
            cur.execute("UPDATE notes SET file_hash = NULL")
    except sqlite3.Error:
        pass

    current_paths = {p.relative_to(vault).as_posix() for p in md_files}
    # Reconcile the *union* of the two tables. Removing only the paths `notes` knows
    # about left a `notes_fts` row behind after `DELETE FROM notes`, and the note was then
    # invisible to every list that reads `notes` while `search` still found it — two
    # contradictory answers about the same note. Both tables are cleared for anything
    # that is no longer on disk.
    removed = 0
    for path in _indexed_paths(cur):
        if path not in current_paths:
            cur.execute("DELETE FROM notes WHERE path = ?", (path,))
            cur.execute("DELETE FROM links WHERE source = ?", (path,))
            cur.execute("DELETE FROM notes_fts WHERE path = ?", (path,))
            removed += 1

    # Every note is re-extracted on every rebuild. There is no "unchanged" shortcut to
    # take, which is the point: a row that claims to be unchanged is a row nobody checked.
    note_count = link_count = fts_updates = 0
    failed: list[str] = []
    worker_args = [(p, vault, lookup) for p in md_files]
    workers = min(8, max(1, (os.cpu_count() or 2)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_process_file, worker_args))

    for rel, payload in results:
        if isinstance(payload, Exception):
            print(f"Error processing {rel}: {payload}", file=sys.stderr)
            failed.append(rel)
            continue
        note_data, resolved_links, fts_row = payload
        cur.execute("DELETE FROM links WHERE source = ?", (rel,))
        cur.execute(_INSERT_NOTE_SQL, note_data)
        cur.execute("DELETE FROM notes_fts WHERE path = ?", (rel,))
        cur.execute(
            "INSERT INTO notes_fts(path, title, body, tags, description) VALUES (?, ?, ?, ?, ?)",
            fts_row,
        )
        fts_updates += 1
        note_count += 1
        for dest, raw in resolved_links:
            cur.execute(
                "INSERT INTO links (source, destination, raw_destination) VALUES (?, ?, ?)",
                (rel, dest, raw),
            )
            link_count += 1

    for key, value in (
        ("last_rebuild_note_count", note_count),
        ("last_rebuild_link_count", link_count),
        ("last_fts_updates", fts_updates),
        ("last_rebuild_removed", removed),
    ):
        cur.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    # Computed at the very end, from the rows themselves, so it cannot describe a state
    # that was never written.
    index_digest_value = index_digest(conn) or ""
    return {
        "notes": note_count,
        "links": link_count,
        "fts_updates": fts_updates,
        "removed": removed,
        "failed": failed,
        "index_digest": index_digest_value,
    }
