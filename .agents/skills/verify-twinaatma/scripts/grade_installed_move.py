"""Recompute the single installed move outcome from retained native observations."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import sys

import installed_move as journey

TARGET = "PORT.same_device_move"
EXPECTED = "A same-device vault move preserves note/link content, retrieval and declared host wiring."
LABELS = ("session_start", "project", "source", "capture", "search", "related", "session_end")
PRODUCER = "verify-twinaatma.native-installed-move-grade/v2"
SUPPORT = ("installed_move.py", "grade_installed_move.py", "native_process.py", "acceptance.py", "artifact.py")


def helper_hashes():
    return {name: journey.sha(journey.plain(journey.SCRIPTS / name, journey.ROOT)) for name in SUPPORT}


def argv(command):
    count = ctypes.c_int()
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        raise ValueError("Unparseable observed Windows command line")
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(pointer)


def path_equal(left, right):
    return Path(left).absolute() == Path(right).absolute()


def process_tree(record, *, require_live_parameters=True):
    tree = record.get("kernel_tree", {})
    rows = tree.get("processes")
    if tree.get("monitor_stopped") is not True or tree.get("errors") != [] or not isinstance(rows, list) or not rows:
        raise ValueError("Native process observation is missing or incomplete")
    by_pid = {}
    for item in rows:
        pid = item.get("pid")
        if not isinstance(pid, int) or pid <= 0 or pid in by_pid:
            raise ValueError("Invalid or duplicated native process identity")
        if (item.get("stopped") is not True or item.get("wait_result") != 0
                or not isinstance(item.get("exit_code"), int) or item.get("handle_open_error") is not None
                or item.get("verifier_forced_termination") or not item.get("creation_filetime_100ns")):
            raise ValueError("Native child shutdown or original kernel identity is unknown")
        if not item.get("image") or not re.fullmatch("[0-9a-f]{64}", item.get("image_sha256", "")):
            raise ValueError("Native child image binding is missing")
        if require_live_parameters and (item.get("identity_error") or not item.get("cwd") or not item.get("command_line")):
            raise ValueError("Native child command or inherited cwd is unknown")
        created_ns = (item["creation_filetime_100ns"] - 116444736000000000) * 100
        if not record["started_ns"] - 100_000_000 <= created_ns <= item["observed_ns"] <= item["shutdown_observed_ns"]:
            raise ValueError("Native process timestamps are inconsistent")
        by_pid[pid] = item
    if record.get("pid") not in by_pid or record.get("stopped") is not True:
        raise ValueError("Native direct process has no retained kernel identity")
    for pid, item in by_pid.items():
        if pid == record["pid"]:
            continue
        seen, cursor = {pid}, item
        while cursor["parent_pid"] != record["pid"]:
            parent = cursor["parent_pid"]
            if parent not in by_pid or parent in seen:
                raise ValueError("Foreign child is not descended from this exact native host")
            seen.add(parent)
            if by_pid[parent]["creation_filetime_100ns"] > cursor["creation_filetime_100ns"]:
                raise ValueError("Observed parent identity was reused")
            cursor = by_pid[parent]
    return by_pid


def native_protocol(record, messages, requests, *, generated, launcher, native_cli, installed_python=None):
    if record.get("requests") != requests:
        raise ValueError("Native request inventory changed")
    expected_command = [str(native_cli), "--disable", "apps", "--disable", "plugins", "--disable", "remote_plugin",
                        "app-server", "--strict-config", "--stdio"]
    if record.get("command") != expected_command or record.get("model_calls") != 0 or record.get("turn_start_sent") is not False or record.get("sign_in_copied") is not False:
        raise ValueError("Native local-only protocol or CLI binding changed")
    if record.get("collect_errors") != [] or record.get("stdout_reader_stopped") is not True or record.get("stdin_closed") is not True or record.get("verifier_terminated_host"):
        raise ValueError("Native transport shutdown is not complete")
    method_counts, response_by_id = {}, {}
    for message in messages:
        if "id" in message:
            if "method" in message or message["id"] in response_by_id:
                raise ValueError("Native server requested an unreviewed action or duplicated a response")
            response_by_id[message["id"]] = message
        elif str(message.get("method", "")).startswith(("turn/", "item/")):
            raise ValueError("A model turn notification is outside this local journey")
    native_calls, response_records = [], {}
    initialized = 0
    for message in requests:
        method = message.get("method")
        if method == "initialized" and "id" not in message:
            initialized += 1
            continue
        if method not in journey.METHODS or message.get("id") not in response_by_id:
            raise ValueError("Native method is not allowed or lacks an original response")
        method_counts[method] = method_counts.get(method, 0) + 1
        response = response_by_id[message["id"]]
        response_records[str(message["id"])] = response
        if method == "mcpServer/tool/call":
            params = message["params"]
            if params.get("tool") not in journey.TOOLS or params.get("server") != "knowledgeos" or params.get("threadId") != record.get("thread_id"):
                raise ValueError("Native product tool is outside the local allowlist")
            native_calls.append((params, response))
        elif method == "initialize":
            result = response.get("result", {})
            if not path_equal(result.get("codexHome", ""), record["home"]) or result.get("platformFamily") != "windows":
                raise ValueError("Native host did not use its owned credential-free home")
        elif method == "thread/start":
            if message["params"] != {"cwd": record["cwd"], "ephemeral": True, "sandbox": "read-only"}:
                raise ValueError("Native thread context changed")
            if "result" in response and (response["result"]["thread"].get("turns") != [] or response["result"]["thread"].get("ephemeral") is not True):
                raise ValueError("Native thread has model turns or persistent state")
            if "result" in response and (response["result"].get("sandbox") != {"type": "readOnly", "networkAccess": False}
                                         or not path_equal(response["result"]["thread"]["cwd"], record["cwd"])):
                raise ValueError("Native thread permissions or working directory changed")
    if initialized != 1 or method_counts.get("initialize") != 1 or method_counts.get("thread/start") != 1 or response_records != record.get("responses"):
        raise ValueError("Native initialization or raw response inventory is inconsistent")
    tools = record.get("tools", {})
    if len(native_calls) != len(tools):
        raise ValueError("Native tool summary omits original requests")
    for label, (params, response) in zip(tools, native_calls):
        if tools[label] != {"name": params["tool"], "arguments": params.get("arguments"), "result": response.get("result")}:
            raise ValueError("Native tool result does not match its original protocol")
    by_pid = process_tree(record)
    root = by_pid[record["pid"]]
    if root["image_sha256"] != journey.CLI_SHA256 or not path_equal(root["image"], native_cli) or not path_equal(root["cwd"], record["cwd"]) or argv(root["command_line"]) != expected_command:
        raise ValueError("Native host kernel identity differs from its declared invocation")
    launchers = [item for pid, item in by_pid.items() if pid != record["pid"] and path_equal(item["image"], launcher)]
    expected_server = [str(launcher), *generated["args"]]
    for child in launchers:
        if child["parent_pid"] != record["pid"] or argv(child["command_line"]) != expected_server:
            raise ValueError("Native child launch is foreign or its generated arguments changed")
        expected_cwd = generated.get("cwd", record["cwd"])
        if child["image_sha256"] != journey.sha(launcher):
            raise ValueError("Observed native child launcher differs from the installed artifact")
        if installed_python is None:
            if not path_equal(child["cwd"], expected_cwd):
                raise ValueError("Native child inherited an unexpected working directory")
            continue
        python = journey.plain(installed_python, journey.ROOT)
        if python.parent.name.lower() != "scripts" or not path_equal(python, launcher.with_name("python.exe")):
            raise ValueError("Installed wheel interpreter is not bound to its exact launcher")
        settings = {}
        configuration = journey.plain(python.parent.parent / "pyvenv.cfg", journey.ROOT)
        for line in configuration.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                key = key.strip()
                if key in settings:
                    raise ValueError("Installed wheel interpreter configuration has duplicate keys")
                settings[key] = value.strip()
        if not settings.get("executable") or not settings.get("home"):
            raise ValueError("Installed wheel base interpreter binding is missing")
        base_python = journey.plain(settings["executable"])
        if (base_python.name.lower() != "python.exe" or path_equal(base_python, python)
                or not path_equal(base_python.parent, settings["home"])):
            raise ValueError("Installed wheel base interpreter binding is malformed")
        expected_python_argv = [str(python), *expected_server]
        chain = []
        parent_pid = child["pid"]
        for image in (python, base_python):
            matches = [item for item in by_pid.values()
                       if item["parent_pid"] == parent_pid and path_equal(item["image"], image)]
            if len(matches) != 1:
                raise ValueError("Native wheel has no unique exact installed Python continuation")
            item = matches[0]
            if (not path_equal(item["cwd"], expected_cwd) or argv(item["command_line"]) != expected_python_argv
                    or item["image_sha256"] != journey.sha(image)
                    or not path_equal(item.get("image_parameter", ""), image)):
                raise ValueError("Native installed Python continuation has foreign cwd, arguments or image")
            chain.append(item["pid"])
            parent_pid = item["pid"]
        console = Path(os.environ["SystemRoot"]) / "System32/conhost.exe"
        for item in by_pid.values():
            cursor = item
            while cursor["pid"] != record["pid"] and cursor["parent_pid"] != child["pid"]:
                cursor = by_pid[cursor["parent_pid"]]
            if cursor["parent_pid"] != child["pid"] or item["pid"] in chain:
                continue
            if (item["parent_pid"] == child["pid"] and path_equal(item["image"], console)
                    and item["image_sha256"] == journey.sha(console)):
                continue
            raise ValueError("Native installed Python continuation includes a foreign child")
    connected = bool(record.get("discovery", {}).get("data")) if isinstance(record.get("discovery"), dict) else False
    if connected and len(launchers) != 1:
        raise ValueError("Native discovery has no exact direct installed-server process")
    return {"root_pid": record["pid"], "observed_children": len(by_pid) - 1, "all_observed_stopped": True,
            "installed_launcher_pids": [item["pid"] for item in launchers], "tool_calls": len(native_calls)}


def phase_behavior(record, expected, capture, token):
    tools = record.get("tools", {})
    if record.get("error") or tuple(tools) != LABELS:
        return {"passed": False, "reason": record.get("error") or "The exact expected tool sequence did not complete"}
    payloads = {label: journey.tool_payload(value["result"]) for label, value in tools.items()}
    notes = {"project": journey.PROJECT_NOTE, "source": journey.SOURCE_NOTE, "capture": capture}
    for label, relative in notes.items():
        item = payloads[label]
        if item.get("path") != relative or item.get("sha256") != expected[relative] or item.get("truncated") is not False:
            return {"passed": False, "reason": "Native note content or source hash differs", "label": label}
    project = payloads["project"]
    if project.get("frontmatter", {}).get("id") != journey.PROJECT_ID or token not in project.get("body", ""):
        return {"passed": False, "reason": "Native recall selected a different vault or note"}
    ranked = payloads["search"].get("ranked", [])
    related = payloads["related"].get("related", [])
    sid = payloads["session_start"].get("session_id")
    checks = {"capture_recalled": any(row.get("path") == capture for row in ranked),
              "relative_source_link_recalled": any(row.get("path") == journey.SOURCE_NOTE for row in related),
              "relative_source_link_bytes": "[Source](../Research/relocated-orbit-source.md)" in project.get("body", ""),
              "session_propagated": bool(sid) and sid == record.get("session_id") == tools["session_end"]["arguments"].get("session_id") == payloads["session_end"].get("session_id")}
    return {"passed": all(checks.values()), "checks": checks, "session_id": sid,
            "project_sha256": project["sha256"], "source_sha256": payloads["source"]["sha256"]}


def checked_binding(binding):
    artifact, launcher, environment, checked, toolkit = journey.validate_artifact(Path(binding["artifact_report"]))
    if (binding.get("artifact_report_sha256") != journey.sha(binding["artifact_report"])
            or binding.get("artifact") != artifact["artifact"] or binding.get("installation") != artifact["installation"]
            or binding.get("checked_artifact") != checked or binding.get("toolkit") != toolkit):
        raise ValueError("Native move installed artifact binding is malformed or stale")
    return artifact, launcher, environment, checked, toolkit


def checked_evidence(directory, evidence):
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("Original evidence manifest is missing")
    for name, digest in evidence.items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or journey.sha(journey.plain(directory / relative, directory)) != digest):
            raise ValueError("Native move evidence changed: " + name)


def grade(path, expected_sha256):
    if os.name != "nt" or sys.platform != "win32":
        raise ValueError("Installed native move grading requires Windows")
    path = journey.contained_output(path)
    if not re.fullmatch("[0-9a-f]{64}", expected_sha256 or "") or journey.sha(path) != expected_sha256:
        raise ValueError("Original report hash is missing or changed")
    report = journey.read_json(path)
    directory = path.parent
    if report.get("producer") != journey.PRODUCER or report.get("producer_sha256") != journey.sha(journey.__file__) or report.get("support_sha256") != {"native_process.py": journey.sha(journey.BASE / "native_process.py")}:
        raise ValueError("Native move producer or support hash changed")
    if report.get("gate") != TARGET or report.get("scope") != "artifact" or report.get("platform") != "Windows" or report.get("model_calls") != 0 or report.get("sign_in_copied") is not False:
        raise ValueError("Native move report scope changed")
    evidence = report.get("evidence")
    checked_evidence(directory, evidence)
    binding = report["binding"]
    artifact, launcher, environment, checked, toolkit = checked_binding(binding)
    before, after = (journey.read_json(directory / name) for name in ("binding-before.json", "binding-after.json"))
    source_toolkit = journey.acceptance_module().data_toolkit_hashes()
    if (report.get("isolation_unchanged") is not True or before != after
            or before.get("installed_environment") != journey.inventory(environment)
            or before.get("toolkit") != source_toolkit or binding.get("complete_source_toolkit") != source_toolkit):
        raise ValueError("Native move current source, installation or isolation binding changed")
    for name, digest in before["sentinels"].items():
        if journey.sha(name) != digest:
            raise ValueError("Real-vault or user-config sentinel changed since native observation")
    if before.get("native_cli_sha256") != journey.CLI_SHA256 or journey.sha(binding["native_cli"]) != journey.CLI_SHA256:
        raise ValueError("Native host executable changed")
    generated_path = directory / "generated-config.original.toml"
    generated = generated_path.read_bytes()
    if journey.sha(generated_path) != report.get("generated_config_sha256"):
        raise ValueError("Original generated native configuration changed")
    import tomllib
    server = tomllib.loads(generated.decode("utf-8"))["mcp_servers"]["knowledgeos"]
    if server != report.get("generated_server") or not path_equal(server["command"], launcher):
        raise ValueError("Generated server no longer binds the exact installed launcher")
    paths = report["paths"]
    for name in ("original", "moved", "preserved", "gate_state"):
        journey.plain(paths[name], directory)
    if (Path(paths["moved"]) / ".codex/config.toml").read_bytes() != generated:
        raise ValueError("Generated server bytes were changed through relocation")
    inventories = {name: journey.read_json(directory / name) for name in (
        "vault-before-move.inventory.json", "vault-after-rename.inventory.json", "unrelated-before.inventory.json",
        "unrelated-after.inventory.json", "vault-final.inventory.json")}
    if inventories["vault-before-move.inventory.json"] != inventories["vault-after-rename.inventory.json"] or journey.inventory(Path(paths["preserved"])) != inventories["vault-before-move.inventory.json"]:
        raise ValueError("Move or preserved original copy changed content")
    plan = journey.read_json(directory / "move.plan.json")
    if (plan.get("operation") != "Path.rename" or plan.get("all_targets_contained_before_move") is not True
            or plan.get("same_device") is not True or not path_equal(plan["source"], paths["original"])
            or not path_equal(plan["target"], paths["moved"])):
        raise ValueError("Contained same-device move plan is missing or malformed")
    expected = report["note_hashes"]
    for name, digest in expected.items():
        if journey.sha(journey.plain(Path(paths["moved"]) / name, directory)) != digest or inventories["vault-before-move.inventory.json"].get(name) != digest:
            raise ValueError("Protected note, link, identity or vault marker changed")
    marker = journey.read_json(Path(paths["moved"]) / ".knowledgeos-vault.json")
    unrelated_marker = journey.read_json(Path(paths["original"]) / ".knowledgeos-vault.json")
    if marker.get("vault_id") != report.get("vault_id") or unrelated_marker.get("vault_id") != report.get("unrelated_vault_id") or marker["vault_id"] == unrelated_marker["vault_id"]:
        raise ValueError("Original and unrelated replacement vault identities are not distinct and stable")
    phases = report.get("phases")
    if not isinstance(phases, list) or tuple(item.get("phase") for item in phases) != journey.PHASES:
        raise ValueError("All three native relocation phases are required")
    results, process_results = {}, {}
    for phase in phases:
        name = phase["phase"]
        phase_path = directory / name / "report.json"
        if phase.get("path") != name + "/report.json" or phase.get("sha256") != journey.sha(phase_path):
            raise ValueError("Native phase report changed")
        raw = journey.read_json(phase_path)
        expected_cwd = paths["original"] if name == journey.PHASES[0] else paths["moved"]
        if raw.get("phase") != name or not path_equal(raw["cwd"], expected_cwd) or raw.get("generated_config_sha256") != report["generated_config_sha256"]:
            raise ValueError("Native phase context or generated server configuration changed")
        phase_dir = phase_path.parent
        if journey.sha(phase_dir / "host-home/config.toml") != raw.get("home_config_sha256"):
            raise ValueError("Credential-free owned host trust config changed")
        import tomllib
        home_config = tomllib.loads((phase_dir / "host-home/config.toml").read_text(encoding="utf-8"))
        expected_home = {"project_root_markers": [".knowledgeos-vault.json"],
                         "projects": {raw["cwd"]: {"trust_level": "trusted"}}, "analytics": {"enabled": False}}
        if home_config != expected_home or (phase_dir / "host-home/auth.json").exists():
            raise ValueError("Owned host configuration contains unrelated settings or sign-in state")
        messages = [json.loads(line) for line in (phase_dir / "host.stdout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        requests = journey.read_json(phase_dir / "host.requests.json")
        process_results[name] = native_protocol(raw, messages, requests, generated=server, launcher=launcher, native_cli=binding["native_cli"],
                                                installed_python=artifact["installation"]["python"] if artifact["artifact"]["kind"] == "wheel" else None)
        results[name] = phase_behavior(raw, expected, report["capture_path"], report["token"])
    for command in report.get("commands", []):
        process_tree(command, require_live_parameters=False)
        if command.get("exit_code") != 0 or command.get("stopped") is not True:
            raise ValueError("Installed setup command failed or shutdown is unknown")
    unrelated_unchanged = inventories["unrelated-before.inventory.json"] == inventories["unrelated-after.inventory.json"] == journey.inventory(Path(paths["original"]))
    all_passed = all(row["passed"] for row in results.values()) and unrelated_unchanged and report.get("error") is None
    return {"producer": PRODUCER, "producer_sha256": journey.sha(journey.__file__), "adapter_sha256": journey.sha(__file__),
            "path": str(path), "report_sha256": expected_sha256, "scope": "artifact", "eligible_outcomes": [TARGET],
            "artifact_cell": checked["cell"], "artifact_sha256": artifact["artifact"]["sha256"],
            "artifact_report": binding["artifact_report"], "artifact_report_sha256": binding["artifact_report_sha256"],
            "transcript_files": {**evidence, "report.json": expected_sha256}, "helper_hashes": helper_hashes(),
            "verdict": "PASS" if all_passed else "FAIL", "phases": results, "process_proof": process_results,
            "unrelated_replacement_unchanged": unrelated_unchanged, "model_calls": 0,
            "checks": {"port.same_device_move": {"id": "port.same_device_move", "verdict": "PASS" if all_passed else "FAIL",
                       "expected": EXPECTED, "observed": {"phases": results, "unrelated_unchanged": unrelated_unchanged},
                       "evidence": sorted(evidence)}}, "limits": report["limits"],
            "fixed54_credit": "Requires root scorer integration; this standalone adapter never changes the cumulative score."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = grade(arguments.report, arguments.expected_report_sha256)
    journey.save(journey.contained_output(arguments.output, exists=False), result)
    print(json.dumps({"output": str(arguments.output), "verdict": result["verdict"], "eligible_outcomes": result["eligible_outcomes"],
                      "phases": {name: row["passed"] for name, row in result["phases"].items()}, "model_calls": 0}), flush=True)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
