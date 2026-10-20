"""Outcome evidence and optional publishing preserve identity and source content."""
from __future__ import annotations

import contextlib
import datetime
import importlib.util
import io
import sqlite3
import unittest
from unittest import mock

from support import ROOT, TempVaultCase
from knowledgeos.memory import dispatch


def script_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NotionPublishingTests(TempVaultCase):
    def setUp(self):
        super().setUp()
        self.publisher = script_module("publish_to_notion")
        self.publisher.VAULT_DIR = str(self.vault)
        self.pages = []
        self.calls = []

    def transport(self, method, path, data=None, key=None):
        self.calls.append((method, path, data))
        if path == "data_sources/fixture-source/query":
            identity = data["filter"]["url"]["equals"]
            return {"results": [p for p in self.pages if p["properties"]["Obsidian Link"]["url"] == identity], "has_more": False}
        if method == "POST" and path == "pages":
            page = dict(data, id=f"page-{len(self.pages)}", url="https://example.invalid/page")
            self.pages.append(page)
            return page
        if method == "GET" and path.startswith("blocks/"):
            page_id = path.split("/")[1]
            page = next(p for p in self.pages if p["id"] == page_id)
            return {"results": page["children"], "has_more": False}
        raise AssertionError((method, path, data))

    def publish(self, path, dry_run=False):
        with mock.patch.object(self.publisher, "notion_api", side_effect=self.transport), contextlib.redirect_stdout(io.StringIO()):
            return self.publisher.publish_note(path, dry_run=dry_run, key="synthetic-key", ds_id="fixture-source")

    def test_retry_converges_without_duplicate_or_content_truncation(self):
        body = "alpha " * 901 + "ω end\n"
        path = self.write("Concepts/publish.md", "---\ntitle: Share this\nstatus: refined\npublish_to_notion: true\n---\n" + body)
        original = path.read_bytes()
        self.assertTrue(self.publish(path))
        self.assertTrue(self.publish(path))
        self.assertEqual(len(self.pages), 1)
        paragraphs = self.pages[0]["children"]
        actual = "".join(chunk["text"]["content"] for p in paragraphs for chunk in p["paragraph"]["rich_text"])
        self.assertEqual(actual, body)
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(all(len(chunk["text"]["content"]) <= 2000 for p in paragraphs for chunk in p["paragraph"]["rich_text"]))

    def test_existing_remote_edits_are_preserved_with_failure(self):
        path = self.write("Concepts/publish.md", "---\ntitle: Share this\nstatus: refined\npublish_to_notion: true\n---\nOriginal\n")
        self.assertTrue(self.publish(path))
        self.pages[0]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"] = "Edited remotely"
        self.assertFalse(self.publish(path))
        self.assertEqual(len(self.pages), 1)
        self.assertEqual(self.pages[0]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"], "Edited remotely")
        self.assertFalse(any(method in {"PATCH", "DELETE"} for method, _, _ in self.calls))

    def test_dry_run_and_unselected_notes_never_call_transport(self):
        path = self.write("Concepts/publish.md", "---\ntitle: Private\nstatus: refined\npublish_to_notion: false\n---\nPrivate\n")
        self.assertFalse(self.publish(path))
        path.write_text("---\ntitle: Preview\nstatus: refined\npublish_to_notion: true\n---\nPreview\n", encoding="utf-8")
        self.assertTrue(self.publish(path, dry_run=True))
        self.assertEqual(self.calls, [])

    def test_failed_transport_is_nonzero_at_script_entrypoint(self):
        path = self.write("Concepts/publish.md", "---\ntitle: Share this\nstatus: refined\npublish_to_notion: true\n---\nContent\n")
        env = self.publisher._notion_env
        with mock.patch.object(env, "get_notion_config", return_value={}), mock.patch.object(env, "get_notion_key", return_value="synthetic"), mock.patch.object(env, "get_notion_database_id", return_value="fixture-source"), mock.patch.object(self.publisher, "notion_api", side_effect=OSError("network unavailable")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.publisher.main([str(path)]), 1)

    def test_oversized_batch_refuses_before_remote_write(self):
        path = self.write("Concepts/large.md", "---\ntitle: Large\nstatus: refined\npublish_to_notion: true\n---\n" + "x" * 200001)
        self.assertFalse(self.publish(path))
        self.assertEqual(self.calls, [])

    def test_bridge_import_does_not_resolve_credentials(self):
        env = self.publisher._notion_env
        with mock.patch.object(env, "get_notion_key", side_effect=AssertionError("must be lazy")), mock.patch.object(env, "get_notion_database_id", side_effect=AssertionError("must be lazy")):
            script_module("notion_bridge")

    def test_ambiguous_network_create_retry_queries_saved_remote_page(self):
        path = self.write("Concepts/publish.md", "---\ntitle: Retried\nstatus: refined\npublish_to_notion: true\n---\nComplete body\n")
        def lost_reply(method, endpoint, data=None, key=None):
            result = self.transport(method, endpoint, data, key)
            if endpoint == "pages":
                raise OSError("response lost after remote create")
            return result
        with mock.patch.object(self.publisher, "notion_api", side_effect=lost_reply), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.publisher.publish_note(path, key="synthetic", ds_id="fixture-source"))
        self.assertTrue(self.publish(path))
        self.assertEqual(len(self.pages), 1)

    def test_duplicate_source_identity_refuses_any_additional_write(self):
        path = self.write("Concepts/publish.md", "---\ntitle: Existing\nstatus: refined\npublish_to_notion: true\n---\nBody\n")
        self.assertTrue(self.publish(path))
        self.pages.append(dict(self.pages[0], id="duplicate"))
        before = len(self.calls)
        self.assertFalse(self.publish(path))
        self.assertEqual(len(self.pages), 2)
        self.assertEqual([c[1] for c in self.calls[before:]], ["data_sources/fixture-source/query"])

    def test_bridge_dry_runs_make_no_transport_or_credential_calls(self):
        bridge = script_module("notion_bridge")
        path = self.write("Concepts/preview.md", "---\ntitle: Preview\nstatus: refined\npublish_to_notion: true\n---\nComplete body\n")
        with mock.patch.object(bridge.publish_to_notion, "VAULT_DIR", str(self.vault)), mock.patch.object(bridge._notion_env, "get_notion_config", return_value={}), mock.patch.object(bridge._notion_env, "get_notion_key", side_effect=AssertionError("no credentials")), mock.patch.object(bridge._notion_env, "get_notion_database_id", side_effect=AssertionError("no credentials")), mock.patch.object(bridge.publish_to_notion, "notion_api", side_effect=AssertionError("no transport")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bridge.main(["--dry-run", "setup"]), 0)
            self.assertEqual(bridge.main(["--dry-run", "publish", str(path)]), 0)
            self.assertEqual(bridge.main(["--dry-run", "publish", '{"title":"unscoped"}']), 1)

    def test_outside_vault_source_is_refused_before_any_transport(self):
        path = self.root / "outside-publish.md"
        original = b"---\nstatus: refined\npublish_to_notion: true\n---\nOutside scope.\n"
        path.write_bytes(original)
        self.assertFalse(self.publish(path))
        self.assertEqual(self.calls, [])
        self.assertEqual(path.read_bytes(), original)

    def test_all_selection_uses_current_source_opt_in(self):
        selected = self.write("Concepts/selected.md", "---\ntitle: Selected\nstatus: refined\npublish_to_notion: true\n---\nBody\n")
        self.write("Concepts/private.md", "---\ntitle: Private\nstatus: refined\npublish_to_notion: false\n---\nBody\n")
        self.write("Templates/template.md", "---\ntitle: Template\nstatus: refined\npublish_to_notion: true\n---\nBody\n")
        self.assertEqual(self.publisher._collect_publish_candidates(), [str(selected)])


