"""Retained synthetic fixtures for read-only proposal preview checks."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / 'work/gc-artifacts/.knowledgeos/preview-authenticity-regression'
BASE = (
    "# Synthetic Preview Owner\n\n"
    "## Heuristics\n<!-- kos:section=heuristics -->\n"
    "* Keep careful notes for this synthetic fixture.\n\n"
    "## Values\n<!-- kos:section=values -->\n"
    "* Preserve independently supplied owner choices.\n"
).encode("utf-8")
PATCH = "* Ask for a second opinion before changing a synthetic preference."
SUMMARY = "Synthetic preference proposal for preview verification."


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_gate(source: str):
    from knowledgeos import gate
    return gate


class Fixture:
    def __init__(self, gate, group: str):
        self.gate = gate
        self.scope = UNIT / "fixtures" / group / uuid.uuid4().hex[:12]
        self.vault = self.scope / "vault"
        self.self_path = self.vault / "People" / "Self.md"
        self.proposals = self.vault / "People" / "Self-Proposals"
        self.proposals.mkdir(parents=True)
        self.self_path.write_bytes(BASE)
        self.saved_env = {name: os.environ.get(name) for name in (
            "KNOWLEDGEOS_STATE_DIR", "KNOWLEDGEOS_GATE_KEY",
        )}
        os.environ["KNOWLEDGEOS_STATE_DIR"] = str(self.scope / "gate-state")
        os.environ.pop("KNOWLEDGEOS_GATE_KEY", None)
        originals = self.scope / "originals"
        originals.mkdir()
        (originals / "Self.md").write_bytes(BASE)

    def close(self):
        for name, value in self.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def propose(self, *, mode="append", patch=PATCH, summary=SUMMARY):
        result = self.gate.propose(
            self.vault, self.self_path, self.proposals, summary,
            "heuristics", patch, mode=mode, allow_destructive=(mode == "replace"),
        )
        if not result.get("ok"):
            raise AssertionError(result)
        path = self.vault / result["proposal_path"]
        original = path.read_bytes()
        (self.scope / "originals" / path.name).write_bytes(original)
        return path, original

    def describe(self, path):
        return self.gate.describe(self.vault, self.proposals, str(path))

    def preserve(self, path, original):
        assert self.self_path.read_bytes() == BASE
        assert path.read_bytes() == original
        assert (self.scope / "originals" / "Self.md").read_bytes() == BASE
        assert (self.scope / "originals" / path.name).read_bytes() == original
