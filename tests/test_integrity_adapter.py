"""Strict grader controls for the Self integrity outcome.

The controls start from one real retained report written by integrity.py. Every tampered copy
lives in a throwaway control directory beside it and is never public acceptance evidence.
Set TWIN_INTEGRITY_REPORT to a report.json, or leave it unset to use the newest retained run.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / '.agents/skills/verify-twinaatma'
sys.path.insert(0, str(HERE / 'scripts'))
import integrity_adapter as grader  # noqa: E402

spec = importlib.util.spec_from_file_location('integrity_acceptance_controls', HERE / 'scripts/acceptance.py')
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)

PASSING = 19
FAILING_CASE = 'replay_rejected_restored'


def retained_report():
    configured = os.environ.get('TWIN_INTEGRITY_REPORT')
    if configured:
        return Path(configured).absolute()
    found = sorted((ROOT / 'work/gc-artifacts/.knowledgeos/integrity').glob('*/report.json'), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


REPORT = retained_report()


class IntegrityAdapterControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPORT is None or not REPORT.is_file():
            raise unittest.SkipTest('A retained integrity report is required; run integrity.py first.')
        cls.original = json.loads(REPORT.read_text(encoding='utf-8'))
        cls.current = api.product_hashes()
        if (cls.original.get('product_hashes') != cls.current
                or cls.original.get('producer_sha256') != api.sha(HERE / 'scripts/integrity.py')):
            raise unittest.SkipTest('The retained integrity report is stale for the current product; rerun integrity.py.')
        cls.expected = grader._literal('EXPECTED')
        cls.root = ROOT / 'work/gc-artifacts/.knowledgeos/integrity-adapter-controls' / (time.strftime('%Y%m%d-%H%M%S-') + str(os.getpid()))
        cls.root.mkdir(parents=True)
        cls.counter = 0

    def setUp(self):
        type(self).counter += 1
        self.directory = self.root / str(self.counter)
        shutil.copytree(REPORT.parent, self.directory, ignore=shutil.ignore_patterns('fixtures'))
        self.report = self.directory / 'report.json'
        self.data = json.loads(self.report.read_text(encoding='utf-8'))

    def save(self):
        self.report.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding='utf-8')

    def rewrite(self, name, change):
        """Replace one retained file's bytes and keep the report's hash for it truthful."""
        path = self.directory / name
        path.write_bytes(change(path.read_bytes()))
        self.data['evidence_files'][name] = api.sha(path)
        self.save()

    def grade(self, current=None):
        return grader.grade(api, [self.report], current or self.current)

    def rejected(self, current=None):
        with self.assertRaises(ValueError) as caught:
            self.grade(current)
        return str(caught.exception)

    def reader(self, overrides=None):
        overrides = overrides or {}
        return (lambda name: overrides[name] if name in overrides else (self.directory / name).read_bytes(),
                lambda name: name in overrides or (self.directory / name).is_file())

    def judge(self, name, overrides=None):
        read, exists = self.reader(overrides)
        return grader.judge_case(name, self.expected[name], read, exists)

    # ----- the truthful result -------------------------------------------------------------

    def test_truthful_fail_survives_with_the_real_defect_named(self):
        report = self.grade()[0]
        row = report['checks']['identity.integrity.complete']
        self.assertEqual((report['scope'], row['verdict']), ('source', 'FAIL'))
        self.assertEqual(row['observed'][FAILING_CASE], 'FAIL')
        self.assertEqual(sum(value == 'PASS' for value in row['observed'].values()), PASSING)
        self.assertEqual(set(row['observed']), set(self.expected))
        self.assertTrue(all(row['evidence'][name] for name in self.expected))

    def test_scorer_awards_nothing_to_a_truthful_fail(self):
        score = api.snapshot([], [], extension_paths={'integrity': [self.report]})
        self.assertEqual(score['outcomes']['IDENTITY.integrity_refusal']['verdict'], 'FAIL')
        self.assertEqual(score['counts']['PASS'], 0)

    def test_every_case_is_recomputed_from_bytes_in_both_directions(self):
        for name in self.expected:
            judged = self.judge(name)
            self.assertEqual(judged['verdict'], 'FAIL' if name == FAILING_CASE else 'PASS', (name, judged['problems']))
        failing = self.judge(FAILING_CASE)
        self.assertIn(FAILING_CASE + '.approve:never_waited_at_prompt', failing['problems'])
        self.assertIn(FAILING_CASE + '.approve:no_prompt_or_preview_shown', failing['problems'])

    def test_aggregate_is_pass_only_when_every_recomputed_case_passes(self):
        self.data['cases'] = [dict(row, verdict='PASS') for row in self.data['cases']]
        self.data['verdict'] = 'PASS'
        self.save()
        with mock.patch.object(grader, 'judge_case', side_effect=lambda *args: {'verdict': 'PASS', 'checks': {}, 'problems': []}):
            row = self.grade()[0]['checks']['identity.integrity.complete']
        self.assertEqual(row['verdict'], 'PASS')

    def test_a_reported_pass_that_the_evidence_contradicts_is_refused(self):
        for row in self.data['cases']:
            if row['id'].endswith(FAILING_CASE):
                row['verdict'] = 'PASS'
        self.data['verdict'] = 'PASS'
        self.save()
        self.assertIn('contradicts', self.rejected())

    # ----- case judgments flip on evidence changes -----------------------------------------

    def test_changed_self_bytes_fail_the_case(self):
        name = 'body_tampered'
        after = (self.directory / (name + '.self.after.md')).read_bytes() + b'\nOwner text injected\n'
        judged = self.judge(name, {name + '.self.after.md': after})
        self.assertEqual(judged['verdict'], 'FAIL')
        self.assertIn('self_bytes_unchanged', judged['problems'])

    def test_an_applied_ledger_row_fails_the_case(self):
        name = 'stale_base'
        before = (self.directory / (name + '.ledger.after.jsonl')).read_bytes()
        row = json.loads(before.decode().splitlines()[0])
        row['status'] = 'applied'
        judged = self.judge(name, {name + '.ledger.after.jsonl': (json.dumps(row, sort_keys=True) + '\n').encode()})
        self.assertEqual(judged['verdict'], 'FAIL')
        self.assertIn('no_ledger_row_applied', judged['problems'])
        self.assertIn('ledger_bytes_unchanged', judged['problems'])

    def test_reaching_the_prompt_input_or_a_terminal_refusal_fails_the_case(self):
        name, label = 'body_tampered', 'body_tampered.approve'
        record = json.loads((self.directory / (label + '.command.json')).read_text(encoding='utf-8'))
        for change in ({'timed_out': True, 'killed': True}, {'input_sent': True}, {'exit_code': 0}, {'env_overrides': {'X': '1'}}):
            judged = self.judge(name, {label + '.command.json': json.dumps(dict(record, **change)).encode()})
            self.assertEqual(judged['verdict'], 'FAIL', change)
        terminal = b'Refusing to approve without an interactive terminal.\nRun this command yourself in a terminal window.\n'
        self.assertEqual(self.judge(name, {label + '.stderr.txt': terminal})['verdict'], 'FAIL')
        self.assertEqual(self.judge(name, {label + '.stderr.txt': b''})['verdict'], 'FAIL')
        shown = b'Proposal: x.md\nApply this to People/Self.md? [y/N] '
        self.assertEqual(self.judge(name, {label + '.console.txt': shown})['verdict'], 'FAIL')

    def test_the_wrong_refusal_reason_fails_the_case(self):
        name = 'stale_base'
        judged = self.judge(name, {name + '.approve.stderr.txt': b'proposal content was edited after it was created\n'})
        self.assertEqual(judged['verdict'], 'FAIL')
        self.assertIn('stale_base.approve:explicit_integrity_refusal', judged['problems'])

    def test_a_mcp_accept_that_does_not_refuse_fails_the_case(self):
        name = 'mcp_accept_refuses'
        lines = (self.directory / (name + '.mcp.stdout.txt')).read_bytes().decode().splitlines()
        changed = []
        for line in lines:
            message = json.loads(line)
            if message.get('id') == 2:
                message['result']['isError'] = False
            changed.append(json.dumps(message))
        judged = self.judge(name, {name + '.mcp.stdout.txt': ('\n'.join(changed) + '\n').encode()})
        self.assertEqual(judged['verdict'], 'FAIL')
        self.assertIn('mcp_accept_refuses.accept-valid:explicit_refusal', judged['problems'])

    def test_a_console_that_is_not_a_terminal_fails_the_control(self):
        control = 'console_control'
        judged = self.judge(control, {control + '.probe.console.txt': b'stdin_tty=False stdout_tty=False'})
        self.assertEqual(judged['verdict'], 'FAIL')
        self.assertEqual(self.judge(control)['verdict'], 'PASS')

    # ----- invalid runs are refused, never graded ------------------------------------------

    def test_stale_product_is_refused(self):
        stale = dict(self.current)
        stale['AGENTS.md'] = '0' * 64
        self.assertIn('exact current product', self.rejected(stale))
        missing = dict(self.current)
        missing['knowledgeos/__init__.py'] = missing.get('knowledgeos/__init__.py', '0' * 64)
        missing['knowledgeos/zz_new_module.py'] = '1' * 64
        self.assertIn('exact current product', self.rejected(missing))

    def test_changed_producer_or_support_hash_is_refused(self):
        self.data['producer_sha256'] = '0' * 64
        self.save()
        self.assertIn('stale', self.rejected())
        self.data['producer_sha256'] = self.original['producer_sha256']
        self.data['support_sha256'] = {'data_preservation.py': '0' * 64}
        self.save()
        self.assertIn('stale', self.rejected())

    def test_missing_extra_or_reordered_case_is_refused(self):
        original = copy.deepcopy(self.data['cases'])
        self.data['cases'] = original[:-1]
        self.save()
        self.assertIn('missing, extra or reordered', self.rejected())
        self.data['cases'] = original + [dict(original[0], id='identity.integrity.invented_case')]
        self.save()
        self.assertIn('missing, extra or reordered', self.rejected())
        self.data['cases'] = list(reversed(original))
        self.save()
        self.assertIn('missing, extra or reordered', self.rejected())
        self.data['cases'] = original
        self.data['expected_case_ids'] = self.data['expected_case_ids'][:-1]
        self.save()
        self.assertIn('missing, extra or reordered', self.rejected())

    def test_changed_frozen_literal_or_helper_is_refused(self):
        def freeze(raw):
            data = json.loads(raw)
            data['expected']['body_tampered']['expected'] = 'A weaker promise'
            return json.dumps(data).encode()
        self.rewrite('frozen-cases.json', freeze)
        self.assertIn('frozen literal', self.rejected())
        self.rewrite('frozen-cases.json', lambda raw: (REPORT.parent / 'frozen-cases.json').read_bytes())
        self.rewrite('console_host.py', lambda raw: raw + b'\n# edited helper\n')
        self.assertIn('console helper', self.rejected())

    def test_altered_evidence_hash_is_refused(self):
        path = self.directory / 'body_tampered.approve.stderr.txt'
        path.write_bytes(path.read_bytes() + b'x')
        self.assertIn('altered', self.rejected())

    def test_rehashed_evidence_that_changes_a_verdict_is_refused(self):
        self.rewrite('stale_base.approve.stderr.txt',
                     lambda raw: b'Refusing to approve without an interactive terminal.\nRun this command yourself in a terminal window.\n')
        self.assertIn('contradicts', self.rejected())

    def test_missing_or_extra_retained_file_is_refused(self):
        (self.directory / 'body_tampered.approve.console.txt').unlink()
        self.rejected()
        shutil.copy2(REPORT.parent / 'body_tampered.approve.console.txt', self.directory / 'body_tampered.approve.console.txt')
        (self.directory / 'unlisted-extra.txt').write_text('extra', encoding='utf-8')
        self.assertIn('differs from the retained directory', self.rejected())

    def test_escaped_or_nested_evidence_path_is_refused(self):
        outside = self.directory.parent / ('escape-' + str(self.counter) + '.txt')
        outside.write_text('outside', encoding='utf-8')
        for name in ('../' + outside.name, 'nested/file.txt', 'C:\\escape.txt', str(outside)):
            self.data['evidence_files'] = dict(self.original['evidence_files'])
            self.data['evidence_files'][name] = api.sha(outside)
            self.save()
            self.assertIn('contained retained file', self.rejected(), name)

    def test_a_linked_evidence_file_is_refused(self):
        target = self.directory / 'body_tampered.approve.stderr.txt'
        source = self.directory.parent / ('link-source-' + str(self.counter) + '.txt')
        shutil.copy2(target, source)
        target.unlink()
        try:
            os.symlink(source, target)
        except OSError as error:
            self.skipTest('Native symbolic links are unavailable: ' + str(error))
        self.rejected()

    def test_report_outside_contained_evidence_is_refused(self):
        with tempfile.TemporaryDirectory() as outside:
            shutil.copytree(self.directory, Path(outside) / 'run')
            with self.assertRaises(ValueError):
                grader.grade(api, [Path(outside) / 'run/report.json'], self.current)
        parent = self.directory / 'x' / '..' / 'report.json'
        with self.assertRaises(ValueError):
            grader.grade(api, [parent], self.current)

    def test_unstopped_process_is_refused(self):
        self.data['processes'][0]['stopped'] = False
        self.save()
        self.assertIn('typed stopped processes', self.rejected())
        self.data['processes'][0]['stopped'] = True
        self.data['all_started_processes_stopped'] = False
        self.save()
        self.assertIn('shutdown is incomplete', self.rejected())

    def test_retained_process_record_that_is_not_stopped_is_refused(self):
        def unstop(raw):
            record = json.loads(raw)
            record['stopped'] = False
            return json.dumps(record).encode()
        self.rewrite('revision.command.json', unstop)
        self.assertIn('retained command evidence', self.rejected())

    def test_invented_process_or_unknown_role_is_refused(self):
        self.data['processes'].append(dict(self.data['processes'][0], role='invented-role', pid=999999))
        self.save()
        self.assertIn('retained command evidence', self.rejected())

    def test_changed_real_vault_sentinel_is_refused(self):
        self.data['isolation']['after'] = dict(self.data['isolation']['before'], **{
            next(iter(self.data['isolation']['before'])): '2' * 64})
        self.save()
        self.assertIn('sentinels', self.rejected())

    def test_case_list_frozen_after_a_process_started_is_refused(self):
        self.data['frozen_at_ns'] = 2 ** 62
        self.save()
        self.assertIn('frozen before', self.rejected())
        self.data['frozen_at_ns'] = None
        self.save()
        self.assertIn('frozen before', self.rejected())

    def test_an_incomplete_run_with_an_error_is_refused(self):
        self.data['error'] = '{"body_tampered": "setup failed"}'
        self.save()
        self.assertIn('did not finish cleanly', self.rejected())

    def test_wrong_scope_or_credit_claim_is_refused(self):
        self.data['acceptance_credit_awarded'] = True
        self.save()
        self.assertIn('did not finish cleanly', self.rejected())


if __name__ == '__main__':
    unittest.main()
