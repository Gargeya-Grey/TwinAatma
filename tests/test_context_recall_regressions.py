"""Retired multilingual context misses remain public startup regressions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'work/gc-artifacts/.knowledgeos/retrieval-20261023/noncritical-fix'


class ContextRecallRegressionTests(unittest.TestCase):
    def call_memory(self, notes, calls):
        directory = EVIDENCE / uuid.uuid4().hex
        vault = directory / 'vault'
        (vault / 'People').mkdir(parents=True)
        (vault / 'People/Self.md').write_bytes(b'# Self\n\nUnknown.\n')
        for name, content in notes.items():
            path = vault / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode('utf-8'))
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'handoff-regression', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        ]
        requests.extend({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                         'params': {'name': name, 'arguments': arguments}}
                        for index, (name, arguments) in enumerate(calls, start=2))
        command = [sys.executable, '-B', '-P', '-m', 'knowledgeos', 'mcp',
                   '--vault', str(vault), '--framing', 'ndjson']
        product_files = [ROOT / 'knowledgeos/search.py', ROOT / 'knowledgeos/concepts.py']
        before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in product_files}
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
                   KNOWLEDGEOS_STATE_DIR=str(directory / 'gate-state'))
        process = subprocess.Popen(command, cwd=directory, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        stdout = stderr = ''
        timed_out = False
        try:
            stdout, stderr = process.communicate(
                ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in requests), timeout=90)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
        (directory / 'protocol.json').write_text(json.dumps({
            'command': command, 'requests': requests, 'stdout': stdout, 'stderr': stderr,
            'pid': process.pid, 'exit_code': process.returncode, 'stopped': process.poll() is not None,
            'timed_out': timed_out,
            'product_sha256_before': before,
            'product_sha256_after': {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in product_files},
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        self.assertFalse(timed_out, f'MCP timed out; retained evidence at {directory}')
        self.assertEqual(process.returncode, 0, stderr)
        responses = {row['id']: row for row in map(json.loads, stdout.splitlines())}
        self.assertEqual(responses[1]['result']['serverInfo']['name'], 'knowledgeos-memory')
        payloads = []
        for index in range(2, len(calls) + 2):
            result = responses[index]['result']
            self.assertFalse(result.get('isError'), result)
            payloads.append(json.loads(result['content'][0]['text']))
        return payloads

    def test_independent_concept_controls_preserve_literal_search_and_privacy(self):
        notes = {
            'Notes/Planting.md': '# Semis\n\nLes semis restent dans le jardin clos.\n',
            'Notes/Binding.md': '# Encuadernación\n\nLa encuadernación usa lino azul.\n',
            'Notes/Dinner.md': '# Supper\n\nFor supper bring a ceramic plate.\n',
            'Notes/River.md': '# River notes\n\nनाव घाट के पास है।\n',
            'Notes/Private.md': '---\nprivacy: private\n---\n# Private materials\n\n'
                                'The seedling bookbinding supper boat sentinel is copper meadow.\n',
            'Notes/Noise.md': '# A weather conversation\n\nThe clouds looked bright today.\n',
        }
        checks = [
            ('Where are the seedlings?', 'Notes/Planting.md',
             'Les semis restent dans le jardin clos.'),
            ('Help me prepare for bookbinding.', 'Notes/Binding.md',
             'La encuadernación usa lino azul.'),
            ('What should I bring to the meal?', 'Notes/Dinner.md',
             'For supper bring a ceramic plate.'),
            ('Find the boat.', 'Notes/River.md', 'नाव घाट के पास है।'),
        ]
        calls = [('memory_session_start', {'task_hint': hint, 'session_id': f'control-{index}'})
                 for index, (hint, _path, _quote) in enumerate(checks)]
        calls.extend([('memory_search', {'query': 'bookbinding'}),
                      ('memory_search', {'query': 'boat'}),
                      ('memory_search', {'query': 'encuadernación'}),
                      ('memory_search', {'query': 'नाव'})])
        payloads = self.call_memory(notes, calls)
        for payload, (_hint, path, quote) in zip(payloads[:4], checks):
            rows = {row['path']: row for row in payload['context']['relevant']['ranked'][:8]}
            self.assertIn(path, rows)
            self.assertIn(quote, rows[path]['excerpt'])
            for row in rows.values():
                self.assertLessEqual(len(row['excerpt'].encode('utf-8')), 1200)
        self.assertEqual(payloads[4]['ranked'], [])
        self.assertEqual(payloads[5]['ranked'], [])
        self.assertEqual([row['path'] for row in payloads[6]['ranked']], ['Notes/Binding.md'])
        self.assertEqual([row['path'] for row in payloads[7]['ranked']], ['Notes/River.md'])
        for payload in payloads:
            self.assertNotIn('Notes/Private.md', json.dumps(payload, ensure_ascii=False))
            self.assertNotIn('copper meadow', json.dumps(payload, ensure_ascii=False))

    def test_retired_multilingual_sources_and_companions(self):
        corpus = json.loads((ROOT / 'tests/fixtures/quality-v2.json').read_text(encoding='utf-8'))
        selected = {'fresh-held-18', 'fresh-held-20', 'fresh-held-24', 'fresh-held-30'}
        for case in corpus['cases']:
            if case['id'] not in selected:
                continue
            with self.subTest(case=case['id']):
                payload, = self.call_memory(
                    {note['path']: note['content'] for note in corpus['notes']},
                    [('memory_session_start', {'task_hint': case['task_hint'],
                                               'session_id': case['id']})])
                rows = {row['path']: row for row in payload['context']['relevant']['ranked'][:8]}
                for expected in case['expected_sources']:
                    self.assertIn(expected['path'], rows)
                    for claim in expected.get('claims', []):
                        self.assertIn(claim['quote'], rows[expected['path']]['excerpt'])


if __name__ == '__main__':
    unittest.main()

