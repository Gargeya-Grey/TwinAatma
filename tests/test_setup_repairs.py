"""Setup and identity regressions exercised through CLI and memory interfaces."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SetupRepairs(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "work/gc-artifacts/.knowledgeos/repair-20261019/setup"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=scratch)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.env = os.environ.copy()
        self.env["KNOWLEDGEOS_STATE_DIR"] = str(self.root / "state")
        self.env["PYTHONPATH"] = str(ROOT)
        self.patch_env = mock.patch.dict(os.environ, self.env)
        self.patch_env.start()

    def tearDown(self):
        self.patch_env.stop()
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-P", "-m", "knowledgeos", *map(str, args)],
            cwd=ROOT, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )

    def initialize(self):
        result = self.cli("init", self.vault, "--name", "Example", "--non-interactive")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_host_reconfiguration_preserves_invalid_existing_documents(self):
        self.initialize()
        for host, folder, key in (("cursor", ".cursor", "mcpServers"), ("vscode", ".vscode", "servers")):
            config = self.vault / folder / "mcp.json"
            config.parent.mkdir(exist_ok=True)
            for original in (b'{"broken":', b'[]', json.dumps({key: ["other"]}).encode()):
                with self.subTest(host=host, original=original):
                    config.write_bytes(original)
                    result = self.cli("setup-host", "--host", host, "--vault", self.vault, "--write")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(config.read_bytes(), original)
                    self.assertIn("preserv", result.stderr.lower())

    def test_init_reports_required_post_setup_failure_to_shell(self):
        self.vault.mkdir()
        (self.vault / ".knowledgeos").write_text("existing content", encoding="utf-8")
        result = self.cli("init", self.vault, "--force", "--non-interactive")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        report = json.loads(result.stdout)
        self.assertFalse(report["post_init"]["rebuild"]["ok"])
        self.assertFalse(report["ok"])
        self.assertTrue((self.vault / "People/Self.md").is_file())
        self.assertEqual((self.vault / ".knowledgeos").read_text(), "existing content")

    def test_name_only_setup_does_not_invent_owner_preferences(self):
        self.initialize()
        result = self.cli("memory", "memory_self_get", "--vault", self.vault)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        identity = json.loads(result.stdout)
        text = json.dumps(identity)
        self.assertIn("Unknown", text)
        for belief in ("Clarity", "First Principles", "durability over cleverness", "Building before validating"):
            self.assertNotIn(belief, text)

    def test_renamed_canonical_sections_remain_visible_and_writable(self):
        self.initialize()
        identity = self.vault / "People/Self.md"
        text = identity.read_text(encoding="utf-8")
        text = text.replace("## Values Hierarchy", "## My priorities")
        text = text.replace("Unknown. No owner-confirmed values or ranking recorded yet.", "I value learning.")
        identity.write_text(text, encoding="utf-8")
        before = identity.read_bytes()
        result = self.cli("memory", "memory_self_get", "--vault", self.vault)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sections = json.loads(result.stdout)["sections"]
        self.assertIn("I value learning.", sections.get("values", ""))
        proposal = self.cli(
            "memory", "memory_propose_self_update", "--vault", self.vault,
            "--section", "values", "--summary", "Priority", "--mode", "append",
            "--proposed-markdown", "I value patience.",
        )
        self.assertEqual(proposal.returncode, 0, proposal.stdout + proposal.stderr)
        self.assertEqual(identity.read_bytes(), before)

    def test_duplicate_canonical_markers_report_invalid_identity(self):
        self.initialize()
        identity = self.vault / "People/Self.md"
        identity.write_text(identity.read_text(encoding="utf-8") + "\n## Duplicate\n<!-- kos:section=values -->\nConflicting value.\n", encoding="utf-8")
        before = identity.read_bytes()
        result = self.cli("memory", "memory_self_get", "--vault", self.vault)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("duplicate", (result.stdout + result.stderr).lower())
        self.assertEqual(identity.read_bytes(), before)

    def test_older_source_interpreters_refuse_even_with_an_unrelated_console_on_path(self):
        from knowledgeos.__main__ import main
        for version in ((3, 9, 20), (3, 10, 16)):
            with self.subTest(version=version):
                target = self.root / ("vault-" + str(version[1]))
                console = self.root / "bin with spaces" / "twinaatma.exe"
                output, error = io.StringIO(), io.StringIO()
                with mock.patch.object(sys, "version_info", version), mock.patch(
                    "knowledgeos.host_setup._which_trusted", return_value=str(console)
                ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    code = main(["init", str(target), "--non-interactive"])
                self.assertNotEqual(code, 0, output.getvalue())
                self.assertIn("3.11", error.getvalue())
                self.assertFalse(target.exists())

    def test_older_source_interpreter_reports_unsupported_without_console(self):
        from knowledgeos.__main__ import main
        output, error = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "version_info", (3, 10, 16)), mock.patch(
            "knowledgeos.host_setup._which_trusted", return_value=None
        ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(["init", str(self.vault), "--dry-run"])
        self.assertNotEqual(code, 0, output.getvalue())
        self.assertIn("3.11", error.getvalue())
        self.assertFalse(self.vault.exists())

    def test_doctor_rejects_invalid_hook_configuration_and_missing_executables(self):
        self.initialize()
        config = self.vault / ".cursor/hooks.json"
        for value in ("{", "[]", '{"hooks": []}', '{"hooks":{"sessionStart":{}}}',
                      '{"hooks":{"sessionStart":[{}]}}',
                      json.dumps({"hooks": {"sessionStart": [{"command": '"' + str(self.root / 'missing.exe') + '" hook twin_session_start --vault "' + str(self.vault) + '"'}]}})):
            with self.subTest(config=value):
                config.write_text(value, encoding="utf-8")
                result = self.cli("doctor", "--vault", self.vault)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("[ERROR]", result.stdout)
                self.assertIn("hook", result.stdout.lower())
                self.assertNotIn("Traceback", result.stderr)

    def test_doctor_rejects_duplicate_identity_without_traceback(self):
        self.initialize()
        identity = self.vault / "People/Self.md"
        identity.write_text(identity.read_text(encoding="utf-8") + "\n## Duplicate\n<!-- kos:section=values -->\nContradiction.\n", encoding="utf-8")
        result = self.cli("doctor", "--vault", self.vault)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("[ERROR]", result.stdout)
        self.assertIn("duplicate", result.stdout.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_host_reconfiguration_preserves_other_servers_and_custom_fields(self):
        self.initialize()
        for host, folder, key in (("cursor", ".cursor", "mcpServers"), ("vscode", ".vscode", "servers")):
            with self.subTest(host=host):
                config = self.vault / folder / "mcp.json"
                config.parent.mkdir(exist_ok=True)
                original = {"custom": {"keep": True}, key: {"other": {"command": "existing-service", "args": ["--keep"]}}}
                config.write_text(json.dumps(original), encoding="utf-8")
                result = self.cli("setup-host", "--host", host, "--vault", self.vault, "--write")
                self.assertEqual(result.returncode, 0, result.stderr)
                merged = json.loads(config.read_text())
                self.assertEqual(merged["custom"], original["custom"])
                self.assertEqual(merged[key]["other"], original[key]["other"])
                self.assertNotIn("cwd", merged[key]["knowledgeos"])
                self.assertIn("--host-vault-id", merged[key]["knowledgeos"]["args"])
                before = config.read_bytes()
                again = self.cli("setup-host", "--host", host, "--vault", self.vault, "--write")
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertEqual(config.read_bytes(), before)

    def test_generated_source_start_hook_runs_and_ignores_vault_code(self):
        self.initialize()
        hooks = json.loads((self.vault / ".cursor/hooks.json").read_text())
        marker = self.root / "untrusted-code-executed"
        shadow_dir = self.vault / ".cursor/hooks"
        shadow_dir.mkdir()
        for name in ("json.py", "twin_session_start.py"):
            (shadow_dir / name).write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
        result = subprocess.run(
            hooks["hooks"]["sessionStart"][0]["command"], shell=True,
            cwd=self.vault, env=self.env, input='{"hook_event_name":"sessionStart"}',
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("additional_context", json.loads(result.stdout))
        self.assertFalse(marker.exists())

    def test_generated_start_hook_uses_its_own_installation_despite_path_and_vault_shadows(self):
        self.initialize()
        hooks = json.loads((self.vault / ".cursor/hooks.json").read_text())
        command = hooks["hooks"]["sessionStart"][0]["command"]
        unrelated = self.root / "unrelated installation"
        unrelated.mkdir()
        (unrelated / "twinaatma.exe").write_bytes(b"not an executable")
        marker = self.root / "vault-code-ran"
        shadow = self.vault / "knowledgeos.py"
        shadow.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('vault import')\n",
            encoding="utf-8",
        )
        for path in ("", str(unrelated)):
            with self.subTest(path=path):
                result = subprocess.run(
                    command, shell=True, cwd=self.vault,
                    env={**self.env, "PATH": path, "PYTHONPATH": str(self.vault)},
                    input='{"hook_event_name":"sessionStart"}',
                    capture_output=True, text=True, encoding="utf-8", timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                context = json.loads(result.stdout)["additional_context"]
                self.assertIn("FIRST tool call this chat must be memory_session_start", context)
                self.assertNotIn("Pre-warm unavailable", context)
                self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
