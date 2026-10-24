"""Construction checks for the initialized resource-budget workload."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/verify-twinaatma/scripts/resource_budget.py'
EVIDENCE = ROOT / 'work/gc-artifacts/.knowledgeos/resume-20261023/resource-baseline'


@unittest.skipUnless(os.name == 'nt', 'Native Windows resource fixture')
class InitializedResourceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('resource_fixture_test', SCRIPT)
        cls.producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.producer)
        cls.driver = cls.producer.Run(EVIDENCE / ('fixture-' + uuid.uuid4().hex[:8]), [100], 1, None, cls.producer.SEED)
        cls.fixture = cls.driver.build_vault(100)

    def test_baseline_indexes_all_scale_notes_and_reset_preserves_signed_state(self):
        fixture = self.fixture
        baseline = fixture['vault'].parent / 'initialized-baseline'
        self.assertEqual(self.producer.Run.indexed_count(baseline / 'vault'), 100)
        before = self.producer.file_inventory(fixture['state'])
        self.assertIn('gate.key', before)
        (fixture['state'] / 'gate.key').write_text('deliberately changed after setup', encoding='utf-8')
        (fixture['vault'] / 'knowledge_index.db').unlink()
        (fixture['vault'] / '.knowledgeos/autopilot.json').write_text('{}', encoding='utf-8')
        self.driver.reset_cold(fixture)
        self.assertEqual(self.producer.file_inventory(fixture['state']), before)
        self.assertEqual(self.producer.Run.indexed_count(fixture['vault']), 100)
        self.assertEqual(self.producer.file_inventory(fixture['vault'] / '.knowledgeos'),
                         self.producer.file_inventory(baseline / 'vault/.knowledgeos'))
        self.assertTrue(all(p['stopped'] for p in self.driver.processes))
        self.assertTrue(all(p['exit_code'] == 0 for p in self.driver.processes))
        self.assertEqual(self.driver.rows, [])
        self.assertEqual([p['role'] for p in self.driver.processes], ['init-100', 'setup-100'])


if __name__ == '__main__':
    unittest.main()
