"""Validate complete native-host observations before mapping four fixed outcomes."""
from __future__ import annotations

import ctypes
import base64
import binascii
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
import tomllib

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "work/gc-artifacts/.knowledgeos/advanced-host-c-20261020"
FREEZE = ROOT / "work/gc-artifacts/.knowledgeos/acceptance-c-20261020/product-freeze.json"
FROZEN_SHA256 = "bfc17aa0b445bedfd63670c9d7f4f594faa70c575ec8b93a0ae9db38a38dc720"
RUBRIC = ROOT / ".agents/skills/verify-twinaatma/references/acceptance-rubric.json"
RUBRIC_SHA256 = "744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91"
PRODUCER = "verify-twinaatma.advanced-host-staged/v2"
LABELS = ("harbor-brief", "harbor-change", "harbor-next")
ROLES = ("init", "doctor", "setup", "host-version", *LABELS)
TARGETS = ("QUALITY.correction_lifecycle", "LEARNING.host_outcome_loop", "PRIVACY.selective_capture", "PRIVACY.untrusted_notes")
REQUIREMENTS = {identifier: ["advanced_host." + identifier] for identifier in TARGETS}
PINNED_SUPPORT = {
    "advanced_host.py": "884e7b3175162f1f6240c049af49a451bf29a3a44abc6e31924e60d523c71465",
    "controls.py": "d4d526f82feb76e162aa9e07e9b02459ca4c0bb242b416deac206ea497e6e3ee",
    "expectations.json": "b75ea9d59ec512e58dc6034aafaaaa455d59b5e97066b37d95195bd1e9104a1c",
    "prepared.json": "2a6904186a843e25eaa1370af822e9b50b51f3e47a7f7177ce45176508cd1287",
    "private/input.json": "746eb942e2338ce51b9c2a060d18e2e78c7714a085d42d11aeeeca40923f047c",
    "outbound-payload-review.json": "07a506fb2f0d63b67f9a133d41af051868dd589acf94c889f4c253c5cedb7972",
}
HEX = re.compile(r"[0-9a-f]{64}\Z")
RAW_EVIDENCE_SCHEMA = "verify-twinaatma.raw-evidence/v2"
NATIVE_CLI = Path("C:/Users/Gargeya/.codex/packages/standalone/releases/0.163.0-x86_64-pc-windows-msvc/bin/codex.exe")
NATIVE_CLI_SHA256 = "2692c8c7bb2cf8b0aefe638741fc90236f4b824c59578ce84994f9de58200993"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in retained host evidence")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def canonical(value):
    return json.loads(json.dumps(value, default=lambda item: item.isoformat() if isinstance(item, (datetime.date, datetime.datetime)) else None))


def plain_file(root, relative):
    root = Path(root).absolute()
    try:
        root.relative_to(ROOT.absolute())
    except ValueError as error:
        raise ValueError("Host evidence root is outside the current checkout") from error
    cursor = root
    while True:
        info = cursor.lstat()
        if cursor.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError("Host evidence root uses a linked path")
        if cursor == ROOT.absolute():
            break
        cursor = cursor.parent
    root = root.resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Host evidence requires a relative contained file")
    path = root / relative
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise ValueError("Host evidence escapes its retained directory") from error
    cursor = path
    while cursor != root:
        info = cursor.lstat()
        if cursor.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError("Host evidence uses a linked path")
        cursor = cursor.parent
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Host evidence is not a plain single-link file")
    return path


def rows(path):
    result = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line, object_pairs_hook=_unique_raw_pairs)
        if not isinstance(value, dict):
            raise ValueError("Host retained JSONL rows must be objects")
        result.append(value)
    return result


def fixture_vault_id(vault):
    root = Path(vault).absolute()
    observed = {}
    for directory in (root, *root.parents):
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("Host fixture vault contains a linked or non-directory parent")
        observed[directory] = info

    def identity(info):
        return info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns

    identifiers = set()
    marker_observations = {}
    for name in (".knowledgeos-vault.json", "knowledgeos.config.json"):
        path = root / name
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or getattr(before, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                or before.st_size > 65536):
            raise ValueError("Host fixture marker must be a bounded plain single-link file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if identity(before) != identity(opened):
                raise ValueError("Host fixture marker changed while opening")
            raw = stream.read(65537)
            after = os.fstat(stream.fileno())
            if (len(raw) > 65536 or identity(opened) != identity(after)
                    or opened.st_ctime_ns != after.st_ctime_ns):
                raise ValueError("Host fixture marker changed while reading")
        current = path.lstat()
        if identity(current) != identity(before) or current.st_ctime_ns != before.st_ctime_ns:
            raise ValueError("Host fixture marker changed after reading")
        marker_observations[path] = before
        marker = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_raw_pairs)
        if not isinstance(marker, dict):
            raise ValueError("Host fixture marker must be a JSON object")
        if "vault_id" in marker:
            identifier = marker["vault_id"]
            if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-fA-F]{32}", identifier) is None:
                raise ValueError("Host fixture marker needs its complete generated hexadecimal vault ID")
            identifiers.add(identifier.lower())
    for path, before in marker_observations.items():
        after = path.lstat()
        if identity(after) != identity(before) or after.st_ctime_ns != before.st_ctime_ns:
            raise ValueError("Host fixture marker changed during the two-marker observation")
    for directory, before in observed.items():
        after = directory.lstat()
        if (after.st_dev, after.st_ino, after.st_mode) != (before.st_dev, before.st_ino, before.st_mode):
            raise ValueError("Host fixture directory changed during observation")
    if len(identifiers) != 1:
        raise ValueError("Host fixture markers have no complete ID or disagree")
    return next(iter(identifiers))


