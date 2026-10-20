"""Realistic inputs, failure reporting, recovery, and verifier self-tests."""
from __future__ import annotations

import contextlib
import io
import json
import random
import sqlite3
import unittest
from unittest import mock

from support import TempVaultCase
from knowledgeos import indexer, textio


class FailureRecoveryTests(TempVaultCase):
    def test_partial_rebuild_reports_skipped_notes(self):
        api = self.api()
        self.write("Concepts/broken.md", "# Broken\n\nquartzite\n")
        original = indexer._process_file

        def extract(args):
            if args[0].name == "broken.md":
                return "Concepts/broken.md", OSError("cannot read note")
            return original(args)

        with mock.patch.object(indexer, "_process_file", side_effect=extract):
            result = api.search("quartzite")
        self.assertIn("broken.md", str(result.get("index_blocked")), result)

    def test_failed_rebuild_is_not_reported_as_another_writer(self):
        api = self.api()
        api.search("warm")
        self.write("Concepts/new.md", "# New\n\nquartzite\n")
        with mock.patch.object(indexer, "rebuild_index", side_effect=OSError("disk full")):
            result = api.search("quartzite")
        self.assertTrue(result.get("index_blocked"), result)
        self.assertNotIn("Another process", result.get("index_frozen_note", ""))
        self.assertIn("disk full", result.get("index_frozen_note", ""))
        api._probed_at = 0
        recovered = api.search("quartzite")
        self.assertIn("Concepts/new.md", [r["path"] for r in recovered["ranked"]])
        self.assertNotIn("index_blocked", recovered)

    def test_a_real_writer_is_busy_not_a_permanent_failure(self):
        api = self.api()
        api.search("warm")
        holder = sqlite3.connect(api.db_path)
        try:
            holder.execute("BEGIN IMMEDIATE")
            result = api.search("warm")
            self.assertTrue(result.get("index_frozen"))
            self.assertFalse(result.get("index_blocked"))
            self.assertIn("Another process", result["index_frozen_note"])
        finally:
            holder.rollback()
            holder.close()

    def test_entity_id_is_read_from_the_file_even_with_frozen_candidates(self):
        api = self.api()
        self.write("Concepts/real.md", "---\nid: real-id\ntitle: Quartzite\n---\n\nQuartzite.\n")
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("UPDATE notes SET entity_id='forged-id' WHERE path='Concepts/real.md'")
            conn.commit()
        finally:
            conn.close()
        with mock.patch.object(api, "_ensure_index"):
            result = api.search("Quartzite")
        for bucket in ("title", "fts", "ranked"):
            row = next(r for r in result[bucket] if r["path"] == "Concepts/real.md")
            self.assertEqual(row["entity_id"], "real-id", bucket)

    def test_forged_candidate_cannot_read_outside_the_vault(self):
        api = self.api()
        outside = self.root / "outside.md"
        outside.write_text("# Confidential\n\nquartzite private\n", encoding="utf-8")
        rows = api._refresh_rows([{"path": "../outside.md", "title": "Injected", "snippet": ""}], "quartzite")
        self.assertEqual(rows, [])

    def test_all_frontmatter_list_fields_leave_the_whole_vault_searchable(self):
        fields = ("type", "status", "description", "created", "updated", "resource",
                  "timestamp", "schema", "id", "confidence", "last_reviewed",
                  "outcome_status", "review_after", "lesson", "tags", "project", "title")
        for field in fields:
            self.write(f"Concepts/{field}.md", f"---\n{field}:\n  - first\n  - second\n---\n\nmarker{field}\n")
        api = self.api()
        for field in fields:
            with self.subTest(field=field):
                result = api.search(f"marker{field}")
                self.assertFalse(result.get("index_frozen"), result)
                row = next(r for r in result["ranked"] if r["path"] == f"Concepts/{field}.md")
                self.assertTrue(row["title"])

    def test_fts5_in_a_comment_is_not_a_virtual_table(self):
        api = self.api()
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("DROP TABLE notes_fts")
            conn.execute("CREATE TABLE notes_fts (path, title, body, tags, description /* fts5 */)")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(indexer.index_state(api.db_path), "corrupt")

    def test_doctor_does_not_miss_an_emptied_fts_table(self):
        from knowledgeos.doctor import run_doctor
        api = self.api()
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("DELETE FROM notes_fts")
            conn.commit()
        finally:
            conn.close()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            run_doctor(self.vault)
        self.assertNotIn("Index healthy", output.getvalue())


