"""Generated-hook proof rejects success-shaped output without observed behavior."""
import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from support import ROOT

SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/runtime_hooks.py"
spec = importlib.util.spec_from_file_location("runtime_hooks_proof", SCRIPT)
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class RuntimeHookProofTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/runtime-hooks-20261019/driver-tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_printed_additional_context_does_not_prove_prewarm(self):
        output = json.dumps({"additional_context": "Autopilot active. Pre-warm unavailable."})
        result = hooks.prewarm_observation(output, {}, {}, [], "literal-token")
        self.assertEqual(result["ran"], False)
        output = json.dumps({"additional_context": "Autopilot pre-warm ran: rebuilt_index."})
        result = hooks.prewarm_observation(output, {}, {}, [], "literal-token")
        self.assertEqual(result["ran"], False)
        result = hooks.prewarm_observation(output, {}, {}, [["Inbox/a.md", "Note", "literal-token"]], "literal-token")
        self.assertEqual(result["ran"], True)

    def test_prewarm_cannot_spend_real_sessions_or_prompts(self):
        before = {"real_sessions": 2, "sessions": {"first": {"status": "orphaned"}},
                  "soft_prompts_asked": [], "orphan_unsaved_session": True}
        same = dict(before, last_rebuild_ts=1234, updated_at="new timestamp")
        result = hooks.prewarm_observation("{}", before, same, [], "token")
        self.assertEqual(result["no_session"], True)
        for changed in (dict(before, real_sessions=3), dict(before, soft_prompts_asked=["orphan"]),
                        dict(before, sessions={"first": {"status": "ended"}}),
                        dict(before, orphan_unsaved_session=False)):
            with self.subTest(changed=changed):
                self.assertEqual(hooks.prewarm_observation("{}", before, changed, [], "token")["no_session"], False)

    def test_malformed_or_multi_command_generated_events_are_rejected(self):
        config = {"hooks": {"sessionStart": [{"command": "absolute-start --vault vault"}],
                            "sessionEnd": [{"command": "absolute-end --vault vault"}]}}
        self.assertEqual(hooks.generated_commands(config),
                         {"sessionStart": "absolute-start --vault vault", "sessionEnd": "absolute-end --vault vault"})
        for replacement in (None, [], [{"command": ""}], [{"command": "one"}, {"command": "two"}],
                            [{"command": 7}]):
            broken = json.loads(json.dumps(config))
            broken["hooks"]["sessionEnd"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                hooks.generated_commands(broken)

    def test_index_observation_reads_actual_literal_row_without_importing_product(self):
        database = self.directory / "index.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE notes_fts(path, title, body)")
            connection.execute("INSERT INTO notes_fts VALUES (?, ?, ?)", ("Inbox/new.md", "New note", "real literal"))
            connection.commit()
        self.assertEqual(hooks.indexed_note(database, "Inbox/new.md"),
                         [["Inbox/new.md", "New note", "real literal"]])
        self.assertEqual(hooks.indexed_note(database, "Inbox/absent.md"), [])

    def test_driver_shell_uses_exact_command_stdin_cwd_and_poisoned_environment(self):
        fixture = self.directory / "fixture.whl"
        fixture.write_bytes(b"Not installed in this command-only test")
        run = hooks.HookRun(self.directory / ".knowledgeos/proof", fixture, "wheel", sys.executable)
        run.vault.mkdir()
        program = ("import os,sys,json; print(json.dumps({'cwd':os.getcwd(),'stdin':sys.stdin.read(),"
                   "'path':os.environ.get('PATH'),'pythonpath':os.environ.get('PYTHONPATH')}))")
        if os.name == "nt":
            command = subprocess.list2cmdline([sys.executable, "-I", "-c", program])
        else:
            import shlex
            command = shlex.join([sys.executable, "-I", "-c", program])
        run.generated = {"commands": {"sessionStart": command}}
        observed = json.loads(run.hook("actual-command", "sessionStart", {"memory_session_id": "first"}))
        self.assertEqual(Path(observed["cwd"]), run.vault)
        self.assertEqual(json.loads(observed["stdin"]), {"memory_session_id": "first"})
        self.assertIn(observed["path"], ("", None))
        self.assertIn(str(run.vault), observed["pythonpath"])
        self.assertEqual(run.processes[0]["stopped"], True)
        record = json.loads((run.directory / "actual-command.command.json").read_text(encoding="utf-8"))
        self.assertEqual(record["command"], command)
        self.assertEqual(record["shell"], True)
        self.assertEqual(record["exit_code"], 0)

    def test_hostile_fixture_marks_execution_but_is_not_run_by_fixture_creation(self):
        fixture = self.directory / "fixture.whl"
        fixture.write_bytes(b"Not installed in this fixture-only test")
        run = hooks.HookRun(self.directory / ".knowledgeos/proof", fixture, "wheel", sys.executable)
        run.poison_vault()
        self.assertEqual(run.marker.exists(), False)
        poison = run.vault / ".cursor/hooks/twin_session_start.py"
        command = [sys.executable, "-I", str(poison)]
        child = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(child.returncode, 1)
        self.assertEqual(run.marker.read_text(encoding="utf-8"), "vault code executed\n")

    def test_failed_child_retains_exit_and_shutdown_evidence(self):
        fixture = self.directory / "fixture.whl"
        fixture.write_bytes(b"Not installed in this command-only test")
        run = hooks.HookRun(self.directory / ".knowledgeos/proof", fixture, "wheel", sys.executable)
        with self.assertRaisesRegex(RuntimeError, "failed"):
            run.command("failed-child", [sys.executable, "-I", "-c", "import sys;sys.exit(7)"])
        self.assertEqual(run.processes[0]["exit_code"], 7)
        self.assertEqual(run.processes[0]["stopped"], True)
        self.assertEqual(run.finish(ValueError("Retained failed attempt")), 1)
        report = json.loads((run.directory / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["all_started_processes_stopped"], True)
        self.assertIn("failed-child.command.json", report["transcript_files"])
        self.assertIn("execution-error.json", report["transcript_files"])
        self.assertEqual(json.loads((run.directory / "execution-error.json").read_text(encoding="utf-8")),
                         {"error": "Retained failed attempt"})


if __name__ == "__main__":
    unittest.main()
