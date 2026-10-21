"""Independently grade the Self integrity outcome from retained source observations."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re

PRODUCER = 'verify-twinaatma.integrity/v1'
CHECK = 'identity.integrity.complete'
OUTCOME = 'IDENTITY.integrity_refusal'
FORBIDDEN_SCREEN = ('Apply this to People/Self.md', '[y/N]', 'yes-wipe', 'What this replaces', 'What it puts there',
                    'Proposal:', 'Section :', 'Changes :', '(identical to the current section)')
SENTINELS = ('People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Integrity JSON contains duplicate keys')
        result[key] = value
    return result


def _loads(text):
    return json.loads(text, object_pairs_hook=_unique)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _literal(name):
    tree = ast.parse(Path(__file__).with_name('integrity.py').read_text(encoding='utf-8'))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    if len(values) != 1:
        raise ValueError('Integrity producer literal is missing or duplicated')
    return ast.literal_eval(values[0])


def _rows(raw):
    rows = []
    for line in raw.decode('utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _text(raw):
    return raw.decode('utf-8', errors='replace')


def _original_hash(raw):
    return _digest(_text(raw).replace('\r\n', '\n').replace('\r', '\n').encode('utf-8'))


def _mcp_exchange(read, label, count):
    """Parse one retained NDJSON MCP exchange into (requests, [(is_error, payload)])."""
    requests = [json.loads(line) for line in _text(read(label + '.stdin.txt')).splitlines() if line.strip()]
    responses = [json.loads(line) for line in _text(read(label + '.stdout.txt')).splitlines() if line.strip()]
    by_id = {response.get('id'): response for response in responses}
    if (len(requests) != count + 2 or len(responses) != count + 1 or set(by_id) != set(range(1, count + 2))
            or by_id[1].get('result', {}).get('serverInfo', {}).get('name') != 'knowledgeos-memory'
            or requests[0].get('method') != 'initialize' or requests[1].get('method') != 'notifications/initialized'):
        raise ValueError('MCP exchange inventory or server identity differs')
    results = []
    for index in range(2, count + 2):
        request, response = requests[index], by_id[index]
        value = response.get('result', {})
        content = value.get('content')
        if (request.get('id') != index or request.get('method') != 'tools/call' or response.get('jsonrpc') != '2.0'
                or 'error' in response or type(value.get('isError')) is not bool or not isinstance(content, list)
                or len(content) != 1 or content[0].get('type') != 'text'):
            raise ValueError('MCP request or response schema differs')
        payload = json.loads(content[0]['text'])
        if not isinstance(payload, dict):
            raise ValueError('MCP payload must be an object')
        results.append((value['isError'], payload))
    return requests, results


def judge_case(name, spec, read, exists):
    """Recompute one case verdict from retained bytes. Returns verdict, named checks and failed names."""
    prefix = name + '.'
    checks = {}
    try:
        if spec.get('needs_links') and exists(prefix + 'unavailable.json'):
            return {'verdict': 'NOT CHECKED', 'checks': {'links_available': False}, 'problems': ['native link creation unsupported']}
        if spec['kind'] == 'control':
            checks.update(_control(prefix, spec, read))
        else:
            checks.update(_gate(name, prefix, spec, read))
    except (KeyError, IndexError, ValueError, TypeError, OSError, AttributeError) as error:
        checks['evidence_readable_and_well_formed'] = False
        return {'verdict': 'FAIL', 'checks': checks, 'problems': ['evidence unreadable: ' + type(error).__name__ + ': ' + str(error)]}
    failed = [key for key, value in checks.items() if value is not True]
    return {'verdict': 'FAIL' if failed else 'PASS', 'checks': checks, 'problems': failed}


def _console(prefix, action, read, targets, expected_env):
    """Checks that one `self approve` ended in a refusal before any prompt."""
    label = prefix + action['label']
    record = json.loads(read(label + '.command.json'))
    stderr, screen = _text(read(label + '.stderr.txt')), _text(read(label + '.console.txt'))
    command = record.get('command')
    shaped = (isinstance(command, list) and len(command) == 10 and isinstance(command[0], str) and command[0]
              and command[1:3] == ['-B', '-P'] and command[3:7] == ['-m', 'knowledgeos', 'self', 'approve']
              and command[7] == targets[action['target']] and command[8] == '--vault' and record.get('vault') == command[9])
    return {
        label + ':command_is_self_approve': bool(shaped),
        label + ':no_input_sent': record.get('input_sent') is False and record.get('shell') is False,
        label + ':never_waited_at_prompt': record.get('timed_out') is False and record.get('killed') is False
        and record.get('harness_stopped_child') is None,
        label + ':child_stopped_with_refusal_code': record.get('stopped') is True and record.get('exit_code') == 1
        and record.get('host_stopped') is True and record.get('host_exit_code') == 0 and record.get('host_error') is None,
        label + ':explicit_integrity_refusal': any(text in stderr for text in action['any']),
        label + ':not_a_missing_terminal_refusal': 'interactive terminal' not in stderr and 'Refusing' not in stderr
        and 'No answer possible' not in screen,
        label + ':no_prompt_or_preview_shown': not any(marker in screen + stderr for marker in FORBIDDEN_SCREEN) and not screen.strip(),
        label + ':environment_as_frozen': record.get('env_overrides') == expected_env,
    }


def _control(prefix, spec, read):
    action = spec['actions'][0]
    label = prefix + action['label']
    record = json.loads(read(label + '.command.json'))
    screen = _text(read(label + '.console.txt'))
    return {
        label + ':probe_is_real_console': record.get('surface') == 'console_probe' and record.get('stopped') is True
        and record.get('exit_code') == 0 and record.get('timed_out') is False and record.get('input_sent') is False
        and record.get('host_stopped') is True and record.get('host_exit_code') == 0,
        label + ':child_saw_terminal_on_stdin_and_stdout': screen.strip() == action['screen'],
    }


def _gate(name, prefix, spec, read):
    observation = json.loads(read(prefix + 'observation.json'))
    targets, env = observation['targets'], observation.get('env_overrides', {})
    expected_env = spec.get('env_overrides', {})
    checks = {'environment_matches_frozen_case': env == expected_env}
    self_before, self_after = read(prefix + 'self.before.md'), read(prefix + 'self.after.md')
    proposal_time = read(prefix + 'self.proposal-time.md')
    checks['self_bytes_unchanged'] = bool(self_before) and self_before == self_after
    checks['self_is_the_initialized_identity'] = b'type: person' in self_before and b'kos:section=heuristics' in self_before
    checks['self_setup_as_frozen'] = (self_before != proposal_time) == spec['self_changed_after_proposal']
    ledger_before, ledger_after = read(prefix + 'ledger.before.jsonl'), read(prefix + 'ledger.after.jsonl')
    rows = _rows(ledger_before) + _rows(ledger_after)
    checks['ledger_bytes_unchanged'] = ledger_before == ledger_after
    checks['no_ledger_row_applied'] = all(row.get('status') not in ('applied', 'superseded') and 'applied_at' not in row
                                          and 'authorized_by' not in row for row in rows)
    original, proposal_before, proposal_after = (read(prefix + 'proposal.' + phase + '.md') for phase in ('original', 'before', 'after'))
    checks['proposal_bytes_unchanged'] = bool(proposal_before) and proposal_before == proposal_after
    checks['proposal_setup_as_frozen'] = (proposal_before == original) == (spec['proposal_state'] == 'pristine')
    identifier = re.search(rb'^proposal_id: (\S+)\s*$', original, re.M)
    identifier = identifier.group(1).decode() if identifier else None
    setup_requests, setup = _mcp_exchange(read, prefix + 'setup-A', 1)
    checks['setup_proposal_created_by_public_tool'] = (
        setup_requests[2]['params']['name'] == 'memory_propose_self_update' and setup[0][0] is False
        and setup[0][1].get('ok') is True and setup[0][1].get('proposal_id') == identifier and identifier is not None
        and setup[0][1].get('proposal_path') == targets['A'] and setup[0][1].get('mutated_self') is False)
    if spec['ledger_registered_before']:
        matches = [row for row in _rows(ledger_before) if row.get('id') == identifier]
        checks['ledger_row_is_for_the_original_bytes'] = (
            len(matches) == 1 and matches[0].get('file_sha256') == _original_hash(original)
            and matches[0].get('status') in ('draft', 'rejected')
            and matches[0].get('status') == spec.get('ledger_status_before', 'draft'))
    else:
        checks['ledger_absent_as_frozen'] = ledger_before == b'' and ledger_after == b''
    people_before, people_after = (json.loads(read(prefix + 'files.' + phase + '.json')) for phase in ('before', 'after'))
    checks['people_tree_and_planted_files_unchanged'] = people_before == people_after
    checks['self_inventory_matches_bytes'] = people_after['people'].get('Self.md', {}).get('sha256') == _digest(self_after)
    state_before, state_after = (json.loads(read(prefix + 'state.' + phase + '.json')) for phase in ('before', 'after'))
    new = sorted(set(state_after) - set(state_before))
    checks['gate_state_unchanged'] = (all(state_after.get(path) == row for path, row in state_before.items())
                                      and set(new) <= set(spec.get('state_new_files_allowed', [])))
    mcp_actions = []
    for action in spec['actions']:
        if action['surface'] == 'console':
            checks.update(_console(prefix, action, read, targets, expected_env))
        elif action['surface'] == 'cli':
            label = prefix + action['label']
            record = json.loads(read(label + '.command.json'))
            stdout, stderr = _text(read(label + '.stdout.txt')), _text(read(label + '.stderr.txt'))
            command = record.get('command')
            checks[label + ':ran_the_frozen_command'] = (isinstance(command, list) and command[3:5] == ['-m', 'knowledgeos']
                                                         and command[5:5 + len(action['argv'])] == action['argv'] and record.get('shell') is False
                                                         and record.get('env_overrides') == expected_env and record.get('stopped') is True)
            checks[label + ':read_only_report'] = record.get('exit_code') == 0 and record.get('error') is None
            checks[label + ':ledger_failure_reported_and_nothing_listed'] = (
                any(text in stderr for text in action['stderr_any']) and not any(targets[key] in stdout for key in action['stdout_excludes'])
                and 'No Self proposals waiting for you.' in stdout)
        else:
            mcp_actions.append(action)
    if mcp_actions:
        label = prefix + 'mcp'
        record = json.loads(read(label + '.command.json'))
        command = record.get('command')
        requests, results = _mcp_exchange(read, label, len(mcp_actions))
        checks[label + ':process_clean'] = (isinstance(command, list) and command[3:5] == ['-m', 'knowledgeos'] and command[5] == 'mcp'
                                            and command[-2:] == ['--framing', 'ndjson'] and record.get('stopped') is True
                                            and record.get('exit_code') == 0 and record.get('error') is None and record.get('shell') is False
                                            and record.get('env_overrides') == expected_env)
        for index, action in enumerate(mcp_actions):
            call = prefix + action['label']
            params = requests[index + 2].get('params', {})
            is_error, payload = results[index]
            arguments_ok = params.get('name') == action['tool'] and params.get('arguments') == (
                {} if action['tool'] == 'memory_list_self_proposals' else {'proposal_path': targets[action['target']]})
            checks[call + ':asked_the_frozen_tool'] = arguments_ok
            message = str(payload.get('error') or '')
            if action['expect'] in ('refuse', 'accept_refuse'):
                refused = (is_error is True and any(text in message for text in action['any']) and payload.get('ok') is not True
                           and payload.get('mutated_self') is not True and payload.get('status') not in ('applied', 'accepted'))
                if action['expect'] == 'accept_refuse':
                    refused = refused and payload.get('policy') == 'human_only' and payload.get('mutated_self') is False
                checks[call + ':explicit_refusal'] = refused
            else:
                listed = payload.get('open')
                untrusted = payload.get('untrusted')
                paths = {item.get('path') for item in listed} if isinstance(listed, list) else None
                bad = {path for path in untrusted} if isinstance(untrusted, list) else None
                checks[call + ':listing_matches_frozen_trust'] = (
                    is_error is False and paths is not None and bad is not None
                    and all(targets[key] in paths for key in action.get('open_includes', []))
                    and all(targets[key] not in paths for key in action.get('open_excludes', []))
                    and all(targets[key] in bad for key in action.get('untrusted_includes', [])))
    return checks


def _evidence_name(api, directory, name):
    if (not isinstance(name, str) or not name or name in ('.', '..') or Path(name).name != name
            or '/' in name or '\\' in name or ':' in name):
        raise ValueError('Integrity evidence must name a contained retained file: ' + str(name))
    return api.data_evidence(directory, name)


def integrity_report(api, path, current):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Integrity report traverses lexical parents')
    directory = path.parent
    try:
        relative = directory.relative_to(api.ROOT.absolute())
    except ValueError:
        raise ValueError('Integrity report leaves contained synthetic evidence')
    if relative.parts[:2] != ('work', 'gc-artifacts') or '.knowledgeos' not in relative.parts[2:]:
        raise ValueError('Integrity report leaves contained synthetic evidence')
    api.data_evidence(directory, path.name)
    data = _loads(path.read_text(encoding='utf-8'))
    producer_path = Path(__file__).with_name('integrity.py')
    support = {'data_preservation.py': api.sha(Path(__file__).with_name('data_preservation.py'))}
    if (not isinstance(data, dict) or data.get('producer') != PRODUCER or data.get('producer_sha256') != api.sha(producer_path)
            or data.get('support_sha256') != support or data.get('support_sha256_after') != support):
        raise ValueError('Integrity producer or support hash is unknown or stale')
    api.check_product(data, 'product_hashes', current)
    api.check_product(data, 'product_hashes_after', current)
    if data.get('product_and_producer_unchanged') is not True:
        raise ValueError('Integrity product or producer changed during the run')
    if (data.get('scope') != 'source' or data.get('error') is not None or data.get('verdict') not in ('PASS', 'FAIL', 'NOT CHECKED')
            or not isinstance(data.get('platform'), str) or not data['platform'] or not isinstance(data.get('python'), str)
            or not data['python'] or not isinstance(data.get('revision'), str) or not re.fullmatch('[0-9a-f]{40}', data['revision'])
            or data.get('ideal_system_verdict') != 'NOT CHECKED' or data.get('acceptance_credit_awarded') is not False):
        raise ValueError('Integrity execution identity differs or the run did not finish cleanly')
    expected = _literal('EXPECTED')
    case_ids = ['identity.integrity.' + name for name in expected]
    rows = data.get('cases')
    if (data.get('expected_case_ids') != case_ids or not isinstance(rows, list) or [row.get('id') for row in rows if isinstance(row, dict)] != case_ids
            or len(rows) != len(case_ids)):
        raise ValueError('Integrity case list is missing, extra or reordered')
    evidence = data.get('evidence_files')
    if not isinstance(evidence, dict) or not evidence or path.name in evidence:
        raise ValueError('Integrity evidence inventory is missing')
    for name, digest in evidence.items():
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or api.sha(_evidence_name(api, directory, name)) != digest:
            raise ValueError('Integrity evidence is missing, escaped, linked or altered: ' + str(name))
    present = {item.name for item in directory.iterdir() if item.is_file()} - {path.name}
    if present != set(evidence) or any(item.is_symlink() for item in directory.iterdir()):
        raise ValueError('Integrity evidence inventory differs from the retained directory')

    def read(name):
        if name not in evidence:
            raise ValueError('Integrity required retained evidence is absent: ' + name)
        return _evidence_name(api, directory, name).read_bytes()

    def exists(name):
        return name in evidence

    frozen = _loads(_text(read('frozen-cases.json')))
    if frozen != {'producer': PRODUCER, 'case_ids': list(expected), 'expected': expected}:
        raise ValueError('Integrity frozen literal case list differs from the producer')
    if _text(read('console_host.py')).replace('\r\n', '\n') != _literal('HELPER_SOURCE'):
        raise ValueError('Integrity console helper differs from the current trusted producer')
    # Recompute every process record from the retained per-command evidence.
    derived = {}
    for name in sorted(evidence):
        if not name.endswith('.command.json'):
            continue
        record = _loads(_text(read(name)))
        role = name[:-len('.command.json')]
        if record.get('surface') in ('console', 'console_probe'):
            derived[role + '.host'] = (record.get('host_pid'), record.get('host_exit_code'), record.get('host_stopped'))
            derived[role + '.child'] = (record.get('pid'), record.get('exit_code'), record.get('stopped'))
        else:
            derived[role] = (record.get('pid'), record.get('exit_code'), record.get('stopped'))
    processes = data.get('processes')
    if not isinstance(processes, list) or not processes or data.get('all_started_processes_stopped') is not True:
        raise ValueError('Integrity process shutdown is incomplete')
    seen = {}
    for row in processes:
        if (not isinstance(row, dict) or not isinstance(row.get('role'), str) or row['role'] in seen or type(row.get('pid')) is not int
                or row['pid'] <= 0 or type(row.get('exit_code')) is not int or row.get('stopped') is not True
                or row.get('error') is not None or row.get('shell') is not False):
            raise ValueError('Integrity requires unique roles and typed stopped processes')
        seen[row['role']] = (row['pid'], row['exit_code'], row['stopped'])
    if seen != derived or any(value[2] is not True or type(value[0]) is not int or type(value[1]) is not int for value in derived.values()):
        raise ValueError('Integrity process records differ from retained command evidence or a process is not stopped')
    starts = [row['started_ns'] for row in processes if type(row.get('started_ns')) is int]
    if (type(data.get('frozen_at_ns')) is not int or not starts or min(starts) <= data['frozen_at_ns']):
        raise ValueError('Integrity case list was not frozen before the first process started')
    isolation = data.get('isolation', {})
    before = isolation.get('before') if isinstance(isolation, dict) else None
    if (not isinstance(before, dict) or before != isolation.get('after') or isolation.get('selected_sentinels_unchanged') is not True
            or {api.data_repository_location(key) for key in before} != set(SENTINELS)
            or any(value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)) for value in before.values())):
        raise ValueError('Integrity selected real-vault sentinels are missing or changed')
    verdicts, evidence_by_case = {}, {}
    for name, spec in expected.items():
        row = rows[case_ids.index('identity.integrity.' + name)]
        judged = judge_case(name, spec, read, exists)
        if row.get('verdict') != judged['verdict'] or row.get('expected') != spec['expected']:
            raise ValueError('Integrity reported case verdict or expectation contradicts the retained evidence: ' + name)
        verdicts[name] = judged['verdict']
        evidence_by_case[name] = sorted(file for file in evidence if file.startswith(name + '.'))
        if not evidence_by_case[name] or any(file not in evidence for file in row.get('evidence', [])):
            raise ValueError('Integrity case evidence is absent from the hashed inventory: ' + name)
    aggregate = 'PASS' if all(v == 'PASS' for v in verdicts.values()) else 'FAIL' if 'FAIL' in verdicts.values() else 'NOT CHECKED'
    if data['verdict'] != aggregate:
        raise ValueError('Integrity aggregate contradicts independently recomputed cases')
    return {'path': str(path), 'report_sha256': api.sha(path), 'scope': 'source', 'producer': data['producer'],
            'producer_sha256': data['producer_sha256'], 'support_sha256': support, 'integrity_adapter_sha256': api.sha(__file__),
            'evidence_files': evidence,
            'checks': {CHECK: {'id': CHECK, 'verdict': aggregate, 'expected': 'Tamper, stale-base, replay and invalid approval state fail closed with unchanged identity.',
                               'observed': verdicts, 'evidence': evidence_by_case}}}


def grade(api, paths, current):
    if not paths:
        raise ValueError('Integrity adapter needs at least one report')
    return [integrity_report(api, Path(path), current) for path in paths]
