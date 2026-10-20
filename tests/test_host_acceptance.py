"""Public setup and host-proof regressions in synthetic vaults."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from support import TempVaultCase, ROOT

@unittest.skipIf(sys.version_info < (3, 11), "Source host acceptance requires Python 3.11+; older installed commands remain supported.")
class CodexSetupTests(TempVaultCase):
    def cli(self,*args):
        return subprocess.run([sys.executable,"-B","-m","knowledgeos",*map(str,args)],cwd=ROOT,
            env=os.environ.copy(),capture_output=True,text=True,encoding="utf-8",timeout=60)

    def test_codex_print_uses_native_toml_and_no_user_configuration_write(self):
        result=self.cli("setup-host","--host","codex","--vault",self.vault,"--print")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("[mcp_servers.knowledgeos]",result.stdout)
        self.assertIn("memory",(self.vault/"AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("default_tools_approval_mode = \"approve\"",result.stdout)
        if sys.version_info >= (3,11):
            import tomllib
            server=tomllib.loads(result.stdout)["mcp_servers"]["knowledgeos"]
            self.assertIn(str(self.vault),server["args"])
            self.assertEqual(server["env"]["KNOWLEDGEOS_VAULT"],str(self.vault))
        self.assertFalse((self.vault/".codex/config.toml").exists())

    def test_write_merges_native_config_preserving_custom_settings_comments_and_foreign_text(self):
        target = self.vault / ".codex/config.toml"
        target.parent.mkdir(exist_ok=True)
        foreign = '# Owner settings stay verbatim.\nmodel = "chosen-model"\n\n[mcp_servers.other]\ncommand = "other-service" # keep this comment\n\n'
        owned = '[mcp_servers.knowledgeos]\ncommand = "old-service"\nargs = ["old"]\nstartup_timeout_sec = 45 # owner tuning\n\n[mcp_servers.knowledgeos.env]\nCUSTOM_MODE = "careful" # keep env\nKNOWLEDGEOS_VAULT = "old"\n'
        target.write_bytes((foreign + owned).encode())
        result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = target.read_bytes().decode()
        self.assertTrue(text.startswith(foreign))
        self.assertIn('startup_timeout_sec = 45 # owner tuning', text)
        self.assertIn('CUSTOM_MODE = "careful" # keep env', text)
        import tomllib
        server = tomllib.loads(text)["mcp_servers"]["knowledgeos"]
        self.assertNotIn("cwd", server)
        self.assertIn("--host-vault-id", server["args"])
        self.assertEqual(server["startup_timeout_sec"], 45)
        self.assertEqual(server["env"]["CUSTOM_MODE"], "careful")
        before = target.read_bytes()
        again = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(target.read_bytes(), before)

    def test_malformed_or_unsupported_existing_config_preserves_every_byte(self):
        target = self.vault / ".codex/config.toml"
        target.parent.mkdir(exist_ok=True)
        for original in (b'[broken', b'mcp_servers = 4\n', b'[mcp_servers]\nknowledgeos = "bad"\n',
                         b'[mcp_servers]\nknowledgeos = {command="existing"}\n',
                         b'[mcp_servers.knowledgeos]\nenv.CUSTOM = "preserve"\n'):
            with self.subTest(original=original):
                target.write_bytes(original)
                result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(target.read_bytes(), original)
                self.assertIn("preserv", result.stderr.lower())

    def test_out_emits_native_toml_and_refuses_existing_file(self):
        target = self.vault / "codex-export.toml"
        result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--out", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        import tomllib
        self.assertIn("knowledgeos", tomllib.loads(target.read_text())["mcp_servers"])
        before = target.read_bytes()
        result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--out", target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), before)

    def test_linked_config_is_refused_without_changing_original(self):
        target = self.vault / ".codex/config.toml"
        target.parent.mkdir(exist_ok=True)
        original = self.vault / "owner-config.toml"
        original.write_bytes(b'model = "keep"\n')
        os.link(original, target)
        result = self.cli("setup-host", "--host", "codex", "--vault", self.vault, "--write")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(original.read_bytes(), b'model = "keep"\n')
        self.assertEqual(target.read_bytes(), original.read_bytes())

    def test_new_config_can_emit_without_tomllib_but_existing_merge_refuses(self):
        from unittest import mock
        from knowledgeos.codex_config import render, merge, UnsafeToml
        from knowledgeos.host_setup import build_config
        server = build_config("codex", self.vault)["mcp_servers"]["knowledgeos"]
        self.assertIn("[mcp_servers.knowledgeos]", render(server))
        import builtins
        real_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == "tomllib":
                raise ImportError("unavailable")
            return real_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=importing):
            with self.assertRaisesRegex(UnsafeToml, "3.11"):
                merge('model = "preserve"\n', server)


@unittest.skipIf(sys.version_info < (3, 11), "Existing TOML merge requires the standard-library parser on Python 3.11+.")
class NativeTomlMergeTests(unittest.TestCase):
    def test_inline_env_and_quoted_tables_preserve_owned_custom_values(self):
        import tomllib
        from knowledgeos.codex_config import merge
        server = {"command": "new", "args": ["mcp"], "cwd": "new-vault",
                  "default_tools_approval_mode": "approve", "env": {"KNOWLEDGEOS_VAULT": "new-vault"}}
        original = '[mcp_servers."knowledgeos"]\ncommand = "old"\nenv = {CUSTOM="yes", KNOWLEDGEOS_VAULT="old"}\nenabled = false # custom\n'
        result = merge(original, server)
        data = tomllib.loads(result)["mcp_servers"]["knowledgeos"]
        self.assertEqual(data["env"], {"CUSTOM": "yes", "KNOWLEDGEOS_VAULT": "new-vault"})
        self.assertFalse(data["enabled"])
        self.assertIn('enabled = false # custom', result)
        self.assertEqual(merge(result, server), result)

    def test_header_looking_foreign_multiline_string_is_untouched(self):
        from knowledgeos.codex_config import merge
        server = {"command": "new", "args": ["mcp"], "cwd": "vault", "env": {"KEY": "value"}}
        original = 'instructions = \"\"\"\n[mcp_servers.knowledgeos]\ncommand = "foreign text"\n\"\"\"\n'
        result = merge(original, server)
        self.assertTrue(result.startswith(original))
        self.assertEqual(merge(result, server), result)

if __name__ == "__main__": unittest.main()
