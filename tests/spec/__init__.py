"""A deterministic scorecard for TwinAatma: claims, scenarios, and a number.

Why this exists
---------------
Eleven rounds of adversarial review produced 31, 28, 38, 34, 22, 38, 34, then 34 again.
That sequence is not a measurement trending anywhere. Each round drew a different reader
who probed a different surface, so "is this better than yesterday" could not be answered:
a fix and a regression looked the same. More rounds bought more opinions, not a position.

This module is the position. Every clause of the product promise becomes a *scenario* —
a claim, an observation, a verdict — and the score is the weighted pass rate over those
scenarios. It is reproducible: same tree, same number, no reviewer variance.

What it is not
--------------
It cannot find a class of bug nobody imagined. It found none of the first eleven rounds'
defects by itself, because a spec written from imagination encodes what its author
already knows. So the corpus is *seeded from the reviewers' reproducers*: every finding
becomes a permanent scenario before its fix. The reviewer's job narrows to exploring for
genuinely new classes; this stops being paid for twice.

Scenarios are behavioral, not structural. "An ordinary vault write cannot change
Self.md" is durable. "gate.py delegates to textio.atomic_write" rots on the next
refactor and says nothing about whether the product works.

Scoring
-------
Each scenario has a weight (default 1) inside its dimension. A dimension scores the
fraction of *applicable* weight that passed; the total is the weighted mean of the six
dimension scores. Weights live in ``DIMENSIONS`` below and are deliberately not tunable
by the code being measured. ``SKIP`` is excluded from the denominator rather than counted
as either outcome: a check that cannot run on this platform is not evidence either way.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

# --------------------------------------------------------------------------- #
# weights: declared once, visible, arguable, and never read from product code
# --------------------------------------------------------------------------- #

DIMENSIONS: dict[str, int] = {
    # The identity boundary is the thing that must not break. Everything else is
    # recoverable by comparison.
    "identity_safety": 30,
    # A gate a human cannot read is a gate that consents to anything.
    "approval_fidelity": 25,
    # Notes, index and state must stay where they belong and survive ordinary use.
    "vault_integrity": 15,
    # The product's whole value is that what it quotes is what the user wrote.
    "truthfulness_of_reads": 15,
    # Silent staleness is the default failure mode of a background index.
    "autopilot_reliability": 10,
    # Honest packaging: installable, diagnosable, documented as built.
    "install_ops_honesty": 5,
}

DIMENSION_TITLES = {
    "identity_safety": "Identity safety",
    "approval_fidelity": "Approval fidelity",
    "vault_integrity": "Vault integrity",
    "truthfulness_of_reads": "Truthfulness of reads",
    "autopilot_reliability": "Autopilot reliability",
    "install_ops_honesty": "Install/ops honesty",
}


# --------------------------------------------------------------------------- #
# scenario model
# --------------------------------------------------------------------------- #


class ScenarioFailure(AssertionError):
    """A scenario ran and the product did not do what the claim says."""


class ScenarioSkip(Exception):
    """This check does not apply here; excluded from the denominator."""


@dataclass(frozen=True)
class Scenario:
    id: str
    dimension: str
    claim: str
    source: str
    run: Callable[["Case"], None]
    weight: int = 1


SCENARIOS: dict[str, Scenario] = {}


def scenario(
    scenario_id: str,
    dimension: str,
    claim: str,
    source: str,
    weight: int = 1,
) -> Callable[[Callable[["Case"], None]], Callable[["Case"], None]]:
    """Register a scenario. The id is the permanent name; never reuse one."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"scenario {scenario_id}: unknown dimension {dimension!r}")

    def register(fn: Callable[["Case"], None]) -> Callable[["Case"], None]:
        if scenario_id in SCENARIOS:
            raise ValueError(f"duplicate scenario id: {scenario_id}")
        SCENARIOS[scenario_id] = Scenario(
            id=scenario_id,
            dimension=dimension,
            claim=claim,
            source=source,
            run=fn,
            weight=weight,
        )
        return fn

    return register


