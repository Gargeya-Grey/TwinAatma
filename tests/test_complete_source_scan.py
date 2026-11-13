from __future__ import annotations

import contextlib
import os
from pathlib import Path
import secrets
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI, dispatch
from knowledgeos import indexer


class CompleteSourceScanTests(unittest.TestCase):

    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/complete-source-scan-controls" / secrets.token_hex(8))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\nUnknown.\n")
        self.before = self.identity.read_bytes()
        self.environment = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        (self.vault / "Concepts").mkdir()
        self.source = self.vault / "Concepts/source.md"
        self.source.write_text("# Amber source\n\nambertoken denotes a paper model.\n", encoding="utf-8")
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        self.assertEqual(self.identity.read_bytes(), self.before)

    def test_unavailable_source_cannot_be_reported_as_complete_empty_recall(self):
        initial = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual([row["path"] for row in initial["ranked"]], ["Concepts/source.md"])
        original = os.open

        def denied(path, *args, **kwargs):
            if Path(path).absolute() == self.source.absolute():
                raise PermissionError("Synthetic unreadable source")
            return original(path, *args, **kwargs)

        with mock.patch("os.open", side_effect=denied):
            result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertTrue(result.get("error") or result.get("index_frozen"), result)
        restored = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual([row["path"] for row in restored["ranked"]], ["Concepts/source.md"])

    def test_unavailable_directory_is_not_a_complete_empty_census(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        original = os.scandir

        def denied(path):
            if Path(path).absolute() == self.source.parent.absolute():
                raise PermissionError("Synthetic unavailable directory")
            return original(path)

        with mock.patch("os.scandir", side_effect=denied):
            result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertTrue(result.get("error") or result.get("index_frozen"), result)
        restored = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual([row["path"] for row in restored["ranked"]], ["Concepts/source.md"])

    def test_failed_target_does_not_hide_an_indexed_path_outside_the_manifest(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        original = os.open
        opens = []

        def exclude_after_census(path, *args, **kwargs):
            if Path(path).absolute() == self.source.absolute():
                opens.append(True)
                if len(opens) == 2:
                    self.source.write_text("---\nprivacy: exclude\n---\n\nPrivate synthetic source.\n", encoding="utf-8")
            return original(path, *args, **kwargs)

        with mock.patch("os.open", side_effect=exclude_after_census):
            updated = indexer.index_files(self.vault, [self.source])
        self.assertIn("Concepts/source.md", updated["failed"])
        changed, reason = indexer.manifest_diff(self.vault)
        self.assertTrue(changed, reason)
        recalled = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual(recalled["ranked"], [])


    def test_unavailable_source_metadata_is_not_an_intentional_exclusion(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        original = os.lstat

        def denied(path, *args, **kwargs):
            if Path(path).absolute() == self.source.absolute():
                raise PermissionError("Synthetic unavailable source metadata")
            return original(path, *args, **kwargs)

        with mock.patch("os.lstat", side_effect=denied):
            result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertTrue(result.get("error") or result.get("index_frozen"), result)
        restored = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual([row["path"] for row in restored["ranked"]], ["Concepts/source.md"])

    def test_source_changed_during_read_is_incomplete_until_retry(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        source_inode = self.source.stat().st_ino
        original = os.fstat
        edited = []

        def edit_during_read(descriptor):
            info = original(descriptor)
            if info.st_ino == source_inode and not edited:
                self.source.write_text("# Cedar source\n\ncedartoken denotes a paper model.\n", encoding="utf-8")
                edited.append(True)
            return info

        with mock.patch("os.fstat", side_effect=edit_during_read):
            result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual(edited, [True])
        self.assertTrue(result.get("error") or result.get("index_frozen"), result)
        restored = dispatch(self.api, "memory_search", {"query": "cedartoken"})
        self.assertEqual([row["path"] for row in restored["ranked"]], ["Concepts/source.md"])

    def test_intentional_exclusion_is_a_complete_empty_recall(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.source.write_text("---\nprivacy: exclude\n---\n\nambertoken is private.\n", encoding="utf-8")
        result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertNotIn("error", result)
        self.assertFalse(result.get("index_frozen"), result)
        self.assertEqual(result["ranked"], [])
        changed, reason = indexer.manifest_diff(self.vault)
        self.assertFalse(changed, reason)


    def test_directory_type_failure_does_not_hide_a_source_subtree(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        original = os.scandir
        injected = []

        def unavailable(*args, **kwargs):
            injected.append(True)
            raise PermissionError("Synthetic unavailable directory type")

        @contextlib.contextmanager
        def denied(directory):
            with original(directory) as entries:
                if Path(directory).absolute() != self.vault.absolute():
                    yield entries
                    return
                observed = []
                for entry in entries:
                    if entry.name == "Concepts":
                        proxy = mock.Mock(wraps=entry)
                        proxy.name, proxy.path = entry.name, entry.path
                        proxy.is_dir.side_effect = unavailable
                        observed.append(proxy)
                    else:
                        observed.append(entry)
                yield iter(observed)

        with mock.patch("os.scandir", side_effect=denied):
            result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertTrue(injected)
        self.assertTrue(result.get("error") or result.get("index_frozen"), result)
        restored = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertEqual([row["path"] for row in restored["ranked"]], ["Concepts/source.md"])


    def test_excluded_directory_type_failure_does_not_block_recall(self):
        dispatch(self.api, "memory_search", {"query": "ambertoken"})
        original = os.scandir

        def unavailable(*args, **kwargs):
            raise PermissionError("Synthetic unavailable excluded directory type")

        @contextlib.contextmanager
        def denied(directory):
            with original(directory) as entries:
                if Path(directory).absolute() != self.vault.absolute():
                    yield entries
                    return
                observed = []
                for entry in entries:
                    if entry.name == ".knowledgeos":
                        proxy = mock.Mock(wraps=entry)
                        proxy.name, proxy.path = entry.name, entry.path
                        proxy.is_dir.side_effect = unavailable
                        observed.append(proxy)
                    else:
                        observed.append(entry)
                yield iter(observed)

        with mock.patch("os.scandir", side_effect=denied):
            result = dispatch(self.api, "memory_search", {"query": "ambertoken"})
        self.assertNotIn("error", result)
        self.assertFalse(result.get("index_frozen"), result)
        self.assertEqual([row["path"] for row in result["ranked"]], ["Concepts/source.md"])


if __name__ == "__main__":
    unittest.main()
