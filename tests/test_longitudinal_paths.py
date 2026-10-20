"""Retained Windows evidence must bind to the exact checkout when graded in WSL."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/verify-twinaatma/scripts'))
from longitudinal_adapter import RecordedPaths


class LongitudinalRecordedPathsTests(unittest.TestCase):
    def test_native_paths_roundtrip_and_reject_outside(self):
        paths = RecordedPaths(ROOT, str(ROOT))
        selected = ROOT / 'work/gc-artifacts/.knowledgeos/proof/report.json'
        self.assertEqual(paths.local(paths.text(selected)), selected)
        with self.assertRaises(ValueError):
            paths.text(ROOT.parent / 'other-vault/report.json')

    def test_only_exact_windows_wsl_checkout_alias_is_accepted(self):
        native = str(ROOT)
        if native.startswith('/mnt/'):
            declared = ROOT.parts[2].upper() + ':\\' + '\\'.join(ROOT.parts[3:])
        elif len(native) > 2 and native[1] == ':':
            declared = '/mnt/' + native[0].lower() + '/' + '/'.join(ROOT.parts[1:])
        else:
            self.skipTest('No Windows/WSL drive mapping on this checkout')
        paths = RecordedPaths(ROOT, declared)
        selected = ROOT / 'People/Self.md'
        self.assertEqual(paths.local(paths.text(selected)), selected)
        for invalid in (declared + '-other', declared + '/..', 'relative/root', '//server/share', 'Z:\\outside'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                RecordedPaths(ROOT, invalid)

    def test_observed_sentinel_cannot_escape_or_change_spelling(self):
        paths = RecordedPaths(ROOT, str(ROOT))
        for invalid in ('relative/note.md', str(ROOT / '..' / 'outside.md'), str(ROOT.parent / 'unowned.md')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                paths.local(invalid)


if __name__ == '__main__':
    unittest.main()
