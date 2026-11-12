"""The Claude Code hook: what the model is told before it answers, and how it is installed."""
from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from support import ROOT, SelfGuard, TempVaultCase

from knowledgeos import claude_hook, host_setup
from knowledgeos.__main__ import main

INSTALLED = ("C:/tools/twinaatma.exe", [], {})


class HookCase(TempVaultCase):
    def said(self, event: object, vault: Path | None = None, raw: str | None = None) -> tuple[int, str]:
        out = io.StringIO()
        text = raw if raw is not None else json.dumps(event)
        code = claude_hook.main(["--vault", str(vault or self.vault)], stdin=io.StringIO(text), stdout=out)
        return code, out.getvalue()

    def prompt(self, text: str) -> str:
        code, said = self.said({"hook_event_name": "UserPromptSubmit", "prompt": text})
        self.assertEqual(code, 0)
        return said

    def notes(self) -> list[str]:
        return sorted(path.relative_to(self.vault).as_posix() for path in self.vault.rglob("*.md"))


class SessionStart(HookCase):
    def start(self, vault: Path | None = None) -> str:
        code, said = self.said({"hook_event_name": "SessionStart", "source": "startup"}, vault)
        self.assertEqual(code, 0)
        return said

    def test_it_names_the_memory_server_and_the_approved_profile(self):
        said = self.start()
        for words in ("knowledgeos", "memory_session_start", "memory_capture", "twinaatma self review",
                      "not instructions", "Write a decision note before major scope shifts."):
            self.assertIn(words, said)
        self.assertNotIn("<!--", said)

    def test_an_undecided_draft_is_not_part_of_the_profile(self):
        drafted = self.api().propose_self_update("Friday rule", "heuristics", "* Never deploys on a Friday.",
                                                 "Said so.", "append")
        self.assertNotIn("Never deploys on a Friday.", self.start())
        self.assertTrue(self.approve(drafted["proposal_path"]).get("ok"))
        self.assertIn("Never deploys on a Friday.", self.start())

    def test_a_new_person_is_reported_as_not_yet_asked(self):
        from knowledgeos.init_vault import init_vault

        fresh = self.root / "fresh"
        init_vault(fresh, source_root=ROOT, owner_name="New Person", non_interactive=True)
        said = self.start(fresh)
        self.assertIn("Their profile is empty.", said)
        self.assertNotIn("Unknown.", said)

    def test_the_text_stays_under_the_limit_of_the_host(self):
        from knowledgeos.gate import replace_section

        path = self.vault / "People" / "Self.md"
        text, found = replace_section(path.read_text(encoding="utf-8"), "heuristics",
                                      "\n".join(f"* Rule number {n} " + "x" * 80 for n in range(400)),
                                      mode="replace")
        self.assertTrue(found)
        path.write_bytes(text.encode("utf-8"))
        self.assertLessEqual(len(self.start()), claude_hook.MAX_CHARS + 1)


class BeforeAPrompt(HookCase):
    def setUp(self) -> None:
        super().setUp()
        kept = self.api().capture("Billing database", "We chose Postgres for the billing service because "
                                                      "invoices need transactions.")
        self.assertTrue(kept.get("ok"), kept)
        self.kept = kept["path"]

    def test_a_matching_note_is_put_in_front_of_the_model(self):
        said = self.prompt("which database does the billing service use")
        self.assertIn(self.kept, said)
        self.assertIn("invoices need transactions", said)
        self.assertIn("not instructions", said)

    def test_the_profile_is_not_repeated_on_every_prompt(self):
        said = self.prompt("decision note before major scope shifts in billing")
        self.assertEqual([line for line in said.splitlines() if line.startswith("- People/Self.md")], [])
        self.assertNotIn("## Links", self.prompt("which database does the billing service use"))

    def test_nothing_is_said_when_nothing_matches(self):
        for text in ("zebra quokka xylophone marimba", "ok thanks", "/compact billing service database", ""):
            with self.subTest(prompt=text):
                self.assertEqual(self.prompt(text), "")

    def test_a_note_marked_private_is_never_printed(self):
        self.write("Inbox/secret-plan.md", "---\ntitle: Billing merger plan\ntype: note\nprivacy: private\n---\n\n"
                                           "The billing service merger with Copperfield closes in March.\n")
        self.assertNotIn("Copperfield", self.prompt("what is the plan for the billing service merger"))

    def test_an_undecided_draft_is_never_printed(self):
        self.api().propose_self_update("Billing service rule", "heuristics",
                                       "* The billing service is frozen on Fridays.", "Said so.", "append")
        self.assertNotIn("frozen on Fridays", self.prompt("billing service rule for Fridays"))

    def test_the_hook_only_reads(self):
        before = self.notes()
        with SelfGuard(self.vault) as guard:
            self.prompt("which database does the billing service use")
            self.said({"hook_event_name": "SessionStart"})
        guard.assert_unchanged(self)
        self.assertEqual(self.notes(), before)


