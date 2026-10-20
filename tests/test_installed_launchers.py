"""Installed entry points generate configuration for their own executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
from support import TempVaultCase, ROOT


class InstalledLauncherTests(TempVaultCase):
    def generated_server(self, entry):
        code = "import sys;from knowledgeos.__main__ import main;sys.argv[0]=sys.argv.pop(1);raise SystemExit(main(sys.argv[1:]))"
        env = dict(os.environ, PYTHONPATH=str(ROOT), PATH="")
        result = subprocess.run([sys.executable, "-B", "-c", code, str(entry),
            "setup-host", "--host", "cursor", "--vault", str(self.vault), "--print"],
            cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["mcpServers"]["knowledgeos"]

    def test_posix_console_entry_is_preserved_without_path_activation(self):
        entry = self.root / "bin/twinaatma"
        entry.parent.mkdir(); entry.write_text("# installed console script\n", encoding="utf-8")
        server = self.generated_server(entry)
        self.assertEqual(Path(server["command"]), entry)
        expected_id = json.loads((self.vault / ".knowledgeos-vault.json").read_text())["vault_id"]
        self.assertEqual(server["args"], ["mcp", "--host-vault-id", expected_id, "--vault", str(self.vault)])
        self.assertNotIn("PYTHONPATH", server["env"])

    def test_windows_console_entry_resolves_exe_after_setuptools_strips_suffix(self):
        entry = self.root / "Scripts/twinaatma"
        executable = entry.with_suffix(".exe")
        executable.parent.mkdir(); executable.write_bytes(b"installed executable fixture")
        server = self.generated_server(entry)
        self.assertEqual(Path(server["command"]), executable)
        expected_id = json.loads((self.vault / ".knowledgeos-vault.json").read_text())["vault_id"]
        self.assertEqual(server["args"], ["mcp", "--host-vault-id", expected_id, "--vault", str(self.vault)])
        self.assertNotIn("PYTHONPATH", server["env"])
