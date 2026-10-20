"""Retain redacted public-source privacy observations against a complete toolkit copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import traceback
import uuid

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "knowledgeos/memory.py").is_file())
SUPPORT = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SUPPORT))
from data_preservation import checked_output, inventory, sha, source_files

PRODUCER = "verify-twinaatma.privacy-source/v1"
CASE_IDS = (
    "human_policy", "native_setup", "ordinary_retention", "credential_rpc", "credential_cli",
    "explicit_metadata", "third_party_patterns", "third_party_semantic", "legacy_admission",
    "forged_busy_cache", "generated_outputs", "correction_stale_hash", "reviewed_correction",
    "forget_stale_hash", "reviewed_forgetting", "forget_replay_restart_copy", "forget_session_state",
    "concurrent_forgetting", "export_scope", "malformed_local", "duplicate_local", "valid_empty_local",
    "valid_replacement_local", "deleted_local", "linked_local", "hardlinked_local", "tampered_authority",
    "deleted_authority", "tampered_key", "deleted_key", "linked_authority", "hardlinked_authority",
    "linked_source", "publication_failure_retry", "native_pending_diagnostic", "native_git_diagnostic",
    "publisher_dry_run", "publisher_all_dry_run", "bridge_setup_dry_run", "bridge_publish_dry_run",
    "bridge_unscoped_json", "source_and_identity_preservation", "redacted_evidence", "transport_scope")
ORDINARY = "Rill planning reviews happen every second Thursday morning."
CURRENT = "Rill release reviews happen on Friday."
PRIOR = "Rill release reviews happen on Tuesday."
BENIGN = "Mira reviews Rill release plans with me."
POLICY_SHA256 = "cbec26e0349f5615c6895cde5be81e13b917895982d75827dc94b3f6cd3901d5"
APPROVAL_SHA256 = "934bdc4fa93728537c93ab9259a322fe27ce685072c07a29a0871ca520421791"
EXPECTED = {
    'human_policy': 'Exact human user-role question and approval authorize the fixed remembering policy.',
    'native_setup': 'Supported complete-copy init --force and doctor both succeed with truthful post-init checks.',
    'ordinary_retention': 'Ordinary project preference and benign collaboration retain exact bodies and source hashes after restart.',
    'credential_rpc': 'Credential title, body, tags, task hint and summary all return sanitized protocol refusals.',
    'credential_cli': 'Credential CLI capture exits nonzero and releases no private input.',
    'explicit_metadata': 'All three explicit exclusion labels refuse ordinary-looking capture.',
    'third_party_patterns': 'All three sensitive third-party categories refuse capture.',
    'third_party_semantic': 'Indirect sensitive third-party clinical meaning refuses capture without operator metadata.',
    'legacy_admission': 'Legacy credential and excluded-metadata sources never enter public current views.',
    'forged_busy_cache': 'A real busy SQLite holder and forged sensitive cache cannot release excluded source data.',
    'generated_outputs': 'All five supported generated-output paths release policy-permitted bytes only.',
    'correction_stale_hash': 'A stale reviewed hash refuses correction without rewriting sources.',
    'reviewed_correction': 'Two exact reviewed hashes bind correction; prior read is historical and current recall uses replacement.',
    'forget_stale_hash': 'A stale reviewed hash refuses forgetting without rewriting sources.',
    'reviewed_forgetting': 'The exact reviewed source is explicitly forgotten while source bytes survive.',
    'forget_replay_restart_copy': 'Restart, exact copy and request retry cannot revive or recapture a forgotten literal.',
    'forget_session_state': 'Persisted session state contains no forgotten literal.',
    'concurrent_forgetting': 'Four simultaneous distinct native actors merge all exclusions and preserve prior exclusions.',
    'export_scope': 'Export omits credentials and forgotten literals and retains exact historical/current manifest attribution.',
    'malformed_local': 'Malformed signed-policy mirror refuses release and preserves inputs.',
    'duplicate_local': 'Duplicate-key mirror refuses release and preserves inputs.',
    'valid_empty_local': 'A syntactically valid empty rewrite cannot remove authenticated exclusions.',
    'valid_replacement_local': 'A syntactically valid replacement cannot remove authenticated exclusions.',
    'deleted_local': 'Missing local mirror recovers exclusions and historical correction from off-vault signed authority.',
    'linked_local': 'A real linked local mirror refuses release.',
    'hardlinked_local': 'A real hardlinked local mirror refuses release.',
    'tampered_authority': 'Changed authenticated state refuses release.',
    'deleted_authority': 'Missing off-vault authority cannot fall back to a signed local mirror.',
    'tampered_key': 'Changed signing key refuses release.',
    'deleted_key': 'Missing signing key refuses release.',
    'linked_authority': 'A real linked off-vault authority refuses release.',
    'hardlinked_authority': 'A real hardlinked off-vault authority refuses release.',
    'linked_source': 'Contained permitted alias reveals its exact canonical source; excluded, protected and outside aliases preserve all sources and cannot bypass policy.',
    'publication_failure_retry': 'Interrupted mirror publication returns failure; retry converges and forgotten source stays excluded.',
    'native_pending_diagnostic': 'Native pending CLI retains an ordinary draft and omits a signed legacy sensitive draft.',
    'native_git_diagnostic': 'Real local Git activity shows the permitted current source and excludes private activity paths.',
    'publisher_dry_run': 'Direct opted-in publisher dry-run succeeds without credential resolution or publishing HTTP.',
    'publisher_all_dry_run': 'All-selection publisher dry-run succeeds without credential resolution or publishing HTTP.',
    'bridge_setup_dry_run': 'Bridge schema dry-run succeeds without credential resolution or publishing HTTP.',
    'bridge_publish_dry_run': 'Scoped bridge publish dry-run succeeds without credential resolution or publishing HTTP.',
    'bridge_unscoped_json': 'Unscoped JSON bridge input exits nonzero without any credential or transport attempt.',
    'source_and_identity_preservation': 'Every protected source, Self and complete copied toolkit input remains byte-identical.',
    'redacted_evidence': 'No persisted public evidence contains raw controlled private inputs.',
    'transport_scope': 'All original child audit traces record zero credential resolution, publishing HTTP and socket attempts.'}

AUDIT_SOURCE = r'''import atexit, builtins, hashlib, json, os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
_role = os.environ['TWIN_PRIVACY_ROLE']
_root = Path(os.environ['TWIN_PRIVACY_RUN'])
_private = json.loads((_root / 'private-inputs.json').read_text(encoding='utf-8'))
_counts = {'credential_resolution': 0, 'publishing_http': 0, 'socket_connect': 0}
_children = []
_popen = subprocess.Popen
def _redact(value):
    text = str(value)
    for key, secret in sorted(_private.items(), key=lambda pair: -len(pair[1])):
        text = text.replace(secret, '<private:' + key + '>')
    return text
def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()
class PrivacyPopen(_popen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        argv = args[0] if args else kwargs.get('args')
        if not isinstance(argv, (tuple, list)):
            argv = [str(argv)]
        _children.append((self, list(map(str, argv))))
subprocess.Popen = PrivacyPopen
def _credentials(*args, **kwargs):
    _counts['credential_resolution'] += 1
    raise RuntimeError('Task transport guard refused credential resolution')
def _http(*args, **kwargs):
    _counts['publishing_http'] += 1
    raise RuntimeError('Task transport guard refused publishing HTTP')
def _socket(*args, **kwargs):
    _counts['socket_connect'] += 1
    raise RuntimeError('Task transport guard refused socket connection')
urllib.request.urlopen = _http
socket.create_connection = _socket
socket.socket.connect = _socket
_import = builtins.__import__
def _guarded_import(name, *args, **kwargs):
    result = _import(name, *args, **kwargs)
    module = sys.modules.get('_notion_env')
    if module is not None:
        module.get_notion_key = _credentials
        module.get_notion_database_id = _credentials
    module = sys.modules.get('knowledgeos.remembering')
    fault = os.environ.get('TWIN_PRIVACY_FAIL_MIRROR')
    if module is not None and hasattr(module, 'atomic_write_bytes') and fault and not getattr(module, '_privacy_fault_set', False):
        original = module.atomic_write_bytes
        def _fault(path, *values, **options):
            if Path(path).absolute() == Path(fault).absolute():
                raise OSError('Task-owned interrupted mirror publication')
            return original(path, *values, **options)
        module.atomic_write_bytes = _fault
        module._privacy_fault_set = True
    return result
builtins.__import__ = _guarded_import
gate = os.environ.get('TWIN_PRIVACY_START_GATE')
if gate:
    ready = _root / 'concurrent-ready' / (_role + '.json')
    ready.parent.mkdir(exist_ok=True)
    ready.write_text(json.dumps({'role': _role, 'pid': os.getpid(), 'ready': True}), encoding='utf-8')
    deadline = time.monotonic() + 30
    while not Path(gate).exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Task start barrier expired')
        time.sleep(0.01)
def _finish():
    rows = []
    for child, argv in _children:
        forced = child.poll() is None
        if forced:
            child.kill()
        child.wait()
        rows.append({'pid': child.pid, 'command': [_redact(part) for part in argv],
                     'argv_sha256': _digest(argv), 'stopped': child.poll() is not None,
                     'exit_code': child.returncode, 'cleanup_required': forced})
    package = sys.modules.get('knowledgeos')
    imported = getattr(package, '__file__', None)
    body = {'role': _role, 'pid': os.getpid(), 'parent_pid': os.getppid(),
            'counts': _counts, 'children': rows, 'knowledgeos_file': imported,
            'python': sys.executable, 'prefix': sys.prefix}
    (_root / 'child-traces' / (_role + '.' + str(os.getpid()) + '.json')).write_text(json.dumps(body), encoding='utf-8')
atexit.register(_finish)
'''

HELPER_SOURCE = r'''import argparse, json, os, sqlite3, sys
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('operation')
p.add_argument('vault', type=Path)
p.add_argument('--token')
a = p.parse_args()
if a.operation == 'holder':
    connection = sqlite3.connect(a.vault / 'knowledge_index.db', timeout=2)
    connection.execute('BEGIN IMMEDIATE')
    print(json.dumps({'ready': True, 'pid': os.getpid(), 'path': str(a.vault / 'knowledge_index.db')}), flush=True)
    sys.stdin.readline()
    connection.rollback()
    connection.close()
elif a.operation == 'legacy-proposal':
    from knowledgeos.gate import propose
    result = propose(a.vault, a.vault / 'People/Self.md', a.vault / 'People/Self-Proposals',
                     'Legacy ' + a.token, 'heuristics', '* Prefer concise Rill reviews.', mode='append')
    print(json.dumps(result))
else:
    raise SystemExit(2)
'''


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def excluded(result):
    return result.get('is_error') is True and result.get('payload', {}).get('ok') is False and bool(result.get('payload', {}).get('error'))


class PrivacyRun:
    def __init__(self, output):
        self.directory = checked_output(output) / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True)
        self.fixture = self.directory / 'fixture'
        self.vault = self.fixture / 'toolkit'
        self.state = self.fixture / 'gate-state'
        self.vault.mkdir(parents=True)
        self.inputs = source_files()
        self.product = {p.relative_to(ROOT).as_posix(): sha(p) for p in self.inputs}
        self.support = {'data_preservation.py': sha(SUPPORT / 'data_preservation.py')}
        self.producer_hash = sha(__file__)
        for source in self.inputs:
            target = self.vault / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.save('toolkit.before.json', inventory(self.vault))
        self.private = {f'credential{i}': 'sk-' + secrets.token_hex(20) for i in range(6)}
        self.private.update(legacy='sk-' + secrets.token_hex(20), diagnostic='sk-' + secrets.token_hex(20),
            third0='Mira was diagnosed with diabetes.', third1="Mira's bank account funds her private care.",
            third2="Mira's private phone is available only to family.",
            semantic="My colleague's biopsy showed a malignant growth in her left lung.")
        self.save('private-inputs.json', self.private, redact=False)
        (self.directory / 'child-traces').mkdir()
        (self.directory / 'audit').mkdir()
        (self.directory / 'audit/sitecustomize.py').write_text(AUDIT_SOURCE, encoding='utf-8')
        (self.directory / 'fixture_ops.py').write_text(HELPER_SOURCE, encoding='utf-8')
        self.processes, self.cases, self.active = [], [], []
        self.evidence = set()
        self.saved_sources = {}
        self.lock = threading.Lock()
        self.sentinels_before = self.sentinels()
        self.save('frozen-expectations.json', {'producer': PRODUCER, 'case_ids': list(CASE_IDS), 'expected': EXPECTED})
        self.env = {key: value for key, value in os.environ.items() if key not in {
            'PYTHONPATH', 'PYTHONHOME', 'KNOWLEDGEOS_VAULT', 'KNOWLEDGEOS_STATE_DIR', 'KNOWLEDGEOS_GATE_KEY', 'VIRTUAL_ENV'}
            and not any(word in key.upper() for word in ('NOTION', 'API_KEY', 'ACCESS_TOKEN', 'CLIENT_SECRET', 'PASSWORD'))}
        self.env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
            PYTHONPATH=os.pathsep.join((str(self.directory / 'audit'), str(self.vault))),
            KNOWLEDGEOS_STATE_DIR=str(self.state), KNOWLEDGEOS_VAULT=str(self.vault), TWIN_PRIVACY_RUN=str(self.directory))

    def sentinels(self):
        return {str(ROOT / name): sha(ROOT / name) if (ROOT / name).is_file() else None
                for name in ('People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json')}

    def redact(self, value):
        text = value if isinstance(value, str) else encoded(value)
        for name, secret in sorted(self.private.items(), key=lambda pair: -len(pair[1])):
            text = text.replace(secret, '<private:' + name + '>')
        return text

    def save(self, name, value, *, redact=True):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
        path.write_text(self.redact(text) if redact and hasattr(self, 'private') else text, encoding='utf-8')
        if hasattr(self, 'evidence') and name != 'private-inputs.json':
            self.evidence.add(name)

    def start(self, role, command, *, env=None, stdin=None):
        if any(row['role'] == role for row in self.processes):
            raise ValueError('Duplicate launch role')
        environment = dict(self.env, TWIN_PRIVACY_ROLE=role, **(env or {}))
        began = time.monotonic_ns()
        process = subprocess.Popen(list(map(str, command)), cwd=self.vault, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        record = {'role': role, 'pid': process.pid, 'command': list(map(str, command)),
            'argv_sha256': digest(encoded(list(map(str, command)))), 'cwd': str(self.vault),
            'vault': str(self.vault), 'import_path': environment['PYTHONPATH'], 'state_dir': str(self.state),
            'shell': False, 'started_ns': began, 'stdin_sha256': digest(stdin or b''),
            'is_python': Path(str(command[0])).resolve() == Path(sys.executable).resolve(), 'error': None}
        self.processes.append(record)
        self.active.append((process, record))
        return process, record, stdin

    def finish(self, started, *, timeout=70):
        process, record, stdin = started
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except BaseException as error:
            record['error'] = type(error).__name__
            process.kill()
            stdout, stderr = process.communicate(timeout=15)
        stdout = record.pop('stdout_prefix', b'') + stdout
        record.update(stopped=process.poll() is not None, exit_code=process.returncode,
            finished_ns=time.monotonic_ns(), stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))
        role = record['role']
        for suffix, raw in (('.stdout.txt', stdout), ('.stderr.txt', stderr)):
            (self.directory / (role + suffix)).write_text(self.redact(raw.decode('utf-8')), encoding='utf-8', newline='')
            self.evidence.add(role + suffix)
        self.save(role + '.command.json', record)
        self.active.remove((process, record))
        return record, stdout.decode('utf-8'), stderr.decode('utf-8')

    def command(self, role, arguments, **options):
        return self.finish(self.start(role, arguments, **options))

    def cli(self, role, arguments, **options):
        return self.command(role, [sys.executable, '-B', '-P', '-m', 'knowledgeos', *arguments], **options)

    def script(self, role, name, arguments=(), **options):
        return self.command(role, [sys.executable, '-B', '-P', str(self.vault / 'scripts' / name), *arguments], **options)

    def memory(self, role, tool, arguments, **options):
        record, raw, err = self.cli(role, ['memory', tool, '--vault', str(self.vault), '--args', encoded(arguments)], **options)
        return {'payload': json.loads(raw), 'is_error': record['exit_code'] != 0}

    def rpc(self, role, calls):
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'verify-twinaatma-privacy', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
        messages += [{'jsonrpc': '2.0', 'id': number, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
                     for number, (name, arguments) in enumerate(calls, 2)]
        wire = ''.join(encoded(row) + '\n' for row in messages).encode()
        self.save(role + '.requests.json', messages)
        record, stdout, stderr = self.cli(role, ['mcp', '--vault', str(self.vault), '--framing', 'ndjson'], stdin=wire)
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        if (record['exit_code'] != 0 or len(responses) != len(calls) + 1
                or responses[0].get('result', {}).get('serverInfo', {}).get('name') != 'knowledgeos-memory'):
            raise RuntimeError('Public MCP initialization, protocol or shutdown failed')
        results = []
        for number, response in enumerate(responses[1:], 2):
            value = response.get('result', {})
            if response.get('id') != number or type(value.get('isError')) is not bool:
                raise RuntimeError('Public MCP result inventory differs')
            results.append({'payload': json.loads(value['content'][0]['text']), 'is_error': value['isError']})
        self.save(role + '.results.json', results)
        self.save(role + '.wire-hashes.json', {'requests': [digest(encoded(row)) for row in messages],
            'responses': [digest(encoded(row)) for row in responses]})
        return results

    def case(self, name, valid, observed, roles=()):
        self.save('observations/' + name + '.json', observed)
        self.cases.append({'id': 'privacy.' + name, 'verdict': 'PASS' if valid else 'FAIL',
            'expected': EXPECTED[name], 'action': list(roles) or ['independent retained file observation'],
            'entry_point': 'source CLI/MCP, source-only script or independent fixture observation',
            'platform': platform.system(), 'observed': observed, 'evidence': ['observations/' + name + '.json',
                *[role + '.command.json' for role in roles]]})
        print(self.cases[-1]['verdict'] + ' ' + self.cases[-1]['id'], flush=True)

    def write_source(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='')
        self.saved_sources[relative] = sha(path)
        return path

    def views(self, prefix, relative):
        return self.rpc(prefix, [('memory_get_note', {'path_or_id': relative}),
            ('memory_search', {'query': 'Rill'}), ('memory_bootstrap_context', {'task_hint': 'Rill'}),
            ('memory_decisions', {}), ('memory_timeline', {'days': 3650}),
            ('memory_pending_outcomes', {}), ('memory_related', {'path_or_id': relative})])

    def observe(self):
        policy = ROOT / 'work/gc-artifacts/.knowledgeos/privacy-policy-20261019'
        for source, name in ((policy / 'approved-policy.json', 'policy.json'),
                (policy / 'human-approval-source.jsonl', 'human-approval-source.jsonl'),
                (policy / 'human-approval-provenance.json', 'human-approval-provenance.json')):
            shutil.copy2(source, self.directory / name)
            self.evidence.add(name)
        self.case('human_policy', sha(self.directory / 'policy.json') == POLICY_SHA256
            and sha(self.directory / 'human-approval-source.jsonl') == APPROVAL_SHA256,
            {'policy_sha256': sha(self.directory / 'policy.json'), 'approval_sha256': sha(self.directory / 'human-approval-source.jsonl')})
        init, output, _ = self.cli('init', ['init', str(self.vault), '--name', 'Synthetic Privacy Owner', '--non-interactive', '--force'])
        doctor, _, _ = self.cli('doctor', ['doctor', '--vault', str(self.vault)])
        self.case('native_setup', init['exit_code'] == doctor['exit_code'] == 0
            and all(row.get('ok') is True for row in json.loads(output).get('post_init', {}).values()),
            {'initialized': json.loads(output), 'init_exit': init['exit_code'], 'doctor_exit': doctor['exit_code']}, ('init', 'doctor'))
        self.saved_sources['People/Self.md'] = sha(self.vault / 'People/Self.md')
        first = self.rpc('capture-ordinary', [('memory_capture', {'title': 'Rill contextual preference', 'content': ORDINARY,
            'request_id': 'privacy-rill-review'}), ('memory_capture', {'title': 'Rill collaboration', 'content': BENIGN})])
        original = first[0]['payload'].get('path', 'missing.md')
        original_raw = (self.vault / original).read_bytes()
        self.saved_sources[original] = sha(self.vault / original)
        self.saved_sources[first[1]['payload']['path']] = sha(self.vault / first[1]['payload']['path'])
        read = self.rpc('retention-restart', [('memory_get_note', {'path_or_id': original}),
            ('memory_get_note', {'path_or_id': first[1]['payload']['path']}), ('memory_search', {'query': 'Rill'})])
        self.case('ordinary_retention', all(row['payload'].get('ok') is True for row in first)
            and ORDINARY in encoded(read) and BENIGN in encoded(read) and read[0]['payload'].get('sha256') == digest(original_raw),
            {'path': original, 'sha256': digest(original_raw)}, ('capture-ordinary', 'retention-restart'))
        credentials = [('memory_capture', {'title': self.private['credential0'], 'content': 'Service title'}),
            ('memory_capture', {'title': 'Service', 'content': 'API key: ' + self.private['credential1']}),
            ('memory_capture', {'title': 'Service', 'content': 'Routine note', 'tags': [self.private['credential2']]}),
            ('memory_session_start', {'task_hint': 'Bearer ' + self.private['credential3'], 'session_id': 'private-hint'}),
            ('memory_session_end', {'summary': 'API key: ' + self.private['credential4'], 'session_id': 'private-summary'})]
        results = self.rpc('credential-surfaces', credentials)
        self.case('credential_rpc', all(excluded(row) for row in results) and not self.exposed(encoded(results)), {}, ('credential-surfaces',))
        result = self.memory('credential-cli', 'memory_capture', {'title': 'Private CLI', 'content': 'API key: ' + self.private['credential5']})
        self.case('credential_cli', excluded(result) and not self.exposed(encoded(result)), {}, ('credential-cli',))
        result = self.rpc('metadata', [('memory_capture', {'title': 'Opaque excluded record', 'content': 'Opaque fixture detail.', 'privacy': label})
            for label in ('exclude', 'credential', 'sensitive-third-party')])
        self.case('explicit_metadata', all(excluded(row) for row in result), {}, ('metadata',))
        result = self.rpc('third-patterns', [('memory_capture', {'title': 'Sensitive third-party detail', 'content': self.private['third' + str(n)]}) for n in range(3)])
        self.case('third_party_patterns', all(excluded(row) for row in result) and not self.exposed(encoded(result)), {}, ('third-patterns',))
        semantic = self.rpc('third-semantic', [('memory_capture', {'title': 'Colleague private clinical detail', 'content': self.private['semantic']})])[0]
        self.case('third_party_semantic', excluded(semantic) and not self.exposed(encoded(semantic)),
            {'policy_expected': 'Sensitive third-party clinical detail is excluded without requiring operator metadata.'}, ('third-semantic',))
        legacy = self.write_source('Decisions/LegacySensitive.md', '---\ntype: decision\ntitle: Legacy service\nstatus: active\nproject: Rill\nupdated: 2026-10-19\n---\n# Legacy service\nAPI key: ' + self.private['legacy'] + '\n')
        meta = self.write_source('Concepts/ExplicitExcluded.md', '---\nprivacy: exclude\n---\n# Opaque excluded source\nOpaque private fixture detail.\n')
        result = self.views('legacy-views', 'Decisions/LegacySensitive.md')
        metadata_read = self.rpc('legacy-metadata', [('memory_get_note', {'path_or_id': 'Concepts/ExplicitExcluded.md'})])
        self.case('legacy_admission', excluded(result[0]) and excluded(metadata_read[0]) and not self.exposed(encoded(result)), {}, ('legacy-views', 'legacy-metadata'))
        connection = sqlite3.connect(self.vault / 'knowledge_index.db')
        connection.execute('INSERT OR REPLACE INTO notes(title,path,type,tags,project,status,updated,outcome_status) VALUES (?,?,?,?,?,?,?,?)',
            (self.private['legacy'], 'Decisions/LegacySensitive.md', 'decision', self.private['legacy'], 'Rill', 'active', '2026-10-19', 'pending'))
        connection.execute('INSERT INTO notes_fts(path,title,body,tags,description) VALUES (?,?,?,?,?)',
            ('Decisions/LegacySensitive.md', self.private['legacy'], 'Rill ' + self.private['legacy'], self.private['legacy'], self.private['legacy']))
        connection.commit()
        connection.close()
        shutil.copy2(self.vault / 'knowledge_index.db', self.directory / 'private-forged-cache.db')
        self.save('forged-cache.json', {'path': 'Decisions/LegacySensitive.md', 'title': self.private['legacy'], 'body': 'Rill ' + self.private['legacy'],
            'database_sha256': sha(self.directory / 'private-forged-cache.db')})
        holder = self.start('busy-holder', [sys.executable, '-B', '-P', str(self.directory / 'fixture_ops.py'), 'holder', str(self.vault)])
        ready_raw = holder[0].stdout.readline()
        holder[1]['stdout_prefix'] = ready_raw
        ready = json.loads(ready_raw)
        self.save('busy-ready.json', ready)
        busy = self.views('busy-views', 'Decisions/LegacySensitive.md')
        alive = holder[0].poll() is None
        self.case('forged_busy_cache', excluded(busy[0]) and not self.exposed(encoded(busy)) and alive and ready.get('ready') is True,
            {'native_holder_alive_during': alive, 'ready': ready}, ('busy-holder', 'busy-views'))
        generated = []
        for n, script in enumerate(('weekly_data.py', 'intelligence_brief.py', 'experiment_dashboard.py', 'outcomes_dashboard.py', 'draft_weekly_synthesis.py')):
            record, out, err = self.script('generated-' + str(n), script)
            generated.append(record['exit_code'] == 0 and not self.exposed(out + err))
        self.finish((holder[0], holder[1], b'\n'))
        generated_scan = self.scan_paths([path for path in self.vault.rglob('*.md') if path.relative_to(self.vault).as_posix() not in self.saved_sources
            and not path.is_relative_to(self.vault / 'Templates') and 'knowledgeos' not in path.relative_to(self.vault).parts])
        self.case('generated_outputs', all(generated) and not generated_scan['exposures'], generated_scan, tuple('generated-' + str(n) for n in range(5)))
        pair = self.rpc('correction-sources', [('memory_capture', {'title': 'Rill prior release', 'content': PRIOR}),
            ('memory_capture', {'title': 'Rill current release', 'content': CURRENT})])
        prior, current = [row['payload']['path'] for row in pair]
        prior_sha, current_sha = sha(self.vault / prior), sha(self.vault / current)
        self.saved_sources.update({prior: prior_sha, current: current_sha})
        args = {'path_or_id': prior, 'expected_sha256': prior_sha, 'replacement_path_or_id': current, 'replacement_sha256': current_sha}
        bad = self.rpc('correction-stale', [('memory_supersede', dict(args, expected_sha256='0' * 64))])[0]
        self.case('correction_stale_hash', excluded(bad), {'source': prior}, ('correction-stale',))
        corrected = self.rpc('correction', [('memory_get_note', {'path_or_id': prior}), ('memory_get_note', {'path_or_id': current}), ('memory_supersede', args)])
        after = self.rpc('correction-restart', [('memory_get_note', {'path_or_id': prior}), ('memory_search', {'query': 'Rill release'})])
        self.case('reviewed_correction', corrected[0]['payload'].get('sha256') == prior_sha and corrected[1]['payload'].get('sha256') == current_sha
            and corrected[2]['payload'].get('ok') is True and after[0]['payload'].get('memory_status') == 'historical'
            and after[0]['payload'].get('superseded_by') == current and prior not in [row.get('path') for row in after[1]['payload'].get('ranked', [])]
            and CURRENT in encoded(after[1]), {'prior': prior, 'current': current, 'prior_sha256': prior_sha, 'current_sha256': current_sha}, ('correction', 'correction-restart'))
        self.write_source('Projects/CopiedMemory.md', original_raw.decode())
        self.rpc('before-forget-session', [('memory_session_start', {'task_hint': ORDINARY, 'session_id': 'forget-session'})])
        bad = self.rpc('forget-stale', [('memory_forget', {'path_or_id': original, 'expected_sha256': '0' * 64})])[0]
        self.case('forget_stale_hash', excluded(bad), {'path': original}, ('forget-stale',))
        forget_args = {'path_or_id': original, 'expected_sha256': digest(original_raw)}
        forgotten = self.rpc('forget', [('memory_forget', forget_args)])[0]
        self.case('reviewed_forgetting', forgotten['payload'].get('ok') is True,
            {'path': original, 'sha256': digest(original_raw)}, ('forget',))
        after = self.views('after-forget', original)
        retries = self.rpc('forget-retries', [('memory_get_note', {'path_or_id': 'Projects/CopiedMemory.md'}),
            ('memory_forget', forget_args), ('memory_capture', {'title': 'Recapture under another title', 'content': ORDINARY, 'request_id': 'privacy-rill-review'})])
        self.case('forget_replay_restart_copy', ORDINARY not in encoded(after + retries) and excluded(after[0]) and excluded(retries[0])
            and retries[1]['payload'].get('ok') is True and excluded(retries[2]), {}, ('after-forget', 'forget-retries'))
        state = self.vault / '.knowledgeos/autopilot.json'
        self.case('forget_session_state', state.is_file() and ORDINARY.encode() not in state.read_bytes(),
            {'state': '.knowledgeos/autopilot.json', 'sha256': sha(state), 'forbidden_literal_present': ORDINARY.encode() in state.read_bytes()})
        captures = self.rpc('concurrent-sources', [('memory_capture', {'title': 'Independent Rill source ' + str(n),
            'content': 'Rill independent review number ' + str(n) + ' uses an isolated record.'}) for n in range(4)])
        gate = self.directory / 'concurrent-go'
        workers, paths = [], []
        for n, result in enumerate(captures):
            relative = result['payload']['path']
            self.saved_sources[relative] = sha(self.vault / relative)
            arguments = {'path_or_id': relative, 'expected_sha256': self.saved_sources[relative]}
            workers.append(self.start('concurrent-' + str(n), [sys.executable, '-B', '-P', '-m', 'knowledgeos', 'memory', 'memory_forget',
                '--vault', str(self.vault), '--args', encoded(arguments)], env={'TWIN_PRIVACY_START_GATE': str(gate)}))
            paths.append(relative)
        deadline = time.monotonic() + 30
        while len(list((self.directory / 'concurrent-ready').glob('*.json'))) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        simultaneous = [{'role': record['role'], 'pid': process.pid, 'alive': process.poll() is None} for process, record, _ in workers]
        self.save('concurrent-live.json', simultaneous)
        gate.write_text('release\n')
        outputs = [self.finish(worker) for worker in workers]
        retried = []
        for n, relative in enumerate(paths):
            retried.append(self.memory('concurrent-retry-' + str(n), 'memory_forget',
                {'path_or_id': relative, 'expected_sha256': self.saved_sources[relative]}))
        reads = self.rpc('concurrent-restart', [('memory_get_note', {'path_or_id': relative}) for relative in paths])
        visible = []
        acceptable_initial = []
        for n, (record, out, _) in enumerate(outputs):
            payload = json.loads(out)
            success = record['exit_code'] == 0 and payload.get('ok') is True
            partial = (record['exit_code'] != 0 and payload == {'ok': False,
                'error': 'Forgetting is durable; session-state scrubbing needs a retry.',
                'forgotten': True, 'source_preserved': True, 'retryable': True})
            acceptable_initial.append(success or partial)
            if partial:
                visible.append(n)
        self.case('concurrent_forgetting', len({row['pid'] for row in simultaneous}) == 4 and all(row['alive'] for row in simultaneous)
            and all(acceptable_initial) and all(result['payload'].get('ok') is True and result['is_error'] is False for result in retried)
            and all(excluded(row) for row in reads), {'paths': paths, 'simultaneous': simultaneous, 'initial_visible_retryable_failures': visible},
            tuple('concurrent-' + str(n) for n in range(4)) + tuple('concurrent-retry-' + str(n) for n in range(4)) + ('concurrent-restart',))
        record, _, _ = self.script('export', 'export_bundle.py', ('--paths', 'Inbox', 'Projects', 'Decisions', '--out', 'Bundles/review'))
        bundle_scan = self.scan_paths([p for p in (self.vault / 'Bundles/review').rglob('*') if p.is_file()], extra=[ORDINARY])
        manifest = json.loads((self.vault / 'Bundles/review/manifest.json').read_text())
        attribution = {row['path']: row for row in manifest.get('notes', [])}
        historical = attribution.get(prior, {})
        current_entry = attribution.get(current, {})
        self.case('export_scope', record['exit_code'] == 0 and bool(bundle_scan['files']) and not bundle_scan['exposures']
            and any(CURRENT.encode() in (self.vault / name).read_bytes() for name in bundle_scan['files'])
            and historical.get('memory_status') == 'historical' and historical.get('superseded_by') == current
            and historical.get('reviewed_sha256') == prior_sha and current_entry.get('memory_status') == 'current', bundle_scan, ('export',))
        self.state_cases(original, forget_args, current, prior)
        self.native_diagnostics()
        self.external_writes(current)
        changed = [name for name, before in self.saved_sources.items() if not (self.vault / name).is_file() or sha(self.vault / name) != before]
        toolkit_changed = [name for name, before in self.product.items() if sha(self.vault / name) != before]
        self.save('protected-sources.json', self.saved_sources)
        self.case('source_and_identity_preservation', not changed and not toolkit_changed,
            {'unexpected_changed_sources': changed, 'unexpected_changed_toolkit': toolkit_changed})

    def exposed(self, text):
        return [name for name, value in self.private.items() if value in text]

    def scan_paths(self, paths, extra=()):
        files, exposures = {}, []
        for path in sorted(paths):
            if path.is_symlink() or not path.is_file():
                continue
            name = path.relative_to(self.vault).as_posix()
            data = path.read_bytes()
            files[name] = {'sha256': digest(data), 'size': len(data)}
            for value in self.exposed(data.decode('utf-8', errors='replace')):
                exposures.append({'path': name, 'canary': value})
            for n, value in enumerate(extra):
                if value.encode() in data:
                    exposures.append({'path': name, 'literal': n})
        return {'files': files, 'exposures': exposures}

    def state_cases(self, original, forget_args, current, prior):
        local = self.vault / '.knowledgeos/remembering-policy.json'
        authority = next(self.state.glob('vaults/*/remembering-policy.json'))
        key = self.state / 'gate.key'
        if not key.exists():
            candidates = [p for p in self.state.rglob('*') if p.is_file() and 'key' in p.name]
            if len(candidates) != 1:
                raise RuntimeError('Unique private signing key not found')
            key = candidates[0]
        baseline = {local: local.read_bytes(), authority: authority.read_bytes(), key: key.read_bytes()}
        self.save('state-baseline.json', {path.relative_to(self.fixture).as_posix(): {'sha256': digest(raw), 'size': len(raw)} for path, raw in baseline.items()})
        for name in ('malformed_local', 'duplicate_local', 'valid_empty_local', 'valid_replacement_local', 'deleted_local',
                     'linked_local', 'hardlinked_local', 'tampered_authority', 'deleted_authority', 'tampered_key', 'deleted_key', 'linked_authority', 'hardlinked_authority'):
            for path, raw in baseline.items():
                if path.is_symlink() or path.exists():
                    path.rename(path.with_name(path.name + '.retained-' + name))
                path.write_bytes(raw)
            target = authority if 'authority' in name else key if 'key' in name else local
            backup = self.directory / 'private-state-backups' / name
            backup.parent.mkdir(exist_ok=True)
            target.rename(backup)
            native_error = None
            try:
                if name == 'malformed_local':
                    target.write_bytes(b'{"version":1,"forgotten":[],"superseded":{}}')
                elif name == 'duplicate_local':
                    target.write_bytes(b'{"version":1,"forgotten":{},"forgotten":{},"superseded":{}}')
                elif name.startswith('valid_'):
                    value = {'version': 1, 'forgotten': {}, 'superseded': {}}
                    if name == 'valid_replacement_local':
                        value['superseded'][original] = {'sha256': forget_args['expected_sha256'], 'recorded_at': '2026-10-19T00:00:00+00:00',
                            'replacement': current, 'replacement_sha256': sha(self.vault / current)}
                    target.write_text(encoded(value))
                elif name.startswith('linked_'):
                    target.symlink_to(backup)
                elif name.startswith('hardlinked_'):
                    os.link(backup, target)
                elif name == 'tampered_key':
                    target.write_bytes(b'42' * 32)
                elif name == 'tampered_authority':
                    value = json.loads(backup.read_bytes())
                    value['state']['forgotten'] = {}
                    target.write_text(encoded(value))
            except OSError as error:
                native_error = type(error).__name__
            snapshot = self.directory / 'private-mutated-state' / name
            snapshot.parent.mkdir(exist_ok=True)
            if target.exists() and not target.is_symlink():
                shutil.copy2(target, snapshot)
            elif target.is_symlink():
                snapshot.symlink_to(backup)
            self.save('mutations/' + name + '.json', {'target': target.relative_to(self.fixture).as_posix(), 'before_sha256': digest(baseline[target]),
                'backup_sha256': sha(backup), 'native_error': native_error,
                'kind': 'link' if target.is_symlink() else 'file' if target.exists() else 'missing',
                'links': target.stat().st_nlink if target.exists() and not target.is_symlink() else None,
                'body': target.read_text() if target.exists() and not target.is_symlink() and target != key else None})
            read = self.rpc('state-' + name, [('memory_get_note', {'path_or_id': original}),
                ('memory_get_note', {'path_or_id': prior}), ('memory_search', {'query': 'Rill'})])
            expected_missing = name == 'deleted_local'
            valid = (excluded(read[0]) and ORDINARY not in encoded(read) and original not in encoded(read[2])
                and (read[1]['payload'].get('memory_status') == 'historical' if expected_missing else excluded(read[1])))
            self.case(name, native_error is None and valid, {'native_error': native_error, 'target': target.relative_to(self.fixture).as_posix()}, ('state-' + name,))
        for path, raw in baseline.items():
            if path.exists() or path.is_symlink():
                path.rename(path.with_name(path.name + '.retained-final'))
            path.write_bytes(raw)
        outside = self.fixture / 'outside/Outsider.md'
        outside.parent.mkdir()
        outside.write_bytes(b'# Outside source\nOutside private fixture evidence must stay outside memory.\n')
        aliases = {'Permitted': self.vault / current, 'Excluded': self.vault / 'Decisions/LegacySensitive.md',
            'Forgotten': self.vault / original, 'Self': self.vault / 'People/Self.md', 'Outside': outside}
        alias_paths = {name: 'Projects/Alias' + name + '.md' for name in aliases}
        before = {str(target): sha(target) for target in aliases.values()}
        for name, target in aliases.items():
            (self.vault / alias_paths[name]).symlink_to(target)
        self.save('linked-source-setup.json', {'aliases': {alias_paths[name]: str(target) for name, target in aliases.items()}, 'target_hashes': before})
        linked = self.rpc('linked-source-read', [('memory_get_note', {'path_or_id': path}) for path in alias_paths.values()])
        protected = self.rpc('linked-source-protected', [('memory_forget', {'path_or_id': alias_paths['Self'], 'expected_sha256': sha(aliases['Self'])}),
            ('memory_supersede', {'path_or_id': alias_paths['Self'], 'expected_sha256': sha(aliases['Self']),
                'replacement_path_or_id': current, 'replacement_sha256': sha(self.vault / current)})])
        outside_result = self.rpc('linked-source-outside', [('memory_forget', {'path_or_id': alias_paths['Outside'], 'expected_sha256': sha(outside)}),
            ('memory_supersede', {'path_or_id': alias_paths['Outside'], 'expected_sha256': sha(outside),
                'replacement_path_or_id': current, 'replacement_sha256': sha(self.vault / current)})])
        canonical = self.rpc('linked-source-forget-canonical', [('memory_forget', {'path_or_id': current, 'expected_sha256': sha(self.vault / current)})])[0]
        generic_refusal = lambda row: row['is_error'] is True and bool(row['payload'].get('error'))
        preserved = before == {str(target): sha(target) for target in aliases.values()}
        self.case('linked_source', linked[0]['is_error'] is False and linked[0]['payload'].get('path') == current
            and linked[0]['payload'].get('sha256') == before[str(aliases['Permitted'])] and excluded(linked[1]) and excluded(linked[2])
            and linked[3]['payload'].get('path') == 'People/Self.md' and generic_refusal(linked[4])
            and all(generic_refusal(row) for row in protected + outside_result) and canonical['payload'].get('ok') is True
            and preserved and not self.exposed(encoded(linked + protected + outside_result)), {'sources_preserved': preserved},
            ('linked-source-read', 'linked-source-protected', 'linked-source-outside', 'linked-source-forget-canonical'))
        retained_aliases = self.directory / 'private-linked-sources'
        retained_aliases.mkdir()
        for name in aliases:
            (self.vault / alias_paths[name]).rename(retained_aliases / (name + '.md'))
        extra = self.rpc('fault-source', [('memory_capture', {'title': 'Rill fault source', 'content': 'Rill publication retry uses a reversible synthetic checkpoint.'})])[0]['payload']['path']
        self.saved_sources[extra] = sha(self.vault / extra)
        arguments = {'path_or_id': extra, 'expected_sha256': self.saved_sources[extra]}
        failure = self.memory('fault-forget', 'memory_forget', arguments, env={'TWIN_PRIVACY_FAIL_MIRROR': str(local)})
        retry = self.memory('fault-retry', 'memory_forget', arguments)
        read = self.rpc('fault-restart', [('memory_get_note', {'path_or_id': extra})])[0]
        self.case('publication_failure_retry', excluded(failure) and retry['payload'].get('ok') is True and excluded(read),
            {'path': extra, 'sha256': self.saved_sources[extra]}, ('fault-forget', 'fault-retry', 'fault-restart'))

    def native_diagnostics(self):
        _, out, _ = self.command('legacy-proposal', [sys.executable, '-B', '-P', str(self.directory / 'fixture_ops.py'), 'legacy-proposal', str(self.vault), '--token', self.private['diagnostic']])
        legacy_path = json.loads(out)['proposal_path']
        self.saved_sources[legacy_path] = sha(self.vault / legacy_path)
        ordinary = self.rpc('ordinary-proposal', [('memory_propose_self_update', {'summary': 'Rill review cadence', 'section': 'heuristics',
            'proposed_markdown': '* Prefer concise Rill reviews.', 'mode': 'append'})])[0]
        ordinary_path = ordinary['payload'].get('proposal_path')
        if isinstance(ordinary_path, str):
            self.saved_sources[ordinary_path] = sha(self.vault / ordinary_path)
        record, out, err = self.cli('pending', ['self', 'pending', '--vault', str(self.vault)])
        self.case('native_pending_diagnostic', record['exit_code'] == 0 and not self.exposed(out + err)
            and isinstance(ordinary_path, str) and ordinary_path in out and legacy_path not in out,
            {'ordinary_proposal': ordinary_path, 'legacy_proposal': legacy_path}, ('legacy-proposal', 'ordinary-proposal', 'pending'))
        self.write_source('Concepts/PermittedActivity.md', '# Permitted activity\nUse concise Rill project reviews.\n')
        private_path = 'Concepts/PrivateActivity-' + self.private['diagnostic'] + '.md'
        self.write_source(private_path, '---\nprivacy: exclude\n---\n# Private activity\n')
        for role, argv in (('git-init', ['git', 'init', '--quiet', str(self.vault)]),
                ('git-add', ['git', '-C', str(self.vault), 'add', '--', 'Concepts/PermittedActivity.md', private_path]),
                ('git-commit', ['git', '-C', str(self.vault), '-c', 'user.name=Synthetic Privacy', '-c', 'user.email=synthetic@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Synthetic diagnostic fixture'])):
            record, _, _ = self.command(role, argv)
            if record['exit_code'] != 0:
                raise RuntimeError('Native synthetic Git fixture could not be created')
        record, out, err = self.script('native-drift', 'semantic_drift.py')
        self.case('native_git_diagnostic', record['exit_code'] == 0 and 'Concepts/PermittedActivity.md' in out and not self.exposed(out + err)
            and 'not evidence of changed beliefs' in out, {'real_git': True}, ('git-init', 'git-add', 'git-commit', 'native-drift'))

    def external_writes(self, current):
        self.write_source('Concepts/Publishable.md', '---\ntype: concept\ntitle: Rill publishing review\nstatus: refined\npublish_to_notion: true\ntags: [synthetic]\n---\n# Rill publishing review\nA permitted synthetic publishing selection.\n')
        operations = (
            ('publisher_dry_run', 'publisher', 'publish_to_notion.py', ('--dry-run', 'Concepts/Publishable.md'), 0, 'DRY RUN: Would publish'),
            ('publisher_all_dry_run', 'publisher-all', 'publish_to_notion.py', ('--dry-run', '--all'), 0, 'DRY RUN: Would publish'),
            ('bridge_setup_dry_run', 'bridge-setup', 'notion_bridge.py', ('--dry-run', 'setup'), 0, 'DRY RUN: Would ensure'),
            ('bridge_publish_dry_run', 'bridge-publish', 'notion_bridge.py', ('--dry-run', 'publish', 'Concepts/Publishable.md'), 0, 'DRY RUN: Would publish'),
            ('bridge_unscoped_json', 'bridge-json', 'notion_bridge.py', ('--dry-run', 'publish', '{"title":"Unscoped synthetic input"}'), 1, 'Unscoped JSON publishing is unsupported'))
        for name, role, script, args, expected, message in operations:
            record, out, err = self.script(role, script, args)
            self.case(name, record['exit_code'] == expected and message in out and not self.exposed(out + err), {}, (role,))

    def complete(self, error):
        for process, record in list(self.active):
            if process.poll() is None:
                process.kill()
            try:
                self.finish((process, record, None), timeout=10)
            except BaseException:
                record.update(stopped=process.poll() is not None, exit_code=process.returncode, error='Interrupted cleanup')
        self.evidence.update({'toolkit.before.json', 'audit/sitecustomize.py', 'fixture_ops.py'})
        self.evidence.update(p.relative_to(self.directory).as_posix() for p in (self.directory / 'child-traces').glob('*.json'))
        traces = [json.loads((self.directory / name).read_text()) for name in sorted(self.evidence) if name.startswith('child-traces/')]
        if error is None:
            raw_exposure = [name for name in self.evidence if self.exposed((self.directory / name).read_text(encoding='utf-8'))]
            self.case('redacted_evidence', not raw_exposure, {'unredacted_evidence_files': raw_exposure})
            counts = {key: sum(trace['counts'][key] for trace in traces) for key in ('credential_resolution', 'publishing_http', 'socket_connect')}
            self.case('transport_scope', counts == {'credential_resolution': 0, 'publishing_http': 0, 'socket_connect': 0}, {'counts': counts})
        complete = [row['id'] for row in self.cases] == ['privacy.' + name for name in CASE_IDS]
        product_after = {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}
        report = {'producer': PRODUCER, 'producer_sha256': self.producer_hash, 'support_sha256': self.support,
            'support_sha256_after': {'data_preservation.py': sha(SUPPORT / 'data_preservation.py')},
            'product_hashes': self.product, 'product_hashes_after': product_after, 'source_root': str(ROOT),
            'product_and_producer_unchanged': self.product == product_after and sha(__file__) == self.producer_hash,
            'platform': platform.platform(), 'python': sys.version, 'scope': 'source-policy privacy in a complete task-owned copied toolkit',
            'cases': self.cases, 'expected_case_ids': ['privacy.' + name for name in CASE_IDS], 'case_inventory_complete': complete,
            'processes': self.processes, 'all_started_processes_stopped': bool(self.processes) and all(row.get('stopped') is True for row in self.processes),
            'isolation': {'before': self.sentinels_before, 'after': self.sentinels(), 'selected_sentinels_unchanged': self.sentinels_before == self.sentinels()},
            'evidence_files': {name: sha(self.directory / name) for name in sorted(self.evidence)},
            'error': type(error).__name__ if error else None, 'verdict': 'PASS' if complete and all(row['verdict'] == 'PASS' for row in self.cases) else 'FAIL',
            'error_location': [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                for frame in traceback.extract_tb(error.__traceback__)] if error else [],
            'acceptance_credit_awarded': False, 'ideal_system_verdict': 'NOT CHECKED',
            'limits': ['Finite lexical patterns and explicit metadata do not establish arbitrary sensitive meaning detection.',
                'Forgetting identifies exact sources, exact copies and normalized literal passages; arbitrary paraphrases remain outside the demonstrated mechanism.',
                'Private synthetic sources, canaries, signing state and database are retained fixture inputs, never real-task observer registrations.',
                'Source proof cannot establish genuine-host capture, note instruction resistance, advice, owner approval, installed artifacts, a week, restore or authenticated Notion release.',
                'Native Git diagnostics observe actual local commits and edit counts, not beliefs or semantic drift acceptance.']}
        self.save('report.json', report)
        print(json.dumps({'report': str(self.directory / 'report.json'), 'verdict': report['verdict'], 'error': report['error'],
            'cases': len(self.cases), 'all_started_processes_stopped': report['all_started_processes_stopped']}), flush=True)
        return int(report['verdict'] != 'PASS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run, error = PrivacyRun(args.output), None
    try:
        run.observe()
    except BaseException as caught:
        error = caught
    return run.complete(error)


if __name__ == '__main__':
    raise SystemExit(main())