def source_server(directory, server):
    if not isinstance(server, dict):
        raise ValueError("Generated source server must be a native configuration object")
    vault = Path(directory) / "vault"
    identifier = fixture_vault_id(vault)
    interpreter = server.get("command")
    args = ["-P", "-m", "knowledgeos", "mcp", "--host-vault-id", identifier, "--vault", str(vault)]
    if (set(server) != {"command", "args", "required", "default_tools_approval_mode", "env"}
            or not isinstance(interpreter, str) or not interpreter or not Path(interpreter).is_absolute()
            or not Path(interpreter).is_file() or server.get("args") != args or "cwd" in server
            or server.get("required") is not True or server.get("default_tools_approval_mode") != "approve"
            or server.get("env") != {"KNOWLEDGEOS_VAULT": str(vault), "PYTHONPATH": str(ROOT)}):
        raise ValueError("Generated server config does not bind the exact isolated source launcher and vault ID")
    return interpreter, args


def checked_authorization_values(directory, data, binding, authorization, claim, authorization_sha256,
                                 *, first_model_ns, initialized_ns):
    if (not isinstance(authorization_sha256, str) or not HEX.fullmatch(authorization_sha256)
            or data.get("root_authorization") != authorization_sha256
            or binding.get("root_authorization") != authorization_sha256
            or not isinstance(authorization, dict) or authorization.get("status") != "approved"
            or authorization.get("product_freeze_sha256") != FROZEN_SHA256
            or authorization.get("payload_inventory_sha256") != PINNED_SUPPORT["outbound-payload-review.json"]
            or not isinstance(authorization.get("allowed_units"), dict)
            or type(authorization["allowed_units"].get("advanced-source")) is not int
            or authorization["allowed_units"]["advanced-source"] != 3
            or not isinstance(authorization.get("direct_user_reply"), str) or not authorization["direct_user_reply"].strip()):
        raise ValueError("Host direct authorization does not bind the fixed product and reviewed three-chat unit")
    expected_claim = {"authorization_sha256": authorization_sha256, "product_freeze_sha256": FROZEN_SHA256,
                      "payload_inventory_sha256": PINNED_SUPPORT["outbound-payload-review.json"],
                      "directory": str(directory), "unit": "advanced-source", "maximum_model_conversations": 3}
    if (not isinstance(claim, dict) or set(claim) != {*expected_claim, "claimed_ns"}
            or any(claim.get(key) != value for key, value in expected_claim.items())
            or type(claim.get("maximum_model_conversations")) is not int
            or type(claim.get("claimed_ns")) is not int or claim["claimed_ns"] <= 0
            or type(first_model_ns) is not int or type(initialized_ns) is not int or initialized_ns <= 0
            or not initialized_ns <= claim["claimed_ns"] < first_model_ns):
        raise ValueError("Host authorization claim is absent, reused, mismatched or not recorded before its first model launch")


def authorization_support(directory, data, binding):
    authorization_path = plain_file(BASE, "human-trial-authorization.json")
    claim_path = plain_file(BASE, "advanced-source-claim.json")
    authorization_sha256, claim_sha256 = sha(authorization_path), sha(claim_path)
    authorization, claim = read_json(authorization_path), read_json(claim_path)
    first_model_ns = min(read_json(plain_file(directory, label + ".launch.json"))["started_ns"] for label in LABELS)
    initialized_ns = max(read_json(plain_file(directory, role + ".completion.json"))["ended_ns"] for role in ROLES if role not in LABELS)
    checked_authorization_values(directory, data, binding, authorization, claim, authorization_sha256,
                                 first_model_ns=first_model_ns, initialized_ns=initialized_ns)
    if sha(authorization_path) != authorization_sha256 or sha(claim_path) != claim_sha256:
        raise ValueError("Host authorization or single-use claim changed during observation")
    return {"human-trial-authorization.json": authorization_sha256, "advanced-source-claim.json": claim_sha256}


def checked_report_version(data, binding):
    if (type(data.get("schema_version")) is not int or data["schema_version"] != 2
            or data.get("producer") != PRODUCER
            or any(row.get("raw_evidence_schema") != RAW_EVIDENCE_SCHEMA for row in (data, binding))):
        raise ValueError("The complete C host report requires the v2 producer and exact raw schema")


def checked_profile_marker(project):
    if plain_file(project, ".twinaatma-host-profile").read_bytes() != b"synthetic-host-profile\n":
        raise ValueError("Host project discovery marker differs from its isolated literal profile")
    if any((project / name).exists() for name in (".knowledgeos-vault.json", "knowledgeos.config.json")):
        raise ValueError("Host profile contains an untracked legacy vault discovery marker")


def checked_wire_rows(wire, redactor):
    for row in wire:
        if not isinstance(row, dict) or row.get("kind") not in {"process", "request", "response", "stderr", "exit", "proxy-exit"}:
            raise ValueError("Host wire includes an unknown structural or payload row")
        if row["kind"] in {"request", "response", "stderr"}:
            if row.get("raw_evidence_schema") != RAW_EVIDENCE_SCHEMA:
                raise ValueError("Host wire payload cannot downgrade its v2 raw evidence")
            raw_envelope(row, redactor)


def checked_command_raw_schema(command, launch, final):
    if (any(row.get("raw_evidence_schema") != RAW_EVIDENCE_SCHEMA for row in (command, launch, final))
            or any(type(row.get(field)) is not int or row[field] < 0
                   for row in (command, final) for field in ("stdout_rows", "stdout_bytes"))
            or any(final.get(field) != command.get(field) for field in ("stdout_rows", "stdout_bytes"))):
        raise ValueError("Complete raw command launch/completion binding differs")


