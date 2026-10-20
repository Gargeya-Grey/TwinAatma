"""Hermetic test support: every test builds its own vault in a temp dir.

Rules enforced here so the suite can never mutate the repo:

* ``ROOT`` is only ever *read* (as the toolkit source for ``init_vault``).
* Vaults live under a per-test ``TemporaryDirectory``.
* ``SelfGuard`` records ``sha256(Self.md)``; any test that claims a gate held
  asserts the digest is unchanged, not just that an error string was returned.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fake_terminal():
    """Pretend stdin/stdout are a TTY, for tests of the human approval path."""
    return mock.patch.multiple(
        sys, stdin=mock.MagicMock(isatty=lambda: True), stdout=mock.MagicMock(isatty=lambda: True)
    )


class SelfGuard:
    """Assert that Self.md did not change across an operation."""

    def __init__(self, vault: Path) -> None:
        self.path = Path(vault) / "People" / "Self.md"

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def __enter__(self) -> "SelfGuard":
        self.before = self.digest()
        return self

    def __exit__(self, *exc_info) -> None:
        self.after = self.digest()

    def assert_unchanged(self, case: unittest.TestCase) -> None:
        case.assertEqual(
            self.before,
            self.after,
            "People/Self.md changed when the gate should have refused the write",
        )


def seed_owner_identity(vault: Path) -> None:
    """Explicit synthetic owner facts for integrity tests, never production defaults."""
    from knowledgeos.gate import replace_section
    path = vault / "People/Self.md"
    text = path.read_text(encoding="utf-8")
    sections = {
        "heuristics": "* Prefer durability over cleverness — markdown remains source of truth.\n* Write a decision note before major scope shifts.\n* Close loops: Capture → Decide → Outcome → Lesson → Self update.",
        "values": "1. **Clarity**\n2. **Autonomy**\n3. **Execution**",
        "mental_models": "* First Principles\n* Inversion",
        "anti_goals": "* Building before validating\n* Letting Inbox grow without triage",
        "active_bets": "* Evaluate this synthetic vault.",
        "drift_log": "| Topic | Shift Observed | Date Flagged | Evidence |\n|---|---|---|---|\n| Bootstrap | Vault initialized | 2026-01-01 | Synthetic owner fixture |",
    }
    for key, body in sections.items():
        text, found = replace_section(text, key, body, mode="replace")
        assert found
    path.write_bytes(text.encode("utf-8"))


class TempVaultCase(unittest.TestCase):
    """Base case: a fresh, real vault created by the toolkit's own initializer."""

    owner = "Test"

    def setUp(self) -> None:
        from knowledgeos.init_vault import init_vault

        self._tmp = tempfile.TemporaryDirectory(prefix="ta-test-")
        self.root = Path(self._tmp.name).resolve()
        self.vault = self.root / "vault"
        # Keep the gate ledger, key and lock out of the real install so tests are
        # hermetic and can never touch the machine's actual proposal history.
        self._old_state = os.environ.get("KNOWLEDGEOS_STATE_DIR")
        os.environ["KNOWLEDGEOS_STATE_DIR"] = str(self.root / "state")
        self.init_result = init_vault(
            self.vault,
            source_root=ROOT,
            owner_name=self.owner,
            non_interactive=True,
        )
        seed_owner_identity(self.vault)

    def tearDown(self) -> None:
        if self._old_state is None:
            os.environ.pop("KNOWLEDGEOS_STATE_DIR", None)
        else:
            os.environ["KNOWLEDGEOS_STATE_DIR"] = self._old_state
        self._tmp.cleanup()

    # --- helpers -----------------------------------------------------------

    def api(self):
        from knowledgeos.memory import MemoryAPI

        return MemoryAPI(self.vault)

    def self_text(self) -> str:
        return (self.vault / "People" / "Self.md").read_text(encoding="utf-8")

    def section(self, heading: str) -> str:
        text = self.self_text()
        start = text.index(heading)
        end = text.find("\n## ", start + 1)
        return text[start : end if end != -1 else len(text)]

    def guard(self) -> SelfGuard:
        return SelfGuard(self.vault)

    def approve(self, proposal_path, api=None):
        """Apply a proposal the way a human does: a real terminal, then the gate.

        The gate refuses without a TTY, so the test must fake the one thing a human
        really has and an agent calling a tool does not. `Home` is a context manager
        for asserting the opposite.
        """
        from knowledgeos import gate

        api = api or self.api()
        with fake_terminal():
            return gate.approve_interactive(
                api.vault, api.self_path, api.proposals_dir, str(proposal_path)
            )

    def write(self, rel: str, text: str) -> Path:
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def proposal_files(self) -> list[Path]:
        return sorted((self.vault / "People" / "Self-Proposals").glob("*.md"))


def repo_is_clean() -> bool:
    """True when the working tree has no modifications."""

    def _git(*args: str) -> str | None:
        import subprocess

        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None

    status = _git("status", "--porcelain")
    if status is None:
        # No git here. Do not pretend the tree is clean: say so, because a caller that
        # treats "unknown" as "clean" is asserting nothing.
        return False
    return not status.strip()


def snapshot(paths: list[Path]) -> dict[str, object]:
    """A comparable fingerprint of paths that may or may not exist.

    `IsolationTests` compares this before and after a run, so an index or proposal
    directory reappearing in the repository shows up as a difference. `stat` alone was
    not enough: a directory that is created and then populated has an unchanged mtime
    for its own entry on some filesystems.
    """
    out: dict[str, object] = {}
    for path in paths:
        if not path.exists():
            out[str(path)] = None
            continue
        if path.is_dir():
            entries = sorted(
                (p.name, p.stat().st_mtime_ns if p.exists() else None)
                for p in path.iterdir()
            )
            out[str(path)] = ("dir", entries)
        else:
            stat = path.stat()
            out[str(path)] = ("file", stat.st_mtime_ns, stat.st_size)
    return out
