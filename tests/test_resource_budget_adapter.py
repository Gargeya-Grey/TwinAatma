import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agents/skills/verify-twinaatma/scripts'
PRODUCER = SCRIPTS / 'resource_budget.py'
SANDBOX = ROOT / 'work/gc-artifacts/.knowledgeos' / ('rb-tests-' + uuid.uuid4().hex[:8])
BASELINE_EVIDENCE = ROOT / 'work/gc-artifacts/.knowledgeos/resume-20261023/resource-baseline' / ('controls-' + uuid.uuid4().hex[:8])


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remove_fixture(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to((ROOT / 'work').resolve()):
        raise ValueError('Test cleanup must stay below this worktree work directory')
    shutil.rmtree(resolved, ignore_errors=True)


@unittest.skipUnless(os.name == 'nt', 'The producer measures native Windows process memory')
class ResourceBudgetAdapterTests(unittest.TestCase):
    """One small real retained run, then tampered copies of its evidence on disk."""

    @classmethod
    def setUpClass(cls):
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        cls.producer = load('resource_budget_under_test', PRODUCER)
        try:
            cls.producer.budget_directory()
        except ValueError:
            raise unittest.SkipTest('The owner-approved budget is retained outside version control and is absent here')
        cls.acceptance = load('acceptance', SCRIPTS / 'acceptance.py')
        cls.adapter = load('resource_budget_adapter', SCRIPTS / 'resource_budget_adapter.py')
        base = SANDBOX / 'real'
        result = subprocess.run([sys.executable, '-B', str(PRODUCER), '--output', str(base), '--scales', '100', '--samples', '2'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=900)
        if result.returncode != 0:
            raise AssertionError('Producer failed: ' + result.stdout[-600:] + result.stderr[-600:])
        cls.run_directory = Path(json.loads(result.stdout.strip().splitlines()[-1])['report']).parent
        cls.current = cls.acceptance.product_hashes()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'run_directory', None):
            shutil.copytree(cls.run_directory, BASELINE_EVIDENCE / 'original', ignore=shutil.ignore_patterns('pycache'))
        remove_fixture(SANDBOX)

    def retained_clone(self, name):
        target = BASELINE_EVIDENCE / name
        shutil.copytree(self.run_directory, target, ignore=shutil.ignore_patterns('pycache'))
        return target

    def test_missing_initialized_baseline_binding_is_refused(self):
        directory = self.retained_clone('missing-binding')
        self.edit_json(directory / 'report.json', lambda report: report['scales']['100'].pop('initialized_baseline'))
        with self.assertRaisesRegex(ValueError, 'initialized baseline is missing or unbound'):
            self.grade(directory)

    def test_missing_external_signing_state_is_refused(self):
        directory = self.retained_clone('missing-signing-state')
        (directory / 'scales/100/initialized-baseline/gate-state/gate.key').unlink()
        with self.assertRaisesRegex(ValueError, 'initialized baseline inventory'):
            self.grade(directory)

    def test_baseline_manifest_tamper_rehashed_into_inventories_is_refused(self):
        directory = self.retained_clone('manifest-tamper')
        base = directory / 'scales/100'
        manifest = base / 'initialized-baseline/vault/.knowledgeos/index-manifest.json'
        self.edit_json(manifest, lambda data: data['files'].pop(next(iter(data['files']))))
        inventory = self.producer.file_inventory(base / 'initialized-baseline/vault')
        self.edit_json(base / 'initialized-baseline.json', lambda data: data.update(vault=inventory))
        (base / 'vault-inventory.json').write_text(json.dumps(inventory), encoding='utf-8')
        def update(report):
            scale = report['scales']['100']
            scale['initialized_baseline']['sha256'] = digest(base / 'initialized-baseline.json')
            scale['vault_inventory_sha256'] = self.producer.inventory_digest(inventory)
            scale['vault_bytes'] = sum(row['size'] for row in inventory.values())
        self.edit_json(directory / 'report.json', update)
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'baseline manifest signature is invalid'):
            self.grade(directory)

    def test_cold_sample_without_complete_state_binding_is_refused(self):
        directory = self.retained_clone('cold-unbound')
        protocol = directory / 'protocol/startup-cold-100-000.jsonl'
        rows = [json.loads(line) for line in protocol.read_text(encoding='utf-8').splitlines()]
        rows[0].pop('initialized_state_sha256')
        protocol.write_text('\n'.join(json.dumps(row, sort_keys=True) for row in rows) + '\n', encoding='utf-8')
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'cold sample does not bind'):
            self.grade(directory)

    def clone(self):
        target = SANDBOX / 'tamper' / uuid.uuid4().hex[:8]
        shutil.copytree(self.run_directory, target, ignore=shutil.ignore_patterns('pycache'))
        self.addCleanup(remove_fixture, target)
        return target

    def edit_json(self, path, change):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        change(value)
        Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8', newline='\n')

    def refresh(self, directory):
        """Re-hash the evidence a tamper rewrote, so only the semantic fault remains."""
        def change(report):
            for name in report['evidence_files']:
                report['evidence_files'][name] = digest(directory / name)
        self.edit_json(directory / 'report.json', change)

    def grade(self, directory, current=None):
        return self.adapter.grade(self.acceptance, [directory / 'report.json'], current or self.current)

    def check(self, directory, current=None):
        return self.grade(directory, current)[0]['checks']['port.resource_budget']

    def retarget_budget(self, directory, **changes):
        """A different but internally consistent budget, for exercising verdict logic with a patched grader."""
        budget = json.loads((directory / 'budget/approved-budget.json').read_text(encoding='utf-8'))
        budget.update(changes)
        (directory / 'budget/approved-budget.json').write_text(json.dumps(budget, indent=2, ensure_ascii=False), encoding='utf-8')
        sha = digest(directory / 'budget/approved-budget.json')
        def change(report):
            report['budget']['sha256'], report['budget']['values'] = sha, budget
            report['budget_comparison'] = {scale: self.producer.compare(summary, budget)
                                           for scale, summary in report['summary'].items()}
        self.edit_json(directory / 'report.json', change)
        self.refresh(directory)
        values = dict(self.adapter.BUDGET_VALUES, **changes)
        for target, replacement in (('BUDGET_SHA256', sha), ('BUDGET_VALUES', values)):
            original = getattr(self.adapter, target)
            setattr(self.adapter, target, replacement)
            self.addCleanup(setattr, self.adapter, target, original)
        return budget

    def narrow_requirement(self, scales=(100,), minimum=2):
        for target, replacement in (('REQUIRED_SCALES', scales), ('MIN_SAMPLES', minimum)):
            original = getattr(self.adapter, target)
            setattr(self.adapter, target, replacement)
            self.addCleanup(setattr, self.adapter, target, original)

    def test_real_small_run_is_graded_from_raw_protocol_but_is_not_a_full_pass(self):
        row = self.check(self.run_directory)
        observed = row['observed']
        self.assertIn(row['verdict'], ('FAIL', 'NOT CHECKED'))
        self.assertFalse(observed['coverage_complete'])
        self.assertEqual(observed['requested_scales'], [100])
        self.assertEqual(observed['budget_sha256'], '9455ea6ec444ba2218b8f8abc4d4dac7231ff3be0a880287d8bf8cf0c1f989d1')
        report = json.loads((self.run_directory / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(observed['summary'], report['summary'])
        self.assertEqual(report['summary']['100']['startup_cold']['n'], 2)
        self.assertEqual(report['summary']['100']['recall']['n'], 2)
        self.assertEqual(report['summary']['100']['capture']['n'], 2)
        self.assertIn('Core', observed['device']['cpu'])
        self.assertGreater(observed['device']['ram_bytes'], 0)
        self.assertTrue(observed['clean_shutdown'])
        samples = [json.loads(line) for line in (self.run_directory / 'samples.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(sample['ok'] for sample in samples))
        self.assertEqual(len(samples), 8)
        compile_result = json.loads((self.run_directory / 'commands/compile.command.json').read_text(encoding='utf-8'))
        self.assertEqual(compile_result['exit_code'], 0)
        self.assertTrue(compile_result['stopped'])

    def test_failed_bytecode_precompile_is_refused(self):
        directory = self.clone()
        def failed(record):
            record['exit_code'] = 1
        self.edit_json(directory / 'commands/compile.command.json', failed)
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'precompile'):
            self.grade(directory)

    def test_scorer_accepts_the_report_through_the_extension_seam_without_awarding_pass(self):
        score = self.acceptance.snapshot([], [], extension_paths={'resource-budget': [self.run_directory / 'report.json']})
        self.assertNotEqual(score['outcomes']['PORT.measured_resource_budget']['verdict'], 'PASS')
        self.assertEqual(score['counts']['PASS'], 0)

    def test_percentile_is_nearest_rank(self):
        values = [float(n) for n in range(1, 21)]
        self.assertEqual(self.adapter.percentile(values, 0.5), 10.0)
        self.assertEqual(self.adapter.percentile(values, 0.95), 19.0)
        self.assertEqual(self.adapter.percentile([7.0], 0.95), 7.0)
        self.assertEqual(self.producer.percentile(values, 0.95), self.adapter.percentile(values, 0.95))

    def test_a_relaxed_budget_over_all_requested_coverage_passes(self):
        directory = self.clone()
        self.retarget_budget(directory, startup_ms=60000, capture_ms=60000, recall_ms=60000, context_bytes=1048576)
        self.narrow_requirement()
        row = self.check(directory)
        self.assertEqual(row['verdict'], 'PASS')
        self.assertTrue(row['observed']['coverage_complete'])
        self.assertEqual(row['observed']['over_budget'], [])

    def test_a_missing_scale_is_never_a_pass_even_inside_a_relaxed_budget(self):
        directory = self.clone()
        self.retarget_budget(directory, startup_ms=60000, capture_ms=60000, recall_ms=60000, context_bytes=1048576)
        row = self.check(directory)
        self.assertEqual(row['verdict'], 'NOT CHECKED')
        self.assertFalse(row['observed']['coverage_complete'])
        self.assertEqual(row['observed']['required_scales'], [100, 1000, 10000])

    def test_too_few_samples_per_operation_is_never_a_pass(self):
        directory = self.clone()
        self.retarget_budget(directory, startup_ms=60000, capture_ms=60000, recall_ms=60000, context_bytes=1048576)
        self.narrow_requirement(scales=(100,), minimum=3)
        self.assertEqual(self.check(directory)['verdict'], 'NOT CHECKED')

    def test_an_over_budget_run_is_fail_not_an_exception(self):
        directory = self.clone()
        self.retarget_budget(directory, startup_ms=1, recall_ms=1, capture_ms=1)
        self.narrow_requirement()
        row = self.check(directory)
        self.assertEqual(row['verdict'], 'FAIL')
        metrics = {item['metric'] for item in row['observed']['over_budget']}
        self.assertTrue({'startup_p95_all_samples', 'startup_p95_cold_samples', 'startup_p95_warm_samples',
                         'capture_p95', 'recall_p95'} <= metrics)

    def test_oversized_context_alone_fails_the_budget(self):
        directory = self.clone()
        self.retarget_budget(directory, context_bytes=1000)
        self.narrow_requirement()
        row = self.check(directory)
        self.assertEqual(row['verdict'], 'FAIL')
        self.assertEqual({item['metric'] for item in row['observed']['over_budget']}, {'context_bytes_max', 'context_field_bytes_max'})

    def test_peak_memory_over_the_limit_fails(self):
        directory = self.clone()
        self.retarget_budget(directory, memory_process_peak_ram_bytes=1024 * 1024)
        self.narrow_requirement()
        row = self.check(directory)
        self.assertEqual(row['verdict'], 'FAIL')
        self.assertIn('memory_process_peak_working_set_max', {item['metric'] for item in row['observed']['over_budget']})

    def test_a_summary_that_disagrees_with_raw_samples_is_refused(self):
        directory = self.clone()
        def change(report):
            report['summary']['100']['startup_all']['p95'] = 1.0
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'summary disagrees'):
            self.grade(directory)

    def test_a_budget_comparison_that_disagrees_with_raw_samples_is_refused(self):
        directory = self.clone()
        def change(report):
            for row in report['budget_comparison']['100']:
                row['within'] = not row['within']
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'comparison disagrees'):
            self.grade(directory)

    def test_a_sample_latency_edited_in_the_retained_rows_is_refused(self):
        directory = self.clone()
        lines = (directory / 'samples.jsonl').read_text(encoding='utf-8').splitlines()
        first = json.loads(lines[0])
        first['latency_ms'] = 1.0
        lines[0] = json.dumps(first, sort_keys=True)
        (directory / 'samples.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'differs from its raw protocol'):
            self.grade(directory)

    def test_altered_evidence_without_a_matching_hash_is_refused(self):
        directory = self.clone()
        path = directory / 'samples.jsonl'
        path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'altered'):
            self.grade(directory)

    def test_unlisted_evidence_is_refused(self):
        directory = self.clone()
        (directory / 'protocol' / 'extra.jsonl').write_text('{}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unlisted evidence'):
            self.grade(directory)

    def test_a_missing_scale_in_the_recorded_matrix_is_refused(self):
        directory = self.clone()
        def change(report):
            report['requested_scales'] = [100, 1000]
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'requested scales and recorded scales differ'):
            self.grade(directory)

    def test_dropping_a_sample_row_is_refused(self):
        directory = self.clone()
        lines = (directory / 'samples.jsonl').read_text(encoding='utf-8').splitlines()
        (directory / 'samples.jsonl').write_text('\n'.join(lines[1:]) + '\n', encoding='utf-8', newline='\n')
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'sample count'):
            self.grade(directory)

    def test_reusing_one_raw_request_as_multiple_samples_is_refused(self):
        directory = self.clone()
        path = directory / 'samples.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        first = next(row for row in rows if row['operation'] == 'recall' and row['index'] == 0)
        for index, row in enumerate(rows):
            if row['operation'] == 'recall' and row['index'] == 1:
                rows[index] = dict(first, index=1)
        path.write_text('\n'.join(json.dumps(row, sort_keys=True) for row in rows) + '\n', encoding='utf-8', newline='\n')
        def change(report):
            report['summary']['100'] = self.producer.summarize(rows, report['process_memory']['100'], 100)
        self.edit_json(directory / 'report.json', change)
        self.retarget_budget(directory, startup_ms=60000, capture_ms=60000, recall_ms=60000, context_bytes=1048576)
        self.narrow_requirement()
        with self.assertRaisesRegex(ValueError, 'reuses a protocol request'):
            self.grade(directory)

    def test_a_stale_product_is_refused(self):
        directory = self.clone()
        stale = dict(self.current)
        name = sorted(stale)[0]
        stale[name] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'product hashes'):
            self.grade(directory, stale)

    def test_report_product_hashes_that_differ_from_the_checkout_are_refused(self):
        directory = self.clone()
        def change(report):
            name = sorted(report['product_hashes'])[0]
            report['product_hashes'][name] = '0' * 64
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'product hashes'):
            self.grade(directory)

    def test_a_stale_producer_is_refused(self):
        directory = self.clone()
        def change(report):
            report['producer_sha256'] = '1' * 64
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'producer is unknown or stale'):
            self.grade(directory)

    def test_a_budget_that_is_not_the_owner_approved_file_is_refused(self):
        directory = self.clone()
        budget = json.loads((directory / 'budget/approved-budget.json').read_text(encoding='utf-8'))
        budget['startup_ms'] = 50000
        (directory / 'budget/approved-budget.json').write_text(json.dumps(budget), encoding='utf-8')
        sha = digest(directory / 'budget/approved-budget.json')
        def change(report):
            report['budget']['sha256'], report['budget']['values'] = sha, budget
        self.edit_json(directory / 'report.json', change)
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'owner-approved budget'):
            self.grade(directory)

    def test_changed_real_vault_sentinels_are_refused(self):
        directory = self.clone()
        def change(report):
            key = sorted(report['isolation']['after'])[0]
            report['isolation']['after'][key] = '2' * 64
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'sentinels'):
            self.grade(directory)

    def test_a_server_that_was_not_stopped_is_refused(self):
        directory = self.clone()
        def change(report):
            report['processes'][-1]['stopped'] = False
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'shutdown'):
            self.grade(directory)

    def test_an_altered_generated_note_in_the_retained_vault_is_refused(self):
        directory = self.clone()
        inventory = json.loads((directory / 'scales/100/vault-inventory.json').read_text(encoding='utf-8'))
        target = next(name for name in inventory if name.startswith('Concepts/') and not name.endswith('_Index.md'))
        with (directory / 'scales/100/vault' / target).open('ab') as stream:
            stream.write(b'\nEdited after generation.\n')
        with self.assertRaisesRegex(ValueError, 'generated note was altered'):
            self.grade(directory)

    def test_a_workload_that_is_not_exactly_the_scale_is_refused(self):
        directory = self.clone()
        def change(report):
            report['scales']['100']['indexed_notes_before_operations'] = 99
        self.edit_json(directory / 'report.json', change)
        with self.assertRaisesRegex(ValueError, 'exactly 100 indexed notes'):
            self.grade(directory)

    def test_memory_counters_read_before_the_last_sample_are_refused(self):
        directory = self.clone()
        name = 'protocol/steady-100.jsonl'
        events = [json.loads(line) for line in (directory / name).read_text(encoding='utf-8').splitlines()]
        events = [e for e in events if e['event'] != 'memory']
        (directory / name).write_text('\n'.join(json.dumps(e, sort_keys=True) for e in events) + '\n', encoding='utf-8', newline='\n')
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'memory counters are missing'):
            self.grade(directory)

    def test_a_measured_process_with_children_is_refused(self):
        directory = self.clone()
        name = 'protocol/startup-warm-100-000.jsonl'
        events = [json.loads(line) for line in (directory / name).read_text(encoding='utf-8').splitlines()]
        for event in events:
            if event['event'] == 'memory':
                event['children'] = [{'pid': 1, 'exe': 'python.exe'}]
        (directory / name).write_text('\n'.join(json.dumps(e, sort_keys=True) for e in events) + '\n', encoding='utf-8', newline='\n')
        self.refresh(directory)
        with self.assertRaisesRegex(ValueError, 'children'):
            self.grade(directory)

    def test_a_report_outside_contained_evidence_is_refused(self):
        outside = ROOT / 'work' / ('outside-contained-' + uuid.uuid4().hex[:8])
        shutil.copytree(self.run_directory, outside, ignore=shutil.ignore_patterns('pycache'))
        self.addCleanup(remove_fixture, outside)
        with self.assertRaisesRegex(ValueError, 'contained'):
            self.grade(outside)


if __name__ == '__main__':
    unittest.main()