def checked_host_version(host_identity, record, events, redactor):
    if host_identity != {"name": "codex-cli", "version": "codex-cli 0.163.0", "configured_model": "gpt-6.1-sol", "mode": "native ephemeral source host"}:
        raise ValueError("Actual host version, configured model or native mode differs")
    raw = raw_stdout(events, record, redactor, role="host-version", require_current=True)
    command = record.get("command")
    if (raw != b"codex-cli 0.163.0\n" or hashlib.sha256(raw).hexdigest() != record.get("stdout_sha256")
            or command not in ([str(NATIVE_CLI), "--version"], ["codex", "--version"])
            or record.get("stopped") is not True or type(record.get("exit_code")) is not int or record["exit_code"] != 0):
        raise ValueError("Host identity is not the actual retained version command")
    try:
        for cursor in (NATIVE_CLI, *NATIVE_CLI.parents):
            info = cursor.lstat()
            if (cursor.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    or cursor == NATIVE_CLI and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                    or cursor != NATIVE_CLI and not stat.S_ISDIR(info.st_mode)):
                raise ValueError("Native host executable uses a linked or non-plain path")
        if NATIVE_CLI.resolve(strict=True) != NATIVE_CLI or sha(NATIVE_CLI) != NATIVE_CLI_SHA256:
            raise ValueError("Native host executable differs from its independent identity pin")
        if command[0] == "codex":
            resolved = shutil.which("codex")
            if not resolved or Path(resolved).resolve(strict=True) != NATIVE_CLI:
                raise ValueError("Bare host command does not resolve to the independently pinned executable")
    except OSError as error:
        raise ValueError("Native host executable identity is unavailable") from error
    return command[0]


def _legacy_raw_envelope(row, redactor, *, allow_cli_json=False):
    message = row.get("message")
    if (not (isinstance(message, dict) or allow_cli_json and isinstance(message, str)) or not HEX.fullmatch(str(row.get("raw_sha256", "")))
            or type(row.get("raw_bytes")) is not int or row["raw_bytes"] <= 0
            or row.get("forbidden_hits") != [] or redactor.hits(json.dumps(message, ensure_ascii=False))):
        raise ValueError("Host raw envelope is absent, malformed or records a privacy exposure")
    candidates = []
    if set(message) == {"text"}:
        candidates.append(message["text"].encode("utf-8"))
    for ascii_only in (False, True):
        for separators in ((",", ":"), (", ", ": ")):
            text = json.dumps(message, ensure_ascii=ascii_only, separators=separators)
            prefixes = ("", "    ") if allow_cli_json and isinstance(message, str) else ("",)
            candidates.extend((prefix + text + ending).encode("utf-8") for prefix in prefixes for ending in ("\n", "\r\n"))
    for candidate in candidates:
        if len(candidate) == row["raw_bytes"] and hashlib.sha256(candidate).hexdigest() == row["raw_sha256"]:
            return candidate
    raise ValueError("Retained redacted envelope cannot reproduce its original raw hash and length")


def _unique_raw_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in original raw output")
        result[key] = value
    return result


def _original_raw_message(raw):
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Original raw output is not valid UTF-8") from error
    try:
        return json.loads(text, object_pairs_hook=_unique_raw_pairs), True
    except json.JSONDecodeError:
        return {"text": text}, False


def raw_envelope(row, redactor, *, allow_cli_json=False):
    raw_keys = {"raw_evidence_schema", "raw_retention", "raw_base64"}
    if not raw_keys.intersection(row):
        return _legacy_raw_envelope(row, redactor, allow_cli_json=allow_cli_json)
    message = row.get("message")
    if (row.get("raw_evidence_schema") != RAW_EVIDENCE_SCHEMA or row.get("raw_retention") != "exact"
            or not isinstance(row.get("raw_base64"), str)
            or not (isinstance(message, dict) or allow_cli_json and isinstance(message, str))
            or not HEX.fullmatch(str(row.get("raw_sha256", "")))
            or type(row.get("raw_bytes")) is not int or row["raw_bytes"] <= 0
            or row.get("forbidden_hits") != [] or redactor.hits(json.dumps(message, ensure_ascii=False))):
        raise ValueError("Complete raw envelope is malformed, withheld or records a privacy exposure")
    try:
        raw = base64.b64decode(row["raw_base64"], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Complete raw envelope is not strict base64") from error
    if (base64.b64encode(raw).decode("ascii") != row["raw_base64"] or len(raw) != row["raw_bytes"]
            or hashlib.sha256(raw).hexdigest() != row["raw_sha256"] or redactor.hits(raw)):
        raise ValueError("Complete raw bytes differ from their count/hash or expose forbidden content")
    original, is_json = _original_raw_message(raw)
    if (json.dumps(original, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            != json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":"))):
        raise ValueError("Complete raw bytes disagree with the retained parsed message")
    if row.get("kind") in {"request", "response"} and (not is_json or not isinstance(original, dict)):
        raise ValueError("MCP protocol requires an original JSON object")
    return raw


