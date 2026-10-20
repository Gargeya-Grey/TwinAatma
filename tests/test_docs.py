"""Docs-vs-code contract: every command and tool the docs promise must exist.

This is the test that would have caught README instructions for ``scripts/``
files that a data-only vault does not have, and the ``twinaatma serve`` command
that was never implemented.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import support  # noqa: F401  (adds the repo root to sys.path)
from support import ROOT

READMES = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CONTRIBUTING.md"]
CLI_COMMANDS = {
    "init",
    "mcp",
    "setup-host",
    "doctor",
    "validate",
    "ids",
    "self",
    "memory",
    "breathe",
    "version",
}
FORBIDDEN = [
    # Commands that never existed, or that only existed as unchecked claims.
    r"twinaatma\s+serve",
    r"knowledgeos\s+serve",
    # A data-only vault has no scripts/ directory; documenting it is a lie.
    r"python\s+scripts/",
]


def _doc_texts() -> list[tuple[Path, str]]:
    out = []
    for path in READMES:
        if path.exists():
            out.append((path, path.read_text(encoding="utf-8")))
    return out


class DocsContractTests(unittest.TestCase):
    def test_every_test_named_in_the_guarantee_table_exists(self):
        """A guarantee table that cites a renamed test proves nothing.

        The table is the README's whole claim to trustworthiness. It is a list of
        names, and a name is free: renaming one test used to leave the README citing
        a test that no longer existed, with nothing failing.
        """
        defined = set()
        sources = sorted((ROOT / "tests").glob("test_*.py"))
        for source in sources:
            defined.update(
                name
                for name in re.findall(r"^\s*def (test_[A-Za-z0-9_]+)", source.read_text(encoding="utf-8"), re.M)
            )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cited = set(re.findall(r"\b(test_[A-Za-z0-9_]+)\b", readme))
        cited -= {source.stem for source in sources}  # file names, not test names
        missing = sorted(cited - defined)
        self.assertEqual(
            missing,
            [],
            "README cites tests that do not exist: " + ", ".join(missing),
        )

    def test_no_documented_command_is_missing(self):
        for path, text in _doc_texts():
            for token in re.findall(r"(?:twinaatma|python -m knowledgeos)\s+([a-z][a-z0-9-]*)", text):
                if token in {"pip", "install", "m", "and"}:
                    continue
                self.assertIn(
                    token,
                    CLI_COMMANDS,
                    f"{path.name} documents '{token}', which the CLI does not implement",
                )

    def test_no_dead_or_unimplemented_instructions(self):
        for path, text in _doc_texts():
            for pattern in FORBIDDEN:
                self.assertIsNone(
                    re.search(pattern, text),
                    f"{path.name} still documents {pattern!r}",
                )

    def test_every_documented_tool_exists(self):
        from knowledgeos.memory import TOOL_SPECS

        names = {spec["name"] for spec in TOOL_SPECS}
        for path, text in _doc_texts():
            for token in set(re.findall(r"\b(memory_[a-z_]+)\b", text)):
                self.assertIn(token, names, f"{path.name} mentions unknown tool {token}")

    def test_tool_list_matches_dispatch(self):
        """Every advertised tool must be dispatchable, and vice versa."""
        from knowledgeos import memory

        advertised = {spec["name"] for spec in memory.TOOL_SPECS}
        source = Path(memory.__file__).read_text(encoding="utf-8")
        dispatch_block = source.split("mapping = {", 1)[1].split("\n    }", 1)[0]
        handled = set(re.findall(r'"(memory_[a-z_]+)":', dispatch_block))
        self.assertEqual(advertised, handled)

    def test_pyproject_declares_the_console_script(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("twinaatma = \"knowledgeos.__main__:main\"", text)
        self.assertIn('requires-python = ">=3.9"', text)

    def test_pyinstaller_bundles_what_init_needs(self):
        spec = (ROOT / "pyinstaller.spec").read_text(encoding="utf-8")
        for required in ("Templates", "AGENTS.md", "hooks.json", "rules"):
            self.assertIn(required, spec, f"binary bundle is missing {required}")

    def test_wheel_build_stages_the_starter_kit(self):
        """`pip install twinaatma` must ship AGENTS.md, hooks and templates.

        The assets live at the repo root as readable files, so packaging them needs an
        explicit build step; without one, `init` silently produced a vault with no
        agent contract and no hooks.
        """
        setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn("build_py", setup_py)
        self.assertIn("_assets", setup_py)
        for required in ("Templates", ".cursor", "AGENTS.md"):
            self.assertIn(required, setup_py, f"wheel build does not stage {required}")

        from knowledgeos.resources import _looks_like_root, toolkit_root

        self.assertTrue(
            _looks_like_root(toolkit_root()),
            "toolkit_root() does not point at a usable starter kit",
        )

    def test_identity_approval_is_documented_as_terminal_only(self):
        """The docs may not advertise a way for the agent to apply a Self change."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("twinaatma self approve", readme)
        self.assertNotIn(
            "twinaatma memory memory_accept_self_update",
            readme,
            "README still shows the tool as a way to apply a Self change",
        )
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("always refuses", agents)


class SafetyDefaultsTests(unittest.TestCase):
    """Defaults that keep a stray command from rewriting the vault."""

    def test_ids_assignment_never_touches_identity(self):
        import inspect

        from knowledgeos import ids

        source = inspect.getsource(ids.assign_ids_for_vault)
        self.assertIn('"People"', source, "ids assign would rewrite Self.md")

    def test_doctor_reports_gate_and_asset_health(self):
        import inspect

        from knowledgeos import doctor

        source = inspect.getsource(doctor.run_doctor)
        for expected in ("identity gate", "toolkit assets", "hook"):
            self.assertIn(expected, source, f"doctor does not check {expected}")

    def test_gate_refuses_mcp_accept_in_source(self):
        """A regression here reopens "agent can approve itself"."""
        from knowledgeos import gate

        result = gate.accept(Path("."), Path("Self.md"), Path("."), "x.md")
        self.assertFalse(result.get("ok"))
        self.assertIn("human", result["error"])



if __name__ == "__main__":
    unittest.main()