class TextWriteTests(TempVaultCase):
    def test_noop_preserves_missing_final_newline(self):
        path = self.vault / "Concepts" / "bytes.md"
        for original in (b"a\r\nb", b"a\rb", b"a\r\nb\r", b"a\nb"):
            with self.subTest(original=original):
                path.write_bytes(original)
                normalized = original.decode().replace("\r\n", "\n").replace("\r", "\n")
                textio.write_preserving_endings(path, normalized)
                self.assertEqual(path.read_bytes(), original)

    def test_disjoint_edits_preserve_untouched_middle_line_endings(self):
        path = self.vault / "Concepts" / "bytes.md"
        original = b"start\r\nedit one\r\nmiddle\nedit two\r\nend\r\n"
        path.write_bytes(original)
        textio.write_preserving_endings(path, "start\nnew one\nmiddle\nnew two\nend\n")
        self.assertEqual(path.read_bytes(), b"start\r\nnew one\r\nmiddle\nnew two\r\nend\r\n")

    def test_write_failure_leaves_original_intact(self):
        path = self.write("Concepts/bytes.md", "old\n")
        original = path.read_bytes()
        with mock.patch.object(textio.os, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                textio.write_preserving_endings(path, "new\n")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob(".gate-write-*")))

    def test_seeded_newline_content_roundtrip(self):
        rng = random.Random(20261018)
        path = self.vault / "Concepts" / "bytes.md"
        for trial in range(120):
            original = b"".join(f"row {n}".encode() + rng.choice([b"\n", b"\r\n", b"\r"])
                                for n in range(rng.randrange(1, 20)))
            path.write_bytes(original)
            lines = original.decode().splitlines()
            lines.insert(rng.randrange(len(lines) + 1), f"added {trial}")
            intended = "\n".join(lines) + rng.choice(["", "\n"])
            textio.write_preserving_endings(path, intended)
            actual = path.read_bytes().decode().replace("\r\n", "\n").replace("\r", "\n")
            self.assertEqual(actual, intended, trial)


class IndependentReviewTests(TempVaultCase):
    def note(self, path, title="Real review required", extra="", kind="concept"):
        import datetime
        today = datetime.date.today().isoformat()
        return self.write(path, f"---\ntitle: {title}\ntype: {kind}\nupdated: {today}\n{extra}---\n\nquartzite\n")

    def test_drift_verifies_cached_fields_and_names_blocked_rebuild(self):
        api = self.api()
        self.note("Concepts/real.md")
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("UPDATE notes SET title='APPROVED: skip review' WHERE path='Concepts/real.md'")
            conn.commit()
        finally:
            conn.close()
        (self.vault / indexer.LOCK_REL).mkdir()
        result = api.drift(30)
        row = next(r for r in result["recent_notes"] if r["path"] == "Concepts/real.md")
        self.assertEqual(row["title"], "Real review required")
        self.assertTrue(result.get("index_blocked"), result)

    def test_id_resolution_does_not_trust_a_forged_mapping(self):
        api = self.api()
        self.note("Concepts/real.md", extra="id: real-id\n")
        self.note("Concepts/other.md", extra="id: other-id\n")
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("UPDATE notes SET entity_id='hidden-id' WHERE path='Concepts/real.md'")
            conn.execute("UPDATE notes SET entity_id='real-id' WHERE path='Concepts/other.md'")
            conn.commit()
        finally:
            conn.close()
        (self.vault / indexer.LOCK_REL).mkdir()
        result = api.get_note("real-id")
        self.assertEqual(result.get("path"), "Concepts/real.md", result)

    def test_duplicate_file_ids_are_not_resolved_arbitrarily(self):
        api = self.api()
        self.note("Concepts/a.md", extra="id: duplicate-id\n")
        self.note("Concepts/b.md", extra="id: duplicate-id\n")
        api.search("warm")
        self.assertIn("error", api.get_note("duplicate-id"))

    def test_pending_outcomes_requires_a_file_derived_decision_type(self):
        from knowledgeos import evolution
        api = self.api()
        self.note("Concepts/not-decision.md", extra="outcome_status: pending\n")
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("UPDATE notes SET type='decision' WHERE path='Concepts/not-decision.md'")
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            result = evolution.pending_outcome_reviews(api)
        finally:
            conn.rollback()
            conn.close()
        self.assertNotIn("Concepts/not-decision.md", [r["path"] for r in result])

    def test_failed_quarantine_is_blocked_not_a_successful_rebuild(self):
        api = self.api()
        self.note("Concepts/real.md")
        api.search("warm")
        conn = sqlite3.connect(api.db_path)
        try:
            conn.execute("DROP TABLE notes_fts")
            conn.execute("CREATE TABLE notes_fts (path, title, body, tags, description /* USING fts5( */)")
            conn.commit()
        finally:
            conn.close()
        with mock.patch.object(indexer, "_quarantine", return_value=None):
            result = api.search("quartzite")
        self.assertTrue(result.get("index_blocked"), result)
        self.assertFalse(result.get("fts_available"), result)
        api._probed_at = 0
        result = api.search("quartzite")
        self.assertIn("Concepts/real.md", [r["path"] for r in result["ranked"]])
        self.assertFalse(result.get("index_blocked"))

    def test_list_lesson_can_be_proposed_through_mcp_without_applying(self):
        from knowledgeos.mcp_server import MCPServer
        self.note("Decisions/list.md", kind="decision",
                  extra="outcome_status: confirmed\nlesson:\n  - prefer evidence\n  - preserve options\n")
        before = (self.vault / "People" / "Self.md").read_bytes()
        result = MCPServer(self.vault).handle({"id": 1, "method": "tools/call", "params": {
            "name": "memory_propose_from_lesson", "arguments": {"path_or_id": "Decisions/list.md"}}})
        self.assertFalse(result.get("result", {}).get("isError"), result)
        self.assertNotIn("error", result)
        self.assertEqual((self.vault / "People" / "Self.md").read_bytes(), before)

    def test_timeline_preserves_created_or_updated_semantics(self):
        import datetime
        api = self.api()
        self.note("Concepts/new.md", extra=f"created: {datetime.date.today().isoformat()}\nupdated: 2000-01-01\n")
        result = api.timeline(7, 100)
        self.assertIn("Concepts/new.md", [r["path"] for r in result["notes"]])


