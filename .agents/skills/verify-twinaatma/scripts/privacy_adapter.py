"""Independently grade three fixed privacy outcomes from retained source observations."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct

CASE_NAMES = (
    'human_policy', 'native_setup', 'ordinary_retention', 'credential_rpc', 'credential_cli',
    'explicit_metadata', 'third_party_patterns', 'third_party_semantic', 'legacy_admission',
    'forged_busy_cache', 'generated_outputs', 'correction_stale_hash', 'reviewed_correction',
    'forget_stale_hash', 'reviewed_forgetting', 'forget_replay_restart_copy', 'forget_session_state',
    'concurrent_forgetting', 'export_scope', 'malformed_local', 'duplicate_local', 'valid_empty_local',
    'valid_replacement_local', 'deleted_local', 'linked_local', 'hardlinked_local', 'tampered_authority',
    'deleted_authority', 'tampered_key', 'deleted_key', 'linked_authority', 'hardlinked_authority',
    'linked_source', 'publication_failure_retry', 'native_pending_diagnostic', 'native_git_diagnostic',
    'publisher_dry_run', 'publisher_all_dry_run', 'bridge_setup_dry_run', 'bridge_publish_dry_run',
    'bridge_unscoped_json', 'source_and_identity_preservation', 'redacted_evidence', 'transport_scope')
STATE_NAMES = CASE_NAMES[19:32]
ORDINARY = 'Rill planning reviews happen every second Thursday morning.'
CURRENT = 'Rill release reviews happen on Friday.'
PRIOR = 'Rill release reviews happen on Tuesday.'
BENIGN = 'Mira reviews Rill release plans with me.'
POLICY_DIGEST = 'cbec26e0349f5615c6895cde5be81e13b917895982d75827dc94b3f6cd3901d5'
APPROVAL_DIGEST = '934bdc4fa93728537c93ab9259a322fe27ce685072c07a29a0871ca520421791'
ELIGIBLE = {'PRIVACY.explicit_policy': ('policy', 'privacy.policy.complete'),
            'PRIVACY.exposure_scope': ('source', 'privacy.exposure.complete'),
            'PRIVACY.external_writes': ('source', 'privacy.external.complete')}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Privacy JSON contains duplicate keys')
        result[key] = value
    return result


def _loads(text):
    return json.loads(text, object_pairs_hook=_unique)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def _literal(name):
    tree = ast.parse(Path(__file__).with_name('privacy.py').read_text(encoding='utf-8'))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    if len(values) != 1:
        raise ValueError('Privacy instrumentation literal is missing or duplicated')
    return ast.literal_eval(values[0])


def native_link_target(path):
    path = Path(path)
    if path.is_symlink():
        target = str(path.readlink())
        # Windows reports native symlink targets in the extended-length form.
        return target[4:] if os.name == 'nt' and target.startswith('\\\\?\\') else target
    info = path.lstat()
    if getattr(info, 'st_reparse_tag', None) != 0xA000001D:
        raise ValueError('Privacy retained native link is missing or has an unsupported tag')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path.absolute()), 0x80000000, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ValueError('Privacy retained WSL link cannot be opened as a reparse point')
    try:
        buffer, returned = ctypes.create_string_buffer(16384), wintypes.DWORD()
        if not kernel.DeviceIoControl(handle, 0x000900A8, None, 0, buffer, len(buffer), ctypes.byref(returned), None):
            raise ValueError('Privacy retained WSL reparse data is unreadable')
        raw = buffer.raw[:returned.value]
    finally:
        kernel.CloseHandle(handle)
    if len(raw) < 12:
        raise ValueError('Privacy retained WSL reparse buffer is truncated')
    tag, size, reserved, version = struct.unpack_from('<IHHI', raw)
    if tag != 0xA000001D or version not in (1, 2) or len(raw) != size + 8:
        raise ValueError('Privacy retained WSL link has an unknown reparse schema')
    target = raw[12:].rstrip(b'\0').decode('utf-8', errors='strict')
    if not target or '\0' in target:
        raise ValueError('Privacy retained WSL link target is malformed')
    return target


def privacy_reports(api, path, current):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Privacy report traverses lexical parents')
    directory = path.parent
    relative = directory.relative_to(api.ROOT.absolute())
    if relative.parts[:2] != ('work', 'gc-artifacts') or '.knowledgeos' not in relative.parts[2:]:
        raise ValueError('Privacy report leaves contained synthetic evidence')
    api.data_evidence(directory, path.name)
    data = _loads(path.read_text(encoding='utf-8'))
    support = {'data_preservation.py': api.sha(api.ROOT / '.agents/skills/verify-twinaatma/scripts/data_preservation.py')}
    toolkit = api.data_toolkit_hashes()
    if (not isinstance(data, dict) or data.get('producer') != 'verify-twinaatma.privacy-source/v1'
            or data.get('producer_sha256') != api.sha(Path(__file__).with_name('privacy.py'))
            or data.get('support_sha256') != support or data.get('support_sha256_after') != support):
        raise ValueError('Privacy producer/support is unknown or stale')
    api.check_product(data, 'product_hashes', current)
    if (data.get('product_hashes') != toolkit or data.get('product_hashes_after') != toolkit
            or data.get('product_and_producer_unchanged') is not True
            or api.data_repository_location(data.get('source_root')) != ''):
        raise ValueError('Privacy complete toolkit is changed or stale')
    if (data.get('scope') != 'source-policy privacy in a complete task-owned copied toolkit'
            or data.get('error') is not None or data.get('verdict') not in ('PASS', 'FAIL')
            or not isinstance(data.get('platform'), str) or not data['platform']
            or not isinstance(data.get('python'), str) or not data['python']
            or data.get('ideal_system_verdict') != 'NOT CHECKED' or data.get('acceptance_credit_awarded') is not False
            or data.get('case_inventory_complete') is not True
            or data.get('expected_case_ids') != ['privacy.' + name for name in CASE_NAMES]):
        raise ValueError('Privacy execution identity or complete matrix differs')
    evidence = data.get('evidence_files')
    if not isinstance(evidence, dict) or not evidence or path.name in evidence or 'private-inputs.json' in evidence:
        raise ValueError('Privacy public evidence inventory is missing or includes private inputs')
    for name, digest in evidence.items():
        try:
            valid = isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) and api.sha(api.retained_observation(directory, name)) == digest
        except OSError:
            valid = False
        if not valid:
            raise ValueError('Privacy evidence is missing, escaped, linked or altered: ' + str(name))
    private = _loads(api.retained_observation(directory, 'private-inputs.json').read_text(encoding='utf-8'))
    if (not isinstance(private, dict) or set(private) != {'credential' + str(n) for n in range(6)} | {'legacy', 'diagnostic', 'third0', 'third1', 'third2', 'semantic'}
            or any(not isinstance(value, str) or not value or '<private:' in value for value in private.values())
            or any(not re.fullmatch('sk-[0-9a-f]{40}', private[name]) for name in (*['credential' + str(n) for n in range(6)], 'legacy', 'diagnostic'))
            or private['third0'] != 'Mira was diagnosed with diabetes.'
            or private['third1'] != "Mira's bank account funds her private care."
            or private['third2'] != "Mira's private phone is available only to family."
            or private['semantic'] != "My colleague's biopsy showed a malignant growth in her left lung."):
        raise ValueError('Privacy controlled synthetic input schema differs')
    def restore(text):
        for name, value in private.items():
            text = text.replace('<private:' + name + '>', value)
        return text
    def read(name, *, json_value=True):
        if name not in evidence:
            raise ValueError('Privacy required retained evidence is absent: ' + name)
        text = restore(api.retained_observation(directory, name).read_bytes().decode('utf-8'))
        return _loads(text) if json_value else text
    for name in evidence:
        raw = api.retained_observation(directory, name).read_bytes()
        if any(value.encode() in raw for value in private.values()):
            raise ValueError('Privacy evidence contains an unredacted synthetic private input')
    rows = api.exact_case_rows(data, ['privacy.' + name for name in CASE_NAMES])
    for name in CASE_NAMES:
        if rows['privacy.' + name]['observed'] != _loads(api.retained_observation(directory, 'observations/' + name + '.json').read_text(encoding='utf-8')):
            raise ValueError('Privacy case observation differs from its retained observation')
    fixture = directory / 'fixture'
    vault, state = fixture / 'toolkit', fixture / 'gate-state'
    def native_path(path):
        separator = '\\' if '\\' in data['source_root'] else '/'
        suffix = separator.join(Path(path).relative_to(api.ROOT.absolute()).parts)
        return data['source_root'].rstrip('/\\') + separator + suffix
    native_pathsep = ';' if '\\' in data['source_root'] else ':'
    expectations = _literal('EXPECTED')
    if read('frozen-expectations.json') != {'producer': data['producer'], 'case_ids': list(CASE_NAMES), 'expected': expectations}:
        raise ValueError('Privacy frozen literal expectations differ')
    if any(rows['privacy.' + name].get('expected') != expectations[name] for name in CASE_NAMES):
        raise ValueError('Privacy case expected outcome differs from the frozen literal')
    before = read('toolkit.before.json')
    if {name: value.get('sha256') for name, value in before.items() if value.get('kind') == 'file'} != toolkit:
        raise ValueError('Privacy initial complete copied toolkit differs')
    for name, digest in toolkit.items():
        copied = api.retained_observation(vault, name)
        if copied.stat().st_nlink != 1 or api.sha(copied) != digest:
            raise ValueError('Privacy retained copied toolkit changed: ' + name)
    actual_sources = {p.relative_to(vault).as_posix() for base in ('knowledgeos', 'scripts', '.cursor/hooks')
                      for p in (vault / base).rglob('*.py') if '__pycache__' not in p.parts}
    expected_sources = {name for name in toolkit if Path(name).suffix == '.py' and name.startswith(('knowledgeos/', 'scripts/', '.cursor/hooks/'))}
    if actual_sources != expected_sources:
        raise ValueError('Privacy copied toolkit has missing or extra executable sources')
    if read('audit/sitecustomize.py', json_value=False) != _literal('AUDIT_SOURCE') or read('fixture_ops.py', json_value=False) != _literal('HELPER_SOURCE'):
        raise ValueError('Privacy generated instrumentation differs from current trusted producer')
    processes = data.get('processes')
    if not isinstance(processes, list) or not processes or data.get('all_started_processes_stopped') is not True:
        raise ValueError('Privacy process shutdown is incomplete')
    records = {}
    parent_pids = set()
    py = None
    for row in processes:
        if (not isinstance(row, dict) or not isinstance(row.get('role'), str) or not re.fullmatch('[a-z0-9_-]+', row['role'])
                or row['role'] in records or type(row.get('pid')) is not int or row['pid'] <= 0
                or type(row.get('exit_code')) is not int or row.get('stopped') is not True
                or type(row.get('started_ns')) is not int or type(row.get('finished_ns')) is not int
                or not 0 < row['started_ns'] < row['finished_ns'] or row.get('error') is not None or row.get('shell') is not False):
            raise ValueError('Privacy requires unique launch roles and typed stopped native processes')
        role = row['role']
        original = read(role + '.command.json')
        if _loads(restore(_encoded(row))) != original:
            raise ValueError('Privacy process record differs from original command evidence')
        command = original.get('command')
        if (not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command)
                or original.get('argv_sha256') != _digest(_encoded(command))
                or original.get('cwd') != native_path(vault) or original.get('vault') != native_path(vault)
                or original.get('state_dir') != native_path(state)
                or original.get('import_path') != native_pathsep.join((native_path(directory / 'audit'), native_path(vault)))
                or type(original.get('is_python')) is not bool):
            raise ValueError('Privacy source, vault, imports, state or argv binding differs')
        for suffix, field in (('.stdout.txt', 'stdout_sha256'), ('.stderr.txt', 'stderr_sha256')):
            if _digest(read(role + suffix, json_value=False)) != original.get(field):
                raise ValueError('Privacy original stdout/stderr hash differs after reversible redaction')
        if original['is_python']:
            py = py or command[0]
            if command[0] != py or command[1:3] != ['-B', '-P']:
                raise ValueError('Privacy Python interpreter command differs')
            trace_name = 'child-traces/' + role + '.' + str(row['pid']) + '.json'
            trace = read(trace_name)
            if (trace.get('role') != role or trace.get('pid') != row['pid'] or type(trace.get('parent_pid')) is not int
                    or trace['parent_pid'] <= 0 or trace.get('python') != py
                    or trace.get('knowledgeos_file') != (None if role == 'busy-holder' else native_path(vault / 'knowledgeos/__init__.py'))
                    or trace.get('counts') != {'credential_resolution': 0, 'publishing_http': 0, 'socket_connect': 0}
                    or not isinstance(trace.get('children'), list)):
                raise ValueError('Privacy import, credential/transport guard or child trace differs: ' + role)
            nested = trace['children']
            parent_pids.add(trace['parent_pid'])
            if role == 'native-drift':
                expected_git = ['git', '-c', 'core.quotePath=false', 'log', '--since=30.days.ago', '--name-only', '--pretty=format:']
                if len(nested) != 1 or nested[0].get('command') != expected_git or nested[0].get('argv_sha256') != _digest(_encoded(expected_git)):
                    raise ValueError('Privacy native Git diagnostic lacks its original real nested command')
            elif nested:
                raise ValueError('Privacy unexpected nested child is not a supported launch')
            for child in nested:
                if (type(child.get('pid')) is not int or child['pid'] <= 0 or child['pid'] == row['pid']
                        or child.get('stopped') is not True or child.get('cleanup_required') is not False
                        or type(child.get('exit_code')) is not int or child['exit_code'] != 0):
                    raise ValueError('Privacy nested child is unsafe or not stopped')
        records[role] = original
    if {name for name in evidence if name.endswith('.command.json')} != {role + '.command.json' for role in records}:
        raise ValueError('Privacy missing or untracked command evidence')
    expected_trace_names = {'child-traces/' + role + '.' + str(row['pid']) + '.json' for role, row in records.items() if row['is_python']}
    if {name for name in evidence if name.startswith('child-traces/')} != expected_trace_names:
        raise ValueError('Privacy complete direct trace inventory differs')
    if len(parent_pids) != 1 or parent_pids & {record['pid'] for record in records.values()}:
        raise ValueError('Privacy direct traces do not share a distinct actual producer parent')
    launches = list(records.values())
    for n, first in enumerate(launches):
        for second in launches[n + 1:]:
            if first['pid'] == second['pid'] and max(first['started_ns'], second['started_ns']) < min(first['finished_ns'], second['finished_ns']):
                raise ValueError('Privacy simultaneous actors claim a shared PID')
    isolation = data.get('isolation', {})
    if (not isinstance(isolation.get('before'), dict) or isolation['before'] != isolation.get('after')
            or isolation.get('selected_sentinels_unchanged') is not True
            or {api.data_repository_location(name) for name in isolation['before']} != {'People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json'}
            or any(value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)) for value in isolation['before'].values())):
        raise ValueError('Privacy selected real-vault isolation sentinels are missing or changed')
    actual_rpc = {}
    for name in evidence:
        if not name.endswith('.requests.json'):
            continue
        role = name.removesuffix('.requests.json')
        messages = read(name)
        responses = [_loads(line) for line in read(role + '.stdout.txt', json_value=False).splitlines() if line.strip()]
        if (records[role]['command'] != [py, '-B', '-P', '-m', 'knowledgeos', 'mcp', '--vault', native_path(vault), '--framing', 'ndjson']
                or records[role]['exit_code'] != 0 or not isinstance(messages, list) or len(messages) < 3
                or messages[:2] != [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05',
                    'capabilities': {}, 'clientInfo': {'name': 'verify-twinaatma-privacy', 'version': '1'}}}, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
                or records[role].get('stdin_sha256') != _digest(''.join(_encoded(row) + '\n' for row in messages))
                or len(responses) != len(messages) - 1 or responses[0].get('result', {}).get('serverInfo', {}).get('name') != 'knowledgeos-memory'):
            raise ValueError('Privacy original public MCP protocol identity differs')
        calls, results = [], []
        for number, (request, response) in enumerate(zip(messages[2:], responses[1:]), 2):
            params, value = request.get('params', {}), response.get('result', {})
            content = value.get('content')
            if (set(request) != {'jsonrpc', 'id', 'method', 'params'} or request.get('jsonrpc') != '2.0'
                    or request.get('id') != number or request.get('method') != 'tools/call'
                    or set(params) != {'name', 'arguments'} or not isinstance(params.get('arguments'), dict)
                    or response.get('jsonrpc') != '2.0' or response.get('id') != number or 'error' in response
                    or type(value.get('isError')) is not bool or not isinstance(content, list) or len(content) != 1
                    or content[0].get('type') != 'text' or not isinstance(content[0].get('text'), str)):
                raise ValueError('Privacy original request/response schema differs')
            calls.append((params['name'], params['arguments']))
            results.append({'payload': _loads(content[0]['text']), 'is_error': value['isError']})
        if read(role + '.results.json') != results or read(role + '.wire-hashes.json') != {
                'requests': [_digest(_encoded(row)) for row in messages], 'responses': [_digest(_encoded(row)) for row in responses]}:
            raise ValueError('Privacy derived payloads or original wire hashes differ')
        actual_rpc[role] = (calls, results)
    def rpc(role, calls):
        if role not in actual_rpc or actual_rpc[role][0] != calls:
            raise ValueError('Privacy literal public call matrix differs: ' + role)
        return actual_rpc[role][1]
    def cli(role, tool, arguments):
        record = records.get(role, {})
        if (record.get('command') != [py, '-B', '-P', '-m', 'knowledgeos', 'memory', tool, '--vault', native_path(vault), '--args', _encoded(arguments)]
                or record.get('stdin_sha256') != _digest(b'')):
            raise ValueError('Privacy literal public CLI differs: ' + role)
        return {'payload': _loads(read(role + '.stdout.txt', json_value=False)), 'is_error': record['exit_code'] != 0}
    def source(relative):
        return api.retained_observation(vault, relative)
    def denied(result):
        payload = result.get('payload')
        return (result.get('is_error') is True and isinstance(payload, dict) and payload.get('ok') is False
                and isinstance(payload.get('error'), str) and bool(payload['error'])
                and not any(secret in _encoded(payload) for secret in private.values()))
    def no_private(value):
        return not any(secret in _encoded(value) for secret in private.values())
    def success(result):
        return result.get('is_error') is False and result.get('payload', {}).get('ok') is True
    def capture_path(result, literal):
        path = result.get('payload', {}).get('path')
        if not isinstance(path, str) or not re.fullmatch(r'Inbox/[^/\\:]+\.md', path):
            raise ValueError('Privacy capture lacks a contained original source path')
        if literal not in source(path).read_text(encoding='utf-8'):
            raise ValueError('Privacy captured source lacks its literal fact')
        return path
    checks = {}
    def case(name, valid):
        checks[name] = api.verified_case(rows['privacy.' + name], bool(valid))
    if api.sha(api.retained_observation(directory, 'policy.json')) != POLICY_DIGEST or api.sha(api.retained_observation(directory, 'human-approval-source.jsonl')) != APPROVAL_DIGEST:
        raise ValueError('Privacy approved policy or independent human provenance differs')
    approval, provenance = read('human-approval-source.jsonl'), read('human-approval-provenance.json')
    text = approval.get('payload', {}).get('content', [{}])[0].get('text', '')
    match = re.fullmatch(r'<send_user_message_question_reply>\n(.*)\n</send_user_message_question_reply>\n', text, re.S)
    answer = _loads(match[1]) if match else []
    if (approval.get('type') != 'response_item' or approval.get('payload', {}).get('role') != 'user' or len(answer) != 1
            or provenance.get('schema') != 'twinaatma.direct-human-policy-approval/v1'
            or provenance.get('source_role') != 'user' or provenance.get('source_line_sha256') != APPROVAL_DIGEST
            or provenance.get('policy_sha256') != POLICY_DIGEST or provenance.get('answer') != 'Yes, implement this policy'
            or answer[0] != {'questionItemId': provenance.get('question_item_id'), 'question': provenance.get('question'), 'answer': provenance.get('answer')}
            or provenance.get('source_kind') != 'native_session_response_item'
            or type(provenance.get('source_line')) is not int or provenance['source_line'] <= 0
            or type(provenance.get('source_byte_offset')) is not int or provenance['source_byte_offset'] < 0
            or provenance.get('source_bytes') != api.retained_observation(directory, 'human-approval-source.jsonl').stat().st_size
            or provenance.get('timestamp') != approval.get('timestamp') or not isinstance(provenance.get('source_session'), str)):
        raise ValueError('Privacy independent human approval source or literal answer provenance is incomplete')
    case('human_policy', True)
    expected_init = [py, '-B', '-P', '-m', 'knowledgeos', 'init', native_path(vault), '--name', 'Synthetic Privacy Owner', '--non-interactive', '--force']
    expected_doctor = [py, '-B', '-P', '-m', 'knowledgeos', 'doctor', '--vault', native_path(vault)]
    initialized = _loads(read('init.stdout.txt', json_value=False))
    if records['init']['command'] != expected_init or records['doctor']['command'] != expected_doctor:
        raise ValueError('Privacy native setup command differs')
    case('native_setup', records['init']['exit_code'] == records['doctor']['exit_code'] == 0 and isinstance(initialized.get('post_init'), dict)
        and set(initialized['post_init']) >= {'rebuild', 'validate'} and all(row.get('ok') is True for row in initialized['post_init'].values()))
    if not checks['native_setup']:
        raise ValueError('Privacy native setup prerequisite failed')
    captures = rpc('capture-ordinary', [('memory_capture', {'title': 'Rill contextual preference', 'content': ORDINARY, 'request_id': 'privacy-rill-review'}),
        ('memory_capture', {'title': 'Rill collaboration', 'content': BENIGN})])
    original = capture_path(captures[0], ORDINARY)
    benign_path = capture_path(captures[1], BENIGN)
    original_sha = api.sha(source(original))
    retained = rpc('retention-restart', [('memory_get_note', {'path_or_id': original}),
        ('memory_get_note', {'path_or_id': benign_path}), ('memory_search', {'query': 'Rill'})])
    case('ordinary_retention', all(success(row) for row in captures) and ORDINARY in _encoded(retained) and BENIGN in _encoded(retained)
        and retained[0]['payload'].get('sha256') == original_sha)
    credential_calls = [('memory_capture', {'title': private['credential0'], 'content': 'Service title'}),
        ('memory_capture', {'title': 'Service', 'content': 'API key: ' + private['credential1']}),
        ('memory_capture', {'title': 'Service', 'content': 'Routine note', 'tags': [private['credential2']]}),
        ('memory_session_start', {'task_hint': 'Bearer ' + private['credential3'], 'session_id': 'private-hint'}),
        ('memory_session_end', {'summary': 'API key: ' + private['credential4'], 'session_id': 'private-summary'})]
    credential_results = rpc('credential-surfaces', credential_calls)
    case('credential_rpc', all(denied(row) for row in credential_results) and no_private(credential_results))
    result = cli('credential-cli', 'memory_capture', {'title': 'Private CLI', 'content': 'API key: ' + private['credential5']})
    case('credential_cli', denied(result) and no_private(result))
    result = rpc('metadata', [('memory_capture', {'title': 'Opaque excluded record', 'content': 'Opaque fixture detail.', 'privacy': label})
                             for label in ('exclude', 'credential', 'sensitive-third-party')])
    case('explicit_metadata', all(denied(row) for row in result))
    result = rpc('third-patterns', [('memory_capture', {'title': 'Sensitive third-party detail', 'content': private['third' + str(n)]}) for n in range(3)])
    case('third_party_patterns', all(denied(row) for row in result) and no_private(result))
    semantic = rpc('third-semantic', [('memory_capture', {'title': 'Colleague private clinical detail', 'content': private['semantic']})])[0]
    case('third_party_semantic', denied(semantic) and no_private(semantic))
    def views(role, relative):
        return rpc(role, [('memory_get_note', {'path_or_id': relative}), ('memory_search', {'query': 'Rill'}),
            ('memory_bootstrap_context', {'task_hint': 'Rill'}), ('memory_decisions', {}), ('memory_timeline', {'days': 3650}),
            ('memory_pending_outcomes', {}), ('memory_related', {'path_or_id': relative})])
    legacy = views('legacy-views', 'Decisions/LegacySensitive.md')
    metadata = rpc('legacy-metadata', [('memory_get_note', {'path_or_id': 'Concepts/ExplicitExcluded.md'})])
    case('legacy_admission', denied(legacy[0]) and denied(metadata[0]) and no_private(legacy))
    busy = views('busy-views', 'Decisions/LegacySensitive.md')
    ready, holder = read('busy-ready.json'), records['busy-holder']
    if (holder['command'] != [py, '-B', '-P', native_path(directory / 'fixture_ops.py'), 'holder', native_path(vault)]
            or ready != {'ready': True, 'pid': holder['pid'], 'path': native_path(vault / 'knowledge_index.db')}
            or not holder['started_ns'] < records['busy-views']['started_ns'] < records['busy-views']['finished_ns'] < holder['finished_ns']
            or holder['pid'] == records['busy-views']['pid']):
        raise ValueError('Privacy busy observation lacks its actual native holder')
    if read('busy-holder.stdout.txt', json_value=False).strip() != _encoded(ready):
        raise ValueError('Privacy actual holder readiness bytes differ')
    forged = read('forged-cache.json')
    if forged != {'path': 'Decisions/LegacySensitive.md', 'title': private['legacy'], 'body': 'Rill ' + private['legacy'],
                  'database_sha256': api.sha(api.retained_observation(directory, 'private-forged-cache.db'))}:
        raise ValueError('Privacy literal forged cache setup differs')
    cache = api.retained_observation(directory, 'private-forged-cache.db')
    connection = sqlite3.connect(cache.as_uri() + '?mode=ro', uri=True)
    try:
        row = connection.execute('SELECT title,tags,project,status FROM notes WHERE path=?', ('Decisions/LegacySensitive.md',)).fetchone()
        fts = connection.execute('SELECT title,body,tags,description FROM notes_fts WHERE path=?', ('Decisions/LegacySensitive.md',)).fetchall()
    finally:
        connection.close()
    if row != (private['legacy'], private['legacy'], 'Rill', 'active') or (private['legacy'], 'Rill ' + private['legacy'], private['legacy'], private['legacy']) not in fts:
        raise ValueError('Privacy literal forged database rows lack retained independent bytes')
    case('forged_busy_cache', denied(busy[0]) and no_private(busy) and rows['privacy.forged_busy_cache']['observed'].get('native_holder_alive_during') is True)
    def scan(observation, *, extra=()):
        if not isinstance(observation, dict) or not isinstance(observation.get('files'), dict) or not isinstance(observation.get('exposures'), list):
            raise ValueError('Privacy filesystem scan schema differs')
        exposures = []
        for name, metadata in observation['files'].items():
            raw = source(name).read_bytes()
            if metadata != {'sha256': _digest(raw), 'size': len(raw)}:
                raise ValueError('Privacy retained filesystem scan differs from physical bytes')
            exposures.extend({'path': name, 'canary': key} for key, value in private.items() if value.encode() in raw)
            exposures.extend({'path': name, 'literal': n} for n, value in enumerate(extra) if value.encode() in raw)
        if observation['exposures'] != exposures:
            raise ValueError('Privacy exposure claims differ from retained output bytes')
        return not exposures
    generated_valid = True
    for n, script in enumerate(('weekly_data.py', 'intelligence_brief.py', 'experiment_dashboard.py', 'outcomes_dashboard.py', 'draft_weekly_synthesis.py')):
        role = 'generated-' + str(n)
        if records[role]['command'] != [py, '-B', '-P', native_path(vault / 'scripts' / script)]:
            raise ValueError('Privacy generated-output writer inventory differs')
        generated_valid &= records[role]['exit_code'] == 0 and no_private(read(role + '.stdout.txt', json_value=False) + read(role + '.stderr.txt', json_value=False))
    case('generated_outputs', generated_valid and scan(read('observations/generated_outputs.json')))
    correction_sources = rpc('correction-sources', [('memory_capture', {'title': 'Rill prior release', 'content': PRIOR}), ('memory_capture', {'title': 'Rill current release', 'content': CURRENT})])
    prior, current_path = capture_path(correction_sources[0], PRIOR), capture_path(correction_sources[1], CURRENT)
    prior_sha, current_sha = api.sha(source(prior)), api.sha(source(current_path))
    correction = {'path_or_id': prior, 'expected_sha256': prior_sha, 'replacement_path_or_id': current_path, 'replacement_sha256': current_sha}
    stale = rpc('correction-stale', [('memory_supersede', dict(correction, expected_sha256='0' * 64))])[0]
    case('correction_stale_hash', denied(stale))
    corrected = rpc('correction', [('memory_get_note', {'path_or_id': prior}), ('memory_get_note', {'path_or_id': current_path}), ('memory_supersede', correction)])
    historical = rpc('correction-restart', [('memory_get_note', {'path_or_id': prior}), ('memory_search', {'query': 'Rill release'})])
    case('reviewed_correction', corrected[0]['payload'].get('sha256') == prior_sha and corrected[1]['payload'].get('sha256') == current_sha
        and success(corrected[2]) and historical[0]['payload'].get('memory_status') == 'historical' and historical[0]['payload'].get('superseded_by') == current_path
        and prior not in [row.get('path') for row in historical[1]['payload'].get('ranked', [])] and CURRENT in _encoded(historical[1]))
    rpc('before-forget-session', [('memory_session_start', {'task_hint': ORDINARY, 'session_id': 'forget-session'})])
    stale = rpc('forget-stale', [('memory_forget', {'path_or_id': original, 'expected_sha256': '0' * 64})])[0]
    case('forget_stale_hash', denied(stale))
    forget_args = {'path_or_id': original, 'expected_sha256': original_sha}
    forgotten = rpc('forget', [('memory_forget', forget_args)])[0]
    case('reviewed_forgetting', success(forgotten))
    forgotten_views = views('after-forget', original)
    retries = rpc('forget-retries', [('memory_get_note', {'path_or_id': 'Projects/CopiedMemory.md'}), ('memory_forget', forget_args),
        ('memory_capture', {'title': 'Recapture under another title', 'content': ORDINARY, 'request_id': 'privacy-rill-review'})])
    case('forget_replay_restart_copy', ORDINARY not in _encoded(forgotten_views + retries) and denied(forgotten_views[0]) and denied(retries[0])
        and success(retries[1]) and denied(retries[2]) and source('Projects/CopiedMemory.md').read_bytes() == source(original).read_bytes())
    session_path = source('.knowledgeos/autopilot.json')
    session_observed = read('observations/forget_session_state.json')
    if (session_observed.get('state') != '.knowledgeos/autopilot.json'
            or not isinstance(session_observed.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', session_observed['sha256'])):
        raise ValueError('Privacy phase session-state observation is malformed')
    case('forget_session_state', ORDINARY.encode() not in session_path.read_bytes() and session_observed.get('forbidden_literal_present') is False)
    concurrent_sources = rpc('concurrent-sources', [('memory_capture', {'title': 'Independent Rill source ' + str(n),
        'content': 'Rill independent review number ' + str(n) + ' uses an isolated record.'}) for n in range(4)])
    concurrent_paths = [capture_path(result, 'Rill independent review number ' + str(n) + ' uses an isolated record.') for n, result in enumerate(concurrent_sources)]
    live = read('concurrent-live.json')
    if (len(live) != 4 or live != [{'role': 'concurrent-' + str(n), 'pid': records['concurrent-' + str(n)]['pid'], 'alive': True} for n in range(4)]
            or len({row['pid'] for row in live}) != 4):
        raise ValueError('Privacy native concurrent actors are missing or share PIDs')
    concurrent_valid = True
    visible_retryable = []
    for n, relative in enumerate(concurrent_paths):
        result = cli('concurrent-' + str(n), 'memory_forget', {'path_or_id': relative, 'expected_sha256': api.sha(source(relative))})
        partial = (result['is_error'] is True and result['payload'] == {'ok': False,
            'error': 'Forgetting is durable; session-state scrubbing needs a retry.', 'forgotten': True, 'source_preserved': True, 'retryable': True})
        concurrent_valid &= success(result) or partial
        if partial:
            visible_retryable.append(n)
        retried = cli('concurrent-retry-' + str(n), 'memory_forget', {'path_or_id': relative, 'expected_sha256': api.sha(source(relative))})
        concurrent_valid &= success(retried)
    concurrent_reads = rpc('concurrent-restart', [('memory_get_note', {'path_or_id': relative}) for relative in concurrent_paths])
    case('concurrent_forgetting', concurrent_valid and all(denied(row) for row in concurrent_reads)
        and rows['privacy.concurrent_forgetting']['observed'].get('initial_visible_retryable_failures') == visible_retryable)
    if records['export']['command'] != [py, '-B', '-P', native_path(vault / 'scripts/export_bundle.py'), '--paths', 'Inbox', 'Projects', 'Decisions', '--out', 'Bundles/review']:
        raise ValueError('Privacy export public selector or output differs')
    bundle_scan = read('observations/export_scope.json')
    bundle_files = {p.relative_to(vault).as_posix() for p in (vault / 'Bundles/review').rglob('*') if p.is_file()}
    if set(bundle_scan['files']) != bundle_files:
        raise ValueError('Privacy complete bundle scan omits retained members')
    manifest = _loads(source('Bundles/review/manifest.json').read_text(encoding='utf-8'))
    attribution = {row['path']: row for row in manifest.get('notes', [])}
    historical_entry, current_entry = attribution.get(prior, {}), attribution.get(current_path, {})
    case('export_scope', records['export']['exit_code'] == 0 and bool(bundle_files) and scan(bundle_scan, extra=(ORDINARY,))
        and any(CURRENT.encode() in source(name).read_bytes() for name in bundle_files)
        and historical_entry.get('memory_status') == 'historical' and historical_entry.get('superseded_by') == current_path
        and historical_entry.get('reviewed_sha256') == prior_sha and current_entry.get('memory_status') == 'current')
    baseline = read('state-baseline.json')
    local_target = 'toolkit/.knowledgeos/remembering-policy.json'
    authorities = [name for name in baseline if name.startswith('gate-state/vaults/') and name.endswith('/remembering-policy.json')]
    if set(baseline) != {local_target, 'gate-state/gate.key', *authorities} or len(authorities) != 1:
        raise ValueError('Privacy signed authority/key baseline inventory differs')
    for name in STATE_NAMES:
        mutation = read('mutations/' + name + '.json')
        wanted_target = authorities[0] if 'authority' in name else 'gate-state/gate.key' if 'key' in name else local_target
        if (mutation.get('target') != wanted_target or mutation.get('native_error') is not None
                or mutation.get('before_sha256') != baseline[wanted_target].get('sha256')
                or mutation.get('backup_sha256') != baseline[wanted_target].get('sha256')):
            raise ValueError('Privacy native state mutation lacks its exact baseline and target')
        kind = 'missing' if name.startswith('deleted_') else 'link' if name.startswith('linked_') else 'file'
        if mutation.get('kind') != kind or name.startswith('hardlinked_') and mutation.get('links') != 2:
            raise ValueError('Privacy native link/deletion mutation differs')
        snapshot = directory / 'private-mutated-state' / name
        if kind == 'missing':
            if snapshot.exists() or snapshot.is_symlink():
                raise ValueError('Privacy deleted-state snapshot unexpectedly exists')
        elif kind == 'link':
            if api.data_repository_location(native_link_target(snapshot)) != api.data_repository_location(native_path(directory / 'private-state-backups' / name)):
                raise ValueError('Privacy native linked-state snapshot differs')
        else:
            actual = api.retained_observation(directory, 'private-mutated-state/' + name)
            if 'key' not in name and actual.read_text(encoding='utf-8') != mutation.get('body'):
                raise ValueError('Privacy original mutation bytes differ from recorded intervention')
            if name == 'tampered_key' and actual.read_bytes() != b'42' * 32:
                raise ValueError('Privacy private key tamper input differs')
        body = mutation.get('body')
        if name == 'malformed_local' and body != '{"version":1,"forgotten":[],"superseded":{}}':
            raise ValueError('Privacy malformed local control differs')
        if name == 'duplicate_local' and body != '{"version":1,"forgotten":{},"forgotten":{},"superseded":{}}':
            raise ValueError('Privacy duplicate-key control differs')
        if name.startswith('valid_'):
            wanted = {'version': 1, 'forgotten': {}, 'superseded': {}}
            if name == 'valid_replacement_local':
                wanted['superseded'][original] = {'sha256': original_sha, 'recorded_at': '2026-10-19T00:00:00+00:00', 'replacement': current_path, 'replacement_sha256': current_sha}
            if _loads(body) != wanted:
                raise ValueError('Privacy syntactically valid rewritten policy differs')
        result = rpc('state-' + name, [('memory_get_note', {'path_or_id': original}), ('memory_get_note', {'path_or_id': prior}), ('memory_search', {'query': 'Rill'})])
        case(name, denied(result[0]) and ORDINARY not in _encoded(result) and original not in _encoded(result[2])
            and (result[1]['payload'].get('memory_status') == 'historical' if name == 'deleted_local' else denied(result[1])))
    outside = api.retained_observation(fixture, 'outside/Outsider.md')
    if outside.read_bytes() != b'# Outside source\nOutside private fixture evidence must stay outside memory.\n':
        raise ValueError('Privacy outside-alias source differs')
    alias_targets = {'Permitted': vault / current_path, 'Excluded': vault / 'Decisions/LegacySensitive.md',
        'Forgotten': vault / original, 'Self': vault / 'People/Self.md', 'Outside': outside}
    aliases = {name: 'Projects/Alias' + name + '.md' for name in alias_targets}
    alias_setup = {'aliases': {aliases[name]: native_path(target) for name, target in alias_targets.items()},
                   'target_hashes': {native_path(target): api.sha(target) for target in alias_targets.values()}}
    if read('linked-source-setup.json') != alias_setup:
        raise ValueError('Privacy native alias setup or preserved source hashes differ')
    for name, target in alias_targets.items():
        retained = directory / 'private-linked-sources' / (name + '.md')
        if api.data_repository_location(native_link_target(retained)) != api.data_repository_location(native_path(target)):
            raise ValueError('Privacy native alias link is missing or changed')
    linked = rpc('linked-source-read', [('memory_get_note', {'path_or_id': path}) for path in aliases.values()])
    self_sha = api.sha(alias_targets['Self'])
    protected_reads = rpc('linked-source-protected', [('memory_forget', {'path_or_id': aliases['Self'], 'expected_sha256': self_sha}),
        ('memory_supersede', {'path_or_id': aliases['Self'], 'expected_sha256': self_sha,
            'replacement_path_or_id': current_path, 'replacement_sha256': current_sha})])
    outside_reads = rpc('linked-source-outside', [('memory_forget', {'path_or_id': aliases['Outside'], 'expected_sha256': api.sha(outside)}),
        ('memory_supersede', {'path_or_id': aliases['Outside'], 'expected_sha256': api.sha(outside),
            'replacement_path_or_id': current_path, 'replacement_sha256': current_sha})])
    canonical_forget = rpc('linked-source-forget-canonical', [('memory_forget', {'path_or_id': current_path, 'expected_sha256': current_sha})])[0]
    generic_refusal = lambda row: row['is_error'] is True and bool(row['payload'].get('error'))
    case('linked_source', linked[0]['is_error'] is False and linked[0]['payload'].get('path') == current_path
        and linked[0]['payload'].get('sha256') == current_sha and denied(linked[1]) and denied(linked[2])
        and linked[3]['payload'].get('path') == 'People/Self.md' and generic_refusal(linked[4])
        and all(generic_refusal(row) for row in protected_reads + outside_reads) and success(canonical_forget)
        and no_private(linked + protected_reads + outside_reads) and rows['privacy.linked_source']['observed'].get('sources_preserved') is True)
    fault_source = rpc('fault-source', [('memory_capture', {'title': 'Rill fault source', 'content': 'Rill publication retry uses a reversible synthetic checkpoint.'})])[0]
    fault_path = capture_path(fault_source, 'Rill publication retry uses a reversible synthetic checkpoint.')
    fault_args = {'path_or_id': fault_path, 'expected_sha256': api.sha(source(fault_path))}
    failed, retry = cli('fault-forget', 'memory_forget', fault_args), cli('fault-retry', 'memory_forget', fault_args)
    fault_read = rpc('fault-restart', [('memory_get_note', {'path_or_id': fault_path})])[0]
    case('publication_failure_retry', denied(failed) and success(retry) and denied(fault_read))
    if records['legacy-proposal']['command'] != [py, '-B', '-P', native_path(directory / 'fixture_ops.py'), 'legacy-proposal', native_path(vault), '--token', private['diagnostic']]:
        raise ValueError('Privacy signed legacy proposal fixture setup differs')
    proposal = rpc('ordinary-proposal', [('memory_propose_self_update', {'summary': 'Rill review cadence', 'section': 'heuristics',
        'proposed_markdown': '* Prefer concise Rill reviews.', 'mode': 'append'})])[0]
    if records['pending']['command'] != [py, '-B', '-P', '-m', 'knowledgeos', 'self', 'pending', '--vault', native_path(vault)]:
        raise ValueError('Privacy native pending diagnostic command differs')
    pending_output = read('pending.stdout.txt', json_value=False) + read('pending.stderr.txt', json_value=False)
    case('native_pending_diagnostic', records['legacy-proposal']['exit_code'] == records['pending']['exit_code'] == 0 and no_private(pending_output)
        and success(proposal) and isinstance(proposal['payload'].get('proposal_path'), str) and proposal['payload']['proposal_path'] in pending_output)
    git_commands = {
        'git-init': ['git', 'init', '--quiet', native_path(vault)],
        'git-add': ['git', '-C', native_path(vault), 'add', '--', 'Concepts/PermittedActivity.md', 'Concepts/PrivateActivity-' + private['diagnostic'] + '.md'],
        'git-commit': ['git', '-C', native_path(vault), '-c', 'user.name=Synthetic Privacy', '-c', 'user.email=synthetic@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Synthetic diagnostic fixture'],
        'native-drift': [py, '-B', '-P', native_path(vault / 'scripts/semantic_drift.py')]}
    if any(records[role]['command'] != command for role, command in git_commands.items()):
        raise ValueError('Privacy genuine Git setup or diagnostic commands differ')
    drift_output = read('native-drift.stdout.txt', json_value=False) + read('native-drift.stderr.txt', json_value=False)
    case('native_git_diagnostic', all(records[role]['exit_code'] == 0 for role in git_commands)
        and 'Concepts/PermittedActivity.md' in drift_output and no_private(drift_output) and 'not evidence of changed beliefs' in drift_output)
    dry_runs = (
        ('publisher_dry_run', 'publisher', 'publish_to_notion.py', ['--dry-run', 'Concepts/Publishable.md'], 0, 'DRY RUN: Would publish'),
        ('publisher_all_dry_run', 'publisher-all', 'publish_to_notion.py', ['--dry-run', '--all'], 0, 'DRY RUN: Would publish'),
        ('bridge_setup_dry_run', 'bridge-setup', 'notion_bridge.py', ['--dry-run', 'setup'], 0, 'DRY RUN: Would ensure'),
        ('bridge_publish_dry_run', 'bridge-publish', 'notion_bridge.py', ['--dry-run', 'publish', 'Concepts/Publishable.md'], 0, 'DRY RUN: Would publish'),
        ('bridge_unscoped_json', 'bridge-json', 'notion_bridge.py', ['--dry-run', 'publish', '{"title":"Unscoped synthetic input"}'], 1, 'Unscoped JSON publishing is unsupported'))
    for name, role, script, args, exit_code, message in dry_runs:
        if records[role]['command'] != [py, '-B', '-P', native_path(vault / 'scripts' / script), *args]:
            raise ValueError('Privacy literal publisher/bridge dry-run surface differs')
        output = read(role + '.stdout.txt', json_value=False) + read(role + '.stderr.txt', json_value=False)
        case(name, records[role]['exit_code'] == exit_code and message in output and no_private(output))
    protected = read('protected-sources.json')
    if not isinstance(protected, dict) or 'People/Self.md' not in protected or original not in protected or prior not in protected or current_path not in protected:
        raise ValueError('Privacy protected source/Self inventory is incomplete')
    changed = [name for name, digest in protected.items() if api.sha(source(name)) != digest]
    case('source_and_identity_preservation', not changed and rows['privacy.source_and_identity_preservation']['observed'] == {
        'unexpected_changed_sources': [], 'unexpected_changed_toolkit': []})
    case('redacted_evidence', rows['privacy.redacted_evidence']['observed'] == {'unredacted_evidence_files': []})
    case('transport_scope', rows['privacy.transport_scope']['observed'] == {'counts': {'credential_resolution': 0, 'publishing_http': 0, 'socket_connect': 0}})
    expected_roles = {'init', 'doctor', 'busy-holder', 'credential-cli', *actual_rpc,
        *['generated-' + str(n) for n in range(5)], *['concurrent-' + str(n) for n in range(4)],
        *['concurrent-retry-' + str(n) for n in range(4)], 'export', 'fault-forget', 'fault-retry',
        'legacy-proposal', 'pending', *git_commands, *[row[1] for row in dry_runs]}
    if set(records) != expected_roles or set(actual_rpc) != {
            'capture-ordinary', 'retention-restart', 'credential-surfaces', 'metadata', 'third-patterns', 'third-semantic', 'legacy-views', 'legacy-metadata',
            'busy-views', 'correction-sources', 'correction-stale', 'correction', 'correction-restart', 'before-forget-session', 'forget-stale', 'forget', 'after-forget',
            'forget-retries', 'concurrent-sources', 'concurrent-restart', *['state-' + name for name in STATE_NAMES],
            'linked-source-read', 'linked-source-protected', 'linked-source-outside', 'linked-source-forget-canonical', 'fault-source', 'fault-restart', 'ordinary-proposal'}:
        raise ValueError('Privacy complete command/public RPC matrix is missing or unknown')
    if set(checks) != set(CASE_NAMES) or data['verdict'] != ('PASS' if all(checks.values()) else 'FAIL'):
        raise ValueError('Privacy complete aggregate contradicts independently recomputed cases')
    external_names = ('native_setup', 'source_and_identity_preservation', 'redacted_evidence', 'transport_scope',
        'publisher_dry_run', 'publisher_all_dry_run', 'bridge_setup_dry_run', 'bridge_publish_dry_run', 'bridge_unscoped_json')
    exposure_names = tuple(name for name in CASE_NAMES if name != 'human_policy')
    policy_names = CASE_NAMES
    result = []
    for scope, selected in (('policy', {'PRIVACY.explicit_policy': policy_names}),
            ('source', {'PRIVACY.exposure_scope': exposure_names, 'PRIVACY.external_writes': external_names})):
        aggregates = {}
        for outcome, names in selected.items():
            identifier = ELIGIBLE[outcome][1]
            aggregates[identifier] = {'id': identifier, 'verdict': 'PASS' if all(checks[name] for name in names) else 'FAIL',
                'observed': {name: checks[name] for name in names}}
        result.append({'path': str(path), 'report_sha256': api.sha(path), 'scope': scope, 'producer': data['producer'],
            'producer_sha256': data['producer_sha256'], 'support_sha256': support, 'privacy_adapter_sha256': api.sha(__file__),
            'evidence_files': evidence, 'independent_final_session_sha256': api.sha(session_path), 'checks': aggregates})
    return result
