"""Adversarial scorer controls only. These synthetic records earn no product credit."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/verify-twinaatma/scripts/acceptance.py'
SPEC = importlib.util.spec_from_file_location('graph_recovery_score_controls', SCRIPT)
metric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metric)


class GraphMeaningControls(unittest.TestCase):
    def test_simultaneously_live_roles_need_distinct_real_pids(self):
        valid = {'owner': {'pid': 41001}, 'contender': {'pid': 41002}}
        metric.require_distinct_live_processes(valid, 'owner', 'contender')
        for pid in (41001, True, 0, '41002'):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                metric.require_distinct_live_processes({'owner': {'pid': 41001}, 'contender': {'pid': pid}}, 'owner', 'contender')

    def relation(self, paths=(), **overrides):
        payload = {'seed': 'Projects/A/LocalSource.md', 'hops': 1, 'related': [{'path': path} for path in paths]}
        payload.update(overrides)
        return {'payload': payload, 'is_error': False}

    def test_literal_graph_inventory_and_additive_fixed_contract(self):
        self.assertEqual(len(metric.GRAPH_IDS), 16)
        self.assertEqual(len(metric.RECOVERY_INDEX), 6)
        self.assertEqual(len(metric.RECOVERY_LOCKS), 15)
        self.assertEqual(len(metric.RECOVERY_FAULTS), 3)
        rubric = metric.read_json(metric.RUBRIC)
        self.assertEqual(len(rubric['outcomes']), 54)
        self.assertEqual(metric.sha(metric.RUBRIC), '744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91')
        self.assertEqual(metric.ADAPTER_REQUIREMENTS['version'], 'verify-twinaatma.adapters/v12')
        self.assertEqual(metric.ADAPTER_REQUIREMENTS['outcomes']['RECOVERY.ownership_locks'],
                         ['recovery.locks.complete', 'recovery.write-faults.complete'])
        self.assertNotIn('verify-twinaatma.generated-writers/v1', metric.ALL_DATA_PRODUCERS)
        self.assertNotIn('verify-twinaatma.memory-census/v1', metric.ALL_DATA_PRODUCERS)

    def test_local_relative_cannot_be_substituted_by_root_collision(self):
        self.assertTrue(metric.graph_relation(self.relation(['Projects/A/Target.md']), 'Projects/A/LocalSource.md', ['Projects/A/Target.md']))
        self.assertFalse(metric.graph_relation(self.relation(['Target.md']), 'Projects/A/LocalSource.md', ['Projects/A/Target.md']))

    def test_wrong_seed_hops_duplicate_or_malformed_neighbors_fail(self):
        for result in (self.relation(['Projects/A/Target.md'], seed='Target.md'),
                       self.relation(['Projects/A/Target.md'], hops=True),
                       self.relation(['Projects/A/Target.md'], hops=2),
                       self.relation(['Projects/A/Target.md', 'Projects/A/Target.md']),
                       self.relation(related=[{}]), self.relation(related=[3])):
            with self.subTest(result=result):
                self.assertFalse(metric.graph_relation(result, 'Projects/A/LocalSource.md', ['Projects/A/Target.md']))

    def test_empty_related_is_not_disclosed_ambiguity(self):
        result = self.relation(seed='Projects/A/AmbiguousSource.md')
        self.assertFalse(metric.graph_relation(result, 'Projects/A/AmbiguousSource.md', [], ambiguity=True))
        result['payload']['diagnostics'] = [{'issue': 'ambiguous_link', 'source': 'Projects/A/AmbiguousSource.md',
            'target': 'Twin', 'candidates': ['Concepts/Twin.md', 'Projects/B/Twin.md']}]
        self.assertTrue(metric.graph_relation(result, 'Projects/A/AmbiguousSource.md', [], ambiguity=True))
        result['payload']['diagnostics'][0]['candidates'].pop()
        self.assertFalse(metric.graph_relation(result, 'Projects/A/AmbiguousSource.md', [], ambiguity=True))

    def test_misplaced_ambiguity_does_not_cover_literal_source(self):
        result = self.relation(seed='Projects/A/AmbiguousSource.md', diagnostics=[{'kind': 'ambiguous',
            'source': 'Projects/B/AmbiguousSource.md', 'target': 'Twin', 'candidates': ['Concepts/Twin.md', 'Projects/B/Twin.md']}])
        self.assertFalse(metric.graph_relation(result, 'Projects/A/AmbiguousSource.md', [], ambiguity=True))

    def test_complete_failure_is_preserved_and_manual_pass_is_rejected(self):
        row = {'id': 'memory.graph.ambiguous_basename', 'verdict': 'FAIL'}
        self.assertFalse(metric.verified_case(row, False))
        row['verdict'] = 'PASS'
        with self.assertRaises(ValueError):
            metric.verified_case(row, False)

    def test_missing_partial_write_proof_cannot_complete_lock_outcome(self):
        item = next(row for row in metric.read_json(metric.RUBRIC)['outcomes'] if row['id'] == 'RECOVERY.ownership_locks')
        def report(check):
            return {'path': 'synthetic scorer control', 'report_sha256': 'a' * 64, 'scope': 'source',
                    'checks': {check: {'id': check, 'verdict': 'PASS'}}}
        self.assertEqual(metric.outcome(item, [report('recovery.locks.complete')])['verdict'], 'NOT CHECKED')
        self.assertEqual(metric.outcome(item, [report('recovery.locks.complete'), report('recovery.write-faults.complete')])['verdict'], 'PASS')


class RecoveryMeaningControls(unittest.TestCase):
    def search(self, *, frozen=False, fresh=True):
        rows = [{'path': 'Concepts/Recovery.md', 'snippet': 'rq731quote current evidence after an external edit.'}]
        if fresh:
            rows.append({'path': 'Concepts/Fresh.md', 'snippet': 'rq731quote new evidence created while indexing is unavailable.'})
        payload = {'query': 'rq731quote', 'ranked': rows}
        if frozen:
            payload.update(index_frozen=True, index_frozen_note='A live owner blocks index refresh; new notes may be absent.')
        return {'payload': payload, 'is_error': False}

    def test_degraded_current_quotes_need_explicit_incompleteness(self):
        result = self.search(frozen=True, fresh=False)
        self.assertTrue(metric.recovery_search(result, True, False))
        result['payload'].pop('index_frozen_note')
        self.assertFalse(metric.recovery_search(result, True, False))

    def test_retry_needs_fresh_note_and_no_frozen_status(self):
        self.assertTrue(metric.recovery_search(self.search(), False, True))
        self.assertFalse(metric.recovery_search(self.search(fresh=False), False, True))
        self.assertFalse(metric.recovery_search(self.search(frozen=True), False, True))

    def test_stale_or_removed_source_and_wrong_query_fail(self):
        for mutate in (lambda result: result['payload']['ranked'].append({'path': 'Concepts/Removed.md'}),
                       lambda result: result['payload']['ranked'][0].update(snippet='rq731quote evidence before the editor changes it.'),
                       lambda result: result['payload'].update(query='other'),
                       lambda result: result.update(is_error=True)):
            result = self.search()
            mutate(result)
            self.assertFalse(metric.recovery_search(result, False, True))


class RetainedControlFixtures(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'work/gc-artifacts/.knowledgeos/graph-recovery-score-controls'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.evidence = {}

    def save(self, name, value):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        self.evidence[name] = metric.sha(path)
        return path

    def wire(self, *, role='search', calls=None, results=None):
        calls = calls or [('memory_search', {'query': 'rq731quote', 'limit': 20})]
        results = results or [{'payload': {'query': 'rq731quote', 'ranked': []}, 'is_error': False}]
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05',
            'capabilities': {}, 'clientInfo': {'name': 'verify-twinaatma-recovery', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
        requests += [{'jsonrpc': '2.0', 'id': number, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
                     for number, (name, arguments) in enumerate(calls, 2)]
        self.save(role + '.requests.json', requests)
        responses = [{'jsonrpc': '2.0', 'id': 1, 'result': {'serverInfo': {'name': 'knowledgeos-memory'}}}]
        responses += [{'jsonrpc': '2.0', 'id': number, 'result': {'isError': result['is_error'],
            'content': [{'type': 'text', 'text': json.dumps(result['payload'])}]}} for number, result in enumerate(results, 2)]
        path = self.directory / (role + '.stdout.txt')
        path.write_text(''.join(json.dumps(row) + '\n' for row in responses), encoding='utf-8')
        self.evidence[path.name] = metric.sha(path)
        self.save(role + '.results.json', results)
        return calls, results

    def test_wire_bytes_and_literal_rpc_inventory_are_required(self):
        calls, results = self.wire()
        self.assertEqual(metric.proof_rpc(self.directory, self.evidence, 'search', calls, 'verify-twinaatma-recovery'), results)
        altered = [('memory_get_note', {'path_or_id': 'People/Self.md'})]
        with self.assertRaises(ValueError):
            metric.proof_rpc(self.directory, self.evidence, 'search', altered, 'verify-twinaatma-recovery')

    def test_forged_parsed_result_cannot_override_actual_wire(self):
        calls, _ = self.wire()
        self.save('search.results.json', [{'payload': {'forged': True}, 'is_error': False}])
        with self.assertRaises(ValueError):
            metric.proof_rpc(self.directory, self.evidence, 'search', calls, 'verify-twinaatma-recovery')

    def test_duplicate_response_ids_and_wrong_server_are_rejected(self):
        calls, _ = self.wire()
        path = self.directory / 'search.stdout.txt'
        original = path.read_text()
        for index, mutate in ((1, lambda row: row.update(id=1)),
                              (0, lambda row: row['result'].update(serverInfo={'name': 'foreign-server'}))):
            responses = [json.loads(line) for line in original.splitlines()]
            mutate(responses[index])
            path.write_text(''.join(json.dumps(row) + '\n' for row in responses), encoding='utf-8')
            with self.assertRaises(ValueError):
                metric.proof_rpc(self.directory, self.evidence, 'search', calls, 'verify-twinaatma-recovery')

    def test_path_parent_escape_and_hardlinked_evidence_are_refused(self):
        self.save('plain.json', {'observation': 'retained'})
        for name in ('../plain.json', '/plain.json', 'x/../../plain.json', 'x\\plain.json', 'C:/plain.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                metric.retained_observation(self.directory, name)
        try:
            os.link(self.directory / 'plain.json', self.directory / 'hard.json')
        except OSError as error:
            self.skipTest('Native hardlink setup unavailable: ' + str(error))
        with self.assertRaises(ValueError):
            metric.retained_observation(self.directory, 'plain.json')

    def test_source_hash_cannot_be_omitted_under_cache_read_limitation(self):
        row = {'kind': 'file', 'size': 8, 'links': 1, 'sha256': None,
               'observation_error': 'PermissionError', 'limitation': 'native byte-range lock'}
        self.save('inventory.json', {'vault/Concepts/Recovery.md': row})
        with self.assertRaises(ValueError):
            metric.proof_inventory(self.directory, self.evidence, 'inventory.json')
        self.save('inventory.json', {'vault/knowledge_index.db': row})
        self.assertIn('vault/knowledge_index.db', metric.proof_inventory(self.directory, self.evidence, 'inventory.json'))

    def test_complete_case_registry_refuses_missing_duplicate_or_unhashed_rows(self):
        self.save('actual.json', {'actual': 'observation'})
        row = {'id': 'case-one', 'verdict': 'PASS', 'observed': {}, 'evidence': ['actual.json']}
        data = {'cases': [row], 'evidence_files': self.evidence}
        self.assertEqual(list(metric.exact_case_rows(data, ['case-one'])), ['case-one'])
        for cases in ([], [None], [row, None], [row, copy.deepcopy(row)], [dict(row, evidence=['invented.json'])]):
            with self.assertRaises(ValueError):
                metric.exact_case_rows(dict(data, cases=cases), ['case-one'])

    def test_wrong_actual_import_vault_or_native_fault_wrapper_is_rejected(self):
        scope = self.directory / 'fixtures/case-one'
        vault = scope / 'vault'
        record = {'command': [sys.executable, '-B', '-P', '-m', 'knowledgeos', 'mcp', '--vault', str(vault), '--framing', 'ndjson'],
                  'cwd': str(scope), 'vault': str(vault), 'state_dir': str(scope / 'gate-state'), 'import_path': str(scope / 'toolkit')}
        metric.proof_operation(record, self.directory, 'case-one', 'mcp')
        for field, value in (('import_path', str(ROOT)), ('vault', str(ROOT)), ('cwd', str(ROOT)), ('state_dir', str(ROOT))):
            changed = dict(record, **{field: value})
            with self.assertRaises(ValueError):
                metric.proof_operation(changed, self.directory, 'case-one', 'mcp')
        changed = dict(record, command=[sys.executable, '-B', '-P', '-c', 'print("pretend efbig")'])
        with self.assertRaises((ValueError, IndexError)):
            metric.proof_operation(changed, self.directory, 'case-one', 'memory', fault=True, kind='gate')

    def test_source_loss_cannot_be_hidden_by_true_preservation_flag(self):
        scope = self.directory / 'fixtures/case-one'
        note = scope / 'vault/People/Self.md'
        note.parent.mkdir(parents=True)
        note.write_bytes(b'Unknown synthetic owner.\n')
        row = {'kind': 'file', 'size': note.stat().st_size, 'links': 1, 'sha256': metric.sha(note)}
        before = {'vault/People/Self.md': row}
        self.save('before.inventory.json', before)
        self.save('after.inventory.json', before)
        observed = {'source_and_unrelated_files_unchanged': True, 'complete_copied_toolkit_unchanged': True,
                    'self_sha256': row['sha256'], 'changed_protected_entries': [], 'unexpected_new_notes': []}
        self.assertTrue(metric.recovery_preservation(self.directory, self.evidence, 'case-one', 'before', 'after', observed))
        note.write_bytes(b'Invented synthetic owner.\n')
        changed = {'vault/People/Self.md': dict(row, size=note.stat().st_size, sha256=metric.sha(note))}
        self.save('after.inventory.json', changed)
        with self.assertRaises(ValueError):
            metric.recovery_preservation(self.directory, self.evidence, 'case-one', 'before', 'after', observed)

    def test_real_owner_requires_matching_pid_path_threshold_and_token(self):
        scope = self.directory / 'fixtures/case-one'
        vault = scope / 'vault'
        ready = {'ready': True, 'pid': 39001, 'kind': 'index', 'path': str(vault / '.knowledgeos/index-rebuild.lock'),
                 'stale_threshold_seconds': 600.0, 'token': json.dumps({'pid': 39001, 'nonce': 'actual-owner'}).encode().hex()}
        record = {'command': [sys.executable, '-B', '-P', '-c', metric.producer_literal('recovery.py', 'HOLDER_CODE'), str(vault), 'index'],
                  'cwd': str(scope), 'vault': str(vault), 'state_dir': str(scope / 'gate-state'), 'import_path': str(scope / 'toolkit'),
                  'pid': 39001, 'ready_observation': ready, 'ready_was_observed': True}
        target = self.directory / 'owner.stdout.txt'
        target.write_text(json.dumps(ready) + '\n', encoding='utf-8')
        self.assertEqual(metric.recovery_holder(self.directory, self.evidence, record, 'case-one', 'index', 'owner'), ready)
        for mutate in (lambda value: value.update(pid=39002), lambda value: value.update(path=str(ROOT / 'unrelated.lock')),
                       lambda value: value.update(stale_threshold_seconds=0),
                       lambda value: value.update(token=json.dumps({'pid': 39002, 'nonce': 'foreign-owner'}).encode().hex())):
            changed = copy.deepcopy(record)
            mutate(changed['ready_observation'])
            target.write_text(json.dumps(changed['ready_observation']) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                metric.recovery_holder(self.directory, self.evidence, changed, 'case-one', 'index', 'owner')

    def test_pid_reuse_keeps_distinct_owned_command_records(self):
        current = {'knowledgeos/control.py': 'a' * 64, 'AGENTS.md': 'b' * 64}
        sentinel = {str(ROOT / name): 'c' * 64 for name in ('People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json')}
        record = {'command': ['git', 'rev-parse', 'HEAD'], 'cwd': str(ROOT), 'vault': None,
                  'state_dir': str(self.directory / 'gate-state'), 'pid': 44001, 'exit_code': 0,
                  'shell': False, 'error': None, 'stopped': True, 'seconds': 0.01}
        processes = []
        for role in ('revision', 'later-probe'):
            self.save(role + '.command.json', record)
            for suffix, text in (('stdout.txt', 'e' * 40 + '\n'), ('stderr.txt', '')):
                target = self.directory / (role + '.' + suffix)
                target.write_text(text, encoding='utf-8')
                self.evidence[target.name] = metric.sha(target)
            processes.append({'pid': 44001, 'role': role, 'stopped': True, 'exit_code': 0})
        data = {'producer': 'verify-twinaatma.graph/v1', 'producer_sha256': metric.sha(SCRIPT.with_name('graph.py')),
                'support_sha256': {name: metric.sha(SCRIPT.with_name(name)) for name in ('identity.py', 'data_preservation.py')},
                'product_hashes': current, 'product_hashes_after': current, 'product_and_producer_unchanged': True,
                'source_root': str(ROOT), 'scope': 'source-only public CLI initialization and persistent public MCP graph',
                'platform': 'synthetic control', 'python': sys.version, 'verdict': 'FAIL', 'error': None,
                'ideal_system_verdict': 'NOT CHECKED', 'acceptance_credit_awarded': False, 'revision': 'e' * 40,
                'processes': processes, 'all_started_processes_stopped': True, 'evidence_files': dict(self.evidence),
                'isolation': {'before': sentinel, 'after': copy.deepcopy(sentinel), 'selected_sentinels_unchanged': True}}
        path = self.directory / 'report.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(metric, 'data_toolkit_hashes', return_value=current):
            _path, _data, _toolkit, _evidence, records = metric.graph_recovery_source(path, current, graph=True)
            self.assertEqual(set(records), {'revision', 'later-probe'})
            for mutate in (lambda value: value['processes'][1].update(role='revision'),
                           lambda value: value['processes'][1].update(pid=44002),
                           lambda value: value['processes'][1].update(pid=True),
                           lambda value: value['processes'][1].update(stopped=False)):
                changed = copy.deepcopy(data)
                mutate(changed)
                path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises(ValueError):
                    metric.graph_recovery_source(path, current, graph=True)

    def test_complete_source_boundary_rejects_stale_inventory_pid_and_isolation(self):
        current = {'knowledgeos/control.py': 'a' * 64, 'AGENTS.md': 'b' * 64}
        sentinel = {str(ROOT / name): 'c' * 64 for name in ('People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json')}
        record = {'command': ['git', 'rev-parse', 'HEAD'], 'cwd': str(ROOT), 'vault': None,
                  'state_dir': str(self.directory / 'gate-state'), 'pid': 44001, 'exit_code': 0,
                  'shell': False, 'error': None, 'stopped': True, 'seconds': 0.01}
        self.save('revision.command.json', record)
        for suffix, text in (('stdout.txt', 'e' * 40 + '\n'), ('stderr.txt', '')):
            target = self.directory / ('revision.' + suffix)
            target.write_text(text, encoding='utf-8')
            self.evidence[target.name] = metric.sha(target)
        data = {'producer': 'verify-twinaatma.graph/v1', 'producer_sha256': metric.sha(SCRIPT.with_name('graph.py')),
                'support_sha256': {name: metric.sha(SCRIPT.with_name(name)) for name in ('identity.py', 'data_preservation.py')},
                'product_hashes': current, 'product_hashes_after': current, 'product_and_producer_unchanged': True,
                'source_root': str(ROOT), 'scope': 'source-only public CLI initialization and persistent public MCP graph',
                'platform': 'synthetic control', 'python': sys.version, 'verdict': 'FAIL', 'error': None,
                'ideal_system_verdict': 'NOT CHECKED', 'acceptance_credit_awarded': False, 'revision': 'e' * 40,
                'processes': [{'pid': 44001, 'role': 'revision', 'stopped': True, 'exit_code': 0}],
                'all_started_processes_stopped': True, 'evidence_files': dict(self.evidence),
                'isolation': {'before': sentinel, 'after': copy.deepcopy(sentinel), 'selected_sentinels_unchanged': True}}
        path = self.directory / 'report.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(metric, 'data_toolkit_hashes', return_value=current):
            metric.graph_recovery_source(path, current, graph=True)
            for mutate in (lambda value: value.update(producer_sha256='0' * 64),
                           lambda value: value.update(product_hashes_after={}),
                           lambda value: value['processes'][0].update(pid=True),
                           lambda value: value['processes'][0].update(stopped=False),
                           lambda value: value['isolation']['after'].update({str(ROOT / 'People/Self.md'): '0' * 64}),
                           lambda value: value['evidence_files'].update({'missing.json': '0' * 64})):
                changed = copy.deepcopy(data)
                mutate(changed)
                path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises((ValueError, OSError)):
                    metric.graph_recovery_source(path, current, graph=True)


if __name__ == '__main__':
    unittest.main()
