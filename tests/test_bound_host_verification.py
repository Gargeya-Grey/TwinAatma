"""Full fixture identity is independently required by host evidence bindings."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).absolute().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HOST = load("_bound_config_host", "host.py")
ARTIFACT = load("_bound_config_artifact", "artifact.py")
ACCEPTANCE = load("_bound_config_acceptance", "acceptance.py")


class BoundHostVerificationTests(unittest.TestCase):
    def setUp(self):
        self.scope = ROOT / "work/gc-artifacts/.knowledgeos/bound-config-regressions" / uuid.uuid4().hex
        self.vault = self.scope / "vault"
        self.vault.mkdir(parents=True)
        self.marker = self.vault / ".knowledgeos-vault.json"
        self.identifier = "5af8e104d27c4069aeb315f0c9627d83"
        self.marker.write_text(json.dumps({"vault_id": self.identifier}), encoding="utf-8")
        self.executable = self.scope / "installed-launcher.exe"
        self.executable.write_bytes(b"Binding-only fixture; never executed.\n")
        self.server = {"command": str(self.executable),
                       "args": ["mcp", "--host-vault-id", self.identifier, "--vault", str(self.vault)],
                       "env": {"KNOWLEDGEOS_VAULT": str(self.vault)},
                       "required": True, "default_tools_approval_mode": "approve"}
        self.installation = {"executable": str(self.executable), "vault": str(self.vault)}

    def source_server(self, server):
        source = copy.deepcopy(server)
        source["command"] = sys.executable
        source["args"] = ["-P", "-m", "knowledgeos", *source["args"]]
        source.setdefault("env", {})["PYTHONPATH"] = str(ROOT)
        return source

    def assert_all_bindings(self, server, expected):
        self.assertIs(ARTIFACT.installed_server_binding(server, self.executable, self.vault), expected)
        self.assertIs(HOST.source_binding(self.source_server(server), self.vault), expected)
        if expected:
            ACCEPTANCE.checked_installed_host_config(server, self.installation)
        else:
            with self.assertRaises((OSError, ValueError)):
                ACCEPTANCE.checked_installed_host_config(server, self.installation)

    def test_exact_bound_launcher_and_actual_marker_agree(self):
        before = self.marker.read_bytes()
        self.assert_all_bindings(self.server, True)
        self.assertEqual(self.marker.read_bytes(), before)

    def test_legacy_markerless_fixture_retains_its_original_argument_contract(self):
        self.marker.rename(self.scope / "retained-marker.json")
        legacy = copy.deepcopy(self.server)
        legacy["args"] = ["mcp", "--vault", str(self.vault)]
        legacy["cwd"] = str(self.vault)
        self.assert_all_bindings(legacy, True)

    def test_bound_argv_refuses_wrong_truncated_duplicate_and_extra_identity(self):
        for args in (["mcp", "--host-vault-id", "6" * 32, "--vault", str(self.vault)],
                     ["mcp", "--host-vault-id", self.identifier[:12], "--vault", str(self.vault)],
                     [*self.server["args"], "--host-vault-id", self.identifier],
                     [*self.server["args"], "unexpected"], ["mcp", "--vault", str(self.vault)]):
            with self.subTest(args=args):
                server = copy.deepcopy(self.server)
                server["args"] = args
                self.assert_all_bindings(server, False)

    def test_bound_startup_policy_cwd_and_environment_are_checked(self):
        for change in ({"cwd": str(self.vault)}, {"cwd": None}, {"required": False},
                       {"default_tools_approval_mode": "prompt"},
                       {"env": {"KNOWLEDGEOS_VAULT": str(self.scope / "other")}},
                       {"env": {"KNOWLEDGEOS_VAULT": str(self.vault), "pythonpath": "foreign"}}):
            with self.subTest(change=change):
                self.assert_all_bindings({**self.server, **change}, False)

    def test_changed_executable_refuses_at_both_installed_boundaries(self):
        foreign = self.scope / "foreign.exe"
        foreign.write_bytes(b"Foreign binding-only fixture.\n")
        server = {**self.server, "command": str(foreign)}
        self.assertFalse(ARTIFACT.installed_server_binding(server, self.executable, self.vault))
        with self.assertRaises(ValueError):
            ACCEPTANCE.checked_installed_host_config(server, self.installation)

    def test_malformed_duplicate_and_conflicting_marker_identities_refuse(self):
        for text in ('{"vault_id":', '[]', '{"vault_id":"short"}',
                     '{"vault_id":"' + self.identifier + '","vault_id":"' + self.identifier + '"}'):
            with self.subTest(text=text):
                self.marker.write_text(text, encoding="utf-8")
                self.assert_all_bindings(self.server, False)
        self.marker.write_text(json.dumps({"vault_id": self.identifier}), encoding="utf-8")
        (self.vault / "knowledgeos.config.json").write_text(json.dumps({"vault_id": "6" * 32}), encoding="utf-8")
        self.assert_all_bindings(self.server, False)


if __name__ == "__main__":
    unittest.main()
