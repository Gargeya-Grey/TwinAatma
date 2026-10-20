"""Public CLI and stdio relocation behavior in retained synthetic vaults."""
from __future__ import annotations

import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('TWIN_MOVE_OUTPUT') or
              (ROOT / 'work/gc-artifacts/.knowledgeos/host-move-controls' / uuid.uuid4().hex[:12]))
PROCESSES = []


def run(command, cwd, environment, data=b'', timeout=90):
    directory = OUTPUT / 'commands' / (str(time.time_ns()) + '-' + uuid.uuid4().hex[:6])
    directory.mkdir(parents=True)
    started = time.time_ns()
    process = subprocess.Popen(command, cwd=cwd, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        stdout, stderr = process.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    record = {'command': list(map(str, command)), 'cwd': str(cwd), 'pid': process.pid,
              'started_ns': started, 'finished_ns': time.time_ns(),
              'exit_code': process.returncode, 'stopped': process.poll() is not None,
              'timed_out': timed_out, 'evidence': str(directory)}
    (directory / 'stdout.txt').write_bytes(stdout)
    (directory / 'stderr.txt').write_bytes(stderr)
    (directory / 'stdin.jsonl').write_bytes(data)
    (directory / 'command.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    PROCESSES.append(record)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class HostVaultMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        cls.environment = dict(os.environ, PYTHONPATH=str(ROOT), PATH='',
                               KNOWLEDGEOS_STATE_DIR=str(OUTPUT / 'base-state'))
        cls.environment.pop('KNOWLEDGEOS_GATE_KEY', None)
        cls.environment.pop('KNOWLEDGEOS_VAULT', None)
        cls.base = OUTPUT / 'base-vault'
        result = run([sys.executable, '-B', '-P', '-m', 'knowledgeos', 'init', str(cls.base),
                      '--name', 'Synthetic Move Owner', '--non-interactive'], ROOT, cls.environment)
        if result.returncode:
            raise AssertionError(result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))

    @classmethod
    def tearDownClass(cls):
        (OUTPUT / 'processes.json').write_text(json.dumps(PROCESSES, indent=2), encoding='utf-8')

    def setUp(self):
        self.directory = OUTPUT / self.id().rsplit('.', 1)[-1]
        self.directory.mkdir()
        self.vault = self.directory / 'vault'
        shutil.copytree(self.base, self.vault)
        self.environment = dict(self.environment, KNOWLEDGEOS_STATE_DIR=str(self.directory / 'state'))

    def cli(self, *args, cwd=None, environment=None, data=b''):
        return run([sys.executable, '-B', '-P', '-m', 'knowledgeos', *map(str, args)],
                   cwd or self.directory, environment or self.environment, data)

    def identity(self, vault=None):
        return json.loads(((vault or self.vault) / '.knowledgeos-vault.json').read_text())['vault_id']

    def inventory(self, root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}

    def note(self, vault, value):
        path = vault / 'Projects/Harborline.md'
        path.parent.mkdir(exist_ok=True)
        path.write_text('---\nid: kos:project:harborline\ntype: project\ntitle: Harborline\n'
                        'status: active\n---\n# Harborline\n\n' + value +
                        '\n\n[Source](../Sources/Harborline-source.md)\n', encoding='utf-8')
        source = vault / 'Sources/Harborline-source.md'
        source.parent.mkdir(exist_ok=True)
        source.write_text('---\nid: kos:source:harborline-source\ntype: source\n'
                          'title: Harborline source\n---\nOriginal source detail.\n', encoding='utf-8')
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def server(self, host='cursor'):
        result = self.cli('setup-host', '--host', host, '--vault', self.vault, '--write')
        self.assertEqual(result.returncode, 0, result.stderr)
        if host == 'codex':
            import tomllib
            return tomllib.loads((self.vault / '.codex/config.toml').read_text())['mcp_servers']['knowledgeos']
        folder, key = ('.vscode', 'servers') if host == 'vscode' else ('.cursor', 'mcpServers')
        return json.loads((self.vault / folder / 'mcp.json').read_text())[key]['knowledgeos']

    def mcp(self, calls, *, server=None, cwd=None, arguments=None, environment=None):
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
        requests += [{'jsonrpc': '2.0', 'id': index + 2, 'method': 'tools/call',
                      'params': {'name': name, 'arguments': args}} for index, (name, args) in enumerate(calls)]
        payload = b''.join(json.dumps(request).encode() + b'\n' for request in requests)
        if server is None:
            result = self.cli('mcp', *(arguments or []), cwd=cwd, environment=environment, data=payload)
        else:
            env = dict(environment or self.environment, **server['env'])
            result = run([server['command'], *server['args']], cwd or self.directory, env, payload)
        values = []
        if result.returncode == 0:
            messages = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(messages[0]['result']['serverInfo']['name'], 'knowledgeos-memory')
            for message in messages[1:]:
                self.assertFalse(message['result'].get('isError'), message)
                values.append(json.loads(message['result']['content'][0]['text']))
        return result, values

    def bound(self, vault=None, expected=None):
        return ['--host-vault-id', expected or self.identity(), '--vault', str(vault or self.vault)]

    def refusal(self, arguments, *, cwd=None, environment=None):
        before = self.inventory(self.directory)
        result, _ = self.mcp([], arguments=arguments, cwd=cwd or self.directory, environment=environment)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn(b'Traceback', result.stderr)
        self.assertEqual(self.inventory(self.directory), before)
        self.assertFalse((self.directory / 'state').exists())
        return result

    def test_generated_config_binds_full_id_and_omits_fixed_cwd(self):
        marker_id = json.loads((self.vault / '.knowledgeos-vault.json').read_text())['vault_id']
        result = self.cli('setup-host', '--host', 'cursor', '--vault', self.vault, '--write')
        self.assertEqual(result.returncode, 0, result.stderr)
        server = json.loads((self.vault / '.cursor/mcp.json').read_text())['mcpServers']['knowledgeos']
        self.assertIn('--host-vault-id', server['args'])
        self.assertEqual(server['args'][server['args'].index('--host-vault-id') + 1], marker_id)
        self.assertNotIn('cwd', server)
        self.assertEqual(server['env']['KNOWLEDGEOS_VAULT'], str(self.vault))
        self.assertNotIn('KNOWLEDGEOS_HOST_VAULT_ID', server['env'])

    def test_exact_generated_stdio_survives_move_and_different_vault_at_old_path(self):
        expected = self.note(self.vault, 'Use cobalt sails for Harborline.')
        server = self.server()
        config_before = (self.vault / '.cursor/mcp.json').read_bytes()
        calls = [('memory_get_note', {'path_or_id': 'Projects/Harborline.md'}),
                 ('memory_capture', {'title': 'Harborline sail decision', 'content': 'Remember cobalt sails.'})]
        result, values = self.mcp(calls, server=server, cwd=self.vault)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)
        capture = values[1].get('path') or values[1].get('note_path')
        self.assertIsNotNone(capture, values[1])
        selected = {name: (self.vault / name).read_bytes() for name in
                    ('People/Self.md', 'Projects/Harborline.md', 'Sources/Harborline-source.md', capture)}
        shutil.copytree(self.vault, self.directory / 'original-preserved')
        old = self.vault
        moved = self.directory / 'moved'
        self.assertTrue(old.resolve().is_relative_to(self.directory.resolve()))
        self.assertTrue(moved.resolve().is_relative_to(self.directory.resolve()))
        inventory = self.inventory(old)
        old.rename(moved)
        self.assertEqual(self.inventory(moved), inventory)
        self.assertEqual((moved / '.cursor/mcp.json').read_bytes(), config_before)
        reads = [('memory_get_note', {'path_or_id': 'Projects/Harborline.md'}),
                 ('memory_get_note', {'path_or_id': capture}),
                 ('memory_get_note', {'path_or_id': 'Sources/Harborline-source.md'}),
                 ('memory_search', {'query': 'Harborline cobalt sails'})]
        result, values = self.mcp(reads, server=server, cwd=moved)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)
        self.assertIn('../Sources/Harborline-source.md', json.dumps(values[0]))
        self.assertIn('Remember cobalt sails.', json.dumps(values[1]))
        self.assertIn('Original source detail.', json.dumps(values[2]))
        self.assertIn('Harborline.md', json.dumps(values[3]))
        shutil.copytree(self.base, old)
        (old / '.knowledgeos-vault.json').write_text(json.dumps({'vault_id': 'f' * 32}), encoding='utf-8')
        unrelated = self.note(old, 'The unrelated vault requires amber canvas.')
        self.assertNotEqual(unrelated, expected)
        unrelated_before = self.inventory(old)
        result, values = self.mcp(reads + [('memory_capture', {'title': 'Moved-only capture',
                                                            'content': 'This belongs to the original moved vault.'})],
                                  server=server, cwd=moved)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)
        self.assertEqual(self.inventory(old), unrelated_before)
        for name, original in selected.items():
            self.assertEqual((moved / name).read_bytes(), original)
        self.assertEqual((moved / '.cursor/mcp.json').read_bytes(), config_before)

    def test_bound_nested_other_vault_does_not_hide_matching_ancestor(self):
        expected = self.note(self.vault, 'The matching parent owns cobalt sails.')
        nested = self.vault / 'nested'
        nested.mkdir()
        (nested / '.knowledgeos-vault.json').write_text(json.dumps({'vault_id': 'e' * 32}))
        leaf = nested / 'leaf'
        leaf.mkdir()
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=self.bound(), cwd=leaf)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)

    def test_checked_external_fallback_ignores_unrelated_inherited_environment(self):
        expected = self.note(self.vault, 'The external vault owns cobalt sails.')
        copied = self.directory / 'copy'
        shutil.copytree(self.vault, copied)
        workspace = self.directory / 'workspace'
        workspace.mkdir()
        (workspace / '.knowledgeos-vault.json').write_text(json.dumps({'vault_id': 'd' * 32}))
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=self.bound(), cwd=workspace,
                                  environment=dict(self.environment, KNOWLEDGEOS_VAULT=str(copied)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)

    def test_environment_fallback_requires_the_full_matching_id(self):
        expected = self.note(self.vault, 'The environment fallback owns cobalt sails.')
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=['--host-vault-id=' + self.identity()],
                                  environment=dict(self.environment, KNOWLEDGEOS_VAULT=str(self.vault)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)

    def test_distinct_visible_same_id_vaults_refuse_without_writes(self):
        copied = self.directory / 'copy'
        shutil.copytree(self.vault, copied)
        result = self.refusal(self.bound(copied), cwd=self.vault)
        self.assertIn(b'ambiguous', result.stderr)

    def test_shared_prefix_wrong_full_id_refuses_without_writes(self):
        expected = self.identity()
        other = expected[:16] + ('0' if expected[16] != '0' else '1') + expected[17:]
        self.refusal(self.bound(expected=other), cwd=self.vault)

    def test_missing_target_and_relative_fallback_refuse_without_writes(self):
        self.refusal(self.bound(self.directory / 'absent'))
        self.refusal(['--host-vault-id', self.identity(), '--vault', 'vault'])

    def test_malformed_and_duplicate_cli_bindings_refuse_before_protocol(self):
        expected = self.identity()
        for arguments in (['--host-vault-id', ''], ['--host-vault-id='],
                          ['--host-vault-id', 'wrong'], ['--host-vault-id', expected,
                           '--host-vault-id=' + expected], ['--host-vault-id', expected,
                           '--host-vault-id', 'f' * 32], ['--host-vault-i', expected]):
            with self.subTest(arguments=arguments):
                self.refusal([*arguments, '--vault', str(self.vault)])

    def test_ordinary_explicit_precedence_and_stale_path_compatibility_remain(self):
        expected = self.note(self.vault, 'The explicit vault owns cobalt sails.')
        workspace = self.directory / 'other'
        shutil.copytree(self.base, workspace)
        self.note(workspace, 'Another vault owns amber sails.')
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=['--vault', str(self.vault)], cwd=workspace,
                                  environment=dict(self.environment, KNOWLEDGEOS_HOST_VAULT_ID='malformed'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=['--vault', str(self.directory / 'absent')], cwd=self.vault)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)

    def test_marker_malformed_shapes_duplicate_keys_encoding_and_size_refuse(self):
        marker = self.vault / '.knowledgeos-vault.json'
        expected = self.identity()
        for raw in (b'[]', b'{', b'{"vault_id":null}', b'{"vault_id":16}',
                    b'{"vault_id":""}', b'{"vault_id":"not-hex"}',
                    ('{"vault_id":"' + expected + '","vault_id":"' + expected + '"}').encode(),
                    b'\xff', b' ' * 65537 + b'{}'):
            with self.subTest(raw=raw[:80]):
                marker.write_bytes(raw)
                self.refusal(self.bound(expected=expected), cwd=self.vault)

    def test_conflicting_markers_and_malformed_fallback_cannot_hide_behind_a_match(self):
        expected = self.identity()
        legacy = self.vault / 'knowledgeos.config.json'
        legacy.write_text(json.dumps({'vault_id': 'f' * 32}))
        self.refusal(self.bound(expected=expected), cwd=self.vault)
        legacy.write_text('{}')
        fallback = self.directory / 'fallback'
        fallback.mkdir()
        (fallback / '.knowledgeos-vault.json').write_text('{')
        self.refusal(self.bound(fallback, expected), cwd=self.vault)

    def test_new_legacy_vault_remains_unbound_without_allocating_id_or_state(self):
        legacy = self.directory / 'legacy'
        (legacy / 'People').mkdir(parents=True)
        shutil.copyfile(self.vault / 'People/Self.md', legacy / 'People/Self.md')
        self.vault = legacy
        before = (legacy / 'People/Self.md').read_bytes()
        server = self.server()
        self.assertNotIn('--host-vault-id', server['args'])
        self.assertEqual(server['cwd'], str(legacy))
        self.assertFalse((legacy / '.knowledgeos-vault.json').exists())
        self.assertFalse((self.directory / 'state').exists())
        self.assertEqual((legacy / 'People/Self.md').read_bytes(), before)

    def test_all_native_config_migrations_remove_owned_cwd_preserve_settings_and_repeat(self):
        expected = self.identity()
        for host, folder, key in (('cursor', '.cursor', 'mcpServers'), ('vscode', '.vscode', 'servers')):
            target = self.vault / folder / 'mcp.json'
            target.parent.mkdir(exist_ok=True)
            foreign = {'command': 'foreign-command', 'args': ['keep'], 'required': False}
            original = {'owner': {'mode': 'careful'}, key: {'other': foreign,
                        'knowledgeos': {'command': 'old', 'args': ['mcp', '--vault', str(self.vault)],
                                        'cwd': str(self.vault), 'custom': 47,
                                        'env': {'CUSTOM': 'retain', 'KNOWLEDGEOS_VAULT': 'old'}}}}
            target.write_text(json.dumps(original))
            server = self.server(host)
            parsed = json.loads(target.read_text())
            self.assertEqual(parsed['owner'], original['owner'])
            self.assertEqual(parsed[key]['other'], foreign)
            self.assertNotIn('cwd', server)
            self.assertEqual(server['custom'], 47)
            self.assertEqual(server['env']['CUSTOM'], 'retain')
            self.assertEqual(server['args'][server['args'].index('--host-vault-id') + 1], expected)
            before = target.read_bytes()
            self.server(host)
            self.assertEqual(target.read_bytes(), before)
        target = self.vault / '.codex/config.toml'
        target.parent.mkdir(exist_ok=True)
        foreign_text = '# Retain owner text.\nmodel="synthetic"\n[mcp_servers.other]\ncommand="other" # foreign\nrequired=false\n\n'
        for inline in (True, False):
            original = foreign_text + '[mcp_servers."knowledgeos"]\ncommand="old"\nargs=["mcp"]\ncwd="old"\nstartup_timeout_sec=45 # custom\n'
            original += ('env={CUSTOM="keep",KNOWLEDGEOS_VAULT="old"}\n' if inline else
                         '\n[mcp_servers.knowledgeos.env]\nCUSTOM="keep" # retain\nKNOWLEDGEOS_VAULT="old"\n')
            target.write_text(original)
            server = self.server('codex')
            self.assertNotIn('cwd', server)
            self.assertTrue(server['required'])
            self.assertEqual(server['default_tools_approval_mode'], 'approve')
            self.assertEqual(server['env']['CUSTOM'], 'keep')
            self.assertTrue(target.read_text().startswith(foreign_text))
            self.assertIn('startup_timeout_sec=45 # custom', target.read_text())
            before = target.read_bytes()
            self.server('codex')
            self.assertEqual(target.read_bytes(), before)

    def test_bound_migration_refuses_downgrade_rebind_and_malformed_old_flags(self):
        expected = self.identity()
        for host, folder, key in (('cursor', '.cursor', 'mcpServers'), ('vscode', '.vscode', 'servers'),
                                  ('codex', '.codex', 'mcp_servers')):
            target = self.vault / folder / ('config.toml' if host == 'codex' else 'mcp.json')
            target.parent.mkdir(exist_ok=True)
            for old_args, marker in ((['mcp', '--host-vault-id', expected], {}),
                                     (['mcp', '--host-vault-id=' + expected], {'vault_id': 'f' * 32}),
                                     (['mcp', '--host-vault-id='], {'vault_id': expected}),
                                     (['mcp', '--host-vault-id', expected, '--host-vault-id=' + expected], {'vault_id': expected}),
                                     (['mcp', '--host-vault-id', 'wrong'], {'vault_id': expected})):
                with self.subTest(host=host, old_args=old_args, marker=marker):
                    (self.vault / '.knowledgeos-vault.json').write_text(json.dumps(marker))
                    server = {'command': 'old', 'args': old_args, 'cwd': str(self.vault), 'env': {}}
                    if host == 'codex':
                        original = '[mcp_servers.knowledgeos]\ncommand="old"\nargs=' + json.dumps(old_args) + '\n'
                    else:
                        original = json.dumps({key: {'knowledgeos': server}})
                    target.write_text(original)
                    before = self.inventory(self.directory)
                    result = self.cli('setup-host', '--host', host, '--vault', self.vault, '--write')
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(self.inventory(self.directory), before)
                    self.assertFalse((self.directory / 'state').exists())

    def test_marker_hardlink_and_linked_vault_path_refuse(self):
        marker = self.vault / '.knowledgeos-vault.json'
        alias = self.directory / 'marker-hardlink'
        self.assertTrue(alias.resolve().is_relative_to(self.directory.resolve()))
        os.link(marker, alias)
        self.refusal(self.bound(), cwd=self.vault)
        result = self.cli('setup-host', '--host', 'cursor', '--vault', self.vault, '--write')
        self.assertNotEqual(result.returncode, 0)
        plain = self.directory / 'plain'
        shutil.copytree(self.base, plain)
        junction = self.directory / 'junction'
        self.assertTrue(plain.resolve().is_relative_to(self.directory.resolve()))
        self.assertTrue(junction.resolve().is_relative_to(self.directory.resolve()))
        if os.name == 'nt':
            command = [str(Path(os.environ['SystemRoot']) / 'System32/cmd.exe'), '/d', '/c',
                       'mklink', '/J', str(junction), str(plain)]
            linked = run(command, self.directory, self.environment)
            self.assertEqual(linked.returncode, 0, linked.stderr)
        else:
            junction.symlink_to(plain, target_is_directory=True)
        before = self.inventory(plain)
        result = self.cli('setup-host', '--host', 'cursor', '--vault', junction, '--write')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.inventory(plain), before)
        result = self.cli('setup-host', '--host', 'cursor', '--write',
                          environment=dict(self.environment, KNOWLEDGEOS_VAULT=str(junction)))
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.inventory(plain), before)
        result, _ = self.mcp([], arguments=['--host-vault-id', self.identity(plain), '--vault', str(junction)])
        self.assertNotEqual(result.returncode, 0)
        result = self.cli('setup-host', '--host', 'cursor', '--vault', junction / '..' / 'plain', '--write')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.inventory(plain), before)

    def test_public_mcp_refuses_marker_replacement_during_checked_open(self):
        from knowledgeos.__main__ import main
        marker = self.vault / '.knowledgeos-vault.json'
        expected = self.identity()
        before = (self.vault / 'People/Self.md').read_bytes()
        actual_open = os.open
        fired = []

        def replacing(path, flags, *args, **kwargs):
            if Path(path) == marker and not fired:
                fired.append(True)
                marker.rename(self.directory / 'original-marker-preserved.json')
                marker.write_text(json.dumps({'vault_id': expected}))
            return actual_open(path, flags, *args, **kwargs)

        output, error = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.environment), mock.patch('os.open', side_effect=replacing), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(['mcp', *self.bound(expected=expected)])
        self.assertTrue(fired)
        self.assertEqual(code, 2)
        self.assertEqual(output.getvalue(), '')
        self.assertIn('changed', error.getvalue())
        self.assertFalse((self.directory / 'state').exists())
        self.assertEqual((self.vault / 'People/Self.md').read_bytes(), before)
        (self.directory / 'fault-observation.json').write_text(json.dumps({
            'public_command': ['mcp', *self.bound(expected=expected)], 'pid': os.getpid(),
            'code': code, 'stdout': output.getvalue(), 'stderr': error.getvalue(),
            'fault_fired': True, 'Self_unchanged': True, 'state_created': False}, indent=2))

    def test_public_mcp_refuses_named_marker_replacement_after_descriptor_read(self):
        from knowledgeos.__main__ import main
        marker = self.vault / '.knowledgeos-vault.json'
        expected = self.identity()
        actual_fdopen = os.fdopen
        calls = []

        @contextlib.contextmanager
        def replacing(descriptor, *args, **kwargs):
            with actual_fdopen(descriptor, *args, **kwargs) as handle:
                yield handle
            if not calls:
                calls.append(True)
                marker.rename(self.directory / 'original-marker-preserved.json')
                marker.write_text(json.dumps({'vault_id': expected}))

        before = (self.vault / 'People/Self.md').read_bytes()
        output, error = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.environment), mock.patch('os.fdopen', side_effect=replacing), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(['mcp', *self.bound(expected=expected)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(code, 2)
        self.assertEqual(output.getvalue(), '')
        self.assertIn('changed', error.getvalue())
        self.assertFalse((self.directory / 'state').exists())
        self.assertEqual((self.vault / 'People/Self.md').read_bytes(), before)

    def test_source_command_ignores_vault_import_shadow(self):
        expected = self.note(self.vault, 'The trusted toolkit owns cobalt sails.')
        server = self.server()
        executed = self.directory / 'untrusted-code-ran'
        (self.vault / 'knowledgeos.py').write_text('from pathlib import Path\nPath(' + repr(str(executed)) + ').touch()\n')
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  server=server, cwd=self.vault)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)
        self.assertFalse(executed.exists())

    def test_plain_dotdot_fallback_deduplicates_the_same_physical_vault(self):
        expected = self.note(self.vault, 'A plain lexical spelling still owns cobalt sails.')
        other = self.directory / 'other'
        shutil.copytree(self.vault, other)
        fallback = self.vault / '..' / 'other'
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=self.bound(fallback), cwd=self.directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)
        result, values = self.mcp([('memory_get_note', {'path_or_id': 'Projects/Harborline.md'})],
                                  arguments=self.bound(fallback), cwd=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0]['sha256'], expected)


if __name__ == '__main__':
    unittest.main()
