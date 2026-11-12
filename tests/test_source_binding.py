"""Public source reads retain complete path and descriptor safety checks."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from types import SimpleNamespace
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI
from knowledgeos.remembering import EXCLUDED, POLICY, RememberingPolicy


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.scope = (Path(__file__).resolve().parents[1]
                      / "work/gc-artifacts/.knowledgeos/source-binding-controls"
                      / secrets.token_hex(8))
        self.vault = self.scope / "vault"
        (self.vault / "People").mkdir(parents=True)
        (self.vault / "Concepts").mkdir()
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\nUnknown.\n")
        (self.vault / ".knowledgeos-vault.json").write_text(
            json.dumps({"vault_id": secrets.token_hex(16)}), encoding="utf-8")
        self.source = self.vault / "Concepts/source.md"
        self.original = "# Amber café\r\n\r\nambertoken denotes a paper model.\n".encode("utf-8")
        self.source.write_bytes(self.original)
        self.control = self.vault / "Concepts/control.md"
        self.control.write_bytes(b"# Control\n\ncontroltoken denotes a copper model.\n")
        self.environment = mock.patch.dict(os.environ, {
            "KNOWLEDGEOS_STATE_DIR": str(self.scope / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        self.assertEqual(self.identity.read_bytes(), b"# Self\n\nUnknown.\n")

    def assert_refused(self, result):
        self.assertEqual(result, {"ok": False, "error": EXCLUDED, "policy": POLICY})
        control = self.api.get_note("Concepts/control.md")
        self.assertEqual(control["body"], "# Control\n\ncontroltoken denotes a copper model.\n")

    def link_directory(self, target, link):
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(target), str(link))
            else:
                link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest("Native directory links unavailable: " + str(error))

    def link_file(self, source, link):
        try:
            os.link(source, link)
        except OSError as error:
            self.skipTest("Native hardlinks unavailable: " + str(error))

    @contextlib.contextmanager
    def during_read(self, action):
        expected = self.source.stat()
        fdopen = os.fdopen
        fired = []

        class SourceReader:
            def __init__(reader, handle):
                reader.handle = handle

            def __enter__(reader):
                reader.handle.__enter__()
                return reader

            def __exit__(reader, *args):
                return reader.handle.__exit__(*args)

            def fileno(reader):
                return reader.handle.fileno()

            def read(reader, *args, **kwargs):
                raw = reader.handle.read(*args, **kwargs)
                if not fired:
                    action()
                    fired.append(True)
                return raw

        def opened(descriptor, *args, **kwargs):
            handle = fdopen(descriptor, *args, **kwargs)
            actual = os.fstat(descriptor)
            if (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino):
                return SourceReader(handle)
            return handle

        with mock.patch("os.fdopen", side_effect=opened):
            yield fired

    def test_public_read_refuses_lexical_escape_and_preserves_contained_text(self):
        sibling = self.scope / "vault-other/source.md"
        sibling.parent.mkdir()
        sibling.write_bytes(b"# Outside\n\nOutside sentinel.\n")
        policy = RememberingPolicy(self.vault)
        self.assertIsNone(policy.read(sibling))
        self.assertIsNone(policy.read(self.vault / "../vault-other/source.md"))
        self.assertEqual(policy.read(self.vault / "Concepts/../Concepts/source.md"),
                         self.original.decode("utf-8"))
        result = self.api.get_note("Concepts/source.md")
        self.assertEqual(result["body"].encode("utf-8"), self.original)
        self.assertEqual(result["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(sibling.read_bytes(), b"# Outside\n\nOutside sentinel.\n")

    def test_public_read_refuses_hardlinked_source(self):
        retained = self.scope / "source-alias.md"
        self.link_file(self.source, retained)
        self.assert_refused(self.api.get_note("Concepts/source.md"))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(retained.read_bytes(), self.original)

    def test_public_read_refuses_symbolic_leaf(self):
        alias = self.vault / "Concepts/alias.md"
        try:
            alias.symlink_to(self.source)
        except OSError as error:
            self.skipTest("Native file symbolic links unavailable: " + str(error))
        policy = RememberingPolicy(self.vault)
        self.assertIsNone(policy.read(alias))
        self.assertEqual(policy.read(self.source), self.original.decode("utf-8"))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_public_read_refuses_linked_ancestor_even_for_contained_target(self):
        alias = self.vault / "LinkedConcepts"
        self.link_directory(self.source.parent, alias)
        policy = RememberingPolicy(self.vault)
        self.assertIsNone(policy.read(alias / self.source.name))
        self.assertEqual(policy.read(self.source), self.original.decode("utf-8"))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_public_read_refuses_replacement_between_guard_and_open(self):
        before = self.source.stat()
        replacement = self.scope / "replacement.md"
        changed = self.original.replace(b"ambertoken", b"cedartoken")
        replacement.write_bytes(changed)
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        retained = self.scope / "retained-original.md"
        opened = os.open
        fired = []

        def replace(path, *args, **kwargs):
            if Path(path) == self.source and not fired:
                self.source.rename(retained)
                replacement.rename(self.source)
                fired.append(True)
            return opened(path, *args, **kwargs)

        with mock.patch("os.open", side_effect=replace):
            result = self.api.get_note("Concepts/source.md")
        self.assertEqual(fired, [True])
        self.assert_refused(result)
        self.assertEqual(retained.read_bytes(), self.original)
        self.assertEqual(self.source.read_bytes(), changed)
        current = self.api.get_note("Concepts/source.md")
        self.assertEqual(current["body"].encode("utf-8"), changed)
        self.assertEqual(current["sha256"], hashlib.sha256(changed).hexdigest())

    def test_public_read_refuses_new_hardlink_after_read(self):
        retained = self.scope / "source-alias-after-read.md"
        with self.during_read(lambda: self.link_file(self.source, retained)) as fired:
            result = self.api.get_note("Concepts/source.md")
        self.assertEqual(fired, [True])
        self.assert_refused(result)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(retained.read_bytes(), self.original)

    def test_public_read_refuses_unavailable_ancestor_after_read(self):
        lstat = Path.lstat
        completed = []

        def unavailable(path, *args, **kwargs):
            if Path(path) == self.source.parent and completed:
                raise PermissionError("Synthetic source ancestor became unavailable")
            return lstat(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=unavailable):
            with self.during_read(lambda: completed.append(True)) as fired:
                result = self.api.get_note("Concepts/source.md")
        self.assertEqual(fired, [True])
        self.assert_refused(result)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.api.get_note("Concepts/source.md")["body"].encode("utf-8"),
                         self.original)

    def test_public_read_refuses_reparse_ancestor_observation_after_read(self):
        lstat = Path.lstat
        completed = []

        def linked(path, *args, **kwargs):
            if Path(path) == self.source.parent and completed:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777,
                                       st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
            return lstat(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=linked):
            with self.during_read(lambda: completed.append(True)) as fired:
                result = self.api.get_note("Concepts/source.md")
        self.assertEqual(fired, [True])
        self.assert_refused(result)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.api.get_note("Concepts/source.md")["body"].encode("utf-8"),
                         self.original)

    def test_forgotten_unreadable_source_remains_a_complete_exclusion(self):
        forgotten = self.api.forget("Concepts/source.md", hashlib.sha256(self.original).hexdigest())
        self.assertEqual(forgotten.get("ok"), True, forgotten)
        opened = os.open

        def denied(path, *args, **kwargs):
            if Path(path) == self.source:
                raise PermissionError("Synthetic forgotten source is unreadable")
            return opened(path, *args, **kwargs)

        with mock.patch("os.open", side_effect=denied):
            result = self.api.search("ambertoken")
        self.assertNotIn("error", result)
        self.assertEqual(result["ranked"], [])
        self.assertFalse(result.get("index_frozen"), result)
        control = self.api.search("controltoken")
        self.assertEqual([row["path"] for row in control["ranked"]], ["Concepts/control.md"])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertNotIn("denotes a paper model", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