def raw_stdout(events, record, redactor, *, role, require_current=False):
    if role not in ROLES or record.get("role") != role or record.get("stdout_forbidden_hits") != []:
        raise ValueError("Raw stdout role or privacy binding differs")
    schema = record.get("raw_evidence_schema")
    if require_current and schema != RAW_EVIDENCE_SCHEMA:
        raise ValueError("The complete C host stdout cannot downgrade its v2 raw evidence")
    if schema is None:
        if any({"raw_evidence_schema", "raw_retention", "raw_base64"}.intersection(row) for row in events):
            raise ValueError("A complete raw stream cannot downgrade to legacy aggregate binding")
        raw = b"".join(_legacy_raw_envelope(row, redactor, allow_cli_json=role not in LABELS) for row in events)
    else:
        if (schema != RAW_EVIDENCE_SCHEMA or type(record.get("stdout_rows")) is not int
                or record["stdout_rows"] != len(events) or type(record.get("stdout_bytes")) is not int
                or record["stdout_bytes"] < 0):
            raise ValueError("Complete raw stdout schema, row count or byte count is invalid")
        chunks = []
        for index, row in enumerate(events):
            if (row.get("raw_evidence_schema") != RAW_EVIDENCE_SCHEMA or row.get("role") != role
                    or type(row.get("line_index")) is not int or row["line_index"] != index):
                raise ValueError("Complete raw stdout role/order binding is invalid")
            chunk = raw_envelope(row, redactor, allow_cli_json=role not in LABELS)
            if chunk.splitlines(keepends=True) != [chunk]:
                raise ValueError("Complete raw stdout chunk does not represent one original line")
            if role in LABELS:
                original, is_json = _original_raw_message(chunk)
                if not is_json or not isinstance(original, dict):
                    raise ValueError("Host protocol stdout requires JSON objects only")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if len(raw) != record["stdout_bytes"]:
            raise ValueError("Complete raw stdout aggregate byte count differs")
    if hashlib.sha256(raw).hexdigest() != record.get("stdout_sha256"):
        raise ValueError("Host stdout differs from its original retained aggregate hash")
    return raw


def probe_pid(pid, launch_ns):
    result = {"pid": pid, "observed_ns": time.time_ns(), "method": "read-only kernel process wait", "stopped": False}
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            result.update(stopped=True, missing=True)
        except (PermissionError, OSError) as error:
            result["error"] = type(error).__name__
        return result
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00101000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        result.update(open_error=error, wait_result=None, stopped=error == 87)
        return result
    try:
        wait_result = kernel.WaitForSingleObject(handle, 0)
        result.update(open_error=None, wait_result=wait_result, stopped=False)
        from ctypes import wintypes
        creation, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        if kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            created_ns = (((creation.dwHighDateTime << 32) | creation.dwLowDateTime) - 116444736000000000) * 100
            result["current_creation_ns"] = created_ns
            result["pid_reused_after_original_launch"] = created_ns > launch_ns
            result["stopped"] = wait_result == 0 or result["pid_reused_after_original_launch"]
        else:
            result["creation_time_error"] = ctypes.get_last_error()
    finally:
        kernel.CloseHandle(handle)
    return result


def validate_lifetimes(directory, records, wire_by_label):
    lifetimes = {}
    probes = []
    expected_processes = []
    nested_processes = []
    for role in ROLES:
        command = records[role]
        launch_path = plain_file(directory, role + ".launch.json")
        final_path = plain_file(directory, role + ".completion.json")
        launch, final = read_json(launch_path), read_json(final_path)
        if (type(command.get("pid")) is not int or command["pid"] <= 0
                or command.get("role") != role or command.get("stopped") is not True
                or launch.get("schema") != "verify-twinaatma.command-launch/v1"
                or final.get("schema") != "verify-twinaatma.command-completion/v1"
                or any(row.get("run") != directory.name or row.get("role") != role or row.get("pid") != command["pid"] for row in (launch, final))
                or launch.get("command") != command.get("command") or launch.get("cwd") != command.get("cwd")
                or launch.get("stdin_sha256") != command.get("stdin_sha256")
                or type(launch.get("parent_pid")) is not int or launch["parent_pid"] <= 0
                or command.get("launch_sha256") != sha(launch_path) or final.get("launch_sha256") != sha(launch_path)
                or command.get("completion_sha256") != sha(final_path)
                or final.get("stopped") is not True or type(final.get("exit_code")) is not int or final["exit_code"] != 0
                or final["exit_code"] != command.get("exit_code") or final.get("failure") is not None
                or type(launch.get("started_ns")) is not int or type(final.get("ended_ns")) is not int or final["ended_ns"] <= launch["started_ns"]
                or not isinstance(final.get("seconds"), (int, float)) or final["seconds"] <= 0):
            raise ValueError("Host direct lifetime lacks an exact durable launch PID and final communicate/exit receipt")
        for field in ("stdout_sha256", "stderr_sha256", "stdout_forbidden_hits", "stderr_forbidden_hits"):
            if final.get(field) != command.get(field):
                raise ValueError("Host command and durable completion disagree on raw output")
        checked_command_raw_schema(command, launch, final)
        if final["stdout_forbidden_hits"] != [] or final["stderr_forbidden_hits"] != []:
            raise ValueError("Host command records a private output exposure")
        lifetimes[role] = (command["pid"], launch["started_ns"], final["ended_ns"])
        expected_processes.append({"pid": command["pid"], "role": role, "stopped": True, "exit_code": 0})
        if role not in LABELS:
            continue
        wire = wire_by_label[role]
        starts = [row for row in wire if row.get("kind") == "process"]
        exits = [row for row in wire if row.get("kind") == "exit"]
        proxy_exits = [row for row in wire if row.get("kind") == "proxy-exit"]
        if len(starts) != 1 or len(exits) > 1 or len(proxy_exits) > 1:
            raise ValueError("Host nested lifetimes lack one exact actual start or have duplicate exits")
        start = starts[0]
        if (any(type(start.get(key)) is not int or start[key] <= 0 for key in ("pid", "proxy_pid", "proxy_parent_pid", "started_ns"))
                or start["proxy_parent_pid"] != command["pid"]
                or len({start["pid"], start["proxy_pid"], command["pid"]}) != 3
                or start["started_ns"] < launch["started_ns"] or start["started_ns"] > final["ended_ns"]):
            raise ValueError("Host nested PID/parent/start/exit binding is incomplete")
        for exit_rows, key in ((exits, "pid"), (proxy_exits, "proxy_pid")):
            for row in exit_rows:
                if (row.get("pid") != start[key] or type(row.get("exit_code")) is not int
                        or type(row.get("ended_ns")) is not int or row["ended_ns"] < start["started_ns"]
                        or key == "proxy_pid" and row.get("parent_pid") != command["pid"]):
                    raise ValueError("Host nested retained exit differs from its actual launch identity")
        for key in ("pid", "proxy_pid"):
            observed = probe_pid(start[key], start["started_ns"])
            probes.append({"role": role + ":" + key, "wire": role + ".wire.jsonl", **observed})
            if not observed["stopped"]:
                raise ValueError("Host nested process shutdown remains unknown or running")
            nested_processes.append({"pid": start[key], "role": key, "stopped": True, "exit_code": exits[0]["exit_code"] if key == "pid" and exits else None, "wire": role + ".wire.jsonl"})
    if len({read_json(directory / (role + ".launch.json"))["parent_pid"] for role in ROLES}) != 1:
        raise ValueError("Host command launch receipts disagree on their owning driver")
    for left, (left_pid, left_start, left_end) in lifetimes.items():
        for right, (right_pid, right_start, right_end) in lifetimes.items():
            if left < right and left_pid == right_pid and max(left_start, right_start) < min(left_end, right_end):
                raise ValueError("Distinct concurrent host actors reuse one PID")
    return expected_processes + nested_processes, probes