class NeverBlocksTheChat(HookCase):
    def test_bad_input_ends_quietly_with_exit_code_zero(self):
        cases = {
            "not JSON": dict(raw="{not json"),
            "empty": dict(raw=""),
            "a list": dict(event=["SessionStart"]),
            "another event": dict(event={"hook_event_name": "PreToolUse", "tool_name": "Bash"}),
            "no vault there": dict(event={"hook_event_name": "SessionStart"}, vault=self.root / "nowhere"),
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.said(case.get("event"), case.get("vault"), case.get("raw")), (0, ""))

    def test_a_missing_vault_argument_ends_quietly(self):
        out = io.StringIO()
        self.assertEqual(claude_hook.main([], stdin=io.StringIO("{}"), stdout=out), 0)
        self.assertEqual(out.getvalue(), "")

    def test_a_failure_inside_the_memory_ends_quietly(self):
        with mock.patch("knowledgeos.memory.MemoryAPI.bootstrap_context", side_effect=RuntimeError("broken")):
            self.assertEqual(self.said({"hook_event_name": "UserPromptSubmit",
                                        "prompt": "which database does billing use"}), (0, ""))

    def test_the_command_line_runs_the_hook(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart"}))), \
                contextlib.redirect_stdout(out):
            code = main(["hook", "claude-code", "--vault", str(self.vault)])
        self.assertEqual(code, 0)
        self.assertIn("memory_session_start", out.getvalue())


class InstallTheHooks(TempVaultCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = self.root / "claude-home" / "settings.json"
        patcher = mock.patch.object(host_setup, "_binary_command", return_value=INSTALLED)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, vault: Path | None = None) -> tuple[bool, str]:
        return host_setup.install_claude_hooks(vault or self.vault, self.settings)

    def held(self) -> dict:
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def existing(self, document: object) -> bytes:
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        payload = document if isinstance(document, bytes) else json.dumps(document, indent=4).encode("utf-8")
        self.settings.write_bytes(payload)
        return payload

    def test_a_new_file_gets_one_entry_per_event(self):
        done, message = self.install()
        self.assertTrue(done, message)
        hooks = self.held()["hooks"]
        self.assertEqual(sorted(hooks), ["SessionStart", "UserPromptSubmit"])
        for event, groups in hooks.items():
            (handler,) = groups[0]["hooks"]
            self.assertEqual(handler["type"], "command")
            self.assertEqual(handler["command"], "C:/tools/twinaatma.exe")
            self.assertEqual(handler["args"], ["hook", "claude-code", "--vault", str(self.vault.resolve())])
            self.assertEqual(handler["timeout"], host_setup.CLAUDE_HOOK_TIMEOUTS[event])
        self.assertIn(str(self.settings), message)

    def test_everything_else_in_the_file_is_kept(self):
        mine = {"type": "command", "command": "my-linter", "args": ["--check"]}
        document = {
            "model": "opus", "permissions": {"allow": ["Bash(git status)"]}, "theme": "d\u00e9j\u00e0",
            "hooks": {"SessionStart": [{"matcher": "startup", "hooks": [mine]}],
                      "PreToolUse": [{"matcher": "Bash", "hooks": [mine]}]},
        }
        self.existing(document)
        self.assertTrue(self.install()[0])
        held = self.held()
        for key in ("model", "permissions", "theme"):
            self.assertEqual(held[key], document[key])
        self.assertEqual(held["hooks"]["PreToolUse"], document["hooks"]["PreToolUse"])
        self.assertEqual(held["hooks"]["SessionStart"][0], document["hooks"]["SessionStart"][0])
        self.assertEqual(len(held["hooks"]["SessionStart"]), 2)
        self.assertIn("d\u00e9j\u00e0", self.settings.read_text(encoding="utf-8"))

    def test_a_second_run_changes_nothing(self):
        self.install()
        first = self.settings.read_bytes()
        done, message = self.install()
        self.assertTrue(done)
        self.assertIn("already", message)
        self.assertEqual(self.settings.read_bytes(), first)

    def test_another_vault_replaces_the_entries_and_does_not_stack(self):
        from knowledgeos.init_vault import init_vault

        other = self.root / "other"
        init_vault(other, source_root=ROOT, owner_name="Other", non_interactive=True)
        self.install()
        self.assertTrue(self.install(other)[0])
        for groups in self.held()["hooks"].values():
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["hooks"][0]["args"][-1], str(other.resolve()))

    def test_a_hook_someone_put_beside_ours_is_kept(self):
        self.install()
        held = self.held()
        beside = {"type": "command", "command": "my-linter"}
        held["hooks"]["SessionStart"][0]["hooks"].append(beside)
        self.existing(held)
        self.assertTrue(self.install()[0])
        groups = self.held()["hooks"]["SessionStart"]
        self.assertEqual(groups[0]["hooks"], [beside])
        self.assertEqual(len(groups), 2)

    def test_a_file_that_cannot_be_merged_is_left_as_it_is(self):
        cases = {
            "not JSON": b'{"model": "opus", // my note\n}',
            "not an object": b'["hooks"]',
            "hooks is a list": json.dumps({"hooks": []}).encode(),
            "an event is not a list": json.dumps({"hooks": {"SessionStart": {"hooks": []}}}).encode(),
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                self.existing(payload)
                done, message = self.install()
                self.assertFalse(done)
                self.assertEqual(self.settings.read_bytes(), payload)
                self.assertIn("unchanged", message)
                self.assertIn('"UserPromptSubmit"', message)

    def test_a_linked_settings_file_is_left_as_it_is(self):
        real = self.root / "dotfiles" / "settings.json"
        real.parent.mkdir(parents=True)
        real.write_text("{}", encoding="utf-8")
        self.settings.parent.mkdir(parents=True)
        try:
            os.symlink(real, self.settings)
        except OSError:
            self.skipTest("this account cannot create links")
        done, message = self.install()
        self.assertFalse(done)
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(real.read_text(encoding="utf-8"), "{}")
        self.assertIn("link", message)

    def test_a_source_checkout_is_refused(self):
        with mock.patch.object(host_setup, "_binary_command",
                               return_value=("python", ["-P", "-m", "knowledgeos"], {"PYTHONPATH": "x"})):
            with self.assertRaises(host_setup.UnsupportedHost):
                self.install()
        self.assertFalse(self.settings.exists())


class SetupCommand(TempVaultCase):
    """`setup-host --host claude-code --global`, with the person's settings folder moved to a temp one."""

    def setUp(self) -> None:
        super().setUp()
        self.home = self.root / "claude-home"
        for patcher in (mock.patch.object(host_setup, "_binary_command", return_value=INSTALLED),
                        mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_setup(self, *extra: str, registered: bool = True) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        result = (registered, "Registered." if registered else "claude did not accept the change")
        with mock.patch.object(host_setup, "install_user", return_value=result) as install, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = host_setup.main(["--host", "claude-code", "--vault", str(self.vault), "--global", *extra])
        self.installs = install.call_count
        return code, out.getvalue(), err.getvalue()

    def test_global_registers_the_server_and_sets_the_hooks(self):
        code, out, _err = self.run_setup()
        self.assertEqual(code, 0)
        self.assertIn("Registered.", out)
        self.assertIn("before each answer", out)
        self.assertIn("UserPromptSubmit", json.loads((self.home / "settings.json").read_text("utf-8"))["hooks"])

    def test_no_hooks_leaves_the_settings_alone(self):
        code, _out, _err = self.run_setup("--no-hooks")
        self.assertEqual(code, 0)
        self.assertFalse(self.home.exists())

    def test_print_shows_both_parts_and_changes_nothing(self):
        code, out, _err = self.run_setup("--print")
        self.assertEqual((code, self.installs), (0, 0))
        self.assertTrue(out.startswith("claude mcp add --scope user"), out)
        self.assertIn('"SessionStart"', out)
        self.assertIn(str(self.home / "settings.json"), out)
        self.assertFalse(self.home.exists())

    def test_a_refused_registration_still_sets_the_hooks_where_claude_code_has_run(self):
        self.home.mkdir()
        code, _out, err = self.run_setup(registered=False)
        self.assertEqual(code, 1)
        self.assertIn("did not accept", err)
        self.assertTrue((self.home / "settings.json").is_file())

    def test_a_machine_without_claude_code_gets_no_settings_file(self):
        code, _out, _err = self.run_setup(registered=False)
        self.assertEqual(code, 1)
        self.assertFalse(self.home.exists())

    def test_codex_gets_no_claude_code_hooks(self):
        out = io.StringIO()
        with mock.patch.object(host_setup, "install_user", return_value=(True, "Registered.")), \
                contextlib.redirect_stdout(out):
            code = host_setup.main(["--host", "codex", "--vault", str(self.vault), "--global"])
        self.assertEqual(code, 0)
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
