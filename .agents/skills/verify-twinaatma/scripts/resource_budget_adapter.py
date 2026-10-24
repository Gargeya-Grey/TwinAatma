"""Independently grade PORT.measured_resource_budget from retained raw MCP protocol and memory counters."""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3

PRODUCER = 'verify-twinaatma.resource-budget/v1'
CHECK = 'port.resource_budget'
REQUIRED_SCALES = (100, 1000, 10000)
MIN_SAMPLES = 20
BUDGET_SHA256 = '9455ea6ec444ba2218b8f8abc4d4dac7231ff3be0a880287d8bf8cf0c1f989d1'
BUDGET_SOURCE_LINE_SHA256 = 'e74a1ce1bd89f77b61e7f3357b9de7283ce100e7dc00c0660092e838841d943a'
BUDGET_VALUES = {
    'schema': 'twinaatma.owner-device-budget/v1', 'note_counts': [100, 1000, 10000], 'latency_statistic': 'p95',
    'model_response_time_excluded': True, 'startup_ms': 5000, 'capture_ms': 2000, 'recall_ms': 2000,
    'memory_process_peak_ram_bytes': 268435456, 'context_bytes': 16384, 'source_role': 'user'}
TOOLS = {'startup': 'memory_session_start', 'recall': 'memory_search', 'capture': 'memory_capture'}
GROUPS = (('startup', 'cold'), ('startup', 'warm'), ('recall', 'steady'), ('capture', 'steady'))
ROW_KEYS = {'scale', 'operation', 'kind', 'index', 'process', 'request_id', 'tool', 'ok', 'latency_ms'}
OPTIONAL_ROW_KEYS = {'response_bytes', 'context_bytes', 'context_field_bytes', 'results', 'expected_in_results',
                     'query', 'title', 'path'}
EXCLUDED_EVIDENCE_ROOTS = ('pycache',)
EXCLUDED_SCALE_DIRECTORIES = ('vault', 'gate-state', 'index-seed', 'initialized-baseline')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Resource-budget JSON contains duplicate keys')
        result[key] = value
    return result


