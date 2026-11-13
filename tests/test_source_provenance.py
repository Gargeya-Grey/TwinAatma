from __future__ import annotations

import os
from pathlib import Path
import secrets
import sqlite3
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI, dispatch


class SourceProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/source-provenance" / secrets.token_hex(8))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\nUnknown.\n")
        self.identity_before = self.identity.read_bytes()
        self.environment = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = self.write("source", "ambertoken", "Amber title")
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        self.assertEqual(self.identity.read_bytes(), self.identity_before)

    def write(self, name, body, title="Synthetic source", newline="\n"):
        path = self.vault / "Concepts" / (name + ".md")
        path.parent.mkdir(exist_ok=True)
        text = "---\ntype: concept\ntitle: " + title + "\nstatus: active\n---\n\n" + body + "\n"
        path.write_bytes(text.replace("\n", newline).encode("utf-8"))
        return path

    def search(self, query):
        result = dispatch(self.api, "memory_search", {"query": query})
        self.assertNotIn("error", result)
        return result

    def test_search_sees_an_edit_made_after_the_index_commit(self):
        before = self.source.stat()
        raw = self.source.read_bytes()
        changed = raw.replace(b"ambertoken", b"cedartoken").replace(b"Amber title", b"Cedar title")
        self.assertEqual(len(raw), len(changed))
        fired = []
        connect = sqlite3.connect
        source = self.source

        class EditorAfterCommit(sqlite3.Connection):
            def commit(connection):
                super(EditorAfterCommit, connection).commit()
                if not fired:
                    source.write_bytes(changed)
                    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
                    fired.append(True)

        def connect_with_editor(*args, **kwargs):
            kwargs["factory"] = EditorAfterCommit
            return connect(*args, **kwargs)

        with mock.patch("sqlite3.connect", side_effect=connect_with_editor):
            self.search("ambertoken")
        self.assertEqual(fired, [True])
        self.assertEqual(self.source.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual([row["path"] for row in self.search("cedartoken")["ranked"]],
                         ["Concepts/source.md"])

    def test_capture_keeps_the_signature_of_its_parsed_bytes(self):
        self.search("ambertoken")
        connect = sqlite3.connect
        vault = self.vault
        edited = []

        class EditorAfterCommit(sqlite3.Connection):
            def commit(connection):
                super(EditorAfterCommit, connection).commit()
                if not edited:
                    path, = (vault / "Inbox").glob("*.md")
                    before = path.stat()
                    raw = path.read_bytes()
                    changed = raw.replace(b"ambertoken", b"cedartoken")
                    if changed == raw:
                        raise AssertionError("the captured source was not present")
                    path.write_bytes(changed)
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                    edited.append(path.relative_to(vault).as_posix())

        def connect_with_editor(*args, **kwargs):
            kwargs["factory"] = EditorAfterCommit
            return connect(*args, **kwargs)

        with mock.patch("sqlite3.connect", side_effect=connect_with_editor):
            captured = dispatch(self.api, "memory_capture", {
                "title": "Amber capture", "content": "ambertoken is a fictional paper sample."})
        self.assertTrue(captured.get("indexed"), captured)
        self.assertEqual(edited, [captured["path"]])
        self.assertEqual([row["path"] for row in self.search("cedartoken")["ranked"]], edited)

    def test_capture_does_not_bless_new_bytes_of_an_untouched_source(self):
        self.search("ambertoken")
        before = self.source.stat()
        raw = self.source.read_bytes()
        changed = raw.replace(b"ambertoken", b"cedartoken")
        edited = []
        connect = sqlite3.connect
        source = self.source

        class EditorAfterCommit(sqlite3.Connection):
            def commit(connection):
                super(EditorAfterCommit, connection).commit()
                if not edited:
                    source.write_bytes(changed)
                    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
                    edited.append(True)

        def connect_with_editor(*args, **kwargs):
            kwargs["factory"] = EditorAfterCommit
            return connect(*args, **kwargs)

        with mock.patch("sqlite3.connect", side_effect=connect_with_editor):
            captured = dispatch(self.api, "memory_capture", {
                "title": "Other sample", "content": "violetglyph is a fictional paper sample."})
        self.assertTrue(captured.get("indexed"), captured)
        self.assertEqual(edited, [True])
        self.assertEqual([row["path"] for row in self.search("cedartoken")["ranked"]],
                         ["Concepts/source.md"])

    def test_crlf_source_stays_fresh_after_it_is_indexed(self):
        self.write("source", "ambertoken", "Amber title", newline="\r\n")
        self.assertEqual([row["path"] for row in self.search("ambertoken")["ranked"]],
                         ["Concepts/source.md"])
        started = dispatch(self.api, "memory_session_start", {
            "task_hint": "ambertoken", "session_id": "crlf-provenance"})
        self.assertNotIn("error", started)
        self.assertEqual(started["freshness"], {"rebuilt": False, "reason": "fresh"})


if __name__ == "__main__":
    unittest.main()