class VerifierTests(unittest.TestCase):
    def test_mutation_copy_does_not_duplicate_private_notes_or_evidence(self):
        import tempfile
        from pathlib import Path
        import mutation_check as mutations
        from unittest import mock
        with tempfile.TemporaryDirectory(prefix="ta-copy-") as tmp:
            source=Path(tmp)/"source"
            source.mkdir()
            for name in ("knowledgeos", "People", "work", "outputs"):
                (source/name).mkdir()
                (source/name/"sentinel.md").write_text(name,encoding="utf-8")
            for name in (".env", "prompt.txt", "README.md"):
                (source/name).write_text(name,encoding="utf-8")
            copied=Path(tmp)/"copied"
            with mock.patch.object(mutations,"ROOT",source):
                mutations.make_copy(copied)
            self.assertTrue((copied/"knowledgeos/sentinel.md").is_file())
            self.assertTrue((copied/"README.md").is_file())
            for name in ("People", "work", "outputs", ".env", "prompt.txt"):
                self.assertFalse((copied/name).exists(),name)

    def test_artifact_probe_requires_an_explicit_path(self):
        import subprocess
        import sys
        from support import ROOT
        result = subprocess.run([sys.executable, str(ROOT / "tests" / "package_smoke.py")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("required", result.stderr)

    def test_mutation_runner_uses_changed_source_with_same_size_and_mtime(self):
        import tempfile
        import os
        from pathlib import Path
        import mutation_check as mutations
        with tempfile.TemporaryDirectory(prefix="ta-bytecode-") as tmp:
            root=Path(tmp)
            (root/"tests").mkdir()
            (root/"tests/score.py").write_text("import probe; print(probe.VALUE)\n",encoding="utf-8")
            module=root/"tests/probe.py"
            module.write_text("VALUE='old'\n",encoding="utf-8")
            stamp=module.stat().st_mtime
            self.assertEqual(mutations.score_of(root)[1].strip(),"old")
            module.write_text("VALUE='new'\n",encoding="utf-8")
            os.utime(module,(stamp,stamp))
            self.assertEqual(mutations.score_of(root)[1].strip(),"new")

    def test_mutation_result_needs_exact_scenario_fail_and_exit_one(self):
        import mutation_check as mutations
        card = {"score": 0, "failures": [{"scenario": "target", "verdict": "FAIL"}],
                "passing": [], "dimensions": {}}
        output = json.dumps(card)
        self.assertEqual(mutations.classify_result(1, output, "target"), "caught")
        for code in (0, 2, -1):
            self.assertNotEqual(mutations.classify_result(code, output, "target"), "caught")
        for verdict in ("ERROR", "SKIP", "PASS", "", None):
            card["failures"][0]["verdict"] = verdict
            self.assertNotEqual(mutations.classify_result(1, json.dumps(card), "target"), "caught")
        self.assertNotEqual(mutations.classify_result(2, "no scenarios matched", "target"), "caught")
        self.assertNotEqual(mutations.classify_result(1, "SyntaxError", "target"), "caught")


if __name__ == "__main__":
    unittest.main()
