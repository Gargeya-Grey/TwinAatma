"""Drive unchanged installed project wiring through native Codex, without a model turn."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import stat
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import uuid

from native_process import Tree

ROOT = Path(__file__).absolute().parents[4]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
BASE = Path(__file__).absolute().parent
PRODUCER = "verify-twinaatma.native-installed-move/v3"
CLI = Path("C:/Users/Gargeya/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe")
CLI_SHA256 = "2692c8c7bb2cf8b0aefe638741fc90236f4b824c59578ce84994f9de58200993"
OUTPUT_ROOT = ROOT / "work/gc-artifacts/.knowledgeos"
PROJECT_NOTE = "Projects/relocated-orbit.md"
SOURCE_NOTE = "Research/relocated-orbit-source.md"
PROJECT_ID = "kos:project:native-portmove-original"
METHODS = {"initialize", "thread/start", "mcpServerStatus/list", "mcpServer/tool/call", "thread/unsubscribe"}
TOOLS = {"memory_session_start", "memory_get_note", "memory_search", "memory_related", "memory_session_end"}
PHASES = ("before-move", "after-move-old-absent", "after-move-old-reused")


def sha(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key: " + key)
            value[key] = item
        return value
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def plain(path, root=None, *, exists=True):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("Parent traversal is not supported")
    if root is not None:
        path.relative_to(Path(root).absolute())
        path.resolve().relative_to(Path(root).resolve())
    for parent in (path, *path.parents):
        try:
            information = parent.lstat()
        except FileNotFoundError:
            if exists and parent == path:
                raise
            continue
        if stat.S_ISLNK(information.st_mode) or getattr(information, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked path is outside this journey: " + str(parent))
        if parent == path and stat.S_ISREG(information.st_mode) and information.st_nlink != 1:
            raise ValueError("Multi-linked evidence is outside this journey: " + str(path))
    return path


def contained_output(path, *, exists=True):
    path = plain(path, OUTPUT_ROOT, exists=exists)
    if path == OUTPUT_ROOT:
        raise ValueError("A task-owned path below the evidence root is required")
    return path


def inventory(root):
    root = plain(root)
    result = {}
    for path in sorted(root.rglob("*")):
        plain(path, root)
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def acceptance_module():
    path = plain(SCRIPTS / "acceptance.py", ROOT)
    spec = importlib.util.spec_from_file_location("_move_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_artifact(path):
    path = plain(path, ROOT)
    data = read_json(path)
    acceptance = acceptance_module()
    current = acceptance.product_hashes()
    checked = acceptance.artifact_report(path, current)
    if checked["cell"][0] != "Windows" or data.get("verdict") != "PASS":
        raise ValueError("The native journey needs a passing exact Windows installation report")
    launcher = plain(data["installation"]["executable"], ROOT)
    kind = data["artifact"]["kind"]
    installation = path.parent / "venv" if kind == "wheel" else Path(data["artifact"]["distribution_root"])
    launcher.relative_to(installation)
    return data, launcher, installation, checked, acceptance.build_inputs()


def tool_payload(value):
    if not isinstance(value, dict) or value.get("isError") is True:
        raise ValueError("Native MCP tool refused or returned a malformed result")
    content = value.get("content")
    if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text":
        raise ValueError("Native MCP tool needs one original JSON text result")
    result = json.loads(content[0]["text"])
    if not isinstance(result, dict) or result.get("error") or result.get("ok") is False:
        raise ValueError("Product tool returned an error: " + json.dumps(result))
    return result


class NativeHost:
    def __init__(self, trial, phase, vault):
        self.trial, self.phase, self.vault = trial, phase, vault
        self.directory = trial.owned(trial.output / phase)
        self.directory.mkdir()
        self.home = self.directory / "host-home"
        self.home.mkdir()
        text = ('project_root_markers = [".knowledgeos-vault.json"]\n'
                + '[projects.' + json.dumps(str(vault)) + ']\ntrust_level = "trusted"\n'
                + '[analytics]\nenabled = false\n')
        (self.home / "config.toml").write_text(text, encoding="utf-8", newline="\n")
        self.environment = trial.environment()
        self.environment["CODEX_HOME"] = str(self.home)
        self.command = [str(trial.codex), "--disable", "apps", "--disable", "plugins", "--disable", "remote_plugin",
                        "app-server", "--strict-config", "--stdio"]
        self.requests, self.messages, self.responses, self.notifications = [], [], {}, []
        self.queue, self.collect_errors = queue.Queue(), []
        self.thread_id, self.host, self.tree = None, None, None
        self.record = {"phase": phase, "command": self.command, "cwd": str(vault), "home": str(self.home),
                       "home_config_sha256": sha(self.home / "config.toml"), "pid": None, "exit_code": None,
                       "stopped": False, "started_ns": None, "ended_ns": None, "error": None,
                       "model_calls": 0, "turn_start_sent": False, "sign_in_copied": False,
                       "generated_config_sha256": sha(vault / ".codex/config.toml"),
                       "discovery": None, "tools": {}, "session_id": None}

    def send(self, message):
        self.requests.append(message)
        self.host.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.host.stdin.flush()

    def request(self, method, params, timeout=60):
        if method not in METHODS:
            raise ValueError("Native protocol method outside the allowlist")
        if method == "mcpServer/tool/call" and (params.get("server") != "knowledgeos" or params.get("tool") not in TOOLS):
            raise ValueError("Product tool outside the allowlist")
        request = {"id": len(self.requests) + 1, "method": method, "params": params}
        self.send(request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.queue.get(timeout=max(0.001, deadline - time.monotonic()))
            if message is None:
                raise RuntimeError("Native host stdout ended before its response")
            if message.get("id") == request["id"] and "method" not in message:
                self.responses[str(request["id"])] = message
                self.tree.sample()
                if "error" in message:
                    raise ValueError(method + ": " + json.dumps(message["error"]))
                return message["result"]
            if "id" in message:
                raise ValueError("Unexpected native server request. No approval was supplied.")
            self.notifications.append(message)
        raise TimeoutError("Native response deadline exceeded")

    def tool(self, name, arguments, label):
        result = self.request("mcpServer/tool/call", {"threadId": self.thread_id,
                              "server": "knowledgeos", "tool": name, "arguments": arguments})
        self.record["tools"][label] = {"name": name, "arguments": arguments, "result": result}
        return tool_payload(result)

    def drive(self):
        stdout_path, stderr_path = self.directory / "host.stdout.jsonl", self.directory / "host.stderr.txt"
        with stdout_path.open("x", encoding="utf-8", newline="\n") as stdout, stderr_path.open("xb") as stderr:
            self.record["started_ns"] = time.time_ns()
            try:
                self.host = subprocess.Popen(self.command, cwd=self.vault, env=self.environment,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                             text=True, encoding="utf-8")
                self.record["pid"] = self.host.pid
                self.tree = Tree(self.host.pid, os.getpid())

                def collect():
                    try:
                        for line in self.host.stdout:
                            stdout.write(line)
                            stdout.flush()
                            message = json.loads(line)
                            self.messages.append(message)
                            self.queue.put(message)
                    except Exception as error:
                        self.collect_errors.append(str(error))
                    finally:
                        self.queue.put(None)

                reader = threading.Thread(target=collect, daemon=True)
                reader.start()
                try:
                    self.request("initialize", {"clientInfo": {"name": "twinaatma-installed-move", "version": "1.0"},
                                                "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}})
                    self.send({"method": "initialized", "params": {}})
                    thread = self.request("thread/start", {"cwd": str(self.vault), "ephemeral": True,
                                                            "sandbox": "read-only"})
                    self.thread_id = thread["thread"]["id"]
                    if thread["thread"].get("turns") != [] or thread["thread"].get("ephemeral") is not True:
                        raise ValueError("The local inspection thread must be empty and ephemeral")
                    self.record["thread_id"] = self.thread_id
                    status = self.request("mcpServerStatus/list", {"threadId": self.thread_id,
                                          "serverName": "knowledgeos", "limit": 20})
                    self.record["discovery"] = status
                    rows = status.get("data", [])
                    if len(rows) != 1 or rows[0].get("name") != "knowledgeos" or rows[0].get("runtimeStatus") != "connected":
                        raise ValueError("Generated installed server did not connect in the native host")
                    if rows[0].get("serverInfo", {}).get("name") != "knowledgeos-memory" or not TOOLS <= set(rows[0].get("tools", {})):
                        raise ValueError("Native discovery did not expose the expected memory server and tools")
                    start = self.tool("memory_session_start", {"task_hint": self.trial.token, "limit": 8}, "session_start")
                    session = start.get("session_id")
                    if not isinstance(session, str) or not session:
                        raise ValueError("Installed startup returned no session ID")
                    self.record["session_id"] = session
                    self.tool("memory_get_note", {"path_or_id": PROJECT_NOTE}, "project")
                    self.tool("memory_get_note", {"path_or_id": SOURCE_NOTE}, "source")
                    self.tool("memory_get_note", {"path_or_id": self.trial.capture_path}, "capture")
                    self.tool("memory_search", {"query": self.trial.token, "limit": 20}, "search")
                    self.tool("memory_related", {"path_or_id": PROJECT_NOTE, "hops": 1}, "related")
                    end = self.tool("memory_session_end", {"session_id": session,
                        "summary": "Synthetic installed-vault relocation check for the Aurora crate and its 13 kg limit.",
                        "capture_title": "Native installed move " + self.phase}, "session_end")
                    if end.get("session_id") != session:
                        raise ValueError("Native session end did not preserve its returned session ID")
                finally:
                    if self.thread_id and self.host.poll() is None:
                        try:
                            self.record["unsubscribe"] = self.request("thread/unsubscribe", {"threadId": self.thread_id}, timeout=15)
                        except Exception as error:
                            self.record["unsubscribe_error"] = str(error)
            except Exception:
                self.record["error"] = traceback.format_exc()
            finally:
                if self.host:
                    self.host.stdin.close()
                    try:
                        self.host.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        self.record["verifier_terminated_host"] = True
                        self.host.terminate()
                        self.host.wait(timeout=10)
                    reader.join(timeout=5)
                    self.record.update(exit_code=self.host.returncode, stopped=self.host.poll() is not None,
                                       stdin_closed=self.host.stdin.closed, stdout_reader_stopped=not reader.is_alive())
                    self.host.stdout.close()
                    self.record["kernel_tree"] = self.tree.finish()
                self.record["ended_ns"] = time.time_ns()
        self.record.update(requests=self.requests, responses=self.responses, notifications=self.notifications,
                           collect_errors=self.collect_errors)
        self.record["stream_sha256"] = {"host.stdout.jsonl": sha(stdout_path), "host.stderr.txt": sha(stderr_path)}
        save(self.directory / "host.requests.json", self.requests)
        save(self.directory / "report.json", self.record)
        return self.record


class Trial:
    def __init__(self, artifact, output, codex):
        self.output = contained_output(output, exists=False)
        self.output.mkdir(parents=True, exist_ok=False)
        self.neutral, self.state = self.output / "neutral", self.output / "gate-state"
        self.neutral.mkdir()
        self.state.mkdir()
        self.preparation_home = self.output / "preparation-host-home"
        self.preparation_home.mkdir()
        self.original, self.moved, self.preserved = (self.output / name for name in ("vault-before", "vault-after", "vault-preserved"))
        self.artifact_path, self.codex = plain(artifact, ROOT), plain(codex.resolve(strict=True))
        self.codex_alias = str(codex.absolute())
        self.token = "native-relocation-" + uuid.uuid4().hex
        self.capture_path, self.before, self.environment_root = None, None, None
        self.report = {"producer": PRODUCER, "producer_sha256": sha(__file__),
                       "support_sha256": {"native_process.py": sha(BASE / "native_process.py")},
                       "gate": "PORT.same_device_move", "scope": "artifact", "platform": "Windows",
                       "run_nonce": uuid.uuid4().hex, "output": str(self.output), "token": self.token,
                       "model_calls": 0, "sign_in_copied": False, "cases": [], "commands": [], "phases": [],
                       "error": None, "verdict": "NOT GRADED", "fixed54_credit": 0,
                       "producer_pid": os.getpid(), "producer_parent_pid": os.getppid(),
                       "limits": ["One exact Windows installed artifact and native Codex CLI local MCP connection.",
                                  "No model turn, desktop UI, other host, clean device, elapsed use, performance or owner approval.",
                                  "Kernel process snapshots cover observed descendants, not an exhaustive machine execution audit."]}

    def owned(self, path):
        return plain(path, self.output, exists=False)

    def environment(self):
        result = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
                  and not key.startswith(("KNOWLEDGEOS_", "CODEX_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_"))}
        result.update(PYTHONDONTWRITEBYTECODE="1", PYTHONSAFEPATH="1", PYTHONIOENCODING="utf-8",
                      KNOWLEDGEOS_STATE_DIR=str(self.state), CODEX_HOME=str(self.preparation_home))
        return result

    def snapshot(self):
        sentinels = [ROOT / name for name in ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json",
                     "knowledgeos.config.json", ".codex/config.toml", ".cursor/mcp.json")]
        sentinels.append(Path("C:/Users/Gargeya/.codex/config.toml"))
        return {"toolkit": acceptance_module().data_toolkit_hashes(),
                "sentinels": {str(path): sha(path) for path in sentinels},
                "installed_environment": inventory(self.environment_root),
                "artifact_report_sha256": sha(self.artifact_path),
                "artifact_sha256": sha(Path(self.artifact["artifact"]["path"])),
                "native_cli_sha256": sha(self.codex),
                "verification_helpers": {name: sha(SCRIPTS / name) for name in ("acceptance.py", "artifact.py")}}

    def command(self, label, arguments, *, executable=None):
        command = [str(executable or self.launcher), *map(str, arguments)]
        record = {"role": label, "command": command, "cwd": str(self.neutral), "pid": None,
                  "started_ns": time.time_ns(), "ended_ns": None, "exit_code": None, "stopped": False,
                  "environment_overrides": {key: value for key, value in self.environment().items()
                                            if key.startswith("KNOWLEDGEOS_") or key in {"PYTHONDONTWRITEBYTECODE", "PYTHONSAFEPATH", "PYTHONIOENCODING"}}}
        with (self.output / (label + ".stdout.txt")).open("xb") as out, (self.output / (label + ".stderr.txt")).open("xb") as error:
            child = subprocess.Popen(command, cwd=self.neutral, env=self.environment(), stdin=subprocess.DEVNULL, stdout=out, stderr=error)
            record["pid"] = child.pid
            monitor = Tree(child.pid, os.getpid())
            try:
                child.wait(timeout=90)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                child.kill()
                child.wait(timeout=15)
            finally:
                record.update(exit_code=child.returncode, stopped=child.poll() is not None, ended_ns=time.time_ns(), kernel_tree=monitor.finish())
        save(self.output / (label + ".command.json"), record)
        self.report["commands"].append(record)
        if record["exit_code"] != 0:
            raise RuntimeError("Installed public command failed: " + label)
        return (self.output / (label + ".stdout.txt")).read_text(encoding="utf-8")

    def memory(self, label, tool, arguments, vault):
        if tool not in {"memory_capture"}:
            raise ValueError("Fixture preparation does not approve or alter identity")
        return json.loads(self.command(label, ["memory", tool, "--vault", vault, "--args", json.dumps(arguments)]))

    def initialize_vault(self, path, label):
        self.owned(path)
        result = json.loads(self.command(label, ["init", path, "--name", "Synthetic native relocation fixture", "--non-interactive"]))
        if not result.get("ok"):
            raise ValueError("Installed public init failed")
        marker = read_json(path / ".knowledgeos-vault.json")
        identity = marker.get("vault_id")
        if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Installed init did not create a stable full vault ID")
        return identity

    def phase(self, name, vault):
        record = NativeHost(self, name, vault).drive()
        self.report["phases"].append({"phase": name, "path": name + "/report.json", "sha256": sha(self.output / name / "report.json")})
        inventory_path = name + ".vault.inventory.json"
        save(self.output / inventory_path, inventory(vault))
        return record

    def execute(self):
        if os.name != "nt" or sha(self.codex) != CLI_SHA256:
            raise ValueError("Native move proof needs the exact hash-pinned Windows Codex CLI")
        self.artifact, self.launcher, self.environment_root, self.checked_artifact, self.toolkit = validate_artifact(self.artifact_path)
        self.before = self.snapshot()
        save(self.output / "binding-before.json", self.before)
        self.report["binding"] = {"artifact_report": str(self.artifact_path), "artifact_report_sha256": sha(self.artifact_path),
            "artifact": self.artifact["artifact"], "installation": self.artifact["installation"],
            "checked_artifact": self.checked_artifact, "toolkit": self.toolkit, "native_cli": str(self.codex),
            "native_cli_requested_path": self.codex_alias, "native_cli_sha256": CLI_SHA256,
            "complete_source_toolkit": self.before["toolkit"]}
        version = self.command("native-version", ["--version"], executable=self.codex).strip()
        if version != "codex-cli 0.163.0":
            raise ValueError("Native CLI version changed")
        self.report["native_version"] = version
        if self.artifact["artifact"]["kind"] == "wheel":
            python = plain(self.artifact["installation"]["python"], ROOT)
            code = "import json,knowledgeos,sys; print(json.dumps({'origin':knowledgeos.__file__,'sys_path':sys.path,'executable':sys.executable,'version':knowledgeos.__version__}))"
            origin = json.loads(self.command("installed-origin", ["-B", "-P", "-c", code], executable=python))
            if origin["origin"] != self.artifact["installation"]["import_origin"] or str(ROOT) in origin["sys_path"]:
                raise ValueError("Installed import resolved outside its verified package")
            self.report["installed_import"] = origin
        vault_id = self.initialize_vault(self.original, "init")
        self.report["vault_id"] = vault_id
        project = ("---\nid: " + PROJECT_ID + "\ntitle: Relocated Orbit\ntype: project\nstatus: active\ncreated: 2026-10-20\nupdated: 2026-10-20\n---\n\n"
                   "# Relocated Orbit\n\nThe synthetic Aurora crate has a 13 kg limit. Token " + self.token + ".\n\n"
                   "## Links\n- [Source](../Research/relocated-orbit-source.md)\n")
        source = ("---\nid: kos:research:native-portmove-source\ntitle: Orbit Source\ntype: research\nstatus: draft\ncreated: 2026-10-20\nupdated: 2026-10-20\n---\n\n"
                  "# Orbit Source\n\nSynthetic cargo evidence.\n\n## Links\n- [Project](../Projects/relocated-orbit.md)\n")
        for relative, text in ((PROJECT_NOTE, project), (SOURCE_NOTE, source)):
            self.owned(self.original / relative).write_text(text, encoding="utf-8", newline="\n")
        capture = self.memory("capture", "memory_capture", {"title": "Native move Aurora fact",
            "content": "The synthetic Aurora crate has a 13 kg limit. Token " + self.token + ". [Project](../Projects/relocated-orbit.md)",
            "request_id": self.report["run_nonce"]}, self.original)
        if capture.get("ok") is not True:
            raise ValueError("Installed public capture failed")
        self.capture_path = capture["path"]
        self.report["capture_path"] = self.capture_path
        self.note_hashes = {relative: sha(self.original / relative) for relative in (PROJECT_NOTE, SOURCE_NOTE, self.capture_path, "People/Self.md", ".knowledgeos-vault.json")}
        self.report["note_hashes"] = self.note_hashes
        self.command("setup-host", ["setup-host", "--host", "codex", "--vault", self.original, "--write"])
        generated = (self.original / ".codex/config.toml").read_bytes()
        (self.output / "generated-config.original.toml").write_bytes(generated)
        server = tomllib.loads(generated.decode("utf-8"))["mcp_servers"]["knowledgeos"]
        if Path(server["command"]).resolve() != self.launcher.resolve() or server.get("required") is not True or "PYTHONPATH" in server.get("env", {}):
            raise ValueError("Generated native wiring does not bind the exact installed launcher")
        self.report["generated_config_sha256"] = sha(self.output / "generated-config.original.toml")
        self.report["generated_server"] = server
        save(self.output / "generated-server.json", server)
        self.phase(PHASES[0], self.original)
        before = inventory(self.original)
        save(self.output / "vault-before-move.inventory.json", before)
        shutil.copytree(self.original, self.owned(self.preserved))
        if inventory(self.preserved) != before:
            raise ValueError("Preserved original copy changed bytes")
        source_path, target_path = self.owned(self.original), self.owned(self.moved)
        if not source_path.is_dir() or target_path.exists() or source_path.drive != target_path.drive:
            raise ValueError("Unsafe or cross-device move plan")
        save(self.output / "move.plan.json", {"operation": "Path.rename", "source": str(source_path), "target": str(target_path),
            "resolved_owned_root": str(self.output.resolve()), "same_device": source_path.stat().st_dev == target_path.parent.stat().st_dev,
            "source_resolved": str(source_path.resolve()), "target_resolved": str(target_path.resolve()),
            "source_inventory": "vault-before-move.inventory.json", "preserved_copy": str(self.preserved),
            "all_targets_contained_before_move": True, "before_ns": time.time_ns()})
        if source_path.stat().st_dev != target_path.parent.stat().st_dev:
            raise ValueError("Source and target are on different volumes")
        source_path.rename(target_path)
        after = inventory(self.moved)
        save(self.output / "vault-after-rename.inventory.json", after)
        if before != after or self.original.exists() or (self.moved / ".codex/config.toml").read_bytes() != generated:
            raise ValueError("Same-device move or generated configuration changed bytes")
        self.phase(PHASES[1], self.moved)
        other_id = self.initialize_vault(self.original, "unrelated-init")
        if other_id == vault_id:
            raise ValueError("Replacement fixture reused the original vault ID")
        (self.original / PROJECT_NOTE).write_text(project.replace(PROJECT_ID, "kos:project:native-portmove-unrelated")
            .replace("13 kg", "99 kg").replace(self.token, "unrelated-" + uuid.uuid4().hex), encoding="utf-8", newline="\n")
        self.memory("unrelated-capture", "memory_capture", {"title": "Unrelated synthetic location",
            "content": "The unrelated Cobalt box has a 99 kg limit.", "request_id": uuid.uuid4().hex}, self.original)
        unrelated_before = inventory(self.original)
        save(self.output / "unrelated-before.inventory.json", unrelated_before)
        self.report["unrelated_vault_id"] = other_id
        self.phase(PHASES[2], self.moved)
        unrelated_after = inventory(self.original)
        save(self.output / "unrelated-after.inventory.json", unrelated_after)
        self.report["unrelated_unchanged"] = unrelated_before == unrelated_after
        self.report["generated_bytes_unchanged"] = (self.moved / ".codex/config.toml").read_bytes() == generated
        self.report["paths"] = {"original": str(self.original), "moved": str(self.moved), "preserved": str(self.preserved), "gate_state": str(self.state)}
        save(self.output / "vault-final.inventory.json", inventory(self.moved))
        self.report["notes_unchanged"] = self.note_hashes == {relative: sha(self.moved / relative) for relative in self.note_hashes}

    def finish(self):
        if self.before is not None:
            after = self.snapshot()
            save(self.output / "binding-after.json", after)
            self.report["isolation_unchanged"] = self.before == after
        evidence = {}
        for path in sorted(self.output.rglob("*")):
            relative = path.relative_to(self.output).as_posix()
            if path.is_file() and (len(path.relative_to(self.output).parts) == 1 or
                                  (path.relative_to(self.output).parts[0] in PHASES and len(path.relative_to(self.output).parts) == 2)):
                if relative != "report.json":
                    evidence[relative] = sha(path)
        self.report["evidence"] = evidence
        save(self.output / "report.json", self.report)
        return self.output / "report.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-report", type=Path, required=True)
    parser.add_argument("--codex", type=Path, default=CLI)
    parser.add_argument("--output", type=Path, help="A new task directory beneath work/gc-artifacts/.knowledgeos")
    arguments = parser.parse_args()
    output = arguments.output or OUTPUT_ROOT / "native-installed-move" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    trial = Trial(arguments.artifact_report, output, arguments.codex)
    try:
        trial.execute()
    except BaseException:
        trial.report["error"] = traceback.format_exc()
    path = trial.finish()
    print(json.dumps({"report": str(path), "error": trial.report["error"], "phases": trial.report["phases"], "model_calls": 0}), flush=True)
    return 2 if trial.report["error"] else 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
