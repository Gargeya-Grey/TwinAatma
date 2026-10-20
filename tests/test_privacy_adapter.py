"""Strict grader controls. Synthetic overlays are never public acceptance evidence."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / '.agents/skills/verify-twinaatma'
sys.path.insert(0, str(HERE / 'scripts'))
import privacy_adapter as grader

spec = importlib.util.spec_from_file_location('privacy_acceptance_controls', HERE / 'scripts/acceptance.py')
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
api.ROOT = ROOT
api.RUBRIC = ROOT / '.agents/skills/verify-twinaatma/references/acceptance-rubric.json'

REPORT = Path(os.environ['TWIN_PRIVACY_REPORT']).absolute() if os.environ.get('TWIN_PRIVACY_REPORT') else None


class PrivacyAdapterControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPORT is None:
            raise unittest.SkipTest('A retained final public report is required; no substitute is generated.')
        cls.report = REPORT
        cls.original = json.loads(REPORT.read_text(encoding='utf-8'))
        cls.report_text = REPORT.read_text(encoding='utf-8')
        cls.current = api.product_hashes()
        cls.control_root = ROOT / 'work/gc-artifacts/.knowledgeos/privacy-adapter-integration-controls' / (time.strftime('%Y%m%d-%H%M%S-') + str(os.getpid()))
        cls.control_root.mkdir(parents=True)
        cls.counter = 0

    def setUp(self):
        self.data = copy.deepcopy(self.original)
        self.overrides = {}

    def evidence(self, name):
        return json.loads((self.report.parent / name).read_text(encoding='utf-8'))

    def overlay(self, name, value, *, raw=False):
        type(self).counter += 1
        target = self.control_root / (str(self.counter) + '.txt')
        target.write_text(value if raw else json.dumps(value, ensure_ascii=False), encoding='utf-8', newline='')
        self.overrides[name] = target
        self.data['evidence_files'][name] = api.sha(target)

    def process(self, role, **changes):
        record = self.evidence(role + '.command.json')
        record.update(changes)
        for row in self.data['processes']:
            if row['role'] == role:
                row.update(changes)
        self.overlay(role + '.command.json', record)
        return record

    def grade(self):
        original_load, original_path = grader._loads, api.retained_observation
        def loads(text):
            return copy.deepcopy(self.data) if text == self.report_text else original_load(text)
        def location(directory, name):
            if Path(directory) == self.report.parent and name in self.overrides:
                if '\\' in name or ':' in name or any(part in ('', '.', '..') for part in name.split('/')):
                    return original_path(directory, name)
                return self.overrides[name]
            return original_path(directory, name)
        with mock.patch.object(grader, '_loads', side_effect=loads), mock.patch.object(api, 'retained_observation', side_effect=location):
            return grader.privacy_reports(api, self.report, self.current)

    def rejected(self):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.grade()

    def test_complete_real_report_is_accepted_without_scope_escalation(self):
        reports = self.grade()
        self.assertEqual([report['scope'] for report in reports], ['policy', 'source'])
        self.assertEqual(set(reports[0]['checks']), {'privacy.policy.complete'})
        self.assertEqual(set(reports[1]['checks']), {'privacy.exposure.complete', 'privacy.external.complete'})
        rubric = api.read_json(api.RUBRIC)
        mapped = {item['id']: api.outcome(item, reports)['verdict'] for item in rubric['outcomes']}
        self.assertEqual({name: mapped[name] for name in ('PRIVACY.selective_capture', 'PRIVACY.untrusted_notes',
            'IDENTITY.owner_exact_approval', 'QUALITY.representative_week', 'PORT.clean_device_restore')},
            {name: 'NOT CHECKED' for name in ('PRIVACY.selective_capture', 'PRIVACY.untrusted_notes',
            'IDENTITY.owner_exact_approval', 'QUALITY.representative_week', 'PORT.clean_device_restore')})

    def test_truthful_complete_failure_survives(self):
        self.process('bridge-json', exit_code=0)
        self.data['verdict'] = 'FAIL'
        self.data['cases'][grader.CASE_NAMES.index('bridge_unscoped_json')]['verdict'] = 'FAIL'
        reports = self.grade()
        self.assertEqual(reports[0]['checks']['privacy.policy.complete']['verdict'], 'FAIL')
        self.assertEqual(reports[1]['checks']['privacy.external.complete']['verdict'], 'FAIL')

    def test_changed_producer_rejected(self):
        self.data['producer_sha256'] = '0' * 64
        self.rejected()

    def test_unknown_producer_rejected(self):
        self.data['producer'] = 'unknown'
        self.rejected()

    def test_changed_support_rejected(self):
        self.data['support_sha256_after']['data_preservation.py'] = '0' * 64
        self.rejected()

    def test_changed_product_rejected(self):
        self.data['product_hashes']['knowledgeos/memory.py'] = '0' * 64
        self.rejected()

    def test_partial_toolkit_rejected(self):
        self.data['product_hashes'].pop('scripts/export_bundle.py')
        self.rejected()

    def test_changed_during_run_rejected(self):
        self.data['product_and_producer_unchanged'] = False
        self.rejected()

    def test_changed_after_toolkit_rejected(self):
        self.data['product_hashes_after']['scripts/export_bundle.py'] = '0' * 64
        self.rejected()

    def test_wrong_source_root_rejected(self):
        self.data['source_root'] = str(self.report.parent)
        self.rejected()

    def test_scope_escalation_rejected(self):
        self.data['scope'] = 'real_host'
        self.rejected()

    def test_missing_case_rejected(self):
        self.data['cases'].pop()
        self.rejected()

    def test_changed_case_order_rejected(self):
        self.data['cases'][0], self.data['cases'][1] = self.data['cases'][1], self.data['cases'][0]
        self.rejected()

    def test_unknown_case_rejected(self):
        self.data['cases'][0]['id'] = 'privacy.unknown'
        self.rejected()

    def test_duplicate_case_rejected(self):
        self.data['cases'][1]['id'] = self.data['cases'][0]['id']
        self.rejected()

    def test_missing_observation_rejected(self):
        self.data['cases'][0]['observed'] = None
        self.rejected()

    def test_fabricated_observation_rejected(self):
        self.data['cases'][0]['observed']['policy_sha256'] = '0' * 64
        self.rejected()

    def test_forged_verdict_rejected(self):
        row = self.data['cases'][grader.CASE_NAMES.index('credential_rpc')]
        row['verdict'] = 'FAIL' if row['verdict'] == 'PASS' else 'PASS'
        self.rejected()

    def test_missing_evidence_rejected(self):
        self.data['evidence_files'].pop('doctor.stdout.txt')
        self.rejected()

    def test_altered_evidence_hash_rejected(self):
        self.data['evidence_files']['doctor.stdout.txt'] = '0' * 64
        self.rejected()

    def test_escaped_evidence_rejected(self):
        self.data['evidence_files']['../escaped.json'] = '0' * 64
        self.rejected()

    def test_missing_human_provenance_rejected(self):
        self.data['evidence_files'].pop('human-approval-source.jsonl')
        self.rejected()

    def test_forged_human_role_with_updated_hash_rejected(self):
        value = self.evidence('human-approval-source.jsonl')
        value['payload']['role'] = 'assistant'
        self.overlay('human-approval-source.jsonl', value)
        self.rejected()

    def test_wrong_approval_answer_rejected(self):
        value = self.evidence('human-approval-provenance.json')
        value['answer'] = 'Assistant approved'
        self.overlay('human-approval-provenance.json', value)
        self.rejected()

    def test_wrong_vault_binding_with_updated_hash_rejected(self):
        self.process('doctor', vault=str(self.report.parent / 'other-vault'))
        self.rejected()

    def test_wrong_import_binding_with_updated_hash_rejected(self):
        self.process('doctor', import_path=str(ROOT))
        self.rejected()

    def test_missing_native_setup_rejected(self):
        self.data['processes'] = [row for row in self.data['processes'] if row['role'] != 'init']
        self.rejected()

    def test_unsafe_shutdown_rejected(self):
        self.process('doctor', stopped=False)
        self.rejected()

    def test_malformed_pid_rejected(self):
        self.process('doctor', pid=True)
        self.rejected()

    def test_malformed_timing_rejected(self):
        self.process('doctor', started_ns=1.5)
        self.rejected()

    def test_missing_direct_trace_rejected(self):
        name = next(name for name in self.data['evidence_files'] if name.startswith('child-traces/doctor.'))
        self.data['evidence_files'].pop(name)
        self.rejected()

    def test_nonzero_transport_attempt_with_updated_hash_rejected(self):
        name = next(name for name in self.data['evidence_files'] if name.startswith('child-traces/publisher.'))
        value = self.evidence(name)
        value['counts']['publishing_http'] = 1
        self.overlay(name, value)
        self.rejected()

    def test_credential_resolution_attempt_with_updated_hash_rejected(self):
        name = next(name for name in self.data['evidence_files'] if name.startswith('child-traces/publisher.'))
        value = self.evidence(name)
        value['counts']['credential_resolution'] = 1
        self.overlay(name, value)
        self.rejected()

    def reuse_pid(self, target, reference):
        target_row = next(row for row in self.data['processes'] if row['role'] == target)
        old_pid = target_row['pid']
        wanted_pid = next(row['pid'] for row in self.data['processes'] if row['role'] == reference)
        self.process(target, pid=wanted_pid)
        old_name = 'child-traces/' + target + '.' + str(old_pid) + '.json'
        new_name = 'child-traces/' + target + '.' + str(wanted_pid) + '.json'
        trace = self.evidence(old_name)
        trace['pid'] = wanted_pid
        self.data['evidence_files'].pop(old_name)
        self.overlay(new_name, trace)

    def test_legitimate_sequential_pid_reuse_is_accepted(self):
        self.reuse_pid('doctor', 'init')
        reports = self.grade()
        self.assertEqual([report['scope'] for report in reports], ['policy', 'source'])

    def test_simultaneous_pid_reuse_rejected(self):
        self.reuse_pid('concurrent-1', 'concurrent-0')
        self.rejected()

    def test_missing_native_state_mutation_rejected(self):
        value = self.evidence('mutations/linked_local.json')
        value['native_error'] = 'PermissionError'
        self.overlay('mutations/linked_local.json', value)
        self.rejected()

    def test_wrong_native_mutation_with_updated_hash_rejected(self):
        value = self.evidence('mutations/valid_empty_local.json')
        value['body'] = '{"version":1,"forgotten":[],"superseded":{}}'
        self.overlay('mutations/valid_empty_local.json', value)
        self.rejected()

    def test_changed_literal_rpc_with_updated_hash_rejected(self):
        value = self.evidence('metadata.requests.json')
        value[2]['params']['arguments']['privacy'] = 'ordinary'
        self.overlay('metadata.requests.json', value)
        self.rejected()

    def test_missing_bundle_inspection_with_updated_hash_rejected(self):
        value = self.evidence('observations/export_scope.json')
        value['files'].pop(next(iter(value['files'])))
        self.overlay('observations/export_scope.json', value)
        self.data['cases'][grader.CASE_NAMES.index('export_scope')]['observed'] = value
        self.rejected()

    def test_fabricated_unhashed_child_rejected(self):
        self.data['processes'].append(dict(self.data['processes'][0], role='invented'))
        self.rejected()

    def test_linked_evidence_rejected(self):
        self.data['evidence_files']['private-mutated-state/linked_local'] = '0' * 64
        self.rejected()

    def test_hardlinked_evidence_rejected(self):
        self.data['evidence_files']['private-state-backups/hardlinked_local'] = '0' * 64
        self.rejected()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path)
    arguments, remaining = parser.parse_known_args()
    REPORT = arguments.report.absolute() if arguments.report else REPORT
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
