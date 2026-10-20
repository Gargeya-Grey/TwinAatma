"""Exchange a fresh grading request with a native Windows observer on this machine."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).absolute().parents[4]
SCHEMA = "verify-twinaatma.native-grader-rendezvous/v1"
RECEIPT_KEYS = {"schema", "request_sha256", "response_sha256", "stderr_sha256",
                "command", "pid", "parent_pid", "exit_code", "stopped", "started_ns", "ended_ns",
                "watcher_sha256", "watcher_pid", "watcher_interpreter_sha256"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def channel_directory(path):
    path = Path(path).absolute()
    relative = path.relative_to(ROOT)
    if relative.parts[:3] != ("work", "gc-artifacts", ".knowledgeos") or len(relative.parts) < 4 or ".." in path.parts:
        raise ValueError("Native grading channel must be task-owned beneath work/gc-artifacts/.knowledgeos")
    cursor = path
    while True:
        info = cursor.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400):
            raise ValueError("Native grading channel uses a linked or non-directory path")
        if cursor == ROOT:
            break
        cursor = cursor.parent
    return path


def write_new(path, raw):
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def publish(path, raw):
    path = Path(path)
    temporary = path.with_name(path.name + ".publishing")
    if path.exists():
        raise ValueError("Native grading evidence already exists")
    write_new(temporary, raw)
    os.replace(temporary, path)


def checked_clock_windows(receipt, elapsed_ns):
    if (type(elapsed_ns) is not int or not 0 < elapsed_ns <= 300 * 1_000_000_000
            or any(type(receipt.get(key)) is not int or receipt[key] <= 0 for key in ("started_ns", "ended_ns"))
            or not 0 < receipt["ended_ns"] - receipt["started_ns"] <= 180 * 1_000_000_000):
        raise ValueError("Native grading exceeded its own observer window or bounded caller exchange")
    return {"caller_domain": "linux-monotonic", "caller_elapsed_ns": elapsed_ns,
            "observer_domain": "windows-wall", "observer_started_ns": receipt["started_ns"],
            "observer_ended_ns": receipt["ended_ns"],
            "freshness_basis": "Single-use channel, fresh request nonce, unchanged hashes and stopped native child within its Windows observer window"}


def invoke_windows(path, current, channel, *, bridge, operation="score"):
    bridge.require_wsl()
    if operation not in ("score", "installed-move"):
        raise ValueError("Native rendezvous accepts only the two declared grading operations")
    channel = channel_directory(channel)
    request = bridge.make_request(path, current, operation)
    raw = json.dumps(request, sort_keys=True, allow_nan=False).encode("utf-8")
    request_path = channel / "request.json"
    if any(channel.iterdir()):
        raise ValueError("Native grading requires a new empty channel")
    started_ns = time.time_ns()
    started_monotonic_ns = time.monotonic_ns()
    publish(request_path, raw)
    deadline = time.monotonic() + 300
    receipt_path = channel / "receipt.json"
    while not receipt_path.exists():
        if time.monotonic() >= deadline:
            raise ValueError("Fresh Windows grading receipt did not arrive within five minutes")
        time.sleep(0.5)
    receipt = bridge.parse_json(bridge.plain_file(receipt_path).read_text(encoding="utf-8"))
    response_path = bridge.plain_file(channel / "response.json")
    stderr_path = bridge.plain_file(channel / "stderr.txt")
    response = response_path.read_bytes()
    stderr = stderr_path.read_bytes()
    ended_ns = time.time_ns()
    elapsed_ns = time.monotonic_ns() - started_monotonic_ns
    command = [str(bridge.INTERPRETER), "-I", "-B", request["binding"]["helper"], bridge.NATIVE_FLAGS[operation]]
    if (not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS or receipt["schema"] != SCHEMA
            or receipt["request_sha256"] != sha(raw) or receipt["response_sha256"] != sha(response)
            or receipt["stderr_sha256"] != sha(stderr) or stderr or receipt["command"] != command
            or type(receipt["exit_code"]) is not int or receipt["exit_code"] != 0
            or receipt["stopped"] is not True
            or receipt["watcher_sha256"] != sha(Path(__file__).read_bytes())
            or receipt["watcher_interpreter_sha256"] != bridge.INTERPRETER_SHA256
            or any(type(receipt[key]) is not int or receipt[key] <= 0
                   for key in ("pid", "parent_pid", "watcher_pid", "started_ns", "ended_ns"))
            or receipt["parent_pid"] != receipt["watcher_pid"]
            or not response or len(response) > 16 * 1024 * 1024):
        raise ValueError("Fresh native grading command receipt is incomplete, changed or unsuccessful")
    clock_windows = checked_clock_windows(receipt, elapsed_ns)
    packet = bridge.validate_packet(bridge.parse_json(response.decode("utf-8")), request,
                                    receipt["started_ns"], receipt["ended_ns"])
    if packet["native"]["pid"] != receipt["pid"] or packet["native"]["parent_pid"] != receipt["watcher_pid"]:
        raise ValueError("Native grading packet is not from the observed stopped child")
    if bridge.binding(path, current, operation) != request["binding"] or request_path.read_bytes() != raw:
        raise ValueError("Native grading source, report or request changed during inspection")
    evidence = {"schema": SCHEMA, "mode": "fresh-wsl-windows-file-rendezvous", "operation": operation,
                "channel": str(channel), "receipt": receipt, "receipt_sha256": sha(receipt_path.read_bytes()),
                "request_sha256": sha(raw), "response_sha256": sha(response),
                "native": packet["native"], "binding": packet["binding"], "clock_windows": clock_windows,
                "caller_wall_observation": {"started_ns": started_ns, "ended_ns": ended_ns},
                "process": {"pid": receipt["pid"], "pid_namespace": "windows", "exit_code": 0,
                            "stopped": True, "watcher_pid": receipt["watcher_pid"]}}
    return packet["result"], evidence


def watch(channel, *, bridge, wait_seconds=1800):
    bridge.require_windows()
    channel = channel_directory(channel)
    request_path = channel / "request.json"
    deadline = time.monotonic() + wait_seconds
    while not request_path.exists():
        if (channel / "cancel.json").exists():
            raise ValueError("Root cancelled the waiting grading transport before a request")
        if time.monotonic() >= deadline:
            raise ValueError("Linux scorer did not publish a request before the watcher deadline")
        time.sleep(2)
    raw = bridge.plain_file(request_path).read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("Native grading request exceeds its bounded schema")
    request = bridge.parse_json(raw.decode("utf-8"))
    operation = request.get("operation")
    if request.get("schema") != bridge.SCHEMA + ".request" or operation not in ("score", "installed-move"):
        raise ValueError("Native watcher accepts only a strict grader request")
    bound = request.get("binding")
    if not isinstance(bound, dict) or bound.get("helper") != str(bridge.HELPER):
        raise ValueError("Native watcher refuses an unknown grading helper")
    command = [sys.executable, "-I", "-B", str(bridge.HELPER), bridge.NATIVE_FLAGS[operation]]
    started_ns = time.time_ns()
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        response, stderr = child.communicate(raw, timeout=180)
    except subprocess.TimeoutExpired:
        child.kill()
        response, stderr = child.communicate()
    ended_ns = time.time_ns()
    receipt = {"schema": SCHEMA, "request_sha256": sha(raw), "response_sha256": sha(response),
               "stderr_sha256": sha(stderr), "command": command, "pid": child.pid,
               "parent_pid": os.getpid(), "exit_code": child.returncode, "stopped": child.poll() is not None,
               "started_ns": started_ns, "ended_ns": ended_ns, "watcher_pid": os.getpid(),
               "watcher_sha256": sha(Path(__file__).read_bytes()),
               "watcher_interpreter_sha256": bridge.sha(bridge.plain_file(sys.executable))}
    publish(channel / "response.json", response)
    publish(channel / "stderr.txt", stderr)
    publish(channel / "receipt.json", json.dumps(receipt, sort_keys=True).encode("utf-8"))
    print(json.dumps({key: receipt[key] for key in ("pid", "exit_code", "stopped")}), flush=True)
    return 0 if child.returncode == 0 and not stderr else 2


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--watch":
        raise ValueError("Use the task-owned --watch channel entry point")
    helper_path = Path(__file__).with_name("advanced_host_native.py")
    spec = importlib.util.spec_from_file_location("_rendezvous_native_bridge", helper_path)
    bridge = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bridge
    spec.loader.exec_module(bridge)
    return watch(sys.argv[2], bridge=bridge)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError) as error:
        print("Native grading rendezvous rejected: " + str(error), file=sys.stderr)
        raise SystemExit(2)
