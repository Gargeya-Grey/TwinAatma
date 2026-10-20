"""Public reads must distinguish a racing signed commit from persistent damage."""
import hashlib
import json
import os
from pathlib import Path
import unittest
import uuid
from unittest import mock

from knowledgeos import gate
from knowledgeos.memory import MemoryAPI
from knowledgeos.remembering import RememberingPolicy


class PolicySnapshotTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(os.environ.get('TWIN_SNAPSHOT_FIXTURES') or (Path(__file__).resolve().parents[1] / 'work/gc-artifacts/.knowledgeos/policy-snapshot-regressions'))
        self.scope = fixture_root / uuid.uuid4().hex
        self.vault = self.scope / 'vault'
        (self.vault / 'People').mkdir(parents=True)
        (self.vault / 'Projects').mkdir()
        self.identity = self.vault / 'People/Self.md'
        self.identity.write_bytes(b'# Self\n\nUnknown.\n')
        (self.vault / '.knowledgeos-vault.json').write_text(json.dumps({'vault_id': uuid.uuid4().hex}))
        self.before = {}
        for name, fact in [('seed', 'Oak review cadence stays local.'), ('one', 'Alder packing uses copper cartons.'),
                           ('two', 'Birch packing uses violet cartons.'), ('keep', 'Cedar loading requires signed manifests.')]:
            path = self.vault / f'Projects/{name}.md'
            path.write_text(f'# {name}\n\n{fact}\n', encoding='utf-8')
            self.before[name] = path.read_bytes()
        self.patch_env = mock.patch.dict(os.environ, {'KNOWLEDGEOS_STATE_DIR': str(self.scope / 'state')})
        self.patch_env.start()
        self.api = MemoryAPI(self.vault)
        seeded = self.forget('seed')
        self.assertTrue(seeded.get('ok'), seeded)
        self.mirror = self.vault / '.knowledgeos/remembering-policy.json'
        self.authority = next((self.scope / 'state/vaults').glob('*/remembering-policy.json'))
        self.key = self.scope / 'state/gate.key'

    def tearDown(self):
        self.assertEqual(self.identity.read_bytes(), b'# Self\n\nUnknown.\n')
        for name, data in self.before.items():
            self.assertEqual((self.vault / f'Projects/{name}.md').read_bytes(), data)
        self.patch_env.stop()

    def forget(self, name):
        return MemoryAPI(self.vault).forget(f'Projects/{name}.md', hashlib.sha256(self.before[name]).hexdigest())

    def two_commits(self):
        self.assertTrue(self.forget('one').get('ok'))
        self.assertTrue(self.forget('two').get('ok'))

    def assert_read_and_all_exclusions(self, result):
        self.assertNotIn('error', result)
        self.assertIn('Cedar loading requires signed manifests.', result['body'])
        policy = json.loads(self.authority.read_bytes())
        self.assertEqual(set(policy['state']['forgotten']), {'Projects/seed.md', 'Projects/one.md', 'Projects/two.md'})
        self.assertEqual(self.mirror.read_bytes(), self.authority.read_bytes())
        for name in ('seed', 'one', 'two'):
            self.assertIn('error', MemoryAPI(self.vault).get_note(f'Projects/{name}.md'))

    def test_two_completed_commits_between_snapshot_reads_converge(self):
        original = RememberingPolicy._read_plain
        raced = False

        def read(path):
            nonlocal raced
            raw = original(path)
            if Path(path) == self.mirror and not raced:
                raced = True
                self.two_commits()
            return raw

        with mock.patch.object(RememberingPolicy, '_read_plain', staticmethod(read)):
            result = self.api.get_note('Projects/keep.md')
        self.assertTrue(raced)
        self.assert_read_and_all_exclusions(result)

    def test_atomic_replacement_between_checked_stat_and_open_converges(self):
        original = gate._binding_file
        raced = False

        def checked(path):
            nonlocal raced
            info = original(path)
            if Path(path) == self.mirror and not raced:
                raced = True
                self.two_commits()
            return info

        with mock.patch.object(gate, '_binding_file', side_effect=checked):
            result = self.api.get_note('Projects/keep.md')
        self.assertTrue(raced)
        self.assert_read_and_all_exclusions(result)

    def test_persistent_unsigned_reset_still_refuses_without_repairing_it(self):
        authority, key = self.authority.read_bytes(), self.key.read_bytes()
        tampered = b'{"version":1,"forgotten":{},"superseded":{}}'
        self.mirror.write_bytes(tampered)
        result = self.api.get_note('Projects/keep.md')
        self.assertIn('error', result)
        self.assertNotIn('Cedar loading', json.dumps(result))
        self.assertEqual(self.mirror.read_bytes(), tampered)
        self.assertEqual(self.authority.read_bytes(), authority)
        self.assertEqual(self.key.read_bytes(), key)

    def test_missing_signing_key_still_refuses_and_does_not_regenerate_it(self):
        mirror, authority = self.mirror.read_bytes(), self.authority.read_bytes()
        self.key.rename(self.scope / 'retained-original-key')
        result = self.api.get_note('Projects/keep.md')
        self.assertIn('error', result)
        self.assertFalse(self.key.exists())
        self.assertEqual(self.mirror.read_bytes(), mirror)
        self.assertEqual(self.authority.read_bytes(), authority)


if __name__ == '__main__':
    unittest.main(verbosity=2)