def _loads(text):
    return json.loads(text, object_pairs_hook=_unique)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _is_int(value):
    return type(value) is int


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def percentile(values, quantile):
    """Nearest rank, computed here so the grader does not trust the producer's arithmetic."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError('Resource-budget statistic has no samples')
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def stats(values):
    return {'n': len(values), 'min': min(values), 'p50': percentile(values, 0.5),
            'p95': percentile(values, 0.95), 'max': max(values)}


def _producer_module():
    path = Path(__file__).with_name('resource_budget.py')
    spec = importlib.util.spec_from_file_location('resource_budget_producer_for_grading', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(api, directory, name):
    return api.retained_observation(directory, name)


def _jsonl(path):
    return [_loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _protocol(api, directory, evidence, label, cache):
    if label in cache:
        return cache[label]
    name = 'protocol/' + label + '.jsonl'
    if not re.fullmatch(r'[a-z0-9-]+', label) or name not in evidence:
        raise ValueError('Resource-budget sample has no hashed retained protocol: ' + label)
    events = _jsonl(_read(api, directory, name))
    stamps = [event.get('t_ns') for event in events]
    if (not events or events[0].get('event') != 'spawn' or sum(e.get('event') == 'spawn' for e in events) != 1
            or any(not _is_int(stamp) or stamp <= 0 for stamp in stamps) or stamps != sorted(stamps)):
        raise ValueError('Resource-budget protocol is not one ordered process timeline: ' + label)
    if events[-2:] and [e.get('event') for e in events[-2:]] != ['exit', 'stderr']:
        raise ValueError('Resource-budget protocol lacks a recorded shutdown: ' + label)
    cache[label] = events
    return events


def _response(events, request_id, tool):
    sends = [(i, e) for i, e in enumerate(events) if e.get('event') == 'send'
             and isinstance(e.get('data'), str) and _loads(e['data']).get('id') == request_id]
    if len(sends) != 1:
        raise ValueError('Resource-budget request is missing or duplicated in its protocol')
    position, send = sends[0]
    request = _loads(send['data'])
    if (request.get('method') != 'tools/call' or request.get('params', {}).get('name') != tool
            or not isinstance(request['params'].get('arguments'), dict)):
        raise ValueError('Resource-budget request is not the expected tool call')
    for event in events[position + 1:]:
        if event.get('event') == 'recv':
            try:
                message = _loads(event['data'])
            except ValueError:
                continue
            if message.get('id') == request_id:
                return request, send, event, message
        if event.get('event') in ('timeout', 'eof') and event.get('id') == request_id:
            return request, send, None, None
    raise ValueError('Resource-budget request has neither a response nor a recorded timeout')


def _recomputed_sample(api, directory, evidence, row, scale_dir, cache):
    events = _protocol(api, directory, evidence, row['process'], cache)
    spawn = events[0]
    request, send, received, message = _response(events, row['request_id'], TOOLS[row['operation']])
    base = spawn['t_ns'] if row['operation'] == 'startup' else send['t_ns']
    observed = {'ok': False}
    if received is None:
        return observed, None, request
    observed['latency_ms'] = (received['t_ns'] - base) / 1e6
    result = message.get('result') if isinstance(message.get('result'), dict) else {}
    content = result.get('content') if isinstance(result.get('content'), list) and result['content'] else [{}]
    text = content[0].get('text', '') if isinstance(content[0], dict) else ''
    if not isinstance(text, str):
        raise ValueError('Resource-budget response text is malformed')
    observed['response_bytes'] = len(text.encode('utf-8'))
    try:
        payload = _loads(text)
    except ValueError:
        payload = {}
    ok = isinstance(payload, dict) and not result.get('isError') and 'error' not in payload
    tool = row['operation']
    if tool == 'startup':
        context = payload.get('context') if isinstance(payload, dict) else None
        ok = ok and bool(context) and isinstance(payload.get('session_id'), str)
        observed['context_bytes'] = observed['response_bytes']
        observed['context_field_bytes'] = len((context if isinstance(context, str) else json.dumps(context, ensure_ascii=False)).encode('utf-8')) if context else 0
    elif tool == 'recall':
        ranked = payload.get('ranked') if isinstance(payload, dict) else None
        ok = ok and isinstance(ranked, list) and bool(ranked)
        observed['results'] = len(ranked) if isinstance(ranked, list) else 0
    else:
        path = payload.get('path') if isinstance(payload, dict) else None
        title = request['params']['arguments'].get('title')
        ok = ok and payload.get('ok') is True and isinstance(path, str) and isinstance(title, str)
        if ok:
            note = api.retained_observation(scale_dir / 'vault', path)
            ok = title in note.read_text(encoding='utf-8')
        observed['path'] = path
    observed['ok'] = bool(ok)
    return observed, received, request


def _process_memory(events, label, samples_end_ns):
    memory = [e for e in events if e.get('event') == 'memory']
    keys = ('peak_working_set_bytes', 'working_set_bytes', 'pagefile_usage_bytes', 'peak_pagefile_usage_bytes')
    if (not memory or any(not _is_int(e.get(k)) or e[k] <= 0 for e in memory for k in keys)
            or memory[-1]['t_ns'] < samples_end_ns):
        raise ValueError('Resource-budget memory counters are missing or were read before the last sample: ' + label)
    if any(e.get('children') != [] for e in memory):
        raise ValueError('Resource-budget measured process has children whose memory is not counted: ' + label)
    if any(e['peak_working_set_bytes'] < e['working_set_bytes'] for e in memory):
        raise ValueError('Resource-budget memory counters are inconsistent: ' + label)
    return {'peak_working_set_bytes': max(e['peak_working_set_bytes'] for e in memory),
            'peak_pagefile_usage_bytes': max(e['peak_pagefile_usage_bytes'] for e in memory),
            'last_pagefile_usage_bytes': memory[-1]['pagefile_usage_bytes']}


def _limits():
    return {'startup': BUDGET_VALUES['startup_ms'], 'capture': BUDGET_VALUES['capture_ms'],
            'recall': BUDGET_VALUES['recall_ms']}


def comparison(summary):
    """Budget comparison for one scale from recomputed statistics."""
    limits = _limits()
    rows = [('startup_p95_all_samples', 'startup_all', 'p95', limits['startup'], 'ms'),
            ('startup_p95_cold_samples', 'startup_cold', 'p95', limits['startup'], 'ms'),
            ('startup_p95_warm_samples', 'startup_warm', 'p95', limits['startup'], 'ms'),
            ('capture_p95', 'capture', 'p95', limits['capture'], 'ms'),
            ('recall_p95', 'recall', 'p95', limits['recall'], 'ms'),
            ('memory_process_peak_working_set_max', 'peak_working_set_bytes', 'max',
             BUDGET_VALUES['memory_process_peak_ram_bytes'], 'bytes'),
            ('context_bytes_max', 'context_bytes', 'max', BUDGET_VALUES['context_bytes'], 'bytes'),
            ('context_field_bytes_max', 'context_field_bytes', 'max', BUDGET_VALUES['context_bytes'], 'bytes')]
    return [{'metric': metric, 'observed': summary[group][statistic], 'limit': limit, 'unit': unit,
             'within': summary[group][statistic] <= limit} for metric, group, statistic, limit, unit in rows]


def _check_budget(api, directory, data, evidence):
    budget = data.get('budget')
    if not isinstance(budget, dict) or budget.get('copied_to') != 'budget/approved-budget.json':
        raise ValueError('Resource-budget report does not bind the approved budget')
    raw = _read(api, directory, 'budget/approved-budget.json').read_bytes()
    source = _read(api, directory, 'budget/human-budget-source.jsonl').read_bytes()
    if (_digest(raw) != BUDGET_SHA256 or budget.get('sha256') != BUDGET_SHA256
            or _digest(source) != BUDGET_SOURCE_LINE_SHA256 or budget.get('source_line_sha256') != BUDGET_SOURCE_LINE_SHA256):
        raise ValueError('Resource-budget file is not the owner-approved budget')
    values = _loads(raw.decode('utf-8'))
    if (any(values.get(key) != value for key, value in BUDGET_VALUES.items()) or budget.get('values') != values
            or values.get('source_line_sha256') != BUDGET_SOURCE_LINE_SHA256 or values.get('fixed_target') != 54):
        raise ValueError('Resource-budget values differ from the owner-approved budget')
    return values


def _check_device(api, directory, data):
    device = data.get('device')
    inventory = device.get('inventory') if isinstance(device, dict) else None
    if not isinstance(inventory, dict):
        raise ValueError('Resource-budget device inventory is missing')
    retained = _loads(_read(api, directory, 'commands/device-start.stdout.txt').read_text(encoding='utf-8-sig'))
    cpu, computer, system = inventory.get('cpu'), inventory.get('computer'), inventory.get('os')
    cpu = cpu[0] if isinstance(cpu, list) and cpu else cpu
    if (retained != inventory or not isinstance(cpu, dict) or not isinstance(cpu.get('Name'), str) or not cpu['Name']
            or not _is_int(cpu.get('NumberOfCores')) or cpu['NumberOfCores'] <= 0
            or not _is_int(cpu.get('NumberOfLogicalProcessors')) or not isinstance(computer, dict)
            or not _is_int(computer.get('TotalPhysicalMemory')) or computer['TotalPhysicalMemory'] <= 0
            or not isinstance(system, dict) or not str(system.get('BuildNumber', '')).isdigit()
            or device.get('power', {}).get('source') not in ('ac', 'battery', 'unknown')
            or not isinstance(device.get('python_version'), str) or not device['python_version']
            or 'cpu_load_percent_samples' not in inventory or 'power_plan' not in inventory):
        raise ValueError('Resource-budget device inventory is incomplete or differs from its retained command')
    end = data.get('device_end')
    if not isinstance(end, dict) or _loads(_read(api, directory, 'commands/device-end.stdout.txt').read_text(encoding='utf-8-sig')) != end.get('inventory'):
        raise ValueError('Resource-budget final device inventory is missing or differs from its retained command')
    load = inventory['cpu_load_percent_samples']
    end_load = end['inventory'].get('cpu_load_percent_samples')
    return {'cpu': cpu['Name'], 'physical_cores': cpu['NumberOfCores'], 'logical_processors': cpu['NumberOfLogicalProcessors'],
            'ram_bytes': computer['TotalPhysicalMemory'], 'os_build': system['BuildNumber'],
            'disk': inventory.get('disk'), 'power_source_start': device['power']['source'],
            'power_source_end': end.get('power', {}).get('source'), 'power_plan': inventory['power_plan'],
            'python': device['python_version'].split()[0],
            'cpu_load_percent_samples_start': load, 'cpu_load_percent_samples_end': end_load}


def resource_report(api, path, current):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Resource-budget report traverses lexical parents')
    directory = path.parent
    relative = directory.relative_to(api.ROOT.absolute())
    if relative.parts[:2] != ('work', 'gc-artifacts') or '.knowledgeos' not in relative.parts[2:]:
        raise ValueError('Resource-budget report leaves contained synthetic evidence')
    api.data_evidence(directory, path.name)
    data = _loads(path.read_text(encoding='utf-8'))
    producer_path = Path(__file__).with_name('resource_budget.py')
    if (not isinstance(data, dict) or data.get('producer') != PRODUCER or data.get('producer_sha256') != api.sha(producer_path)
            or data.get('support_sha256') != {} or data.get('support_sha256_after') != {}):
        raise ValueError('Resource-budget producer is unknown or stale')
    api.check_product(data, 'product_hashes', current)
    api.check_product(data, 'product_hashes_after', current)
    if (data.get('product_hashes_after') != data.get('product_hashes') or data.get('product_and_producer_unchanged') is not True
            or data.get('scope') != 'performance' or data.get('error') is not None
            or data.get('ideal_system_verdict') != 'NOT CHECKED' or data.get('acceptance_credit_awarded') is not False
            or not isinstance(data.get('platform'), str) or not data['platform'].startswith('Windows')
            or not isinstance(data.get('python'), str) or not data['python']
            or not isinstance(data.get('revision'), str) or not re.fullmatch('[0-9a-f]{40}', data['revision'])
            or data.get('percentile_method') != 'nearest-rank'):
        raise ValueError('Resource-budget execution identity is incomplete or stale')
    isolation = data.get('isolation')
    if (not isinstance(isolation, dict) or isolation.get('selected_sentinels_unchanged') is not True
            or not isinstance(isolation.get('before'), dict) or not isolation['before']
            or isolation.get('before') != isolation.get('after')):
        raise ValueError('Resource-budget real-vault sentinels changed or are missing')
    evidence = data.get('evidence_files')
    if (not isinstance(evidence, dict) or not evidence or path.name in evidence
            or any(not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for k, v in evidence.items())):
        raise ValueError('Resource-budget evidence inventory is missing')
    for name, digest in evidence.items():
        try:
            valid = _digest(_read(api, directory, name).read_bytes()) == digest
        except OSError:
            valid = False
        if not valid:
            raise ValueError('Resource-budget evidence is missing, escaped, linked or altered: ' + name)
    for candidate in sorted(directory.rglob('*')):
        if not candidate.is_file() or candidate == path:
            continue
        parts = candidate.relative_to(directory).parts
        if parts[0] in EXCLUDED_EVIDENCE_ROOTS or (parts[0] == 'scales' and len(parts) > 2 and parts[2] in EXCLUDED_SCALE_DIRECTORIES):
            continue
        if '/'.join(parts) not in evidence:
            raise ValueError('Resource-budget run directory holds unlisted evidence: ' + '/'.join(parts))
    if not _read(api, directory, 'commands/revision.stdout.txt').read_text(encoding='utf-8').strip() == data['revision']:
        raise ValueError('Resource-budget revision differs from its retained command')
    budget = _check_budget(api, directory, data, evidence)
    device = _check_device(api, directory, data)

    processes = data.get('processes')
    if (not isinstance(processes, list) or not processes or data.get('all_started_processes_stopped') is not True
            or any(not isinstance(p, dict) or p.get('stopped') is not True or not _is_int(p.get('pid')) or p['pid'] <= 0
                   or not _is_int(p.get('exit_code')) or not isinstance(p.get('role'), str) for p in processes)
            or len({p['role'] for p in processes}) != len(processes)):
        raise ValueError('Resource-budget process shutdown is incomplete')
    tracked = {p['role']: p for p in processes}
    compiled = _loads(_read(api, directory, 'commands/compile.command.json').read_text(encoding='utf-8'))
    compile_process = tracked.get('compile', {})
    if (compiled.get('exit_code') != 0 or compiled.get('stopped') is not True or compiled.get('error') is not None
            or compile_process.get('exit_code') != 0 or compile_process.get('pid') != compiled.get('pid')):
        raise ValueError('Resource-budget bytecode precompile did not complete successfully')

    requested, samples = data.get('requested_scales'), data.get('samples_per_operation')
    if (not isinstance(requested, list) or not requested or any(not _is_int(s) or s <= 0 for s in requested)
            or len(set(requested)) != len(requested) or not _is_int(samples) or samples <= 0
            or not isinstance(data.get('scales'), dict) or set(data['scales']) != {str(s) for s in requested}):
        raise ValueError('Resource-budget requested scales and recorded scales differ')

    producer = _producer_module()
    rows = _jsonl(_read(api, directory, 'samples.jsonl'))
    if len(rows) != data.get('sample_count') or len(rows) != 4 * samples * len(requested):
        raise ValueError('Resource-budget sample count differs from the requested matrix')
    cache, grouped, clean, seen = {}, {}, True, set()
    measured_requests = set()
    process_ends = {}
    for row in rows:
        if (not isinstance(row, dict) or not ROW_KEYS <= set(row) or not set(row) <= ROW_KEYS | OPTIONAL_ROW_KEYS
                or (row.get('operation'), row.get('kind')) not in GROUPS or row.get('scale') not in requested
                or not _is_int(row.get('index')) or not 0 <= row['index'] < samples or not _is_int(row.get('request_id'))
                or row.get('tool') != TOOLS[row['operation']] or type(row.get('ok')) is not bool
                or not _number(row.get('latency_ms')) or not isinstance(row.get('process'), str)):
            raise ValueError('Resource-budget sample row is malformed')
        key = (row['scale'], row['operation'], row['kind'], row['index'])
        if key in seen:
            raise ValueError('Resource-budget sample is duplicated')
        seen.add(key)
        request_key = (row['process'], row['request_id'])
        if request_key in measured_requests:
            raise ValueError('Resource-budget sample reuses a protocol request')
        measured_requests.add(request_key)
        scale_dir = directory / 'scales' / str(row['scale'])
        observed, received, _ = _recomputed_sample(api, directory, evidence, row, scale_dir, cache)
        for field, value in observed.items():
            if row.get(field) != value:
                raise ValueError('Resource-budget sample differs from its raw protocol: %s %s' % (row['process'], field))
        if received is None:
            if row['ok']:
                raise ValueError('Resource-budget sample claims success without a response')
        else:
            process_ends[row['process']] = max(process_ends.get(row['process'], 0), received['t_ns'])
        grouped.setdefault((row['scale'], row['operation'], row['kind']), []).append(row)
    for scale in requested:
        for operation, kind in GROUPS:
            if sorted(r['index'] for r in grouped.get((scale, operation, kind), [])) != list(range(samples)):
                raise ValueError('Resource-budget sample matrix is incomplete for scale %d %s %s' % (scale, operation, kind))

    memory_rows, summary_recomputed, scale_observed = {}, {}, {}
    for scale in requested:
        record = data['scales'][str(scale)]
        scale_dir = directory / 'scales' / str(scale)
        _check_workload(api, directory, scale_dir, scale, record, grouped, producer, evidence, samples)
        _check_initialized_baseline(api, directory, scale_dir, scale, record, evidence, cache, tracked, current, grouped)
        labels = sorted({r['process'] for r in rows if r['scale'] == scale})
        peaks = []
        for label in labels:
            events = cache[label]
            spawn = events[0]
            role = tracked.get(label)
            command = spawn.get('argv')
            expected = ['-P', '-m', 'knowledgeos', 'mcp', '--vault']
            if (role is None or role['pid'] != spawn.get('pid') or spawn.get('shell') is not False
                    or not isinstance(command, list) or command[1:6] != expected or command[7:] != ['--framing', 'ndjson']
                    or Path(command[6]).parts[-3:] != ('scales', str(scale), 'vault')):
                raise ValueError('Resource-budget process is not the recorded source MCP server: ' + label)
            exit_event = events[-2]
            if exit_event.get('exit_code') != role['exit_code'] or role.get('forced_kill') != exit_event.get('forced_kill'):
                raise ValueError('Resource-budget process exit differs from its protocol: ' + label)
            clean = clean and exit_event.get('exit_code') == 0 and exit_event.get('forced_kill') is False
            memory = _process_memory(events, label, process_ends.get(label, 0))
            peaks.append(dict(memory, process=label))
        memory_rows[str(scale)] = peaks
        pick = lambda operation, kind=None: [r for r in rows if r['scale'] == scale and r['operation'] == operation
                                              and (kind is None or r['kind'] == kind)]
        summary = {'startup_all': stats([r['latency_ms'] for r in pick('startup')]),
                   'startup_cold': stats([r['latency_ms'] for r in pick('startup', 'cold')]),
                   'startup_warm': stats([r['latency_ms'] for r in pick('startup', 'warm')]),
                   'capture': stats([r['latency_ms'] for r in pick('capture')]),
                   'recall': stats([r['latency_ms'] for r in pick('recall')]),
                   'context_bytes': stats([r['context_bytes'] for r in pick('startup')]),
                   'context_field_bytes': stats([r['context_field_bytes'] for r in pick('startup')]),
                   'peak_working_set_bytes': stats([p['peak_working_set_bytes'] for p in peaks]),
                   'peak_pagefile_usage_bytes': stats([p['peak_pagefile_usage_bytes'] for p in peaks])}
        summary_recomputed[str(scale)] = {'summary': summary, 'budget_comparison': comparison(summary)}
        scale_observed[str(scale)] = {
            'ok_samples': sum(r['ok'] for r in rows if r['scale'] == scale), 'samples': sum(r['scale'] == scale for r in rows)}
    if data.get('summary') != {k: v['summary'] for k, v in summary_recomputed.items()}:
        raise ValueError('Resource-budget summary disagrees with the retained raw samples')
    if data.get('budget_comparison') != {k: v['budget_comparison'] for k, v in summary_recomputed.items()}:
        raise ValueError('Resource-budget comparison disagrees with the retained raw samples')
    if data.get('process_memory') != memory_rows:
        raise ValueError('Resource-budget process memory differs from its retained counters')

    covered = sorted(requested) == list(REQUIRED_SCALES) and samples >= MIN_SAMPLES
    over = [dict(scale=int(scale), **row) for scale, value in summary_recomputed.items()
            for row in value['budget_comparison'] if not row['within']]
    failed_samples = {scale: v['samples'] - v['ok_samples'] for scale, v in scale_observed.items() if v['samples'] != v['ok_samples']}
    observed = {'requested_scales': sorted(requested), 'required_scales': list(REQUIRED_SCALES),
                'samples_per_operation': samples, 'minimum_samples_per_operation': MIN_SAMPLES,
                'percentile_method': 'nearest-rank', 'budget_sha256': BUDGET_SHA256,
                'budget': {k: BUDGET_VALUES[k] for k in ('startup_ms', 'capture_ms', 'recall_ms',
                                                       'memory_process_peak_ram_bytes', 'context_bytes')},
                'device': device, 'revision': data['revision'], 'summary': {k: v['summary'] for k, v in summary_recomputed.items()},
                'budget_comparison': {k: v['budget_comparison'] for k, v in summary_recomputed.items()},
                'over_budget': over, 'failed_samples': failed_samples, 'clean_shutdown': clean,
                'startup_budget_applies_to': 'every startup sample, with cold fresh processes restored to a complete initialized baseline',
                'coverage_complete': covered}
    if over or failed_samples or not clean:
        verdict = 'FAIL'
    elif not covered:
        verdict = 'NOT CHECKED'
    else:
        verdict = 'PASS'
    expected = ('At 100, 1000 and 10000 synthetic notes on the named device, at least %d repeated startup (cold and warm), capture '
                'and recall samples keep p95 startup <= %d ms, capture and recall <= %d ms, memory-process peak RAM <= %d bytes and '
                'context <= %d bytes, with all samples successful and all servers stopped') % (
        MIN_SAMPLES, BUDGET_VALUES['startup_ms'], BUDGET_VALUES['capture_ms'], BUDGET_VALUES['memory_process_peak_ram_bytes'],
        BUDGET_VALUES['context_bytes'])
    return {'path': str(path), 'report_sha256': api.sha(path), 'scope': 'performance', 'producer': PRODUCER,
            'checks': {CHECK: {'id': CHECK, 'verdict': verdict, 'expected': expected, 'observed': observed,
                               'evidence': sorted(evidence)}}}


def _check_workload(api, directory, scale_dir, scale, record, grouped, producer, evidence, samples):
    if (not isinstance(record, dict) or record.get('requested_notes') != scale or record.get('generator') != producer.GENERATOR
            or not _is_int(record.get('seed')) or not _is_int(record.get('base_indexed_notes'))
            or record.get('base_indexed_notes') + record.get('generated_notes', -1) != scale
            or record.get('indexed_notes_after_cold_start') != scale
            or record.get('indexed_notes_before_operations') != scale):
        raise ValueError('Resource-budget workload is not exactly %d indexed notes' % scale)
    notes = producer.generate_notes(record['generated_notes'], record['seed'])
    generated = producer.generated_inventory(notes)
    inventory_name = 'scales/%d/vault-inventory.json' % scale
    inventory = _loads(_read(api, directory, inventory_name).read_text(encoding='utf-8'))
    if (producer.inventory_digest(generated) != record.get('generated_inventory_sha256')
            or producer.inventory_digest(inventory) != record.get('vault_inventory_sha256')
            or len(inventory) != record.get('vault_files') or any(inventory.get(k) != v for k, v in generated.items())
            or sum(v['size'] for v in inventory.values()) != record.get('vault_bytes')):
        raise ValueError('Resource-budget vault inventory differs from the seeded generator')
    vault = scale_dir / 'vault'
    for relative, row in generated.items():
        if _digest(api.retained_observation(vault, relative).read_bytes()) != row['sha256']:
            raise ValueError('Resource-budget retained generated note was altered: ' + relative)


def _check_initialized_baseline(api, directory, scale_dir, scale, record, evidence, cache, tracked, current, grouped):
    name = 'scales/%d/initialized-baseline.json' % scale
    binding = record.get('initialized_baseline')
    if (not isinstance(binding, dict) or binding.get('path') != name or name not in evidence
            or binding.get('sha256') != evidence[name]):
        raise ValueError('Resource-budget initialized baseline is missing or unbound')
    baseline = _loads(_read(api, directory, name).read_text(encoding='utf-8'))
    if (baseline.get('schema') != 'twinaatma.resource-initialized-baseline/v1'
            or baseline.get('scale') != scale or baseline.get('indexed_notes') != scale
            or baseline.get('product_hashes') != current or baseline.get('seed') != record.get('seed')
            or baseline.get('generator') != record.get('generator')):
        raise ValueError('Resource-budget initialized baseline identity is incomplete or stale')
    root = scale_dir / 'initialized-baseline'
    for key, folder in (('vault', 'vault'), ('gate_state', 'gate-state')):
        inventory = baseline.get(key)
        if not isinstance(inventory, dict) or not inventory:
            raise ValueError('Resource-budget initialized baseline inventory is incomplete')
        actual = {}
        for candidate in sorted((root / folder).rglob('*')):
            if candidate.is_file():
                relative = candidate.relative_to(root / folder).as_posix()
                path = api.retained_observation(root / folder, relative)
                actual[relative] = {'size': path.stat().st_size, 'sha256': _digest(path.read_bytes())}
        if actual != inventory:
            raise ValueError('Resource-budget initialized baseline inventory is missing, linked or altered')
    vault_inventory = _loads(_read(api, directory, 'scales/%d/vault-inventory.json' % scale).read_text(encoding='utf-8'))
    if baseline['vault'] != vault_inventory:
        raise ValueError('Resource-budget initialized baseline does not bind the full source and index inventory')
    try:
        manifest_path = api.retained_observation(root / 'vault', '.knowledgeos/index-manifest.json')
        key_path = api.retained_observation(root / 'gate-state', 'gate.key')
        key = bytes.fromhex(key_path.read_text(encoding='ascii').strip())
        manifest = _loads(manifest_path.read_text(encoding='utf-8'))
        body = {k: v for k, v in manifest.items() if k != 'mac'}
        signature = hmac.new(key, json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8'), hashlib.sha256).hexdigest()
        if manifest.get('version') != 1 or not hmac.compare_digest(str(manifest.get('mac')), signature):
            raise ValueError('Resource-budget initialized baseline manifest signature is invalid')
        files = manifest.get('files')
        if not isinstance(files, dict) or len(files) != scale or not manifest.get('index'):
            raise ValueError('Resource-budget initialized baseline manifest is incomplete')
        for relative, row in files.items():
            path = api.retained_observation(root / 'vault', relative)
            if row != [path.stat().st_size, path.stat().st_mtime_ns, _digest(path.read_bytes())]:
                raise ValueError('Resource-budget initialized baseline manifest is stale')
        database = api.retained_observation(root / 'vault', 'knowledge_index.db')
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        try:
            indexed = dict(connection.execute('SELECT path, file_hash FROM notes'))
        finally:
            connection.close()
        if len(indexed) != scale or set(indexed) != set(files):
            raise ValueError('Resource-budget initialized baseline index is incomplete')
        for relative, digest in indexed.items():
            path = api.retained_observation(root / 'vault', relative)
            if _digest(path.read_bytes()) != digest:
                raise ValueError('Resource-budget initialized baseline index does not match its source')
    except (OSError, sqlite3.Error, KeyError, TypeError) as error:
        raise ValueError('Resource-budget initialized baseline signing or index state is incomplete') from error
    label = baseline.get('setup_process')
    if label != 'setup-%d' % scale or not _is_int(baseline.get('setup_request_id')):
        raise ValueError('Resource-budget initialized baseline has no untimed public startup')
    events = _protocol(api, directory, evidence, label, cache)
    role = tracked.get(label, {})
    reference_spawn = cache[grouped[(scale, 'startup', 'cold')][0]['process']][0]
    if (role.get('pid') != events[0].get('pid') or role.get('exit_code') != 0 or role.get('forced_kill') is not False
            or events[-2].get('exit_code') != 0 or events[-2].get('forced_kill') is not False
            or events[0].get('argv') != reference_spawn.get('argv') or events[0].get('shell') is not False
            or events[0].get('state_dir') != reference_spawn.get('state_dir')):
        raise ValueError('Resource-budget initialized baseline setup did not stop cleanly')
    _, _, received, message = _response(events, baseline['setup_request_id'], 'memory_session_start')
    result = (message or {}).get('result', {})
    try:
        payload = _loads(result['content'][0]['text'])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError('Resource-budget initialized baseline setup response is missing') from error
    if received is None or result.get('isError') or not payload.get('context') or not isinstance(payload.get('session_id'), str):
        raise ValueError('Resource-budget initialized baseline setup was not successful')
    state = {'vault': baseline['vault'], 'gate_state': baseline['gate_state']}
    state_digest = _digest(json.dumps(state, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    for row in grouped[(scale, 'startup', 'cold')]:
        spawn = cache[row['process']][0]
        if (spawn.get('initialized_baseline_sha256') != binding['sha256']
                or spawn.get('initialized_state_sha256') != state_digest or spawn['t_ns'] <= events[-2]['t_ns']):
            raise ValueError('Resource-budget cold sample does not bind the complete initialized baseline')


def grade(api, paths, current):
    return [resource_report(api, path, current) for path in paths]
