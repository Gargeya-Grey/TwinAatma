"""Public setup must wait for memory without changing foreign server policy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest
import uuid

ROOT = Path(os.environ.get("TWIN_HOST_SETUP_ROOT", Path(__file__).resolve().parents[1]))
OUTPUT = Path(os.environ.get("TWIN_HOST_SETUP_PROOF_OUTPUT", ROOT / "work/gc-artifacts/.knowledgeos/codex-required-setup-controls"))


class CodexRequiredSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = OUTPUT / uuid.uuid4().hex[:10]
        self.vault = self.directory / "vault"
        self.vault.mkdir(parents=True)
        self.config = self.vault / ".codex/config.toml"

    def setup_host(self, label):
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "setup-host", "--host", "codex", "--vault", str(self.vault), "--write"]
        environment = dict(os.environ, PYTHONPATH=str(ROOT), KNOWLEDGEOS_STATE_DIR=str(self.directory / "gate-state"))
        process = subprocess.Popen(command, cwd=self.directory, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=45)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        (self.directory / (label + ".stdout.txt")).write_bytes(stdout)
        (self.directory / (label + ".stderr.txt")).write_bytes(stderr)
        (self.directory / (label + ".command.json")).write_text(json.dumps({"command": command, "pid": process.pid, "stopped": process.poll() is not None, "exit_code": process.returncode}), encoding="utf-8")
        self.assertEqual(process.returncode, 0, stderr.decode("utf-8", errors="replace"))
        return tomllib.loads(self.config.read_text(encoding="utf-8"))

    def test_fresh_setup_requires_memory_before_the_first_turn(self):
        server = self.setup_host("fresh")["mcp_servers"]["knowledgeos"]
        self.assertIs(server.get("required"), True)
        self.assertEqual(server["args"][-2:], ["--vault", str(self.vault)])

    def test_upgrade_repairs_memory_policy_preserves_foreign_bytes_and_is_idempotent(self):
        self.config.parent.mkdir()
        foreign = '# Preserve foreign policy and layout.\nmodel = "fixture-model"\n\n[mcp_servers.other]\ncommand = "foreign.exe"\nrequired = false\n\n'
        original = foreign + '[mcp_servers.knowledgeos]\ncommand = "old.exe"\nrequired = false\n'
        self.config.write_bytes(original.encode())
        configured = self.setup_host("upgrade")
        self.assertIs(configured["mcp_servers"]["knowledgeos"].get("required"), True)
        self.assertIs(configured["mcp_servers"]["other"]["required"], False)
        first = self.config.read_bytes()
        self.assertTrue(first.startswith(foreign.encode()))
        self.setup_host("repeat")
        self.assertEqual(self.config.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
