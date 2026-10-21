import importlib.util
import sys
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/verify-twinaatma/scripts/acceptance.py'


class ExtensionAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('acceptance', SCRIPT)
        cls.metric = importlib.util.module_from_spec(spec)
        sys.modules['acceptance'] = cls.metric
        spec.loader.exec_module(cls.metric)

    def install(self, reports):
        module = types.ModuleType('fake_extension_adapter')
        module.grade = lambda api, paths, current: reports
        sys.modules['fake_extension_adapter'] = module
        self.addCleanup(sys.modules.pop, 'fake_extension_adapter', None)
        self.metric.EXTENSION_ADAPTERS['fake'] = {
            'module': 'fake_extension_adapter', 'scope': 'source',
            'outcomes': {'IDENTITY.integrity_refusal': ['identity.integrity.complete']}}
        self.metric.ADAPTER_REQUIREMENTS['extensions']['fake'] = {'module_sha256': '0' * 64}
        self.addCleanup(self.metric.EXTENSION_ADAPTERS.pop, 'fake', None)
        self.addCleanup(self.metric.ADAPTER_REQUIREMENTS['extensions'].pop, 'fake', None)

    def row(self, check, verdict='PASS', scope='source'):
        return {'path': 'x', 'report_sha256': '1' * 64, 'scope': scope, 'producer': 'fake',
                'checks': {check: {'id': check, 'verdict': verdict}}}

    def test_declared_check_awards_only_its_outcome(self):
        self.install([self.row('identity.integrity.complete')])
        score = self.metric.snapshot([], [], extension_paths={'fake': []})
        self.assertEqual(score['outcomes']['IDENTITY.integrity_refusal']['verdict'], 'PASS')
        self.assertEqual(score['counts']['PASS'], 1)

    def test_extension_cannot_award_an_undeclared_check(self):
        self.install([self.row('setup.cli_init')])
        with self.assertRaisesRegex(ValueError, 'out-of-scope'):
            self.metric.snapshot([], [], extension_paths={'fake': []})

    def test_extension_cannot_change_its_scope(self):
        self.install([self.row('identity.integrity.complete', scope='real_host')])
        with self.assertRaisesRegex(ValueError, 'out-of-scope'):
            self.metric.snapshot([], [], extension_paths={'fake': []})

    def test_failed_extension_check_stays_fail(self):
        self.install([self.row('identity.integrity.complete', verdict='FAIL')])
        score = self.metric.snapshot([], [], extension_paths={'fake': []})
        self.assertEqual(score['outcomes']['IDENTITY.integrity_refusal']['verdict'], 'FAIL')

    def test_missing_module_is_refused_not_skipped(self):
        self.metric.EXTENSION_ADAPTERS['absent'] = {
            'module': 'absent_extension_adapter', 'scope': 'source',
            'outcomes': {'IDENTITY.integrity_refusal': ['identity.integrity.complete']}}
        self.metric.ADAPTER_REQUIREMENTS['extensions']['absent'] = {'module_sha256': None}
        self.addCleanup(self.metric.EXTENSION_ADAPTERS.pop, 'absent', None)
        self.addCleanup(self.metric.ADAPTER_REQUIREMENTS['extensions'].pop, 'absent', None)
        with self.assertRaisesRegex(ValueError, 'module is missing'):
            self.metric.snapshot([], [], extension_paths={'absent': []})

    def test_every_declared_extension_module_exists_or_is_pending(self):
        pending = {'resource-budget', 'clean-restore'}
        for name, spec in self.metric.EXTENSION_ADAPTERS.items():
            if name in pending or name in ('fake', 'absent'):
                continue
            self.assertIsNotNone(self.metric.ADAPTER_REQUIREMENTS['extensions'][name]['module_sha256'], name)

    def test_declared_outcomes_without_reports_stay_unresolved(self):
        score = self.metric.snapshot([], [])
        for outcome in ('IDENTITY.integrity_refusal', 'PORT.missing_signing_state', 'PORT.upgrade_divergence',
                        'PORT.measured_resource_budget', 'PORT.clean_device_restore'):
            self.assertEqual(score['outcomes'][outcome]['verdict'], 'NOT CHECKED')


if __name__ == '__main__':
    unittest.main()