# --------------------------------------------------------------------------- #
# assertions: fail with a sentence a human can act on
# --------------------------------------------------------------------------- #


def fail(message: str) -> None:
    raise ScenarioFailure(message)


def expect(condition: Any, message: str) -> None:
    if not condition:
        raise ScenarioFailure(message)


def expect_equal(actual: Any, expected: Any, what: str) -> None:
    if actual != expected:
        raise ScenarioFailure(f"{what}: expected {expected!r}, got {actual!r}")


def expect_in(needle: Any, haystack: Any, what: str) -> None:
    try:
        found = needle in haystack
    except TypeError:
        found = False
    if not found:
        raise ScenarioFailure(f"{what}: {needle!r} not present in {haystack!r:.400}")


def skip(reason: str) -> None:
    raise ScenarioSkip(reason)


# --------------------------------------------------------------------------- #
# a case: one hermetic vault per scenario
# --------------------------------------------------------------------------- #


class Case:
    """A fresh vault, a private state directory, and the helpers a scenario needs."""

    def __init__(self, root: Path, state_dir: Path, vault: Path) -> None:
        self.root = root
        self.state_dir = state_dir
        self.vault = vault

    # --- construction ------------------------------------------------------

    @classmethod
    def build(cls, root: Path) -> "Case":
        from knowledgeos.init_vault import init_vault

        root = root.resolve()
        state_dir = root / "state"
        os.environ["KNOWLEDGEOS_STATE_DIR"] = str(state_dir)
        vault = root / "vault"
        init_vault(vault, source_root=ROOT, owner_name="Spec", non_interactive=True)
        from support import seed_owner_identity
        seed_owner_identity(vault)
        return cls(root, state_dir, vault)

    # --- accessors ---------------------------------------------------------

    def api(self):
        from knowledgeos.memory import MemoryAPI

        return MemoryAPI(self.vault)

    @property
    def self_path(self) -> Path:
        return self.vault / "People" / "Self.md"

    def self_text(self) -> str:
        return self.self_path.read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> Path:
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def body(self, section: str) -> str:
        from knowledgeos import gate

        return gate.section_body(self.self_text(), section) or ""

    def proposals(self) -> list[Path]:
        directory = self.vault / "People" / "Self-Proposals"
        return sorted(directory.glob("*.md")) if directory.is_dir() else []

    # --- the human path ----------------------------------------------------

    def fake_terminal(self):
        """Stand in for the one thing a human has and an agent does not.

        The gate refuses without a TTY on purpose; a scenario about what happens *after*
        a human says yes must supply it, and a scenario about the refusal must not.
        """
        from unittest import mock

        return mock.patch.multiple(
            sys,
            stdin=mock.MagicMock(isatty=lambda: True),
            stdout=mock.MagicMock(isatty=lambda: True),
        )

    def approve(self, proposal_path: Any, api=None):
        from knowledgeos import gate

        api = api or self.api()
        with self.fake_terminal():
            return gate.approve_interactive(
                api.vault, api.self_path, api.proposals_dir, str(proposal_path)
            )

    def propose(self, **kwargs):
        api = kwargs.pop("api", None) or self.api()
        result = api.propose_self_update(**kwargs)
        expect("error" not in result, f"proposal was rejected: {result.get('error')}")
        return self.vault / result["proposal_path"]


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    scenario: Scenario
    verdict: str  # PASS | FAIL | SKIP | ERROR
    detail: str = ""


def run_scenario(item: Scenario) -> Result:
    with tempfile.TemporaryDirectory(prefix="ta-spec-") as tmp:
        root = Path(tmp)
        previous = os.environ.get("KNOWLEDGEOS_STATE_DIR")
        try:
            case = Case.build(root)
            item.run(case)
            return Result(item, "PASS")
        except ScenarioSkip as exc:
            return Result(item, "SKIP", str(exc))
        except ScenarioFailure as exc:
            return Result(item, "FAIL", str(exc))
        except Exception as exc:  # noqa: BLE001 - a crash is a failure, not a traceback
            return Result(
                item,
                "ERROR",
                f"{type(exc).__name__}: {exc}".strip() or "no message",
            )
        finally:
            if previous is None:
                os.environ.pop("KNOWLEDGEOS_STATE_DIR", None)
            else:
                os.environ["KNOWLEDGEOS_STATE_DIR"] = previous


