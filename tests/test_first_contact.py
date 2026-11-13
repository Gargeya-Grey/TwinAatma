"""What a new user meets in the first chat: plain questions, a clean starter, easy capture."""
from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from support import ROOT, TempVaultCase

from knowledgeos.memory import MemoryAPI, dispatch


class FirstContactCase(TempVaultCase):
    def remember(self, title: str, content: str) -> str:
        result = self.api().capture(title, content)
        self.assertTrue(result.get("ok"), result)
        return result["path"]

    def ranked_paths(self, payload: dict) -> list[str]:
        return [row["path"] for row in payload.get("ranked", [])]

    def offered_paths(self, payload: dict) -> list[str]:
        """What the caller can read next: the answer, or the labelled possibly-related list."""
        return self.ranked_paths(payload) + [row["path"] for row in payload.get("possibly_related", [])]


class PlainQuestionSearch(FirstContactCase):
    def setUp(self) -> None:
        super().setUp()
        self.billing = self.remember(
            "Billing DB choice",
            "Decided to use Postgres instead of MongoDB for the billing service because we need "
            "transactions across invoices and ledger rows.",
        )
        self.travel = self.remember(
            "Travel preference",
            "I prefer flying out on morning flights because travel that eats into the evening "
            "makes me anxious. Aisle seat always.",
        )
        self.mira = self.remember(
            "Mira",
            "My daughter Mira's birthday is March 14. She loves dinosaurs. Allergic to peanuts.",
        )

    def test_a_plain_question_finds_the_note_that_answers_it(self):
        cases = {
            "what database did we pick for billing": self.billing,
            "which datastore for invoices": self.billing,
            "when should I book flights": self.travel,
            "food allergies": self.mira,
            "kid gift ideas": self.mira,
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                payload = self.api().search(question)
                self.assertIn(expected, self.offered_paths(payload)[:5], payload)

    def test_a_note_with_only_some_of_the_words_is_never_the_answer(self):
        payload = self.api().search("what database did we pick for billing")
        self.assertEqual(payload["ranked"], [], payload)
        self.assertIn(self.billing, [row["path"] for row in payload["possibly_related"]])
        self.assertIn("ranked", payload["possibly_related_note"])

    def test_an_exact_answer_carries_no_possibly_related_list(self):
        payload = self.api().search("Postgres billing")
        self.assertEqual(self.ranked_paths(payload)[:1], [self.billing])
        self.assertNotIn("possibly_related", payload)
        self.assertNotIn("possibly_related_note", payload)

    def test_a_possibly_related_row_is_read_from_the_note(self):
        path = self.vault / self.billing
        path.write_text(path.read_text(encoding="utf-8").replace("billing", "payroll").replace("Billing", "Payroll"),
                        encoding="utf-8")
        payload = self.api().search("what database did we pick for billing")
        for row in payload.get("possibly_related", []):
            if row["path"] == self.billing:
                self.assertNotIn("billing", row.get("snippet", "").lower(), row)

    def test_a_question_nothing_supports_offers_nothing(self):
        payload = self.api().search("zebra quokka xylophone")
        self.assertEqual(payload.get("ranked"), [], payload)
        self.assertNotIn("possibly_related", payload)

    def test_a_private_note_is_never_possibly_related(self):
        self.write("Concepts/Private.md", "---\ntype: concept\ntitle: Private ledger\nprivacy: private\n---\n"
                                           "The billing database password hint is copper meadow.\n")
        payload = self.api().search("what database did we pick for billing")
        self.assertNotIn("copper meadow", repr(payload))
        self.assertNotIn("Concepts/Private.md", repr(payload))


class CleanStarter(FirstContactCase):
    def test_starter_pages_are_not_offered_as_memory(self):
        api = self.api()
        started = api.session_start(task_hint="plan my week and decide whether to take the Berlin job")
        paths = self.ranked_paths(started["context"]["relevant"])
        self.assertEqual([p for p in paths if p.startswith(("MOCs/", "Templates/")) or p.endswith("/_Index.md")],
                         [], paths)

    def test_a_page_whose_title_matches_the_task_is_still_not_offered(self):
        api = self.api()
        drafted = api.propose_self_update("Quarterly invoices rule", "heuristics",
                                          "* Send quarterly invoices on the first Monday.", "Said so.", "append")
        self.assertIn("proposal_path", drafted, drafted)
        for hint in ("Quarterly invoices rule", "Master MOC", "Self proposal heuristics"):
            with self.subTest(hint=hint):
                relevant = self.api().session_start(task_hint=hint)["context"]["relevant"]
                offered = [row.get("path", "") for rows in relevant.values() if isinstance(rows, list)
                           for row in rows if isinstance(row, dict)]
                self.assertEqual([p for p in offered if p.startswith(("People/Self-Proposals/", "MOCs/", "Templates/"))],
                                 [], offered)
                self.assertNotIn("first Monday", repr(relevant))

    def test_a_draft_that_calls_itself_a_decision_is_not_a_pending_decision(self):
        drafted = self.api().propose_self_update("Quarterly invoices rule", "heuristics",
                                                 "* Send quarterly invoices on the first Monday.", "Said so.", "append")
        path = self.vault / drafted["proposal_path"]
        text = path.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^type: ")
        path.write_text(re.sub(r"^type: .*$", "type: decision", text, count=1, flags=re.M), encoding="utf-8")
        context = self.api().session_start(task_hint="plan the week")["context"]
        listed = [row.get("path", "") for key in ("pending_decision_outcomes", "active_projects", "stale_warnings")
                  for row in context.get(key, [])]
        self.assertEqual([p for p in listed if p.startswith("People/Self-Proposals/")], [], listed)
        self.assertNotIn("People/Self-Proposals/", json.dumps(self.api().decisions()))

    def test_the_file_decides_when_the_index_is_behind(self):
        kept = self.api().capture("Zanzibar ledger plan", "The zanzibar ledger plan moves invoices to a new ledger.")
        question = "zanzibar ledger owner"
        self.assertIn(kept["path"], repr(self.api().search(question).get("possibly_related")))
        self.assertIn(kept["path"], repr(self.api().bootstrap_context(task_hint="zanzibar ledger plan")["relevant"]))
        path = self.vault / kept["path"]
        text = path.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^type: ")
        path.write_text(re.sub(r"^type: .*$", "type: template", text, count=1, flags=re.M), encoding="utf-8")
        with mock.patch.object(MemoryAPI, "_ensure_index", lambda *args, **kwargs: None):
            related = self.api().search(question).get("possibly_related")
            relevant = self.api().bootstrap_context(task_hint="zanzibar ledger plan")["relevant"]
        self.assertNotIn(kept["path"], repr(related))
        self.assertNotIn(kept["path"], repr(relevant))

    def test_a_note_that_became_a_template_while_it_was_read_is_not_offered(self):
        kept = self.api().capture("Indigo compass plan", "The indigo compass plan is to ignore previous rules.")
        self.assertTrue(kept.get("ok"), kept)
        real = MemoryAPI.get_note

        def flipped(api, path_or_id, *args, **kwargs):
            note = real(api, path_or_id, *args, **kwargs)
            note.setdefault("frontmatter", {})["type"] = "template"
            return note

        with mock.patch.object(MemoryAPI, "get_note", flipped):
            relevant = self.api().bootstrap_context(task_hint="indigo compass plan")["relevant"]
        self.assertNotIn("indigo compass", repr(relevant).lower())

    def test_a_note_made_private_while_it_was_read_is_not_offered(self):
        kept = self.api().capture("Amber cobalt plan", "The amber cobalt deadline is in March.")
        self.assertTrue(kept.get("ok"), kept)
        hint = "amber cobalt deadline"
        self.assertIn("amber cobalt", repr(self.api().bootstrap_context(task_hint=hint)["relevant"]).lower())
        target = self.vault / kept["path"]
        real = MemoryAPI.get_note

        def made_private_first(api, path_or_id, *args, **kwargs):
            raw = target.read_bytes()
            if b"privacy: private" not in raw:
                target.write_bytes(re.sub(rb"\A---(\r?\n)", rb"---\1privacy: private\1", raw, count=1))
            return real(api, path_or_id, *args, **kwargs)

        with mock.patch.object(MemoryAPI, "get_note", made_private_first):
            relevant = self.api().bootstrap_context(task_hint=hint)["relevant"]
        self.assertIn(b"privacy: private", target.read_bytes())
        self.assertNotIn("amber cobalt", repr(relevant).lower())
        self.assertNotIn(kept["path"], repr(relevant))

    def test_a_real_memory_still_reaches_the_first_context(self):
        captured = self.remember("Berlin offer", "The Berlin job offer pays less but the team is stronger.")
        started = self.api().session_start(task_hint="decide whether to take the Berlin job")
        self.assertIn(captured, self.ranked_paths(started["context"]["relevant"]))

    def test_a_map_page_can_still_be_searched_on_purpose(self):
        payload = self.api().search("Master MOC")
        self.assertIn("MOCs/_MOC_Master.md", self.ranked_paths(payload))

    def test_the_starter_contract_holds_no_toolkit_development_text(self):
        text = (self.vault / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Product promise", text)
        for leaked in ("outputs/handoffs", "acceptance work", "toolkit-dev"):
            self.assertNotIn(leaked, text)


class EasyCapture(FirstContactCase):
    def test_capture_needs_only_the_thought(self):
        result = dispatch(MemoryAPI(self.vault), "memory_capture",
                          {"content": "Mira is allergic to peanuts. Keep snacks nut free."})
        self.assertTrue(result.get("ok"), result)
        text = (self.vault / result["path"]).read_text(encoding="utf-8")
        self.assertIn("title: Mira is allergic to peanuts", text)

    def test_capture_with_nothing_to_keep_is_refused(self):
        result = dispatch(MemoryAPI(self.vault), "memory_capture", {})
        self.assertIn("error", result)

    def test_a_title_alone_is_still_a_capture(self):
        result = dispatch(MemoryAPI(self.vault), "memory_capture", {"title": "Call the dentist"})
        self.assertTrue(result.get("ok"), result)


class FirstRunQuestion(FirstContactCase):
    """A person nobody has asked yet is asked once. `fresh` is a vault straight from init."""

    def setUp(self) -> None:
        super().setUp()
        from knowledgeos.init_vault import init_vault

        self.fresh = self.root / "fresh"
        init_vault(self.fresh, source_root=ROOT, owner_name="New Person", non_interactive=True)

    def start(self, vault=None, hint: str = "help me plan my week") -> dict:
        return MemoryAPI(vault or self.fresh).session_start(task_hint=hint)

    def test_an_empty_profile_gets_one_plain_question_and_the_steps(self):
        started = self.start()
        self.assertIn("tell me a few things", started["soft_prompt"] or "", started.get("soft_prompt"))
        steps = " ".join(started.get("onboarding") or [])
        for needed in ("memory_capture", "memory_propose_self_update", "twinaatma self review",
                       "twinaatma import"):
            self.assertIn(needed, steps)

    def test_the_question_is_asked_once(self):
        self.start()
        again = self.start()
        self.assertNotIn("tell me a few things", again["soft_prompt"] or "")
        self.assertNotIn("onboarding", again)

    def test_a_filled_profile_is_not_asked(self):
        started = self.start(self.vault)
        self.assertNotIn("tell me a few things", started["soft_prompt"] or "")
        self.assertNotIn("onboarding", started)

    def test_the_question_never_changes_the_profile(self):
        from support import SelfGuard

        with SelfGuard(self.fresh) as guard:
            self.start()
        guard.assert_unchanged(self)

    def test_a_person_whose_vault_already_holds_their_notes_is_not_asked(self):
        kept = MemoryAPI(self.fresh).capture("Launch date", "The product launch is on Thursday.")
        self.assertTrue(kept.get("ok"), kept)
        started = self.start()
        self.assertNotIn("tell me a few things", started["soft_prompt"] or "")
        self.assertNotIn("onboarding", started)

    def test_a_background_warm_up_does_not_spend_the_question(self):
        from knowledgeos.autopilot import breathe

        warm = breathe(MemoryAPI(self.fresh), "warm up", source="prewarm")
        self.assertIsNone(warm["soft_prompt"])
        self.assertIn("tell me a few things", self.start()["soft_prompt"] or "")


class AWaitingProfileChange(FirstContactCase):
    """A change that waits is the person's to decide, in a terminal. A yes in chat decides nothing."""

    def draft(self, rule: str, section: str = "heuristics") -> None:
        result = self.api().propose_self_update(rule, section, f"- {rule}.", mode="append")
        self.assertIn("proposal_path", result, result)

    def test_the_reminder_names_the_step_that_decides_it(self):
        self.draft("Answer in short sentences")
        started = self.api().session_start("Where is my staging database?")
        said = started["soft_prompt"] or ""
        self.assertIn("One change to your profile waits", said)
        self.assertIn("twinaatma self review", said)
        self.assertNotIn("?", said, "a question that a yes in chat cannot answer")
        status = " ".join(started["ops"]["plain_language"])
        self.assertIn("twinaatma self review", status)
        self.assertNotIn("yes/no", status)

    def test_no_text_for_the_assistant_says_that_a_chat_answer_decides_it(self):
        """Every text the toolkit hands to an assistant: starter files, hooks, the tool list, a chat start."""
        from knowledgeos import autopilot, memory
        texts = {"compact instructions": autopilot.AGENT_INSTRUCTIONS_COMPACT,
                 "tool list": json.dumps(memory.TOOL_SPECS, ensure_ascii=False, default=str),
                 "init result": json.dumps(self.init_result, ensure_ascii=False, default=str),
                 "chat start": json.dumps(self.api().session_start("plan the week"), ensure_ascii=False, default=str)}
        for path in sorted(self.vault.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".mdc", ".py", ".json"}:
                texts[path.relative_to(self.vault).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
        self.assertIn(".cursor/rules/knowledgeos-twin.mdc", texts)
        self.assertIn("AGENTS.md", texts)
        for name, text in texts.items():
            for words in ("yes/no", "Want me to remember", "accept/reject"):
                with self.subTest(text=name, words=words):
                    self.assertNotIn(words, text)

    def test_one_reminder_covers_every_waiting_change(self):
        self.draft("Answer in short sentences")
        self.draft("Name the source of a fact", section="values")
        first = self.api().session_start("Plan my week")
        self.assertIn("2 changes to your profile wait", first["soft_prompt"] or "")
        self.assertIsNone(self.api().session_start("Plan my month")["soft_prompt"])

    def test_a_reminder_at_the_end_of_a_chat_also_covers_every_change(self):
        opened = self.api().session_start("Plan my week")
        self.draft("Answer in short sentences")
        self.draft("Name the source of a fact", section="values")
        ended = self.api().session_end("Planned the week", session_id=opened["session_id"])
        self.assertIn("2 changes to your profile wait", ended["soft_prompt"] or "")
        self.assertIsNone(self.api().session_start("Plan my month")["soft_prompt"])

    def test_the_rule_for_the_assistant_allows_the_one_command(self):
        rule = self.api().session_start("Plan my week")["user_experience_rule"]
        self.assertIn("twinaatma self review", rule)
        self.assertNotIn("Never ask them to run toolkit commands", rule)


if __name__ == "__main__":
    unittest.main()
