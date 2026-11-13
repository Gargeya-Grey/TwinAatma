"""Natural handoff planning retrieves current and historical evidence across languages."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'work/gc-artifacts/.knowledgeos/retrieval-20261023/handoff-fix'


class MultilingualHandoffTests(unittest.TestCase):
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

    def test_hindi_handoff_hint_recalls_both_original_deadline_sources(self):
        corpus = json.loads((ROOT / 'tests/fixtures/quality-v1.json').read_text(encoding='utf-8'))
        payload, = self.call_memory(
            {note['path']: note['content'] for note in corpus['notes']},
            [('memory_session_start', {
                'task_hint': 'केस्ट्रल की अंतिम सुपुर्दगी के लिए समय-सारणी बनाओ।',
                'session_id': 'handoff-regression'})])
        ranked = {row['path']: row for row in payload['context']['relevant']['ranked'][:8]}
        self.assertIn('Projects/Kestrel/Deadline-Current.md', ranked)
        self.assertIn('Projects/Kestrel/Deadline-History.md', ranked)
        self.assertIn('The current deadline is 2026-05-20.',
                      ranked['Projects/Kestrel/Deadline-Current.md']['excerpt'])
        self.assertIn('The handoff was planned for 2026-05-06. This date was superseded by '
                      'the correction recorded on 2026-04-14; it is not the current deadline.',
                      ranked['Projects/Kestrel/Deadline-History.md']['excerpt'])

    def test_another_project_handover_preserves_history_privacy_and_literal_search(self):
        notes = {
            'Projects/Nacre/Current.md': '# Nacre\n\nThe handover is now on 2027-02-19. This replaces 2027-02-05.\n',
            'Projects/Nacre/History.md': '# Nacre archive\n\nThe handover was on 2027-02-05; that plan is superseded.\n',
            'Projects/Nacre/Private.md': '---\nprivacy: private\n---\n# Nacre confidential\n\nThe handover access phrase is cerulean otter.\n',
            'Notes/Garden.md': '# Garden\n\nThe seedlings need watering.\n',
        }
        startup, hindi_search, english_search = self.call_memory(notes, [
            ('memory_session_start', {'task_hint': 'नाक्रे की सुपुर्दगी की तैयारी करो।',
                                      'session_id': 'independent-handover'}),
            ('memory_search', {'query': 'सुपुर्दगी'}),
            ('memory_search', {'query': 'handover'}),
        ])
        ranked = {row['path']: row for row in startup['context']['relevant']['ranked'][:8]}
        self.assertIn('Projects/Nacre/Current.md', ranked)
        self.assertIn('Projects/Nacre/History.md', ranked)
        self.assertIn('The handover is now on 2027-02-19. This replaces 2027-02-05.',
                      ranked['Projects/Nacre/Current.md']['excerpt'])
        self.assertIn('The handover was on 2027-02-05; that plan is superseded.',
                      ranked['Projects/Nacre/History.md']['excerpt'])
        self.assertEqual(hindi_search['ranked'], [])
        self.assertEqual({row['path'] for row in english_search['ranked']},
                         {'Projects/Nacre/Current.md', 'Projects/Nacre/History.md'})
        for payload in (startup, hindi_search, english_search):
            self.assertNotIn('Projects/Nacre/Private.md', json.dumps(payload, ensure_ascii=False))
            self.assertNotIn('cerulean otter', json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