def scorecard(results: list[Result]) -> dict[str, Any]:
    """The number. Weighted within each dimension, then weighted across dimensions."""
    dimensions: dict[str, Any] = {}
    total_weight = 0
    total_points = 0.0
    for name, weight in DIMENSIONS.items():
        mine = [r for r in results if r.scenario.dimension == name]
        applicable = [r for r in mine if r.verdict != "SKIP"]
        earned = sum(r.scenario.weight for r in applicable if r.verdict == "PASS")
        available = sum(r.scenario.weight for r in applicable)
        # A dimension with nothing to measure is not "perfect", it is unmeasured, and
        # including it as 100% inflates a filtered run. It leaves the weighted mean
        # entirely (`--only` then reports the score of what it actually ran).
        measured = available > 0
        fraction = (earned / available) if measured else 0.0
        dimensions[name] = {
            "title": DIMENSION_TITLES[name],
            "weight": weight,
            "measured": measured,
            "score": round(100 * fraction, 1) if measured else None,
            "passed": sum(1 for r in applicable if r.verdict == "PASS"),
            "failed": sum(1 for r in applicable if r.verdict != "PASS"),
            "skipped": sum(1 for r in mine if r.verdict == "SKIP"),
            "scenarios": [r.scenario.id for r in applicable],
        }
        # Unmeasured dimensions are excluded, so a filtered run cannot claim 100/100.
        if measured:
            total_weight += weight
            total_points += weight * fraction
    overall = (100 * total_points / total_weight) if total_weight else 0.0
    return {
        "score": round(overall, 1),
        "dimensions": dimensions,
        "failures": [
            {
                "scenario": r.scenario.id,
                "dimension": r.scenario.dimension,
                "claim": r.scenario.claim,
                "verdict": r.verdict,
                "detail": r.detail,
                "source": r.scenario.source,
            }
            for r in results
            if r.verdict not in {"PASS", "SKIP"}
        ],
        "skipped": [
            {"scenario": r.scenario.id, "reason": r.detail}
            for r in results
            if r.verdict == "SKIP"
        ],
    }


def run_all(only: str | None = None) -> list[Result]:
    import knowledgeos  # noqa: F401  - import once, so a broken install fails loudly

    from spec import scenarios  # noqa: F401  - registers the corpus

    selected = [
        SCENARIOS[key]
        for key in sorted(SCENARIOS)
        if only is None or only in key or only in SCENARIOS[key].dimension
    ]
    return [run_scenario(item) for item in selected]


# --------------------------------------------------------------------------- #
# baseline: direction of travel as a diff, not a memory
# --------------------------------------------------------------------------- #

BASELINE = Path(__file__).resolve().parent / "baseline.json"


def load_baseline() -> dict[str, Any] | None:
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_baseline(card: dict[str, Any]) -> None:
    BASELINE.write_text(
        json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def compare(card: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """What moved since the baseline. A regression is the only thing that matters."""
    old_pass = set(previous.get("passing") or [])
    new_pass = set(card.get("passing") or [])
    before = previous.get("dimensions") or {}
    deltas = {}
    for name in DIMENSIONS:
        now = card["dimensions"][name]
        was = before.get(name) or {}
        if not now.get("measured") or was.get("score") is None:
            continue
        deltas[name] = round(now["score"] - was["score"], 1)
    return {
        "score_delta": round(card["score"] - float(previous.get("score") or 0.0), 1),
        "dimensions": deltas,
        "newly_passing": sorted(new_pass - old_pass),
        "newly_failing": sorted(old_pass - new_pass),
    }
