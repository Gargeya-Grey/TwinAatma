"""The two commands a person types on day one: `import`, then one sitting of `self review`."""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from support import SelfGuard, TempVaultCase

from knowledgeos.__main__ import main

EXPORT = """## Work
- Prefers Postgres over MongoDB for anything with money in it.
- Always wants code examples in Python with type hints.
- Works as a backend engineer on a billing platform in Pune.
"""


class CommandCase(TempVaultCase):
    def source(self, text: str = EXPORT) -> Path:
        path = self.root / "exports" / "assistant-memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *argv: str, answers=None, terminal: bool = True):
        """Run the command. `answers` are what the person types; none left means stdin closed.

        A callable instead of a list reads the screen shown since the last answer and
        returns what the person types for it.
        """
        queue = [] if callable(answers) else list(answers or [])
        prompts: list[str] = []
        out, err = io.StringIO(), io.StringIO()
        read_to = 0

        def typed(prompt: str = "") -> str:
            nonlocal read_to
            prompts.append(prompt)
            if callable(answers):
                screen, read_to = out.getvalue()[read_to:], len(out.getvalue())
                return answers(screen)
            if not queue:
                raise EOFError
            return queue.pop(0)

        patches = [mock.patch("builtins.input", side_effect=typed)]
        if terminal:
            patches += [mock.patch("knowledgeos.gate.is_real_console", return_value=True),
                        mock.patch("knowledgeos.gate._require_human_terminal", return_value=None)]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue(), prompts

    def drafts(self) -> list[str]:
        from knowledgeos import gate

        return [item["path"] for item in gate.list_open(self.vault)]


class ImportCommand(CommandCase):
    def test_import_reports_what_it_kept_and_names_the_next_step(self):
        with SelfGuard(self.vault) as guard:
            code, out, _err, _ = self.run_cli("import", str(self.source()), "--vault", str(self.vault),
                                              "--label", "Other assistant")
        guard.assert_unchanged(self)
        self.assertEqual(code, 0, out)
        self.assertIn("3 memories found", out)
        self.assertIn("Imported 3.", out)
        self.assertIn("twinaatma self review", out)
        self.assertEqual(len(self.drafts()), 1)

    def test_a_large_source_says_how_to_continue(self):
        from knowledgeos import importer

        with mock.patch.object(importer, "MAX_ITEMS", 2):
            code, out, _err, _ = self.run_cli("import", str(self.source()), "--vault", str(self.vault),
                                              "--no-profile-draft")
        self.assertEqual(code, 0, out)
        self.assertIn("Imported 2.", out)
        self.assertIn("1 more were left for the next run", out)

    def test_a_dry_run_writes_nothing(self):
        code, out, _err, _ = self.run_cli("import", str(self.source()), "--vault", str(self.vault), "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("nothing written", out)
        self.assertEqual(self.drafts(), [])

    def test_a_missing_source_fails_and_says_why(self):
        code, out, err, _ = self.run_cli("import", str(self.root / "nowhere.md"), "--vault", str(self.vault))
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        self.assertIn("0 memories found", out)

    def test_a_withheld_credential_is_not_printed(self):
        secret = "sk-live-9f8e7d6c5b4a39281706f5e4d3c2b1a0"
        code, out, err, _ = self.run_cli(
            "import", str(self.source(f"- My API key is {secret} for the payments account.\n"
                                      "- Prefers short answers with one example.\n")),
            "--vault", str(self.vault), "--json")
        self.assertEqual(code, 0, out)
        self.assertIn('"withheld_by_policy": 1', out)
        self.assertNotIn(secret, out + err)


class ReviewInOneSitting(CommandCase):
    def setUp(self) -> None:
        super().setUp()
        api = self.api()
        self.first = api.propose_self_update("Short answers", "heuristics", "* Prefers short answers.",
                                             "Said so twice.", "append")["proposal_path"]
        self.second = api.propose_self_update("No early meetings", "anti_goals", "* Meetings before ten.",
                                              "Said so once.", "append")["proposal_path"]
        self.third = api.propose_self_update("Ship weekly", "active_bets", "* Ship something every week.",
                                             "A stated plan.", "append")["proposal_path"]

    def test_one_sitting_applies_discards_and_keeps(self):
        code, out, _err, prompts = self.run_cli("self", "review", "--vault", str(self.vault),
                                                answers=["y", "d", "n"])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(prompts), 3)
        self.assertIn("Applied 1, discarded 1, kept for later 1.", out)
        text = self.self_text()
        applied = [line for line in ("Prefers short answers.", "Meetings before ten.", "Ship something every week.")
                   if line in text]
        self.assertEqual(len(applied), 1, applied)
        self.assertEqual(len(self.drafts()), 1)

    def test_the_discard_choice_is_offered_on_the_screen(self):
        _code, _out, _err, prompts = self.run_cli("self", "review", "--vault", str(self.vault),
                                                  answers=["n", "n", "n"])
        self.assertTrue(all("d discards" in prompt for prompt in prompts), prompts)

    def test_review_without_a_terminal_changes_nothing(self):
        with SelfGuard(self.vault) as guard:
            code, _out, err, prompts = self.run_cli("self", "review", "--vault", str(self.vault),
                                                    answers=["y", "y", "y"], terminal=False)
        guard.assert_unchanged(self)
        self.assertEqual(code, 2)
        self.assertEqual(prompts, [])
        self.assertIn("interactive terminal", err)
        self.assertEqual(len(self.drafts()), 3)

    def test_a_closed_stdin_applies_nothing(self):
        with SelfGuard(self.vault) as guard:
            code, out, _err, _ = self.run_cli("self", "review", "--vault", str(self.vault), answers=[])
        guard.assert_unchanged(self)
        self.assertEqual(code, 0, out)
        self.assertIn("Applied 0, discarded 0, kept for later 3.", out)

    def test_plain_approve_does_not_offer_discard(self):
        with SelfGuard(self.vault) as guard:
            code, _out, _err, prompts = self.run_cli("self", "approve", self.first, "--vault", str(self.vault),
                                                     answers=["d"])
        guard.assert_unchanged(self)
        self.assertEqual(code, 1)
        self.assertNotIn("d discards", prompts[0])
        self.assertEqual(len(self.drafts()), 3)

    def test_no_drafts_is_a_quiet_success(self):
        for path in (self.first, self.second, self.third):
            self.api().reject_self_update(path, "not now")
        code, out, _err, prompts = self.run_cli("self", "review", "--vault", str(self.vault), answers=[])
        self.assertEqual((code, prompts), (0, []))
        self.assertIn("No Self proposals waiting", out)


