"""Generated host commands retain literal vault paths through the host shell."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from support import ROOT


@unittest.skipUnless(sys.version_info >= (3, 11), "Source hooks require Python 3.11+")
class HookShellPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hook-shell-")
        self.root = Path(self.temporary.name)
        self.interpreter = sys.executable
        self.env = dict(os.environ, PYTHONPATH=str(ROOT),
                        KNOWLEDGEOS_STATE_DIR=str(self.root / "gate-state"))

    def tearDown(self):
        self.temporary.cleanup()

    def initialize(self, vault):
        return subprocess.run(
            [self.interpreter, "-B", "-m", "knowledgeos", "init", str(vault),
             "--name", "Shell path fixture", "--non-interactive"],
            cwd=self.root, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=90,
        )

    def exercise_literal_path(self, name):
        vault = self.root / name
        initialized = self.initialize(vault)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self_path = vault / "People/Self.md"
        identity = hashlib.sha256(self_path.read_bytes()).hexdigest()
        note = vault / "Inbox/Shell path warmup.md"
        note.write_text("---\ntype: concept\ntitle: Shell path warmup\nstatus: active\n"
                        "schema: knowledgeos-v0.2\n---\n\nliteral-shell-path-proof\n",
                        encoding="utf-8")
        config = json.loads((vault / ".cursor/hooks.json").read_text(encoding="utf-8"))
        env = dict(self.env, PATH="")
        for event in ("sessionStart", "sessionEnd"):
            command = config["hooks"][event][0]["command"]
            result = subprocess.run(command, shell=True, cwd=vault, env=env,
                                    input="{}", capture_output=True, text=True,
                                    encoding="utf-8", timeout=150)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            if event == "sessionStart":
                self.assertNotIn("Pre-warm unavailable", payload["additional_context"])
                with closing(sqlite3.connect(vault / "knowledge_index.db")) as connection:
                    row = connection.execute(
                        "SELECT body FROM notes_fts WHERE path = ?",
                        ("Inbox/Shell path warmup.md",),
                    ).fetchone()
                self.assertIsNotNone(row, "The generated hook warmed a different vault")
                self.assertIn("literal-shell-path-proof", row[0])
        self.assertEqual(hashlib.sha256(self_path.read_bytes()).hexdigest(), identity)

    @unittest.skipUnless(os.name == "nt", "Windows command shell acceptance")
    def test_windows_ampersand_in_vault_path_is_one_literal_argument(self):
        self.exercise_literal_path("vault&__review_no_such_command_59d3")

    @unittest.skipUnless(os.name == "nt", "Windows command shell acceptance")
    def test_windows_ampersand_in_interpreter_path_stays_literal(self):
        installation = self.root / "runtime&__review_no_such_command_59d3"
        created = subprocess.run(
            [sys.executable, "-I", "-m", "venv", "--without-pip", str(installation)],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.interpreter = str(installation / "Scripts/python.exe")
        self.exercise_literal_path("vault")

    @unittest.skipIf(os.name == "nt", "POSIX shell acceptance")
    def test_posix_command_substitution_in_vault_path_stays_literal(self):
        self.exercise_literal_path("vault$(printf hook-substitution)")

    @unittest.skipUnless(os.name == "nt", "Windows command shell expansion")
    def test_windows_expanding_path_is_refused_before_creating_vault(self):
        self.env["TWINAATMA_HOOK_LITERAL"] = "known-nonsecret-fixture"
        for name in ("vault%TWINAATMA_HOOK_LITERAL%", "vault!TWINAATMA_HOOK_LITERAL!"):
            with self.subTest(name=name):
                vault = self.root / name
                initialized = self.initialize(vault)
                self.assertNotEqual(initialized.returncode, 0, initialized.stdout)
                self.assertIn("unsupported shell path", initialized.stderr.lower())
                self.assertFalse(vault.exists(), "Unsupported paths must fail before any write")
