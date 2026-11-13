"""Public reconnect behavior with a carried vault and an unavailable installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("TWIN_RESTORE_OUTPUT") or (
    ROOT / "work/gc-artifacts/.knowledgeos/restore-host-controls" / uuid.uuid4().hex[:12]
))


@unittest.skipIf(sys.version_info < (3, 11), "Source reconnect checks require Python 3.11+.")
class RestoreHostConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        cls.records = []
        cls.environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                               KNOWLEDGEOS_STATE_DIR=str(OUTPUT / "base-state"), PATH="")
        cls.environment.pop("KNOWLEDGEOS_VAULT", None)
        cls.environment.pop("KNOWLEDGEOS_GATE_KEY", None)
        cls.original = OUTPUT / "original-vault"
        cls.old_install = OUTPUT / "original-python"
        result = cls.run_command([sys.executable, "-B", "-m", "venv", "--without-pip", str(cls.old_install)])
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.old_python = cls.old_install / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        result = cls.run_command([str(cls.old_python), "-B", "-P", "-m", "knowledgeos", "init",
                                  str(cls.original), "--non-interactive"])
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        retained = OUTPUT / "retained-original-python"
        assert cls.old_install.resolve().is_relative_to(OUTPUT.resolve())
        assert retained.resolve().is_relative_to(OUTPUT.resolve())
        cls.old_install.rename(retained)

    @classmethod
    def run_command(cls, command, *, cwd=ROOT, environment=None, data=None, shell=False):
        folder = OUTPUT / "commands" / (str(time.time_ns()) + "-" + uuid.uuid4().hex[:6])
        folder.mkdir(parents=True)
        child = subprocess.Popen(command, cwd=cwd, env=environment or cls.environment,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 shell=shell)
        try:
            stdout, stderr = child.communicate(data, timeout=90)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate(timeout=20)
            raise
        finally:
            cls.records.append({"command": command, "cwd": str(cwd), "pid": child.pid,
                                "exit_code": child.returncode, "stopped": child.poll() is not None})
            (OUTPUT / "processes.json").write_text(json.dumps(cls.records, indent=2), encoding="utf-8")
        (folder / "stdout.txt").write_bytes(stdout)
        (folder / "stderr.txt").write_bytes(stderr)
        (folder / "command.json").write_text(json.dumps(cls.records[-1], indent=2), encoding="utf-8")
        return subprocess.CompletedProcess(command, child.returncode, stdout.decode("utf-8"), stderr.decode("utf-8"))

    def setUp(self):
        self.directory = OUTPUT / self.id().rsplit(".", 1)[-1]
        self.vault = self.directory / "restored-vault"
        shutil.copytree(self.original, self.vault)
        self.environment = dict(self.environment, KNOWLEDGEOS_STATE_DIR=str(self.directory / "state"))

    def cli(self, *arguments):
        return self.run_command([sys.executable, "-B", "-P", "-m", "knowledgeos", *map(str, arguments)],
                                environment=self.environment)

    def snapshot(self):
        return {path.relative_to(self.vault).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.vault.rglob("*") if path.is_file()}

    def assert_refused_unchanged(self):
        before = self.snapshot()
        result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("preserv", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.snapshot(), before)
        return result

    def test_reconnect_restores_generated_siblings_and_doctor_without_changing_identity(self):
        identity = (self.vault / "People/Self.md").read_bytes()
        self.assertFalse(self.old_python.exists())
        setup = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        doctor = self.cli("doctor", "--vault", self.vault)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        for relative in (".cursor/hooks.json", ".cursor/mcp.json", "mcp.cursor.json"):
            content = (self.vault / relative).read_text(encoding="utf-8")
            self.assertNotIn(str(self.old_python).replace("\\", "\\\\"), content)
            self.assertNotIn(str(self.original).replace("\\", "\\\\"), content)
        self.assertEqual((self.vault / "People/Self.md").read_bytes(), identity)
        files = (".codex/config.toml", ".cursor/hooks.json", ".cursor/mcp.json", "mcp.cursor.json", ".knowledgeos-init.json")
        before = {name: hashlib.sha256((self.vault / name).read_bytes()).hexdigest() for name in files}
        again = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual({name: hashlib.sha256((self.vault / name).read_bytes()).hexdigest() for name in files}, before)

    def test_edited_and_foreign_hooks_are_preserved_before_any_configuration_write(self):
        hooks = self.vault / ".cursor/hooks.json"
        original = hooks.read_bytes()
        for change in ("foreign-command", "changed-owned-command", "custom-field"):
            with self.subTest(change=change):
                config = json.loads(original)
                if change == "foreign-command":
                    config["hooks"]["sessionStart"].append({"command": "owner-custom-hook --keep"})
                elif change == "changed-owned-command":
                    config["hooks"]["sessionStart"][0]["command"] += " --owner-option"
                else:
                    config["owner-setting"] = "keep"
                hooks.write_bytes(json.dumps(config, indent=2).encode("utf-8"))
                result = self.assert_refused_unchanged()
                self.assertIn("hooks.new.json", result.stderr)

    def test_legacy_hooks_without_a_generation_receipt_are_preserved(self):
        path = self.vault / ".knowledgeos-init.json"
        receipt = json.loads(path.read_bytes())
        receipt.pop("generated_host_files", None)
        path.write_bytes(json.dumps(receipt).encode("utf-8"))
        result = self.assert_refused_unchanged()
        self.assertIn("no matching generation receipt", result.stderr)

    def test_malformed_carried_files_fail_preflight_without_writing_selected_host(self):
        cases = {
            ".cursor/hooks.json": (b"{", b"[]", b'{"hooks":[]}', b'{"hooks":{"sessionStart":[{}]}}'),
            ".cursor/mcp.json": (b"{", b'{"mcpServers":[]}'),
            "mcp.cursor.json": (b"{", b'{"mcpServers":{"knowledgeos":[]}}'),
            ".knowledgeos-init.json": (b"{", b"[]", b'{"generated_host_files":{"version":7,"files":{}}}'),
        }
        for relative, contents in cases.items():
            path = self.vault / relative
            original = path.read_bytes()
            for content in contents:
                with self.subTest(path=relative, content=content):
                    path.write_bytes(content)
                    self.assert_refused_unchanged()
            path.write_bytes(original)

    def test_invalid_selected_config_preserves_all_carried_files(self):
        target = self.vault / ".codex/config.toml"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"[invalid")
        self.assert_refused_unchanged()

    def test_linked_carried_files_and_receipt_are_preserved(self):
        original_vault = self.vault
        for index, relative in enumerate((".cursor/hooks.json", ".cursor/mcp.json", "mcp.cursor.json", ".knowledgeos-init.json")):
            with self.subTest(path=relative):
                self.vault = self.directory / ("linked-vault-" + str(index))
                shutil.copytree(original_vault, self.vault)
                target = self.vault / relative
                retained = self.directory / ("owner-config-" + str(index) + ".json")
                assert target.resolve().is_relative_to(self.directory.resolve())
                assert retained.resolve().is_relative_to(self.directory.resolve())
                target.rename(retained)
                os.link(retained, target)
                owner_bytes = retained.read_bytes()
                result = self.assert_refused_unchanged()
                self.assertIn("hardlinked", result.stderr)
                self.assertEqual(retained.read_bytes(), owner_bytes)

    def test_custom_mcp_siblings_and_selected_codex_settings_survive(self):
        before = {}
        for relative in (".cursor/mcp.json", "mcp.cursor.json"):
            path = self.vault / relative
            config = json.loads(path.read_bytes())
            config["mcpServers"]["other"] = {"command": "owner-service", "args": ["--keep"]}
            config["mcpServers"]["knowledgeos"]["env"]["OWNER_MODE"] = "keep"
            config["owner-setting"] = True
            path.write_bytes(json.dumps(config, indent=4).encode("utf-8"))
            before[relative] = path.read_bytes()
        codex = self.vault / ".codex/config.toml"
        codex.parent.mkdir(exist_ok=True)
        foreign = b'# Owner text is retained.\nmodel = "owner-model"\n[mcp_servers.other]\ncommand = "owner-service"\n'
        codex.write_bytes(foreign)
        result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("custom or unrecorded MCP config", result.stderr)
        for relative, content in before.items():
            self.assertEqual((self.vault / relative).read_bytes(), content)
        self.assertTrue(codex.read_bytes().startswith(foreign))
        doctor = self.cli("doctor", "--vault", self.vault)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    def test_selected_cursor_config_still_merges_foreign_fields(self):
        path = self.vault / ".cursor/mcp.json"
        config = json.loads(path.read_bytes())
        config["mcpServers"]["other"] = {"command": "owner-service"}
        config["mcpServers"]["knowledgeos"]["env"]["OWNER_MODE"] = "keep"
        path.write_bytes(json.dumps(config).encode("utf-8"))
        result = self.cli("setup-host", "--host", "cursor", "--vault", self.vault, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads(path.read_bytes())
        self.assertEqual(after["mcpServers"]["other"], {"command": "owner-service"})
        self.assertEqual(after["mcpServers"]["knowledgeos"]["env"]["OWNER_MODE"], "keep")
        self.assertEqual(after["mcpServers"]["knowledgeos"]["env"]["KNOWLEDGEOS_VAULT"], str(self.vault))

    def test_init_refresh_keeps_existing_files_and_their_old_generation_proof(self):
        names = (".cursor/hooks.json", ".cursor/mcp.json", "mcp.cursor.json")
        before = {name: (self.vault / name).read_bytes() for name in names}
        refreshed = self.cli("init", self.vault, "--non-interactive")
        self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
        self.assertEqual({name: (self.vault / name).read_bytes() for name in names}, before)
        setup = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        doctor = self.cli("doctor", "--vault", self.vault)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    def test_print_and_out_do_not_reconnect_or_write_carried_files(self):
        before = self.snapshot()
        printed = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--print")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assertEqual(self.snapshot(), before)
        exported = self.cli("setup-host", "--host", "codex", "--vault", self.vault,
                            "--out", self.directory / "new-export.toml")
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_reconnected_source_hooks_run_trusted_code_with_poisoned_vault_imports(self):
        marker = self.directory / "untrusted-code-executed"
        for relative in ("knowledgeos.py", "json.py", ".cursor/hooks/twin_session_start.py", ".cursor/hooks/json.py"):
            path = self.vault / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
        identity = (self.vault / "People/Self.md").read_bytes()
        setup = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        hooks = json.loads((self.vault / ".cursor/hooks.json").read_bytes())
        for event in ("sessionStart", "sessionEnd"):
            command = hooks["hooks"][event][0]["command"]
            self.assertNotIn(str(self.vault / ".cursor/hooks"), command)
            result = self.run_command(command, cwd=self.vault, shell=True, data=b"{}",
                                      environment=dict(self.environment, PYTHONPATH=str(self.vault)))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unavailable", result.stdout.lower() + result.stderr.lower())
            self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertFalse(marker.exists())
        self.assertEqual((self.vault / "People/Self.md").read_bytes(), identity)


if __name__ == "__main__":
    unittest.main()