class DraftsForOneSection(CommandCase):
    """Applying one change closes every other draft for that section. Review still shows them."""

    def draft(self, summary: str, body: str, mode: str = "append") -> str:
        made = self.api().propose_self_update(summary, "heuristics", body, "Said so.", mode)
        self.assertIn("proposal_path", made, made)
        return made["proposal_path"]

    def test_two_additions_are_both_decided(self):
        self.draft("Short answers", "* Prefers short answers.")
        self.draft("Friday rule", "* Never deploys on a Friday.")
        code, out, _err, prompts = self.run_cli("self", "review", "--vault", str(self.vault),
                                                answers=lambda screen: "y")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(prompts), 2, out)
        self.assertIn("drafted again", out)
        self.assertIn("Prefers short answers.", self.self_text())
        self.assertIn("Never deploys on a Friday.", self.self_text())
        self.assertEqual(self.drafts(), [])

    def test_a_redrafted_addition_can_still_be_declined(self):
        self.draft("Short answers", "* Prefers short answers.")
        self.draft("Friday rule", "* Never deploys on a Friday.")
        typed: list[str] = []

        def decide(screen: str) -> str:
            typed.append("y" if not typed else "n")
            return typed[-1]

        code, out, _err, _prompts = self.run_cli("self", "review", "--vault", str(self.vault), answers=decide)
        self.assertEqual(code, 0, out)
        kept = [line for line in ("Prefers short answers.", "Never deploys on a Friday.") if line in self.self_text()]
        self.assertEqual(len(kept), 1, kept)
        self.assertEqual(len(self.drafts()), 1)

    def test_a_rejection_made_during_review_is_not_undone(self):
        first = self.draft("Short answers", "* Prefers short answers.")
        second = self.draft("Friday rule", "* Never deploys on a Friday.")

        def decide(screen: str) -> str:
            on_screen, other = (first, second) if Path(first).name in screen else (second, first)
            self.assertIn(Path(on_screen).name, screen)
            rejected = self.api().reject_self_update(other, "The person said no in the chat.")
            self.assertNotIn("error", rejected, rejected)
            return "y"

        code, out, _err, prompts = self.run_cli("self", "review", "--vault", str(self.vault), answers=decide)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(prompts), 1, out)
        self.assertNotIn("drafted again", out)
        self.assertEqual(self.drafts(), [])
        kept = [line for line in ("Prefers short answers.", "Never deploys on a Friday.") if line in self.self_text()]
        self.assertEqual(len(kept), 1, kept)

    def test_a_closed_replacement_is_reported_and_not_drafted_again(self):
        current = self.section("## Operating Heuristics")
        lines = [line for line in current.splitlines() if line.startswith("* ")]
        self.draft("Short answers", "* Prefers short answers.")
        self.draft("Rewrite", "\n".join(lines + ["* One new rule."]), "replace")
        code, out, _err, _prompts = self.run_cli(
            "self", "review", "--vault", str(self.vault),
            answers=lambda screen: "n" if "Changes : replace" in screen else "y")
        self.assertEqual(code, 0, out)
        self.assertIn("written against", out)
        self.assertIn("Prefers short answers.", self.self_text())
        self.assertNotIn("One new rule.", self.self_text())
        self.assertEqual(self.drafts(), [])


if __name__ == "__main__":
    unittest.main()
