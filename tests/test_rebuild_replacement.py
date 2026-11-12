from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import unittest
from unittest import mock

from knowledgeos import indexer


class RebuildReplacementTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/rebuild-replacement" / secrets.token_hex(6))
        self.vault = self.root / "vault"
        self.vault.mkdir(parents=True)
        self.environment = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.write("a", "a originalglyph [[b]]\n")
        self.write("b", "b originalglyph [[a]]\n")
        (self.vault / "People").mkdir()
        self.write("People/Self", "# Self\n\nUnknown.\n")
        self.assertEqual(indexer.rebuild_index(self.vault)["failed"], [])
        self.db = self.vault / indexer.DB_NAME

    def write(self, name, body):
        path = self.vault / (name + ".md")
        if name != "People/Self":
            body = "---\ntitle: " + name.upper() + " current\ntype: concept\nid: kos:concept:" + name + "\n---\n\n" + body
        path.write_bytes(body.encode("utf-8"))

    def sources(self):
        return {path.relative_to(self.vault).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.vault.rglob("*.md")}

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return {table: conn.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                    for table in ("notes", "notes_fts", "links", "metadata")}

    def test_failed_duplicate_and_null_rows_survive_successful_replacement(self):
        with sqlite3.connect(self.db) as conn:
            for path in ("a.md", "b.md", None):
                conn.execute("INSERT INTO notes_fts(path,title,body) VALUES(?, 'Retained', 'old duplicate')", (path,))
            conn.execute("INSERT INTO notes_fts(path,title,body) VALUES('gone.md','Gone','goneglyph')")
            retained = conn.execute("SELECT rowid,* FROM notes_fts WHERE path='b.md' OR path IS NULL ORDER BY rowid").fetchall()
            links = conn.execute("SELECT * FROM links WHERE source='b.md' ORDER BY id").fetchall()
        self.write("a", "a currentglyph [[b]]\n")
        before = self.sources()
        process_file = indexer._process_file

        def unreadable(args):
            if args[0].name == "b.md":
                return "b.md", OSError("synthetic unreadable note")
            return process_file(args)

        with mock.patch.object(indexer, "_process_file", side_effect=unreadable):
            result = indexer.rebuild_index(self.vault)
        self.assertEqual({key: result[key] for key in ("notes", "fts_updates", "removed", "failed", "index_state")},
                         {"notes": 2, "fts_updates": 2, "removed": 2, "failed": ["b.md"], "index_state": "ok"})
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT rowid,* FROM notes_fts WHERE path='b.md' OR path IS NULL ORDER BY rowid").fetchall(), retained)
            self.assertEqual(conn.execute("SELECT path,title,body FROM notes_fts WHERE path='a.md'").fetchall(),
                             [("a.md", "A current", "a currentglyph [[b]]\n")])
            self.assertEqual(conn.execute("SELECT * FROM links WHERE source='b.md' ORDER BY id").fetchall(), links)
            self.assertEqual(conn.execute("SELECT path FROM notes_fts WHERE path='gone.md'").fetchall(), [])
        self.assertEqual(self.sources(), before)

    def test_note_trigger_cannot_leave_forged_search_content(self):
        with sqlite3.connect(self.db) as conn:
            conn.executescript("CREATE TRIGGER forged_later AFTER INSERT ON notes WHEN NEW.path='b.md' BEGIN "
                               "INSERT INTO notes_fts(path,title,body) VALUES('b.md','Forged','forgedglyph'); END;")
        before = self.sources()
        self.assertEqual(indexer.rebuild_index(self.vault)["failed"], [])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT path,title,body FROM notes_fts WHERE path='b.md'").fetchall(),
                             [("b.md", "B current", "b originalglyph [[a]]\n")])
            self.assertEqual(conn.execute("SELECT path FROM notes_fts WHERE notes_fts MATCH 'forgedglyph'").fetchall(), [])
        self.assertEqual(self.sources(), before)

    def test_failed_write_rolls_back_all_tables_and_retry_reads_current_source(self):
        with sqlite3.connect(self.db) as conn:
            conn.executescript("CREATE TRIGGER fail_later BEFORE INSERT ON notes WHEN NEW.path='b.md' "
                               "BEGIN SELECT RAISE(ABORT,'synthetic replacement failure'); END;")
        before = self.rows()
        self.write("a", "a revisedglyph [[b]]\n")
        sources = self.sources()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic replacement failure"):
            indexer.rebuild_index(self.vault)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.sources(), sources)
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TRIGGER fail_later")
        self.assertEqual(indexer.rebuild_index(self.vault)["failed"], [])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT body FROM notes_fts WHERE path='a.md'").fetchall(),
                             [("a revisedglyph [[b]]\n",)])
        self.assertEqual(self.sources(), sources)

    def test_public_rebuild_preserves_link_view_and_instead_of_triggers(self):
        with sqlite3.connect(self.db) as conn:
            conn.executescript(
                "ALTER TABLE links RENAME TO retained_edges;"
                "CREATE VIEW links AS SELECT * FROM retained_edges;"
                "CREATE TRIGGER view_insert INSTEAD OF INSERT ON links BEGIN "
                "INSERT INTO retained_edges(source,destination,raw_destination) "
                "VALUES(NEW.source,NEW.destination,NEW.raw_destination); END;"
                "CREATE TRIGGER view_delete INSTEAD OF DELETE ON links BEGIN "
                "DELETE FROM retained_edges WHERE id=OLD.id; END;")
            before_schema = conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name IN ('links','retained_edges','view_insert','view_delete','kos_links_source_lookup_v1') "
                "ORDER BY name").fetchall()
        before_sources = self.sources()
        result = indexer.rebuild_index(self.vault)
        self.assertEqual((result["notes"], result["links"], result["failed"], result["index_state"]), (3, 2, [], "ok"))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT source,destination,raw_destination FROM links ORDER BY source").fetchall(),
                             [("a.md", "b.md", "b"), ("b.md", "a.md", "a")])
            self.assertEqual(conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name IN ('links','retained_edges','view_insert','view_delete','kos_links_source_lookup_v1') "
                "ORDER BY name").fetchall(), before_schema)
        self.assertEqual(self.sources(), before_sources)

    def test_public_rebuild_preserves_unrelated_same_name_table(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP INDEX IF EXISTS kos_links_source_lookup_v1")
            conn.execute("CREATE TABLE kos_links_source_lookup_v1(sentinel TEXT)")
            conn.execute("INSERT INTO kos_links_source_lookup_v1 VALUES('preserve unknown owner')")
            before_schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='kos_links_source_lookup_v1'").fetchall()
        before_sources = self.sources()
        result = indexer.rebuild_index(self.vault)
        self.assertEqual((result["notes"], result["links"], result["failed"], result["index_state"]), (3, 2, [], "ok"))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT * FROM kos_links_source_lookup_v1").fetchall(), [("preserve unknown owner",)])
            self.assertEqual(conn.execute("SELECT sql FROM sqlite_master WHERE name='kos_links_source_lookup_v1'").fetchall(), before_schema)
        self.assertEqual(self.sources(), before_sources)

    def test_sql_write_refusal_rolls_back_schema_and_preserves_signed_publication(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP INDEX IF EXISTS kos_links_source_lookup_v1")
            before_schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        before_rows = self.rows()
        before_sources = self.sources()
        manifest = self.vault / indexer.MANIFEST_REL
        publication = manifest.read_bytes()
        connect = indexer.connect_database

        def refuse_link_insert(path, **options):
            conn = connect(path, **options)
            conn.set_authorizer(lambda action, table, column, database, origin:
                                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == "links"
                                else sqlite3.SQLITE_OK)
            return conn

        with mock.patch.object(indexer, "connect_database", side_effect=refuse_link_insert):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                indexer.rebuild_index(self.vault)
        self.assertEqual(self.rows(), before_rows)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall(), before_schema)
        self.assertEqual(manifest.read_bytes(), publication)
        self.assertEqual(self.sources(), before_sources)


if __name__ == "__main__":
    unittest.main()