class LearningEvidenceTests(TempVaultCase):
    def test_recent_formatting_activity_does_not_propose_changed_beliefs(self):
        today = datetime.date.today().isoformat()
        self.write("Concepts/format.md", f"---\ntitle: Reformat only\nupdated: {today}\n---\n\nSame belief.\n")
        api = self.api()
        before = self.proposal_files()
        with self.guard() as guard:
            result = dispatch(api, "memory_propose_from_drift", {"days": 30})
        guard.assert_unchanged(self)
        self.assertFalse(result.get("proposed"), result)
        self.assertNotIn("proposal_path", result)
        self.assertEqual(self.proposal_files(), before)
        self.assertFalse(result["semantic_change_assessed"])
        self.assertEqual(result["activity"]["source"], "index_updated")

    def test_unfinished_or_nondecision_lesson_cannot_be_promoted(self):
        for kind, outcome in (("decision", "pending"), ("concept", "confirmed")):
            with self.subTest(kind=kind, outcome=outcome):
                self.write("Decisions/lesson.md", f"---\ntitle: Trial\ntype: {kind}\noutcome_status: {outcome}\nlesson: Prefer options\n---\n\nTrial.\n")
                result = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "Decisions/lesson.md"})
                self.assertIn("error", result, result)
                self.assertFalse(self.proposal_files())

    def test_empty_and_git_edit_counts_never_assert_semantic_change(self):
        api = self.api()
        for activity in ({"source": "git", "edits_by_folder": {}}, {"source": "git", "edits_by_folder": {"People": 10000}}):
            with self.subTest(activity=activity), mock.patch.object(api, "drift", return_value=activity):
                result = dispatch(api, "memory_propose_from_drift", {})
                self.assertFalse(result["proposed"])
                self.assertFalse(result["semantic_change_assessed"])
                self.assertEqual(result["activity"], activity)
                self.assertFalse(self.proposal_files())

    def test_frozen_index_activity_retains_incompleteness_diagnostic(self):
        api = self.api()
        api.search("warm")
        holder = sqlite3.connect(api.db_path)
        try:
            holder.execute("BEGIN IMMEDIATE")
            with self.guard() as guard:
                result = dispatch(api, "memory_propose_from_drift", {})
        finally:
            holder.rollback()
            holder.close()
        guard.assert_unchanged(self)
        self.assertTrue(result["index_frozen"], result)
        self.assertFalse(result["proposed"])
        self.assertFalse(self.proposal_files())

    def test_completed_lesson_links_real_source_and_states_uncertainty(self):
        self.write("Decisions/lesson.md", "---\nid: evidence-decision\ntitle: Trial\ntype: decision\noutcome_status: confirmed\nlesson:\n  - Prefer options\n  - Preserve evidence\n---\n\nTrial.\n")
        with self.guard() as guard:
            result = dispatch(self.api(), "memory_propose_from_lesson", {"path_or_id": "evidence-decision"})
        guard.assert_unchanged(self)
        self.assertNotIn("error", result)
        proposal = (self.vault / result["proposal_path"]).read_text(encoding="utf-8")
        self.assertIn("Decisions/lesson.md", proposal)
        self.assertIn("does not establish a general belief", proposal)
        self.assertIn("Prefer options", proposal)


if __name__ == "__main__":
    unittest.main()
