"""Prove that the Self gate fails closed on tamper, stale base, replay and invalid approval state.

Every case drives public surfaces only: the MCP server over stdio NDJSON, the CLI, and
`self approve` inside a hidden real Windows console. No answer is ever sent to an approval
prompt. A case that reaches the prompt fails and its exact child process is stopped.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import sys
import time

from data_preservation import DataRun, ROOT, inventory, sha

PRODUCER = "verify-twinaatma.integrity/v1"
SCOPE = "source"
GATE_KEY = "integrity-synthetic-mismatched-gate-key-9f2c1a7d"
PROPOSAL_A = "- Synthetic addition IA1. Compare retained evidence before revising this test preference."
PROPOSAL_B = "- Synthetic addition IB1. Keep explicit evidence above untested confidence."

# The frozen literal case list. It is written to frozen-cases.json before any product process
# starts, and the grader reads this very literal from the hashed producer source.
EXPECTED = {
    "console_control": {
        "kind": "control",
        "expected": "The hidden console gives a child a real terminal on stdin and stdout, so a later refusal is not a missing-terminal refusal",
        "actions": [{"label": "probe", "surface": "console_probe", "screen": "stdin_tty=True stdout_tty=True"}],
    },
    "body_tampered": {
        "kind": "gate", "proposal_state": "altered", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A proposal whose proposed body was edited after creation is refused before the approval prompt; Self and ledger stay unchanged",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal content was edited after it was created"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["proposal file was edited after it was created"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "frontmatter_tampered": {
        "kind": "gate", "proposal_state": "altered", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A proposal whose frontmatter mode was edited after creation is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal file was edited after it was created"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["proposal file was edited after it was created"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "target_section_tampered": {
        "kind": "gate", "proposal_state": "altered", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A proposal whose claimed target section was edited after creation is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal file was edited after it was created"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["proposal file was edited after it was created"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "stale_base": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": True, "ledger_registered_before": True,
        "expected": "A proposal made against an earlier Self is refused before the approval prompt after Self changed",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["Self.md changed since this proposal was created"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "replay_rejected": {
        "kind": "gate", "ledger_status_before": "rejected", "proposal_state": "altered", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A rejected proposal presented again is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal file was edited after it was created"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["proposal already rejected"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "replay_rejected_restored": {
        "kind": "gate", "ledger_status_before": "rejected", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A rejected proposal restored to its exact original bytes and presented again is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["rejected"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["proposal already rejected"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "replay_copy_new_name": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A byte-identical copy of a valid proposal under a new filename is refused as unregistered before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "COPY", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "COPY", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "COPY", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "row_repointed": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A ledger row repointed to another file, with its old signature, authorizes neither file",
        "actions": [
            {"label": "approve-copy", "surface": "console", "target": "COPY", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "approve-original", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "COPY", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "COPY", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
            {"label": "list", "surface": "mcp", "tool": "memory_list_self_proposals", "expect": "list", "open_excludes": ["A", "COPY"], "untrusted_includes": ["A", "COPY"]},
        ],
    },
    "row_reused_other_content": {
        "kind": "gate", "proposal_state": "altered", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A ledger row for one proposal does not authorize a different proposal's bytes placed at its path",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal content was edited after it was created"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["proposal file was edited after it was created"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "ledger_mac_broken": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A ledger row with a broken signature is ignored, so its proposal is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "pending", "surface": "cli", "argv": ["self", "pending"], "stdout_excludes": ["A"], "stderr_any": ["failed signature check"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
            {"label": "list", "surface": "mcp", "tool": "memory_list_self_proposals", "expect": "list", "open_excludes": ["A"], "untrusted_includes": ["A"]},
        ],
    },
    "ledger_unsigned_row": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A ledger row stripped of its signature is ignored, so its proposal is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "pending", "surface": "cli", "argv": ["self", "pending"], "stdout_excludes": ["A"], "stderr_any": ["failed signature check"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "ledger_missing": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": False,
        "expected": "A deleted ledger leaves no proposal registered, so the proposal is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "signing_key_replaced": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A replaced signing key invalidates every ledger row, so the proposal is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "pending", "surface": "cli", "argv": ["self", "pending"], "stdout_excludes": ["A"], "stderr_any": ["failed signature check"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "signing_key_missing": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "state_new_files_allowed": ["gate.key"],
        "expected": "A missing signing key invalidates every ledger row, so the proposal is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "gate_key_env_mismatch": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "env_overrides": {"KNOWLEDGEOS_GATE_KEY": "integrity-synthetic-mismatched-gate-key-9f2c1a7d"},
        "expected": "A gate key from the environment that differs from the signing key invalidates every ledger row, so the proposal is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["proposal is not registered in this install's Self proposal ledger"]},
            {"label": "pending", "surface": "cli", "argv": ["self", "pending"], "stdout_excludes": ["A"], "stderr_any": ["failed signature check"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["not a Self proposal registered in this install's ledger"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "mcp_accept_refuses": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "The MCP accept tool refuses every proposal path, valid or not, and leaves the valid proposal an open draft",
        "actions": [
            {"label": "accept-valid", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
            {"label": "accept-missing", "surface": "mcp", "tool": "memory_accept_self_update", "target": "MISSING", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
            {"label": "accept-outside", "surface": "mcp", "tool": "memory_accept_self_update", "target": "OUTSIDE", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
            {"label": "accept-self", "surface": "mcp", "tool": "memory_accept_self_update", "target": "SELF", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
            {"label": "list", "surface": "mcp", "tool": "memory_list_self_proposals", "expect": "list", "open_includes": ["A"]},
        ],
    },
    "path_outside_proposals": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True,
        "expected": "A proposal path outside the proposals directory is refused before the approval prompt, including Self itself",
        "actions": [
            {"label": "approve-inbox", "surface": "console", "target": "INBOX", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "approve-self", "surface": "console", "target": "SELF", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "approve-parent", "surface": "console", "target": "PARENT", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "reject-inbox", "surface": "mcp", "tool": "memory_reject_self_update", "target": "INBOX", "expect": "refuse", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "reject-self", "surface": "mcp", "tool": "memory_reject_self_update", "target": "SELF", "expect": "refuse", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "reject-parent", "surface": "mcp", "tool": "memory_reject_self_update", "target": "PARENT", "expect": "refuse", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "INBOX", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "path_through_link": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True, "needs_links": True,
        "expected": "A proposal path reached through a symbolic link or a hard link is refused before the approval prompt",
        "actions": [
            {"label": "approve-link-self", "surface": "console", "target": "LINK_SELF", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "approve-link-outside", "surface": "console", "target": "LINK_OUTSIDE", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "approve-hardlink", "surface": "console", "target": "HARDLINK", "any": ["proposal is hard-linked; refusing to write through it"]},
            {"label": "reject-link-self", "surface": "mcp", "tool": "memory_reject_self_update", "target": "LINK_SELF", "expect": "refuse", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "reject-link-outside", "surface": "mcp", "tool": "memory_reject_self_update", "target": "LINK_OUTSIDE", "expect": "refuse", "any": ["not a Self proposal in People/Self-Proposals"]},
            {"label": "reject-hardlink", "surface": "mcp", "tool": "memory_reject_self_update", "target": "HARDLINK", "expect": "refuse", "any": ["proposal is hard-linked; refusing to write through it"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "LINK_SELF", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
    "proposals_dir_redirected": {
        "kind": "gate", "proposal_state": "pristine", "self_changed_after_proposal": False, "ledger_registered_before": True, "needs_links": True,
        "expected": "A proposals directory replaced by a link is refused before the approval prompt",
        "actions": [
            {"label": "approve", "surface": "console", "target": "A", "any": ["People/Self-Proposals is not a plain directory inside the vault"]},
            {"label": "reject", "surface": "mcp", "tool": "memory_reject_self_update", "target": "A", "expect": "refuse", "any": ["People/Self-Proposals is not a plain directory inside the vault"]},
            {"label": "accept", "surface": "mcp", "tool": "memory_accept_self_update", "target": "A", "expect": "accept_refuse", "any": ["Self.md changes must be approved by the human in a terminal"]},
        ],
    },
}

# The helper runs inside a hidden real console. It starts `self approve` with the console as
# stdin and stdout and a file as stderr. It never sends input. It reads the console screen back
# as the retained stdout and stops its exact child if the child is still waiting at a deadline.
HELPER_SOURCE = r'''import argparse
import ctypes
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import time
from ctypes import wintypes


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class INFO(ctypes.Structure):
    _fields_ = [("size", COORD), ("cursor", COORD), ("attributes", wintypes.WORD), ("window", SMALL_RECT), ("maximum", COORD)]


def screen(handle):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(INFO)]
    kernel.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    kernel.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, COORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.ReadConsoleOutputCharacterW.restype = wintypes.BOOL
    info = INFO()
    if not kernel.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "console screen buffer is unreadable")
    lines = []
    for row in range(info.cursor.Y + 1):
        buffer = ctypes.create_unicode_buffer(info.size.X + 1)
        count = wintypes.DWORD()
        if not kernel.ReadConsoleOutputCharacterW(handle, buffer, info.size.X, COORD(0, row), ctypes.byref(count)):
            raise OSError(ctypes.get_last_error(), "console row is unreadable")
        lines.append(buffer.value[:count.value].rstrip())
    return "\n".join(lines).rstrip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--screen", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    console_in = os.open("CONIN$", os.O_RDWR)
    console_out = os.open("CONOUT$", os.O_RDWR)
    with open(args.stderr, "wb") as errors:
        started = time.time_ns()
        child = subprocess.Popen(command, cwd=args.cwd, stdin=console_in, stdout=console_out, stderr=errors)
        Path(args.result + ".pid").write_text(json.dumps({"host_pid": os.getpid(), "child_pid": child.pid}), encoding="utf-8")
        timed_out = False
        try:
            code = child.wait(timeout=args.deadline)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            code = child.wait()
        finished = time.time_ns()
    text = screen(msvcrt.get_osfhandle(console_out))
    Path(args.screen).write_text(text, encoding="utf-8", newline="")
    record = {"host_pid": os.getpid(), "child_pid": child.pid, "child_exit_code": code, "timed_out": timed_out,
              "killed": timed_out, "input_sent": False, "started_ns": started, "finished_ns": finished,
              "command": command, "stdin": "console input buffer (CONIN$), never written", "stdout": "console screen buffer (CONOUT$), read back after exit"}
    Path(args.result).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PY = sys.executable
CONSOLE_DEADLINE = 25.0


class LinkUnavailable(Exception):
    pass


def module_command(*arguments):
    return [PY, "-B", "-P", "-m", "knowledgeos", *arguments]


def product_hashes():
    paths = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT / "AGENTS.md"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file()}


class IntegrityRun(DataRun):
    def __init__(self, output):
        super().__init__(output)
        self.producer_hash = sha(__file__)
        self.support = {"data_preservation.py": sha(Path(__file__).with_name("data_preservation.py"))}
        self.product = product_hashes()
        self.base_env = dict(self.env)
        for key in ("KNOWLEDGEOS_GATE_KEY", "KNOWLEDGEOS_STATE_DIR"):
            self.base_env.pop(key, None)
        self.errors = {}
        self.unavailable = {}
        self.frozen_at_ns = None

    # ----- retained files -------------------------------------------------------------------

    def put(self, name, data):
        raw = data if isinstance(data, bytes) else data.encode("utf-8")
        (self.directory / name).write_bytes(raw)

    # ----- ordinary children ----------------------------------------------------------------

    def child(self, label, argv, cwd, env, vault=None, stdin_text=None, timeout=90, overrides=None):
        argv = [str(part) for part in argv]
        stdin_bytes = None if stdin_text is None else stdin_text.encode("utf-8")
        started = time.time_ns()
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        error, interruption = None, None
        try:
            stdout, stderr = process.communicate(stdin_bytes, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            error = "Command exceeded the proof deadline"
        except BaseException as caught:
            process.kill()
            stdout, stderr = process.communicate()
            error, interruption = str(caught), caught
        finally:
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode, error=error, shell=False,
                           started_ns=started, finished_ns=time.time_ns())
        self.put(label + ".stdin.txt", stdin_bytes or b"")
        self.put(label + ".stdout.txt", stdout)
        self.put(label + ".stderr.txt", stderr)
        record = {"surface": "process", "command": argv, "cwd": str(cwd), "shell": False, "vault": str(vault) if vault else None,
                  "state_dir": env.get("KNOWLEDGEOS_STATE_DIR"), "import_path": env.get("PYTHONPATH"),
                  "env_overrides": dict(overrides or {}), "pid": process.pid, "exit_code": process.returncode,
                  "stopped": tracked["stopped"], "error": error, "started_ns": started, "finished_ns": tracked["finished_ns"]}
        self.save(label + ".command.json", record)
        if interruption is not None:
            raise interruption
        return record, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")

    def mcp(self, label, fx, calls, overrides=None):
        overrides = dict(overrides or {})
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-integrity", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        messages += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                     for index, (name, arguments) in enumerate(calls, 2)]
        env = dict(fx["env"], KNOWLEDGEOS_VAULT=str(fx["vault"]), **overrides)
        record, stdout, stderr = self.child(label, module_command("mcp", "--vault", fx["vault"], "--framing", "ndjson"), fx["scope"], env,
                                            vault=fx["vault"], stdin_text="".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages),
                                            overrides=overrides)
        if record["error"] or record["exit_code"] != 0:
            raise RuntimeError("Integrity MCP did not finish cleanly for " + label)
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {response.get("id"): response for response in responses}
        if len(responses) != len(calls) + 1 or set(by_id) != set(range(1, len(calls) + 2)) \
                or by_id[1].get("result", {}).get("serverInfo", {}).get("name") != "knowledgeos-memory":
            raise ValueError("Wrong integrity MCP response inventory or server identity")
        results = []
        for index in range(2, len(calls) + 2):
            result = by_id[index]["result"]
            results.append({"payload": json.loads(result["content"][0]["text"]), "is_error": result["isError"]})
        return results

    # ----- hidden real console --------------------------------------------------------------

    def console(self, label, argv, fx, overrides=None):
        if os.name != "nt":
            raise RuntimeError("The hidden-console journey needs native Windows")
        overrides = dict(overrides or {})
        argv = [str(part) for part in argv]
        host = self.directory / "console_host.py"
        result, screen_file, stderr_file = (self.directory / (label + suffix) for suffix in (".host-result.json", ".console.txt", ".stderr.txt"))
        env = dict(fx["env"], KNOWLEDGEOS_VAULT=str(fx["vault"]), **overrides)
        command = [PY, "-B", "-P", str(host), "--result", str(result), "--stderr", str(stderr_file), "--screen", str(screen_file),
                   "--cwd", str(fx["scope"]), "--deadline", str(CONSOLE_DEADLINE), "--", *argv]
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        started = time.time_ns()
        with open(self.directory / (label + ".host.stdout.txt"), "wb") as out, open(self.directory / (label + ".host.stderr.txt"), "wb") as err:
            process = subprocess.Popen(command, cwd=fx["scope"], env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       startupinfo=info, creationflags=subprocess.CREATE_NEW_CONSOLE)
            host_row = {"pid": process.pid, "role": label + ".host", "stopped": False}
            self.processes.append(host_row)
            error, interruption, stopped_child = None, None, None
            try:
                process.wait(timeout=CONSOLE_DEADLINE + 40)
            except subprocess.TimeoutExpired:
                error = "Console host exceeded the proof deadline"
                pid_file = Path(str(result) + ".pid")
                if pid_file.is_file():
                    stopped_child = json.loads(pid_file.read_text(encoding="utf-8")).get("child_pid")
                    if isinstance(stopped_child, int):
                        try:
                            os.kill(stopped_child, signal.SIGTERM)
                        except OSError:
                            pass
                process.kill()
                process.wait()
            except BaseException as caught:
                process.kill()
                process.wait()
                error, interruption = str(caught), caught
        host_row.update(stopped=process.poll() is not None, exit_code=process.returncode, error=error, shell=False,
                        started_ns=started, finished_ns=time.time_ns())
        pid_file = Path(str(result) + ".pid")
        pids = json.loads(pid_file.read_text(encoding="utf-8")) if pid_file.is_file() else {}
        outcome = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else {}
        child_row = {"pid": outcome.get("child_pid") or pids.get("child_pid"), "role": label + ".child",
                     "stopped": bool(outcome), "exit_code": outcome.get("child_exit_code"), "error": None if outcome else "No child outcome",
                     "shell": False, "started_ns": outcome.get("started_ns"), "finished_ns": outcome.get("finished_ns")}
        if isinstance(child_row["pid"], int):
            self.processes.append(child_row)
        self.put(label + ".stdin.txt", b"")
        record = {"surface": "console" if label.rsplit(".", 1)[-1] != "probe" else "console_probe", "command": argv, "host_command": command,
                  "cwd": str(fx["scope"]), "shell": False, "vault": str(fx["vault"]), "state_dir": env.get("KNOWLEDGEOS_STATE_DIR"),
                  "import_path": env.get("PYTHONPATH"), "env_overrides": overrides, "host_pid": process.pid, "host_exit_code": process.returncode,
                  "host_stopped": host_row["stopped"], "host_error": error, "pid": child_row["pid"], "exit_code": child_row["exit_code"],
                  "stopped": child_row["stopped"], "timed_out": outcome.get("timed_out", True), "killed": outcome.get("killed", True),
                  "input_sent": outcome.get("input_sent", True), "stdin": outcome.get("stdin"), "stdout": outcome.get("stdout"),
                  "started_ns": outcome.get("started_ns"), "finished_ns": outcome.get("finished_ns"), "harness_stopped_child": stopped_child}
        self.save(label + ".command.json", record)
        if interruption is not None:
            raise interruption
        return record

    # ----- fixtures -------------------------------------------------------------------------

    def fixture(self, name):
        scope = self.directory / "fixtures" / name
        vault, state = scope / "vault", scope / "gate-state"
        scope.mkdir(parents=True)
        env = dict(self.base_env, PYTHONPATH=str(ROOT), KNOWLEDGEOS_STATE_DIR=str(state))
        fx = {"name": name, "scope": scope, "vault": vault, "state": state, "env": env}
        init, init_out, _ = self.child(name + ".init", module_command("init", vault, "--name", "Synthetic Integrity", "--non-interactive"), scope, env, vault=vault)
        initialized = json.loads(init_out) if init["exit_code"] == 0 else {}
        post = initialized.get("post_init", {})
        doctor, _, _ = self.child(name + ".doctor", module_command("doctor", "--vault", vault), scope, env, vault=vault)
        if (init["exit_code"] != 0 or not (vault / "People/Self.md").is_file() or not {"rebuild", "validate"} <= set(post)
                or not all(row.get("ok") is True for row in post.values()) or doctor["exit_code"] != 0):
            raise RuntimeError("Fresh integrity fixture failed init or doctor: " + name)
        return fx

    def ledger_file(self, fx):
        found = sorted(fx["state"].glob("vaults/*/self-proposals.jsonl"))
        return found[0] if found else None

    def propose(self, name, fx, key, section="heuristics", text=PROPOSAL_A):
        call = ("memory_propose_self_update", {"summary": "Synthetic integrity proposal " + key, "section": section,
                "proposed_markdown": text, "rationale": "Synthetic integrity acceptance only.", "mode": "append"})
        result = self.mcp(name + ".setup-" + key, fx, [call])[0]
        payload = result["payload"]
        relative = payload.get("proposal_path")
        if result["is_error"] or payload.get("ok") is not True or not isinstance(relative, str):
            raise RuntimeError("Setup proposal was not created: " + name)
        return relative

    def reject_setup(self, name, fx, relative):
        result = self.mcp(name + ".setup-reject", fx, [("memory_reject_self_update", {"proposal_path": relative, "reason": "Synthetic integrity setup"})])[0]
        if result["is_error"] or result["payload"].get("ok") is not True:
            raise RuntimeError("Setup rejection failed: " + name)

    def edit_ledger(self, fx, change):
        path = self.ledger_file(fx)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            change(row)
        path.write_bytes(("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)).encode("utf-8"))

    def prepare(self, name, fx):
        vault = fx["vault"]
        targets, overrides = {}, {}
        relative = self.propose(name, fx, "A")
        targets["A"] = relative
        path_a = vault / relative
        original = path_a.read_bytes()
        self.put(name + ".proposal.original.md", original)
        self.put(name + ".self.proposal-time.md", (vault / "People/Self.md").read_bytes())

        def copy_to(new_name):
            target = vault / "People/Self-Proposals" / new_name
            target.write_bytes(original)
            return target.relative_to(vault).as_posix()

        if name == "body_tampered":
            path_a.write_bytes(original.replace(b"Synthetic addition IA1", b"Synthetic addition TAMPERED", 1))
        elif name == "frontmatter_tampered":
            path_a.write_bytes(original.replace(b"proposal_mode: append", b"proposal_mode: replace", 1))
        elif name == "target_section_tampered":
            path_a.write_bytes(original.replace(b"proposal_section: heuristics", b"proposal_section: values", 1))
        elif name == "stale_base":
            self_path = vault / "People/Self.md"
            self_path.write_bytes(self_path.read_bytes().replace(
                b"Unknown. No owner-confirmed heuristics recorded yet.", b"Synthetic owner edit made after the proposal was written.", 1))
        elif name == "replay_rejected":
            self.reject_setup(name, fx, relative)
        elif name == "replay_rejected_restored":
            self.reject_setup(name, fx, relative)
            path_a.write_bytes(original)
        elif name == "replay_copy_new_name":
            targets["COPY"] = copy_to("copied-under-a-new-filename.md")
        elif name == "row_repointed":
            targets["COPY"] = copy_to("row-repointed-target.md")
            def repoint(row):
                row["proposal"] = targets["COPY"]
            self.edit_ledger(fx, repoint)
        elif name == "row_reused_other_content":
            other = self.propose(name, fx, "B", section="values", text=PROPOSAL_B)
            targets["B"] = other
            path_a.write_bytes((vault / other).read_bytes())
        elif name == "ledger_mac_broken":
            def flip(row):
                mac = str(row["mac"])
                row["mac"] = ("0" if mac[0] != "0" else "1") + mac[1:]
            self.edit_ledger(fx, flip)
        elif name == "ledger_unsigned_row":
            self.edit_ledger(fx, lambda row: row.pop("mac"))
        elif name == "ledger_missing":
            self.ledger_file(fx).unlink()
        elif name == "signing_key_replaced":
            (fx["state"] / "gate.key").write_text(secrets.token_hex(32) + "\n", encoding="ascii")
        elif name == "signing_key_missing":
            (fx["state"] / "gate.key").unlink()
        elif name == "gate_key_env_mismatch":
            overrides = dict(EXPECTED[name]["env_overrides"])
        elif name == "mcp_accept_refuses":
            targets.update(MISSING="People/Self-Proposals/does-not-exist.md", OUTSIDE="../outside.md", SELF="People/Self.md")
        elif name == "path_outside_proposals":
            inbox = vault / "Inbox/outside-copy.md"
            inbox.parent.mkdir(parents=True, exist_ok=True)
            inbox.write_bytes(original)
            (fx["scope"] / "outside-proposal.md").write_bytes(original)
            targets.update(INBOX="Inbox/outside-copy.md", SELF="People/Self.md", PARENT="../outside-proposal.md")
        elif name == "path_through_link":
            proposals = vault / "People/Self-Proposals"
            outside = fx["scope"] / "outside-private.md"
            outside.write_bytes(b"# Outside synthetic private note\n")
            try:
                os.symlink(vault / "People/Self.md", proposals / "link-to-self.md")
                os.symlink(outside, proposals / "link-to-outside.md")
                os.link(path_a, proposals / "hardlink-copy.md")
            except (OSError, NotImplementedError) as error:
                raise LinkUnavailable(str(error))
            targets.update(LINK_SELF="People/Self-Proposals/link-to-self.md", LINK_OUTSIDE="People/Self-Proposals/link-to-outside.md",
                           HARDLINK="People/Self-Proposals/hardlink-copy.md")
        elif name == "proposals_dir_redirected":
            proposals, real = vault / "People/Self-Proposals", vault / "People/Self-Proposals-real"
            proposals.rename(real)
            try:
                os.symlink(real, proposals, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                real.rename(proposals)
                raise LinkUnavailable(str(error))
        return {"targets": targets, "env_overrides": overrides}

    # ----- snapshots ------------------------------------------------------------------------

    def snap(self, name, fx, phase, targets):
        vault = fx["vault"]
        self.put(name + ".self." + phase + ".md", (vault / "People/Self.md").read_bytes())
        ledger = self.ledger_file(fx)
        self.put(name + ".ledger." + phase + ".jsonl", ledger.read_bytes() if ledger else b"")
        proposal = vault / targets["A"]
        self.put(name + ".proposal." + phase + ".md", proposal.read_bytes() if proposal.is_file() else b"")
        state = {path: row for path, row in inventory(fx["state"]).items() if not path.endswith((".guard", ".lock"))}
        extras = {}
        for relative in (vault / "Inbox/outside-copy.md", fx["scope"] / "outside-proposal.md", fx["scope"] / "outside-private.md"):
            extras[relative.relative_to(fx["scope"]).as_posix()] = sha(relative) if relative.is_file() else None
        self.save(name + ".files." + phase + ".json", {"people": inventory(vault / "People"), "extras": extras})
        self.save(name + ".state." + phase + ".json", state)

    # ----- cases ----------------------------------------------------------------------------

    def run_control(self, name, spec):
        scope = self.directory / "fixtures" / name
        scope.mkdir(parents=True)
        fx = {"name": name, "scope": scope, "vault": scope / "vault", "state": scope / "gate-state", "env": dict(self.base_env)}
        code = "import sys;print('stdin_tty=%s stdout_tty=%s' % (sys.stdin.isatty(), sys.stdout.isatty()))"
        self.console(name + ".probe", [PY, "-B", "-P", "-c", code], fx)
        self.report_case(name)

    def run_case(self, name):
        spec = EXPECTED[name]
        if spec["kind"] == "control":
            return self.run_control(name, spec)
        fx = self.fixture(name)
        try:
            observation = self.prepare(name, fx)
        except LinkUnavailable as error:
            self.unavailable[name] = str(error)
            self.save(name + ".unavailable.json", {"reason": str(error)})
            self.cases.append({"id": "identity.integrity." + name, "verdict": "NOT CHECKED", "expected": spec["expected"],
                               "observed": {"links_available": False}, "problems": ["native link creation failed: " + str(error)],
                               "evidence": [name + ".unavailable.json"]})
            print("NOT CHECKED identity.integrity." + name, flush=True)
            return
        targets, overrides = observation["targets"], observation["env_overrides"]
        self.save(name + ".observation.json", observation)
        self.snap(name, fx, "before", targets)
        calls = []
        for action in spec["actions"]:
            label = name + "." + action["label"]
            if action["surface"] == "console":
                self.console(label, module_command("self", "approve", targets[action["target"]], "--vault", fx["vault"]), fx, overrides)
            elif action["surface"] == "cli":
                self.child(label, module_command(*action["argv"], "--vault", fx["vault"]), fx["scope"],
                           dict(fx["env"], KNOWLEDGEOS_VAULT=str(fx["vault"]), **overrides), vault=fx["vault"], overrides=overrides)
            else:
                calls.append(action)
        if calls:
            requests = []
            for action in calls:
                arguments = {} if action["tool"] == "memory_list_self_proposals" else {"proposal_path": targets[action["target"]]}
                requests.append((action["tool"], arguments))
            self.mcp(name + ".mcp", fx, requests, overrides)
        self.snap(name, fx, "after", targets)
        self.report_case(name)

    def report_case(self, name):
        import integrity_adapter as grader
        verdict = grader.judge_case(name, EXPECTED[name], lambda file: (self.directory / file).read_bytes(),
                                    lambda file: (self.directory / file).is_file())
        self.cases.append({"id": "identity.integrity." + name, "verdict": verdict["verdict"], "expected": EXPECTED[name]["expected"],
                           "observed": verdict["checks"], "problems": verdict["problems"],
                           "evidence": sorted(path.name for path in self.directory.iterdir() if path.is_file() and path.name.startswith(name + "."))})
        print(verdict["verdict"] + " identity.integrity." + name, flush=True)

    # ----- run ------------------------------------------------------------------------------

    def finish(self, error=None):
        current = product_hashes()
        support = {name: sha(Path(__file__).with_name(name)) for name in self.support}
        stable = current == self.product and sha(__file__) == self.producer_hash and support == self.support
        after = self.sentinels()
        stopped = bool(self.processes) and all(row["stopped"] and isinstance(row.get("exit_code"), int) for row in self.processes)
        expected_ids = ["identity.integrity." + name for name in EXPECTED]
        problems = {name: str(value) for name, value in self.errors.items()}
        if error is not None:
            problems["run"] = str(error)
        complete = [row["id"] for row in self.cases] == expected_ids
        verdicts = [row["verdict"] for row in self.cases]
        if "FAIL" in verdicts or self.errors or error is not None or not stable or self.before != after or not stopped or not complete:
            aggregate = "FAIL"
        elif any(v != "PASS" for v in verdicts):
            aggregate = "NOT CHECKED"
        else:
            aggregate = "PASS"
        if problems:
            self.save("execution-error.json", problems)
        report = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": self.support, "support_sha256_after": support,
                  "source_root": str(ROOT), "revision": getattr(self, "revision", None), "platform": platform.platform(), "python": sys.version,
                  "scope": SCOPE, "scope_description": "source CLI and MCP with a hidden real Windows console in fresh synthetic vaults",
                  "verdict": aggregate, "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidate": "IDENTITY.integrity_refusal",
                  "acceptance_credit_awarded": False, "product_hashes": self.product, "product_hashes_after": current,
                  "product_and_producer_unchanged": stable, "frozen_at_ns": self.frozen_at_ns, "expected_case_ids": expected_ids,
                  "cases": self.cases, "unavailable_cases": self.unavailable, "processes": self.processes,
                  "all_started_processes_stopped": stopped,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after,
                                "limitation": "Selected real-vault sentinels only; not an exhaustive filesystem audit"},
                  "limits": ["Source CLI and MCP only; no installed package, genuine host or independent owner approval claim",
                             "No answer is ever sent to an approval prompt; a successful owner approval path is not exercised",
                             "Console stdout is the console screen buffer read back after the child exits",
                             "A case that reaches the prompt fails and its exact child is stopped; stopped records cover directly launched children",
                             "The hidden console proves terminal presence for the child; it is not evidence of a human"],
                  "error": json.dumps(problems, sort_keys=True) if problems else None}
        report["evidence_files"] = {path.name: sha(path) for path in sorted(self.directory.iterdir()) if path.is_file() and path.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": aggregate,
                          "passed": sum(v == "PASS" for v in verdicts), "total": len(expected_ids)}), flush=True)
        return 0 if aggregate == "PASS" else 1

    def run(self):
        error = None
        try:
            self.save("frozen-cases.json", {"producer": PRODUCER, "case_ids": list(EXPECTED), "expected": EXPECTED})
            self.put("console_host.py", HELPER_SOURCE)
            self.frozen_at_ns = time.time_ns()
            record, stdout, _ = self.child("revision", ["git", "rev-parse", "HEAD"], ROOT, self.base_env)
            if record["exit_code"] != 0:
                raise RuntimeError("Cannot bind source revision")
            self.revision = stdout.strip()
            for name in EXPECTED:
                try:
                    self.run_case(name)
                except (KeyboardInterrupt, InterruptedError):
                    raise
                except Exception as caught:
                    self.errors[name] = caught
                    print("ERROR identity.integrity." + name + ": " + str(caught), flush=True)
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise InterruptedError("Integrity proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return IntegrityRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
