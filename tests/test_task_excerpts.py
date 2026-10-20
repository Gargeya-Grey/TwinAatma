"""Startup retrieves attributed supporting passages beyond a note's opening."""
import hashlib
import os
from pathlib import Path
import unittest
import uuid

from knowledgeos.memory import MemoryAPI
from knowledgeos.parser import split_frontmatter


class TaskExcerptTests(unittest.TestCase):
    def setUp(self):
        self.scope = Path(__file__).resolve().parents[1] / 'work/gc-artifacts/.knowledgeos/task-excerpt-regression' / uuid.uuid4().hex
        self.vault = self.scope / 'vault'
        (self.vault / 'People').mkdir(parents=True)
        (self.vault / 'Concepts').mkdir()
        (self.vault / 'People/Self.md').write_bytes(b'# Self\n\nUnknown.\n')
        self.saved_state = os.environ.get('KNOWLEDGEOS_STATE_DIR')
        os.environ['KNOWLEDGEOS_STATE_DIR'] = str(self.scope / 'gate-state')
        self.api = MemoryAPI(self.vault)

    def tearDown(self):
        self.assertEqual((self.vault / 'People/Self.md').read_bytes(), b'# Self\n\nUnknown.\n')
        if self.saved_state is None:
            os.environ.pop('KNOWLEDGEOS_STATE_DIR', None)
        else:
            os.environ['KNOWLEDGEOS_STATE_DIR'] = self.saved_state

    def note(self, body):
        path = self.vault / 'Concepts/Source.md'
        path.write_bytes(body.encode('utf-8'))
        return path

    def row(self, hint):
        result = self.api.bootstrap_context(task_hint=hint)
        return next(row for row in result['relevant']['ranked'] if row['path'] == 'Concepts/Source.md')

    def assert_attributed(self, path, row):
        source = path.read_bytes().decode('utf-8')
        body = split_frontmatter(source)[1]
        self.assertEqual(row['sha256'], hashlib.sha256(source.encode('utf-8')).hexdigest())
        self.assertEqual(body[row['excerpt_start']:row['excerpt_end']], row['excerpt'])
        self.assertLessEqual(len(row['excerpt'].encode('utf-8')), 1200)

    def test_supporting_fact_past_opening_is_visible_and_attributed(self):
        claim = 'Juniper archive migration retains signed manifests locally.'
        path = self.note('# Archive\n\n' + 'Neutral shelving inventory. ' * 180 + '\n\n' + claim + '\n\n' + 'Neutral appendix. ' * 100)
        row = self.row('Review Juniper archive migration manifests.')
        self.assertIn(claim, row['excerpt'])
        self.assertTrue(row['excerpt_truncated'])
        self.assertGreater(row['excerpt_start'], 1200)
        self.assert_attributed(path, row)

    def test_heading_passage_includes_its_adjoining_fact(self):
        claim = 'Spruce depot shipping requires handwritten manifests.'
        path = self.note('# Spruce depot shipping\n\n' + claim + '\n\n' + 'Neutral stationery. ' * 160)
        row = self.row('Spruce depot shipping')
        self.assertIn(claim, row['excerpt'])
        self.assert_attributed(path, row)

    def test_long_multilingual_paragraph_stays_byte_bounded(self):
        claim = 'Café voyage timing retains handwritten manifests.'
        path = self.note('# Navigation\n\n' + '甲乙丙丁' * 900 + ' ' + claim + ' ' + '甲乙丙丁' * 900)
        row = self.row('Review café voyage timing.')
        self.assertIn(claim, row['excerpt'])
        self.assert_attributed(path, row)

    def test_later_request_reads_same_size_edit_with_restored_mtime(self):
        path = self.note('# Archive\n\n' + 'Neutral shelving inventory. ' * 180 + '\n\nJuniper archive retains signed manifests locally.\n')
        self.assertIn('signed manifests', self.row('Juniper archive manifests')['excerpt'])
        observed = path.stat()
        before = path.read_bytes()
        path.write_bytes(before.replace(b'signed', b'sealed'))
        os.utime(path, ns=(observed.st_atime_ns, observed.st_mtime_ns))
        row = self.row('Juniper archive manifests')
        self.assertIn('sealed manifests', row['excerpt'])
        self.assertNotIn('signed manifests', row['excerpt'])
        self.assert_attributed(path, row)


if __name__ == '__main__':
    unittest.main(verbosity=2)