def raw_stderr(path, expected):
    raw = Path(path).read_bytes()
    candidates = (raw, raw.replace(b"\r\n", b"\n"), raw.replace(b"\r\r\n", b"\r\n"))
    if not any(hashlib.sha256(candidate).hexdigest() == expected for candidate in candidates):
        raise ValueError("Host stderr cannot reproduce its original raw hash")


def adjacent_historical_advice(answer, old_source, replacement_sources):
    text = re.sub(r"[*_`]", "", answer)
    old_pair = r"delta\s+ferry\s+(?:at|for)\s+09:20"
    current_old = r"(?:current|book|everyday|now|use|recommend|should)[^.!?\n]{0,70}" + old_pair
    old_current = old_pair + r"[^.!?\n]{0,70}(?:current|everyday|now)"
    wrong_history = r"(?:historical|superseded|earlier|old|previous)[^.!?\n]{0,70}willow[^.!?\n]{0,30}08:40"
    if (len(re.findall(r"\bdelta\b", text, re.I)) != 1 or text.count("09:20") != 1
            or re.search(current_old + "|" + old_current + "|" + wrong_history, text, re.I)):
        return None
    date = r"(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\s+)?"
    attribution = re.compile(
        r"\A\s*(?:[-*+]\s+)?(?:what changed:\s*)?(?:the\s+)?" + date
        + r"owner correction replaces\s+" + old_pair + r"\.\s+"
        + r"(?:the|that|this)\s+(?:earlier|previous|old)\s+plan\s+(?:remains|is)\s+historical\s+evidence\.",
        re.I,
    )
    paragraphs = re.split(r"\n\s*\n|\n(?=\s*(?:[-*+]\s|\d+\.\s))", text)
    for paragraph in paragraphs:
        match = attribution.match(paragraph)
        if match is None:
            continue
        citations = re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", paragraph[match.end():])
        old_cited = any(path in {old_source, "../vault/" + old_source} for path in citations)
        replacements = [source for source in replacement_sources
                        if any(path in {source, "../vault/" + source} for path in citations)]
        if old_cited and len(replacements) == 1:
            return {"method": "adjacent explicit replacement and historical-plan sentences",
                    "text": match.group().strip(), "old_source": old_source,
                    "reviewed_current_source": replacements[0]}
    return None


def regrade_observation(host, observation, report):
    graded = host.grade(observation)
    if any(canonical(report.get(key)) != canonical(graded[key]) for key in ("checks", "outcomes", "complete_three_chat_evidence", "automatic_fixed54_credit")):
        raise ValueError("Manual or stale host verdict overrides do not match the independent offline regrade")
    if {row["id"] for row in graded["outcomes"]} != set(TARGETS) or len(graded["outcomes"]) != 4:
        raise ValueError("Host grader does not cover exactly the four fixed existing outcomes")
    checks = {row["id"]: row for row in graded["checks"]}
    advice = checks["host.corrected_advice"]
    observed = advice["observed"]
    associations = observed["associations"]
    candidate = (advice["verdict"] == "FAIL" and associations == {"current": True, "historical": False, "contextual": True}
                 and all(observed[key] is True for key in ("facts_present", "source_attribution", "no_invented_current", "no_invented_identity"))
                 and set(observed["labels"]) == {"current", "historical", "contextual", "inferred", "unknown"}
                 and all(value is True for value in observed["labels"].values()))
    witness = adjacent_historical_advice(observed["answer"], host.OLD,
                                        checks["host.correction_persisted"]["observed"]["replacement_paths"]) if candidate else None
    graded["grading_corrections"] = []
    if witness is not None:
        advice["verdict"] = "PASS"
        associations["historical"] = True
        observed["historical_attribution"] = witness
        for outcome in graded["outcomes"]:
            if outcome["id"] == "QUALITY.correction_lifecycle":
                outcome["verdict"] = "PASS" if (checks["host.correction_persisted"]["verdict"] == "PASS"
                                                and checks["host.lifecycle_safety"]["verdict"] == "PASS"
                                                and graded["complete_three_chat_evidence"] is True) else "FAIL"
        correction = {"check_id": "host.corrected_advice", "producer_reported_verdict": "FAIL",
                      "independently_recomputed_verdict": "PASS", "witness": witness}
        observed["grading_correction"] = correction
        graded["grading_corrections"].append(correction)
    return graded


