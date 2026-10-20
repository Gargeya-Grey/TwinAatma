"""Atomic writes recover from short native Windows replacement refusals."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knowledgeos import textio


@unittest.skipUnless(os.name == "nt", "native Windows handle sharing")
class AtomicReplaceWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ta-atomic-replace-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / ".knowledgeos"
        self.directory.mkdir()
        self.target = self.directory / "note.md"
        self.target.write_bytes(b"original\r\nuntouched\n")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handles = []
        self.addCleanup(self.close_handles)

    def hold_without_delete_sharing(self, path=None):
        handle = self.kernel.CreateFileW(str(path or self.target), 0x80000000, 0x1 | 0x2,
                                         None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append(handle)
        return handle

    def release(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.remove(handle)

    def close_handles(self):
        for handle in self.handles[:]:
            self.release(handle)

    def test_native_handle_release_allows_complete_atomic_write(self):
        held = self.hold_without_delete_sharing()
        real_replace = os.replace
        denials = []

        def release_after_denial(source, destination):
            try:
                return real_replace(source, destination)
            except PermissionError as error:
                denials.append(error.winerror)
                if held in self.handles:
                    self.release(held)
                raise

        with patch.object(textio.os, "replace", side_effect=release_after_denial):
            textio.atomic_write_bytes(self.target, b"complete\nreplacement\r\n")

        self.assertEqual(denials[0], 5)
        self.assertTrue(all(code == 5 for code in denials))
        self.assertEqual(self.target.read_bytes(), b"complete\nreplacement\r\n")
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_persistent_native_handle_refusal_is_bounded_and_preserves_original(self):
        self.hold_without_delete_sharing()
        real_replace = os.replace
        denials = []

        def retain_denial(source, destination):
            try:
                return real_replace(source, destination)
            except PermissionError as error:
                denials.append(error.winerror)
                raise

        with patch.object(textio.os, "replace", side_effect=retain_denial):
            with self.assertRaises(PermissionError):
                textio.atomic_write_bytes(self.target, b"replacement\n")

        self.assertGreater(len(denials), 1)
        self.assertLessEqual(len(denials), 6)
        self.assertTrue(all(code == 5 for code in denials))
        self.assertEqual(self.target.read_bytes(), b"original\r\nuntouched\n")
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_retry_refuses_a_replaced_staging_name(self):
        held = self.hold_without_delete_sharing()
        real_replace = os.replace
        retained = self.directory / "retained-staging"

        def swap_after_denial(source, destination):
            try:
                return real_replace(source, destination)
            except PermissionError:
                self.release(held)
                real_replace(source, retained)
                Path(source).write_bytes(b"untrusted replacement\n")
                self.assertNotEqual(os.lstat(source).st_ino, os.lstat(retained).st_ino)
                raise

        with patch.object(textio.os, "replace", side_effect=swap_after_denial):
            with self.assertRaisesRegex(OSError, "unexpected temp file"):
                textio.atomic_write_bytes(self.target, b"complete intended bytes\n")

        self.assertEqual(self.target.read_bytes(), b"original\r\nuntouched\n")
        self.assertEqual(retained.read_bytes(), b"complete intended bytes\n")
        self.assertFalse(list(self.directory.glob(".gate-write-*")))

    def test_retry_refuses_staging_hardlinked_to_protected_bytes(self):
        held = self.hold_without_delete_sharing()
        real_replace = os.replace
        protected = self.directory / "synthetic-Self.md"
        protected.write_bytes(b"synthetic owner identity must stay intact\n")
        retained = self.directory / "retained-staging"

        def hardlink_after_denial(source, destination):
            try:
                return real_replace(source, destination)
            except PermissionError:
                self.release(held)
                real_replace(source, retained)
                os.link(protected, source)
                raise

        with patch.object(textio.os, "replace", side_effect=hardlink_after_denial):
            with self.assertRaisesRegex(OSError, "unexpected temp file"):
                textio.atomic_write_bytes(self.target, b"complete intended bytes\n")

        self.assertEqual(self.target.read_bytes(), b"original\r\nuntouched\n")
        self.assertEqual(protected.read_bytes(), b"synthetic owner identity must stay intact\n")
        self.assertEqual(retained.read_bytes(), b"complete intended bytes\n")
        self.assertFalse(list(self.directory.glob(".gate-write-*")))

    def test_retry_refuses_an_additional_link_to_the_same_staging_file(self):
        held = self.hold_without_delete_sharing()
        real_replace = os.replace
        alias = self.directory / "staging-alias"

        def link_after_denial(source, destination):
            try:
                return real_replace(source, destination)
            except PermissionError:
                self.release(held)
                os.link(source, alias)
                raise

        with patch.object(textio.os, "replace", side_effect=link_after_denial):
            with self.assertRaisesRegex(OSError, "unexpected temp file"):
                textio.atomic_write_bytes(self.target, b"complete intended bytes\n")

        self.assertEqual(self.target.read_bytes(), b"original\r\nuntouched\n")
        self.assertEqual(alias.read_bytes(), b"complete intended bytes\n")
        self.assertFalse(list(self.directory.glob(".gate-write-*")))

    def test_unrelated_faults_are_not_retried(self):
        failures = (PermissionError("plain permission refusal"), OSError(28, "disk full"),
                    OSError(13, "invalid native operation", None, 87))
        for failure in failures:
            with self.subTest(failure=str(failure)):
                with patch.object(textio.os, "replace", side_effect=failure) as replaced:
                    with self.assertRaises(OSError) as caught:
                        textio.atomic_write_bytes(self.target, b"replacement\n")
                self.assertIs(caught.exception, failure)
                self.assertEqual(replaced.call_count, 1)
                self.assertEqual(self.target.read_bytes(), b"original\r\nuntouched\n")
                self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_exclusive_publication_does_not_retry_native_denials(self):
        destination = self.directory / "new-note.md"
        failure = OSError(13, "exclusive publication denied", None, 5)
        with patch.object(textio.os, "link", side_effect=failure) as linked:
            with self.assertRaises(OSError) as caught:
                textio.atomic_create_bytes(destination, b"complete new file\n")
        self.assertIs(caught.exception, failure)
        self.assertEqual(linked.call_count, 1)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_other_platforms_do_not_retry_windows_shaped_errors(self):
        failure = OSError(13, "native-looking refusal", None, 5)
        with patch.object(textio, "os", wraps=os) as platform_os:
            platform_os.name = "posix"
            platform_os.replace.side_effect = failure
            with self.assertRaises(OSError) as caught:
                textio.atomic_write_bytes(self.target, b"replacement\n")
        self.assertIs(caught.exception, failure)
        self.assertEqual(platform_os.replace.call_count, 1)
        self.assertEqual(self.target.read_bytes(), b"original\r\nuntouched\n")
        self.assertEqual(list(self.directory.iterdir()), [self.target])


if __name__ == "__main__":
    unittest.main(verbosity=2)
