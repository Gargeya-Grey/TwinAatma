"""Vault resolution: --vault > KNOWLEDGEOS_VAULT > walk-up from cwd."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

MARKER_FILES = (".knowledgeos-vault.json", "knowledgeos.config.json")
SELF_REL = Path("People") / "Self.md"
MARKER_LIMIT = 64 * 1024


class HostVaultError(ValueError):
    """The configured memory vault cannot be discovered safely."""


def normalize_host_vault_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{16,64}", value) is None:
        raise HostVaultError("The host vault ID must contain 16 to 64 hexadecimal characters.")
    return value.lower()


def configured_host_vault_id(arguments: list[str]) -> str | None:
    """Read the binding without accepting duplicate or partially formed flags."""
    if not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments):
        raise HostVaultError("The configured server args must be a list of strings.")
    values = []
    for index, item in enumerate(arguments):
        if item == "--host-vault-id":
            if index + 1 == len(arguments):
                raise HostVaultError("--host-vault-id requires the complete vault ID.")
            values.append(normalize_host_vault_id(arguments[index + 1]))
        elif item.startswith("--host-vault-id="):
            values.append(normalize_host_vault_id(item.partition("=")[2]))
        elif item.startswith("--host-vault"):
            raise HostVaultError("Malformed --host-vault-id flag; preserved the configuration.")
    if len(values) > 1:
        raise HostVaultError("Duplicate --host-vault-id flags; preserved the configuration.")
    return values[0] if values else None


def check_host_binding_migration(existing_args: list[str], generated_args: list[str]) -> None:
    existing = configured_host_vault_id(existing_args)
    generated = configured_host_vault_id(generated_args)
    if existing is not None and existing != generated:
        raise HostVaultError(
            "Preserved the host configuration: an existing vault binding cannot be removed or rebound. "
            "Restore the matching vault marker before retrying setup."
        )


def _identity(info):
    return info.st_dev, info.st_ino


def _plain(info) -> bool:
    return not (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _file_observation(info):
    # Windows lstat and fstat expose different creation/change times.
    return (_identity(info), info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HostVaultError("A vault marker contains duplicate JSON keys.")
        result[key] = value
    return result


class _VaultMarkers:
    """One read-only observation, with shared parent checks and a final race check."""

    def __init__(self):
        self.directories = {}
        self.files = {}
        self.missing = set()

    def directory(self, raw: Path | str) -> Path | None:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        for component in (*reversed(path.parents), path):
            if component in self.directories:
                continue
            try:
                info = component.lstat()
            except FileNotFoundError:
                self.missing.add(component)
                return None
            if not stat.S_ISDIR(info.st_mode) or not _plain(info):
                raise HostVaultError(f"Vault discovery refuses a linked or non-directory path: {component}")
            if not info.st_ino:
                raise HostVaultError(f"Vault directory identity is unavailable: {component}")
            self.directories[component] = info
        normalized = Path(os.path.normpath(path))
        self.directories.setdefault(normalized, self.directories[path])
        return normalized

    def marker(self, path: Path) -> dict | None:
        try:
            expected = path.lstat()
        except FileNotFoundError:
            self.missing.add(path)
            return None
        if not stat.S_ISREG(expected.st_mode) or not _plain(expected) or expected.st_nlink != 1:
            raise HostVaultError(f"Vault discovery requires a plain single-link marker: {path}")
        if expected.st_size > MARKER_LIMIT:
            raise HostVaultError(f"Vault marker exceeds the 64 KiB discovery limit: {path}")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            actual = os.fstat(handle.fileno())
            if _file_observation(actual) != _file_observation(expected):
                raise HostVaultError(f"Vault marker changed while opening it: {path}")
            raw = handle.read(MARKER_LIMIT + 1)
            after = os.fstat(handle.fileno())
            if (len(raw) > MARKER_LIMIT or _file_observation(after) != _file_observation(actual)
                    or after.st_ctime_ns != actual.st_ctime_ns):
                raise HostVaultError(f"Vault marker changed while reading it: {path}")
        self.files[path] = expected
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeError, ValueError) as error:
            raise HostVaultError(f"Malformed vault marker; preserved its bytes: {path} ({error})") from error
        if not isinstance(value, dict):
            raise HostVaultError(f"Vault marker must be a JSON object: {path}")
        return value

    def vault_id(self, root: Path) -> str | None:
        values = set()
        for name in MARKER_FILES:
            value = self.marker(root / name)
            if value is not None and "vault_id" in value:
                values.add(normalize_host_vault_id(value["vault_id"]))
        if len(values) > 1:
            raise HostVaultError(f"The two vault markers contain conflicting IDs: {root}")
        return next(iter(values)) if values else None

    def finish(self):
        for path, expected in self.directories.items():
            actual = path.lstat()
            if not stat.S_ISDIR(actual.st_mode) or not _plain(actual) or _identity(actual) != _identity(expected):
                raise HostVaultError(f"Vault directory changed during discovery: {path}")
        for path, expected in self.files.items():
            actual = path.lstat()
            if (_file_observation(actual) != _file_observation(expected) or not _plain(actual)
                    or actual.st_ctime_ns != expected.st_ctime_ns):
                raise HostVaultError(f"Vault marker changed during discovery: {path}")
        for path in self.missing:
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            raise HostVaultError(f"Vault path appeared during discovery; retry after inspecting it: {path}")


def read_vault_id(vault: Path | str) -> str | None:
    """Read the full discovery ID without touching signing or memory state."""
    try:
        observation = _VaultMarkers()
        root = observation.directory(vault)
        result = observation.vault_id(root) if root is not None else None
        observation.finish()
        return result
    except OSError as error:
        raise HostVaultError(f"Vault discovery could not inspect a plain marker: {error}") from error


def resolve_host_vault(expected_vault_id: str, explicit: Path | str | None = None,
                       cwd: Path | str | None = None) -> Path:
    """Resolve only the bound vault in cwd ancestors or one checked fallback."""
    expected = normalize_host_vault_id(expected_vault_id)
    base = Path(cwd).expanduser() if cwd is not None else Path.cwd()
    if not base.is_absolute():
        base = Path.cwd() / base
    fallback = explicit if explicit is not None else os.environ.get("KNOWLEDGEOS_VAULT")
    candidates = [base, *base.parents]
    if fallback is not None:
        fallback = Path(fallback).expanduser()
        if not fallback.is_absolute():
            raise HostVaultError("A bound host vault fallback must be an absolute path.")
        candidates.append(fallback)
    try:
        observation = _VaultMarkers()
        matches = {}
        checked = set()
        for candidate in candidates:
            root = observation.directory(candidate)
            if root is None or root in checked:
                continue
            checked.add(root)
            if observation.vault_id(root) == expected:
                info = observation.directories[root]
                matches[_identity(info)] = root
        observation.finish()
    except OSError as error:
        raise HostVaultError(f"Bound vault discovery failed before memory startup: {error}") from error
    if len(matches) > 1:
        raise HostVaultError("The host vault ID is ambiguous across distinct visible vaults; memory startup refused.")
    if not matches:
        raise HostVaultError("The configured host vault was not found in project ancestors or its checked fallback.")
    return next(iter(matches.values()))


def is_vault_root(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        if (path / SELF_REL).exists():
            return True
        return any((path / m).exists() for m in MARKER_FILES)
    except OSError:
        return False


def walk_up(start: Path) -> Path | None:
    cur = start.resolve()
    while True:
        if is_vault_root(cur):
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent


def resolve_vault(explicit: Path | str | None = None, cwd: Path | str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            # An explicit path always wins, even if it is not a vault: ignoring it
            # would silently operate on a different vault than the caller named.
            return p.resolve()
        # A recorded absolute path goes stale the moment the vault is moved or
        # renamed (or opened on another machine). The generated MCP config stores
        # one, so fall back to walking up from the working directory — the host
        # launches the server inside the vault — instead of failing every call.
        base = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
        found = walk_up(base)
        if found:
            return found
        return p.resolve()
    env = os.environ.get("KNOWLEDGEOS_VAULT")
    if env:
        candidate = Path(env).expanduser()
        if candidate.is_dir() and is_vault_root(candidate.resolve()):
            return candidate.resolve()
    base = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    found = walk_up(base)
    if found:
        return found
    return base


def require_vault(explicit: Path | str | None = None, cwd: Path | str | None = None) -> Path:
    """Like :func:`resolve_vault`, but refuses to invent a vault out of any directory.

    Previously any random directory became the vault: the first memory call created
    ``.knowledgeos/`` and an index there and returned success, so a user who ran the
    tool in the wrong folder got a silently empty "memory" instead of an error.
    """
    vault = resolve_vault(explicit, cwd)
    if not is_vault_root(vault):
        raise ValueError(
            f"{vault} is not a TwinAatma vault (no People/Self.md and no vault marker). "
            "Pass --vault, set KNOWLEDGEOS_VAULT, or run `twinaatma init <path>` first."
        )
    return vault


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts or (0,))


def vault_version_check(vault: Path) -> str | None:
    """Warn when a vault was created by a newer toolkit than this one.

    Returned rather than printed: the caller decides whether the human sees it.
    """
    marker = Path(vault) / ".knowledgeos-vault.json"
    if not marker.exists():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = str(data.get("toolkit_min_version") or "")
    if not required:
        return None
    from knowledgeos import __version__ as current

    if _version_tuple(required) > _version_tuple(current):
        return (
            f"This vault expects toolkit {required} or newer; this build is {current}. "
            "Update the toolkit to avoid writing notes it cannot read."
        )
    return None
