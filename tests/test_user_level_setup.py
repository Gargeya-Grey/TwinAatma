"""Connecting a host for every project, and the Claude Code project file."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from support import TempVaultCase

from knowledgeos import host_setup


class Ran:
    """Stands in for the host's command. It records the call and never touches the machine."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.returncode, self.stderr = returncode, stderr

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs = kwargs
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


class UserLevelSetup(TempVaultCase):
    def install(self, host: str, *, program: str | None = "C:/hosts/host.exe", ran: Ran | None = None):
        ran = ran or Ran()
        done, message = host_setup.install_user(host, self.vault, resolve=lambda name: program, run=ran)
        return done, message, ran

    def test_claude_code_is_registered_for_every_project(self):
        done, message, ran = self.install("claude-code")
        self.assertTrue(done, message)
        call = ran.calls[0]
        self.assertEqual(call[:5], ["C:/hosts/host.exe", "mcp", "add", "--scope", "user"])
        self.assertIn(f"KNOWLEDGEOS_VAULT={self.vault.resolve()}", call)
        split = call.index("--")
        self.assertEqual(call[split - 1], "knowledgeos")
        self.assertNotEqual(call[split - 2].count("="), 1, "the name must not follow --env directly")
        self.assertEqual(call[split + 1:][-2:], ["--vault", str(self.vault.resolve())])
        self.assertIn("mcp", call[split + 1:])
        self.assertFalse(ran.kwargs.get("shell"))

    def test_codex_is_registered_for_every_project(self):
        done, message, ran = self.install("codex")
        self.assertTrue(done, message)
        call = ran.calls[0]
        self.assertEqual(call[:4], ["C:/hosts/host.exe", "mcp", "add", "knowledgeos"])
        self.assertIn(f"KNOWLEDGEOS_VAULT={self.vault.resolve()}", call)
        self.assertEqual(call[call.index("--") + 1:][-2:], ["--vault", str(self.vault.resolve())])

    def test_a_missing_host_changes_nothing_and_gives_the_line_to_run(self):
        done, message, ran = self.install("claude-code", program=None)
        self.assertFalse(done)
        self.assertEqual(ran.calls, [])
        self.assertIn("claude mcp add --scope user", message)

    def test_a_refusal_from_the_host_is_reported_with_the_way_out(self):
        done, message, _ran = self.install("codex", ran=Ran(1, "Error: server knowledgeos already exists"))
        self.assertFalse(done)
        self.assertIn("already exists", message)
        self.assertIn("codex mcp remove knowledgeos", message)

    def test_a_script_wrapper_is_not_started_on_windows(self):
        with mock.patch.object(host_setup.os, "name", "nt"):
            done, message, ran = self.install("claude-code", program="C:/npm/claude.cmd")
        self.assertFalse(done)
        self.assertEqual(ran.calls, [])
        self.assertIn("Run this yourself", message)

    def test_a_host_without_user_level_setup_is_refused(self):
        with self.assertRaises(host_setup.UnsupportedHost):
            host_setup.user_command("cursor", self.vault)

    def test_the_command_prints_the_line_without_running_anything(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(host_setup, "install_user") as install:
            code = host_setup.main(["--host", "codex", "--vault", str(self.vault), "--global", "--print"])
        self.assertEqual(code, 0)
        install.assert_not_called()
        self.assertIn("codex mcp add knowledgeos", out.getvalue())

    def test_global_and_write_together_are_refused(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = host_setup.main(["--host", "codex", "--vault", str(self.vault), "--global", "--write"])
        self.assertEqual(code, 2)
        self.assertFalse((self.vault / ".codex").exists())


class ClaudeCodeProjectFile(TempVaultCase):
    def test_write_creates_the_project_file_and_keeps_other_servers(self):
        target = self.vault / ".mcp.json"
        target.write_text(json.dumps({"mcpServers": {"other": {"command": "other-server"}}}), encoding="utf-8")
        written = host_setup.write_config("claude-code", self.vault)
        self.assertEqual(Path(written), target)
        servers = json.loads(target.read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(servers["other"], {"command": "other-server"})
        self.assertEqual(servers["knowledgeos"]["env"]["KNOWLEDGEOS_VAULT"], str(self.vault.resolve()))
        self.assertEqual(host_setup.write_config("claude-code", self.vault), written)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["mcpServers"], servers)


if __name__ == "__main__":
    unittest.main()