def advanced_host_report(path, current):
    path = Path(path).absolute()
    directory = path.parent
    if directory.parent != BASE or not re.fullmatch(r"native-\d{8}-\d{6}-[0-9a-f]{8}", directory.name) or path.name != "report.json":
        raise ValueError("Host report is outside the trusted corrected journey")
    path = plain_file(directory, path.name)
    support = {name: sha(plain_file(BASE, name)) for name in PINNED_SUPPORT}
    if support != PINNED_SUPPORT:
        raise ValueError("Host original/current producer, support or literal expectations changed")
    if sha(plain_file(FREEZE.parent, FREEZE.name)) != FROZEN_SHA256 or sha(plain_file(RUBRIC.parent, RUBRIC.name)) != RUBRIC_SHA256:
        raise ValueError("Host frozen source manifest or fixed54 rubric changed")
    frozen = read_json(FREEZE)
    product = frozen.get("product_hashes") or frozen.get("product")
    if not isinstance(product, dict) or len(product) != 102 or any(sha(plain_file(ROOT, name)) != digest for name, digest in product.items()):
        raise ValueError("Host report is stale against the complete frozen source inputs")
    bound_current = {name: digest for name, digest in product.items() if name == "AGENTS.md" or Path(name).parent.as_posix() in ("knowledgeos", ".cursor/hooks") and Path(name).suffix == ".py"}
    if bound_current != current:
        raise ValueError("Host complete current source namespace differs from its frozen product")
    data = read_json(path)
    binding = read_json(plain_file(directory, "run-binding.json"))
    checked_report_version(data, binding)
    producer_hashes = {name: support[name] for name in ("advanced_host.py", "controls.py", "expectations.json")}
    if (data.get("directory") != str(directory)
            or data.get("source_hashes") != product or data.get("source_hashes_after") != product
            or data.get("producer_hashes") != producer_hashes or binding.get("producer_hashes") != producer_hashes
            or data.get("rubric_sha256") != RUBRIC_SHA256 or data.get("expected_sha256") != support["expectations.json"]
            or data.get("private_input_sha256") != support["private/input.json"] or data.get("failure") is not None
            or data.get("automatic_fixed54_credit") is not False
            or binding.get("product_manifest") != str(FREEZE) or binding.get("product_manifest_sha256") != FROZEN_SHA256
            or binding.get("product_hashes") != product or binding.get("expectations_sha256") != support["expectations.json"]
            or binding.get("private_input_sha256") != support["private/input.json"]
            or not data.get("root_authorization") or data["root_authorization"] != binding.get("root_authorization")):
        raise ValueError("Host report producer, source, expectations or run binding is incomplete")
    evidence = read_json(plain_file(directory, "evidence-hashes.json"))
    actual_names = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() and p.name != "evidence-hashes.json"}
    if not isinstance(evidence, dict) or set(evidence) != actual_names or any(sha(plain_file(directory, name)) != digest for name, digest in evidence.items()):
        raise ValueError("Host retained evidence inventory is incomplete or tampered")
    spec = importlib.util.spec_from_file_location("verified_advanced_host", BASE / "advanced_host.py")
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    private = read_json(BASE / "private/input.json")
    redactor = host.Redactor(private)
    if any(redactor.hits(plain_file(directory, name).read_bytes()) for name in evidence):
        raise ValueError("Host retained outputs contain disallowed private data")
    expectations = read_json(BASE / "expectations.json")
    checked_report_version(expectations, binding)
    prepared = read_json(BASE / "prepared.json")
    if (prepared.get("expectations_sha256") != support["expectations.json"]
            or prepared.get("private_input_sha256") != support["private/input.json"]
            or prepared.get("model_conversations_started") != 0
            or expectations.get("denominator") != 54 or expectations.get("rubric_sha256") != RUBRIC_SHA256
            or expectations.get("targets") != host.TARGETS
            or [prompt.get("label") for prompt in expectations.get("prompts", [])] != list(LABELS)):
        raise ValueError("Host prepared inputs do not bind the unchanged fixed54 literal journey")
    command_names = {p.name.removesuffix(".command.json") for p in directory.glob("*.command.json")}
    if command_names != set(ROLES):
        raise ValueError("Host command inventory contains missing or untracked direct actors")
    records = {role: read_json(plain_file(directory, role + ".command.json")) for role in ROLES}
    wire_by_label = {label: rows(plain_file(directory, label + ".wire.jsonl")) for label in LABELS}
    processes, probes = validate_lifetimes(directory, records, wire_by_label)
    support.update(authorization_support(directory, data, binding))
    for role in ROLES:
        events = rows(plain_file(directory, role + ".stdout.jsonl"))
        raw = raw_stdout(events, records[role], redactor, role=role, require_current=True)
        record = records[role]
        if hashlib.sha256(raw).hexdigest() != record.get("stdout_sha256"):
            raise ValueError("Host command output differs from original retained raw hashes")
        raw_stderr(plain_file(directory, role + ".stderr.txt"), record.get("stderr_sha256"))
        launch = read_json(directory / (role + ".launch.json"))
        if launch.get("environment_binding") != {"PYTHONPATH": str(ROOT), "KNOWLEDGEOS_STATE_DIR": str(directory / "gate-state"), "PYTHONDONTWRITEBYTECODE": "1"}:
            raise ValueError("Host child does not bind the exact checkout and isolated state")
    host_identity = data.get("host", {})
    host_executable = checked_host_version(host_identity, records["host-version"], rows(directory / "host-version.stdout.jsonl"), redactor)
    generated = tomllib.loads(plain_file(directory, "generated-config.toml").read_text(encoding="utf-8"))
    server = generated.get("mcp_servers", {}).get("knowledgeos", {})
    interpreter, server_args = source_server(directory, server)
    expected_commands = {
        "init": [interpreter, "-B", "-P", "-m", "knowledgeos", "init", str(directory / "vault"), "--name", "Synthetic Harborline Planner", "--non-interactive"],
        "doctor": [interpreter, "-B", "-P", "-m", "knowledgeos", "doctor", "--vault", str(directory / "vault")],
        "setup": [interpreter, "-B", "-P", "-m", "knowledgeos", "setup-host", "--host", "codex", "--vault", str(directory / "vault"), "--write"],
    }
    if any(records[role]["command"] != argv or records[role]["cwd"] != str(ROOT) for role, argv in expected_commands.items()):
        raise ValueError("Host initialization commands differ from the literal isolated public journey")
    snapshots = {label: read_json(plain_file(directory, label + ".sources.json")) for label in ("seeded", *LABELS, "final")}
    for snapshot in snapshots.values():
        for name, row in snapshot.items():
            if (not isinstance(row, dict) or set(row) != {"sha256", "text", "forbidden_hits"} or row["forbidden_hits"] != []
                    or not isinstance(row["text"], str) or hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != row["sha256"]):
                raise ValueError("Host source snapshot lacks original literal bytes or records a leak")
    for name, text in expectations["corpus"].items():
        if snapshots["seeded"].get(name, {}).get("text") != text:
            raise ValueError("Host source corpus differs from the predeclared literal fixture")
    actual_sources = {}
    for source in sorted((directory / "vault").rglob("*.md")):
        name = source.relative_to(directory / "vault").as_posix()
        raw = plain_file(directory / "vault", name).read_bytes()
        actual_sources[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode("utf-8"), "forbidden_hits": redactor.hits(raw)}
    if actual_sources != snapshots["final"]:
        raise ValueError("Actual final source bytes differ from the retained host snapshot")
    chats, thread_ids, session_ids = [], set(), set()
    for prompt in expectations["prompts"]:
        label = prompt["label"]
        project = directory / (label + "-project")
        record = records[label]
        launch = read_json(directory / (label + ".launch.json"))
        config_path = plain_file(project, ".codex/config.toml")
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        profile_server = config.get("mcp_servers", {}).get("knowledgeos", {})
        proxy_args = ["-B", "-P", str(BASE / "advanced_host.py"), "--proxy", str(directory / (label + ".wire.jsonl")), str(BASE / "private/input.json"), "--", interpreter, *server_args]
        if (set(config) != {"mcp_servers"} or set(config["mcp_servers"]) != {"knowledgeos"}
                or profile_server != {**server, "command": interpreter, "args": proxy_args, "env": {**server["env"], "KNOWLEDGEOS_STATE_DIR": str(directory / "gate-state"), "PYTHONDONTWRITEBYTECODE": "1"}}
                or launch.get("profile") != str(config_path) or launch.get("profile_sha256") != sha(config_path)
                or launch.get("project_agents_sha256") != sha(plain_file(project, "AGENTS.md"))
                or (project / "AGENTS.md").read_bytes() != plain_file(directory / "vault", "AGENTS.md").read_bytes()
                or launch.get("configured_model") != host_identity["configured_model"]):
            raise ValueError("Host project profile/source proxy/model binding differs")
        checked_profile_marker(project)
        argv = [host_executable, "--disable", "apps", "--disable", "plugins", "--disable", "remote_plugin", "exec", "--strict-config", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never", "-C", str(project), "-c", 'project_root_markers=[".twinaatma-host-profile"]', "-c", 'projects={' + json.dumps(str(project)) + '={trust_level="trusted"}}', "-m", host_identity["configured_model"]]
        if record["command"] != argv or record["cwd"] != str(project) or record["stdin_sha256"] != hashlib.sha256(prompt["text"].replace("{private_segment}", private["segment"]).encode("utf-8")).hexdigest():
            raise ValueError("Actual host argv, literal prompt or profile location differs")
        freeze = read_json(plain_file(directory, label + ".freeze.json"))
        if (freeze.get("manifest") != str(FREEZE) or freeze.get("manifest_sha256") != FROZEN_SHA256 or freeze.get("source_input_count") != 102
                or freeze.get("product_hashes") != product or type(freeze.get("observed_ns")) is not int or freeze["observed_ns"] > launch["started_ns"]):
            raise ValueError("Host chat lacks the complete original before-launch product freeze check")
        events = rows(plain_file(directory, label + ".stdout.jsonl"))
        wire = wire_by_label[label]
        checked_wire_rows(wire, redactor)
        starts = [row for row in wire if row.get("kind") == "process"]
        if starts[0].get("command") != [interpreter, *server_args] or starts[0].get("cwd") != str(project):
            raise ValueError("Actual wire server was not the configured source subprocess")
        initialize = [row["message"] for row in wire if row.get("kind") == "request" and row.get("message", {}).get("method") == "initialize"]
        if len(initialize) != 1 or initialize[0].get("params", {}).get("clientInfo", {}).get("version") != "0.163.0":
            raise ValueError("Actual MCP client identity differs from the genuine host")
        identifiers = [row["message"]["thread_id"] for row in events if row["message"].get("type") == "thread.started"]
        if len(identifiers) != 1 or identifiers[0] in thread_ids or not identifiers[0] or sum(row["message"].get("type") == "turn.completed" for row in events) != 1:
            raise ValueError("Host does not contain exactly three distinct completed model conversations")
        thread_ids.add(identifiers[0])
        calls = host.calls(wire)
        request_ids = [row["message"].get("id") for row in wire if row.get("kind") == "request" and "id" in row.get("message", {})]
        response_ids = [row["message"].get("id") for row in wire if row.get("kind") == "response"]
        if len(request_ids) != len(set(request_ids)) or len(response_ids) != len(set(response_ids)) or set(request_ids) != set(response_ids):
            raise ValueError("Host wire has duplicate, missing or unpaired protocol IDs")
        responses = {row["message"]["id"]: row["message"] for row in wire if row.get("kind") == "response"}
        tool_results = [responses[row["message"]["id"]].get("result", {}) for row in wire if row.get("kind") == "request" and row.get("message", {}).get("method") == "tools/call"]
        mcp_events = [row["message"]["item"] for row in events if row["message"].get("type") == "item.completed" and row["message"].get("item", {}).get("type") == "mcp_tool_call"]
        if (len(calls) != len(mcp_events) or any(item.get("server") != "knowledgeos" or item.get("tool") != call["name"] or item.get("arguments") != call["arguments"]
                or item.get("status") != "completed" or not isinstance(item.get("result"), dict) or item["result"].get("content") != result.get("content")
                or item["result"].get("structured_content") != result.get("structuredContent")
                for item, call, result in zip(mcp_events, calls, tool_results))):
            raise ValueError("Actual host tool calls differ from source-server wire requests")
        starts = [call for call in calls if call["name"] == "memory_session_start" and call["ok"]]
        ends = [call for call in calls if call["name"] == "memory_session_end" and call["ok"]]
        if len(starts) != 1 or len(ends) != 1 or not calls or calls[0] != starts[0] or calls[-1] != ends[0]:
            raise ValueError("Host session lifecycle does not wrap the actual complete tool conversation")
        session = starts[0]["payload"].get("session_id")
        if not session or session in session_ids or ends[0]["arguments"].get("session_id") != session or ends[0]["payload"].get("session_id") != session:
            raise ValueError("Host session ID propagation is absent or crosses conversations")
        session_ids.add(session)
        answer = "\n".join(row["message"].get("item", {}).get("text", "") for row in events if row["message"].get("type") == "item.completed" and row["message"].get("item", {}).get("type") == "agent_message")
        chats.append({"label": label, "exit_code": record["exit_code"], "answer": answer, "events": events, "wire": wire, "calls": calls, "prompt_sha256": record["stdin_sha256"], "evidence": [label + suffix for suffix in (".stdout.jsonl", ".wire.jsonl", ".command.json", ".stderr.txt")]})
    original = data.get("observations", {})
    expected_sentinels = {str(ROOT / "People/Self.md"), str(ROOT / "knowledge_index.db"), str(ROOT / ".knowledgeos/autopilot.json"), str(Path.home() / ".codex/config.toml")}
    before = original.get("protected_before")
    if not isinstance(before, dict) or set(before) != expected_sentinels or before != original.get("protected_after"):
        raise ValueError("Host protected source/isolation sentinels are absent or changed")
    if any((sha(Path(name)) if Path(name).is_file() else None) != digest for name, digest in before.items()):
        raise ValueError("Host protected source/isolation sentinels no longer match")
    self_sha = snapshots["seeded"].get("People/Self.md", {}).get("sha256")
    if not self_sha or any(snapshot.get("People/Self.md", {}).get("sha256") != self_sha for snapshot in snapshots.values()):
        raise ValueError("Host synthetic Self mutated during the journey")
    envelope, policy_proof = host.policy_evidence(directory / "vault", directory / "gate-state")
    if policy_proof.get("validated") is not True:
        raise ValueError("Host remembering policy lacks authenticated off-vault authority")
    actual_processes = original.get("processes")
    if actual_processes != processes or data.get("all_owned_processes_stopped") is not True:
        raise ValueError("Host reported processes differ from actual launch/exit/proxy lifetimes")
    observation = {"chats": chats, "snapshots": snapshots, "policy": envelope, "policy_proof": policy_proof, "exposures": [], "retained_logs_forbidden_free": True, "self_before": self_sha, "self_after": sha(directory / "vault/People/Self.md"), "protected_before": before, "protected_after": before, "processes": processes, "product_before": product, "product_after": product, "expected_sha256": support["expectations.json"]}
    if canonical(original) != canonical(observation):
        raise ValueError("Host reported observations differ from original retained tools, sources or answers")
    graded = regrade_observation(host, observation, data)
    rubric = read_json(RUBRIC)
    items = {item["id"]: item for item in rubric["outcomes"]}
    if len(items) != 54 or rubric.get("denominator") != 54:
        raise ValueError("Host outcome adapter requires the unchanged fixed54 rubric")
    checks = {}
    for row in graded["outcomes"]:
        if row["id"] not in TARGETS or items[row["id"]]["required_scope"] != "real_host":
            raise ValueError("Host grader attempted an unsupported outcome or scope")
        identifier = REQUIREMENTS[row["id"]][0]
        checks[identifier] = {"id": identifier, "verdict": row["verdict"], "expected": items[row["id"]]["expected"], "observed": {"regraded_outcome": row, "checks": canonical(graded["checks"]), "thread_ids": sorted(thread_ids), "session_ids": sorted(session_ids), "lifetime_probes": probes}, "evidence": sorted(evidence)}
    if set(checks) != {value[0] for value in REQUIREMENTS.values()}:
        raise ValueError("Host adapter requires all four complete existing outcomes")
    return {"path": str(path), "report_sha256": sha(path), "scope": "real_host", "producer": PRODUCER, "producer_sha256": support["advanced_host.py"], "adapter_sha256": sha(__file__), "host": host_identity, "transcript_files": evidence, "support_hashes": {str(BASE / name): digest for name, digest in support.items() if name != "private/input.json"}, "offline_regrade": {"original_report": str(path), "original_report_sha256": sha(path), "new_model_calls": 0, "method": "Independent retained raw envelopes, source snapshots, signed policy and exact command lifetimes; current trusted literal grader"}, "checks": checks}
