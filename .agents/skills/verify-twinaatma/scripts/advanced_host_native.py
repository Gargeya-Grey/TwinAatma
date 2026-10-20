"""Run hash-bound native Windows graders through one WSL bridge."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import secrets
import stat
import subprocess
import sys
import time

HELPER = Path(__file__).absolute()
ROOT = HELPER.parents[4]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
WINDOWS_ROOT = PureWindowsPath("W:/AI-Projects/TwinAatma")
WSL_ROOT = "/mnt/w/AI-Projects/TwinAatma"
RUNTIME = "work/gc-artifacts/.knowledgeos/runtime-hooks-20261019/runtimes/additional/cpython-3.14.7-windows-x86_64-none/python.exe"
INTERPRETER = WINDOWS_ROOT.joinpath(*PurePosixPath(RUNTIME).parts)
WSL_INTERPRETER = WSL_ROOT + "/" + RUNTIME
INTERPRETER_SHA256 = "716fbcb56cb6753dd9ea9f7acb3f988e9c4ba65ab492cb32b9bcd0ab81938737"
INTERPRETER_VERSION = "3.14.7"
DEPENDENCY = ROOT / "work/gc-artifacts/.knowledgeos/host-grader-native-bridge-20261019/dependencies/pyyaml-6.0.1"
DEPENDENCY_MANIFEST_SHA256 = "0abfaa112e29c436d7b4553201718f037db5d9be2336960dfb8868f6d8315d2e"
SCHEMA = "verify-twinaatma.advanced-host-native/v1"
PRODUCER = "verify-twinaatma.advanced-host-staged/v2"
TARGETS = (
    "QUALITY.correction_lifecycle", "LEARNING.host_outcome_loop",
    "PRIVACY.selective_capture", "PRIVACY.untrusted_notes",
)
RESULT_KEYS = {
    "path", "report_sha256", "scope", "producer", "producer_sha256",
    "adapter_sha256", "host", "transcript_files", "support_hashes",
    "offline_regrade", "checks",
}
HEX = re.compile(r"[0-9a-f]{64}\Z")
NATIVE_FLAGS = {"score": "--native", "infrastructure-probe": "--probe-native", "installed-move": "--native-move"}
OPERATIONS = set(NATIVE_FLAGS)
MOVE_SUPPORT = ("installed_move.py", "grade_installed_move.py", "native_process.py", "acceptance.py", "artifact.py")
MOVE_RESULT_KEYS = {
    "producer", "producer_sha256", "adapter_sha256", "path", "report_sha256", "scope", "eligible_outcomes",
    "artifact_cell", "artifact_sha256", "artifact_report", "artifact_report_sha256", "transcript_files", "helper_hashes",
    "verdict", "phases", "process_proof", "unrelated_replacement_unchanged", "model_calls", "checks", "limits", "fixed54_credit",
}
INFRASTRUCTURE_RESULT = {"adapter_called": False, "source_binding_verified": True,
                         "strict_helper_imported": True, "pyyaml_version": "6.0.1",
                         "pure_python_dependency": True}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plain_file(path, root=ROOT):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("Bridge file contains a parent traversal")
    if root is not None:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError("Bridge file escapes the current checkout") from error
    cursor = path
    while True:
        info = cursor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Bridge file or parent uses a linked path")
        if cursor == path:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Bridge file is not a plain single-link file")
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("Bridge file parent is not a directory")
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    if path.resolve(strict=True) != path:
        raise ValueError("Bridge file does not have its canonical path")
    return path


def relative_name(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Bridge requires a nonempty relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or ".." in path.parts
            or any(re.search(r'[\\:<>|?*\x00-\x1f]', part) or part.endswith((" ", ".")) for part in path.parts)):
        raise ValueError("Bridge requires a canonical relative path")
    return path


def windows_path(value):
    raw = str(value)
    path = PurePosixPath(raw)
    if (path.as_posix() != raw or len(path.parts) < 4 or path.parts[:2] != ("/", "mnt")
            or not re.fullmatch(r"[a-z]", path.parts[2])):
        raise ValueError("Bridge supports only canonical /mnt/<drive>/<checkout> paths")
    relative_name("/".join(path.parts[3:]))
    return str(PureWindowsPath(path.parts[2].upper() + ":/").joinpath(*path.parts[3:]))


def native_path(path):
    return str(path) if os.name == "nt" else windows_path(path)


def require_windows():
    if (os.name != "nt" or sys.platform != "win32" or PureWindowsPath(ROOT) != WINDOWS_ROOT
            or PureWindowsPath(sys.executable) != INTERPRETER
            or platform.python_implementation() != "CPython" or platform.python_version() != INTERPRETER_VERSION
            or sha(plain_file(sys.executable)) != INTERPRETER_SHA256):
        raise ValueError("Bridge native mode requires the exact hash-pinned Windows CPython 3.14.7 grading runtime on W:")


def require_wsl():
    if os.name != "posix" or platform.system() != "Linux" or "microsoft" not in platform.release().lower():
        raise ValueError("Bridge supports only native Windows or WSL Linux")
    if str(ROOT) != WSL_ROOT or PureWindowsPath(windows_path(ROOT)) != WINDOWS_ROOT:
        raise ValueError("Bridge requires the canonical /mnt/w/AI-Projects/TwinAatma checkout")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, plain_file(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dependency_hashes():
    manifest = plain_file(DEPENDENCY / "manifest.json")
    if sha(manifest) != DEPENDENCY_MANIFEST_SHA256:
        raise ValueError("Bridge declared dependency manifest changed")
    data = parse_json(manifest.read_text(encoding="utf-8"))
    files = data.get("files")
    if (data.get("schema") != "verify-twinaatma.native-bridge-dependency/v1"
            or data.get("name") != "PyYAML" or data.get("version") != "6.0.1"
            or data.get("mode") != "pure-python" or not isinstance(files, dict) or len(files) != 19):
        raise ValueError("Bridge declared dependency has an unfamiliar inventory")
    actual_names = set()
    for path in DEPENDENCY.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Bridge declared dependency uses a linked path")
        if not stat.S_ISDIR(info.st_mode):
            actual_names.add(path.relative_to(DEPENDENCY).as_posix())
    if actual_names != set(files) | {"manifest.json"}:
        raise ValueError("Bridge declared dependency has missing or unexpected package bytes")
    for name, digest in files.items():
        if (not isinstance(digest, str) or not HEX.fullmatch(digest)
                or sha(plain_file(DEPENDENCY.joinpath(*relative_name(name).parts))) != digest):
            raise ValueError("Bridge declared dependency file changed")
    return {"manifest_sha256": DEPENDENCY_MANIFEST_SHA256, "files": files}


def load_grading_dependency():
    dependency_hashes()
    if any(name == "yaml" or name.startswith("yaml.") for name in sys.modules):
        raise ValueError("Bridge refuses a preloaded undeclared YAML package")
    path = plain_file(DEPENDENCY / "yaml/__init__.py")
    spec = importlib.util.spec_from_file_location("yaml", path, submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["yaml"] = module
    spec.loader.exec_module(module)
    if module.__version__ != "6.0.1" or module.__with_libyaml__ is not False:
        raise ValueError("Bridge requires the declared pure Python PyYAML dependency")
    return module


def validate_current(current):
    if not isinstance(current, dict) or not current:
        raise ValueError("Bridge requires the complete current source hash dictionary")
    for name, digest in current.items():
        path = relative_name(name)
        if (name != "AGENTS.md" and not (path.suffix == ".py" and path.parent.as_posix() in ("knowledgeos", ".cursor/hooks"))
                or not isinstance(digest, str) or not HEX.fullmatch(digest)):
            raise ValueError("Bridge source dictionary contains an unknown path or hash")


def binding(path, current, operation="score"):
    if operation not in OPERATIONS:
        raise ValueError("Unknown bridge operation")
    validate_current(current)
    report = plain_file(path)
    relative = report.relative_to(ROOT).as_posix()
    parts = relative_name(relative).parts
    if parts[:3] != ("work", "gc-artifacts", ".knowledgeos"):
        raise ValueError("Bridge report must be contained beneath work/gc-artifacts/.knowledgeos")
    helper = plain_file(HELPER)
    acceptance_path = plain_file(SCRIPTS / "acceptance.py")
    adapter_path = plain_file(SCRIPTS / ("grade_installed_move.py" if operation == "installed-move" else "advanced_host_acceptance.py"))
    acceptance = load_module(acceptance_path, "_native_bridge_acceptance")
    actual = acceptance.product_hashes()
    validate_current(actual)
    for name in actual:
        plain_file(ROOT.joinpath(*relative_name(name).parts))
    if actual != current:
        raise ValueError("Bridge current source dictionary is missing, unknown or stale")
    interpreter = Path(str(INTERPRETER)) if os.name == "nt" else Path(WSL_INTERPRETER)
    interpreter_sha = sha(plain_file(interpreter))
    if interpreter_sha != INTERPRETER_SHA256:
        raise ValueError("Bridge grading interpreter bytes changed")
    bound = {
        "root": native_path(ROOT), "helper": native_path(helper),
        "helper_sha256": sha(helper), "acceptance_sha256": sha(acceptance_path),
        "adapter_sha256": sha(adapter_path), "interpreter": str(INTERPRETER),
        "interpreter_sha256": interpreter_sha, "interpreter_version": INTERPRETER_VERSION,
        "dependency": dependency_hashes(),
        "report": relative, "report_sha256": sha(report), "current_hashes": actual,
    }
    if operation == "installed-move":
        bound["move_helpers"] = {name: sha(plain_file(SCRIPTS / name)) for name in MOVE_SUPPORT}
    return bound


def parse_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Bridge JSON contains a duplicate key")
            value[key] = item
        return value
    def invalid(value):
        raise ValueError("Bridge JSON contains a nonfinite number")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def make_request(path, current, operation):
    if operation not in OPERATIONS:
        raise ValueError("Unknown bridge operation")
    return {"schema": SCHEMA + ".request", "operation": operation,
            "nonce": secrets.token_hex(32), "binding": binding(path, current, operation)}


def native_process(started_ns):
    return {"pid": os.getpid(), "parent_pid": os.getppid(), "platform": sys.platform,
            "os_name": os.name, "executable": sys.executable,
            "interpreter_sha256": sha(plain_file(sys.executable)),
            "version": platform.python_version(), "sys_version": sys.version,
            "implementation": platform.python_implementation(),
            "started_ns": started_ns, "ended_ns": time.time_ns()}


def report_windows_path(bound):
    return str(PureWindowsPath(bound["root"]).joinpath(*relative_name(bound["report"]).parts))


def validate_result(result, bound, native):
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        raise ValueError("Native grader returned an unfamiliar or incomplete result schema")
    expected_report = report_windows_path(bound)
    producer = ROOT / "work/gc-artifacts/.knowledgeos/advanced-host-c-20261020/advanced_host.py"
    if (result["path"] != expected_report or result["report_sha256"] != bound["report_sha256"]
            or result["scope"] != "real_host" or result["producer"] != PRODUCER
            or result["adapter_sha256"] != bound["adapter_sha256"]
            or result["producer_sha256"] != sha(plain_file(producer))):
        raise ValueError("Native grader result has stale or unknown source/report hashes")
    host = result["host"]
    if (not isinstance(host, dict) or set(host) != {"name", "version", "configured_model", "mode"}
            or host["name"] != "codex-cli" or host["mode"] != "native ephemeral source host"
            or any(not isinstance(value, str) or not value for value in host.values())):
        raise ValueError("Native grader result lacks its genuine-host identity")
    transcripts = result["transcript_files"]
    if not isinstance(transcripts, dict) or not transcripts or transcripts.get("report.json") != bound["report_sha256"]:
        raise ValueError("Native grader result lacks the current complete transcript hashes")
    directory = ROOT.joinpath(*relative_name(bound["report"]).parts).parent
    for name, digest in transcripts.items():
        if not isinstance(digest, str) or not HEX.fullmatch(digest) or sha(plain_file(directory.joinpath(*relative_name(name).parts))) != digest:
            raise ValueError("Native grader retained transcript hash changed")
    support = result["support_hashes"]
    if not isinstance(support, dict) or not support:
        raise ValueError("Native grader result lacks its trusted support hashes")
    for name, digest in support.items():
        if not isinstance(name, str) or str(PureWindowsPath(name)) != name:
            raise ValueError("Native grader support path is not canonical Windows")
        try:
            relative = PureWindowsPath(name).relative_to(PureWindowsPath(bound["root"])).as_posix()
        except ValueError as error:
            raise ValueError("Native grader support path escapes this checkout") from error
        if not isinstance(digest, str) or not HEX.fullmatch(digest) or sha(plain_file(ROOT.joinpath(*relative_name(relative).parts))) != digest:
            raise ValueError("Native grader support hash changed or is unknown")
    regrade = result["offline_regrade"]
    if (not isinstance(regrade, dict) or set(regrade) != {"original_report", "original_report_sha256", "new_model_calls", "method"}
            or regrade["original_report"] != expected_report or regrade["original_report_sha256"] != bound["report_sha256"]
            or type(regrade["new_model_calls"]) is not int or regrade["new_model_calls"] != 0
            or not isinstance(regrade["method"], str) or not regrade["method"]):
        raise ValueError("Native grader result is not the exact retained-observation regrade")
    checks = result["checks"]
    expected_checks = {"advanced_host." + target for target in TARGETS}
    if not isinstance(checks, dict) or set(checks) != expected_checks:
        raise ValueError("Native grader result lacks all four exact target checks")
    rubric = parse_json(plain_file(ROOT / ".agents/skills/verify-twinaatma/references/acceptance-rubric.json").read_text(encoding="utf-8-sig"))
    items = {row["id"]: row for row in rubric["outcomes"]}
    for identifier, row in checks.items():
        target = identifier.removeprefix("advanced_host.")
        if (not isinstance(row, dict) or set(row) != {"id", "verdict", "expected", "observed", "evidence"}
                or row["id"] != identifier or row["verdict"] not in ("PASS", "FAIL", "BLOCKED", "NOT CHECKED")
                or row["expected"] != items[target]["expected"] or row["evidence"] != sorted(transcripts)):
            raise ValueError("Native grader target check is malformed or references unknown evidence")
        observed = row["observed"]
        if (not isinstance(observed, dict) or set(observed) != {"regraded_outcome", "checks", "thread_ids", "session_ids", "lifetime_probes"}
                or not isinstance(observed["regraded_outcome"], dict)
                or observed["regraded_outcome"].get("id") != target or observed["regraded_outcome"].get("verdict") != row["verdict"]
                or not isinstance(observed["checks"], list) or not observed["checks"]):
            raise ValueError("Native grader target check lacks its actual regraded observation")
        for field in ("thread_ids", "session_ids"):
            values = observed[field]
            if not isinstance(values, list) or len(values) != 3 or any(not isinstance(value, str) or not value for value in values) or len(set(values)) != 3:
                raise ValueError("Native grader target check lacks three distinct completed chats")
        probes = observed["lifetime_probes"]
        if not isinstance(probes, list) or len(probes) != 6:
            raise ValueError("Native grader target check lacks six fresh Windows lifetime probes")
        for probe in probes:
            if (not isinstance(probe, dict) or type(probe.get("pid")) is not int or probe["pid"] <= 0
                    or probe.get("method") != "read-only kernel process wait" or probe.get("stopped") is not True
                    or type(probe.get("observed_ns")) is not int
                    or not native["started_ns"] <= probe["observed_ns"] <= native["ended_ns"]):
                raise ValueError("Native grader lifetime probe is stale or did not prove shutdown")


def validate_move_result(result, bound):
    if not isinstance(result, dict) or set(result) != MOVE_RESULT_KEYS:
        raise ValueError("Native move result has an unfamiliar or incomplete schema")
    support = bound.get("move_helpers")
    actual_support = {name: sha(plain_file(SCRIPTS / name)) for name in MOVE_SUPPORT}
    report_path = ROOT.joinpath(*relative_name(bound["report"]).parts)
    report = parse_json(plain_file(report_path).read_text(encoding="utf-8"))
    original = report.get("binding", {})
    expected_cell = original.get("checked_artifact", {}).get("cell")
    if (not isinstance(support, dict) or support != actual_support or result["helper_hashes"] != support
            or result["producer"] != "verify-twinaatma.native-installed-move-grade/v2"
            or result["producer_sha256"] != support["installed_move.py"]
            or result["adapter_sha256"] != bound["adapter_sha256"]
            or result["adapter_sha256"] != support["grade_installed_move.py"]
            or result["path"] != report_windows_path(bound) or result["report_sha256"] != bound["report_sha256"]
            or result["scope"] != "artifact" or result["eligible_outcomes"] != ["PORT.same_device_move"]
            or result["artifact_cell"] != expected_cell or expected_cell not in (["Windows", "wheel"], ["Windows", "binary"])
            or result["artifact_sha256"] != original.get("artifact", {}).get("sha256")
            or not isinstance(result["artifact_sha256"], str) or not HEX.fullmatch(result["artifact_sha256"])
            or result["artifact_report"] != original.get("artifact_report")
            or result["artifact_report_sha256"] != original.get("artifact_report_sha256")):
        raise ValueError("Native move result has stale source/report/artifact/helper binding")
    artifact_relative = PureWindowsPath(result["artifact_report"]).relative_to(PureWindowsPath(bound["root"]))
    artifact_path = plain_file(ROOT.joinpath(*relative_name(artifact_relative.as_posix()).parts))
    if sha(artifact_path) != result["artifact_report_sha256"]:
        raise ValueError("Native move artifact report changed after native inspection")
    transcripts = result["transcript_files"]
    if (not isinstance(transcripts, dict) or transcripts != {**report.get("evidence", {}), "report.json": bound["report_sha256"]}
            or not report.get("evidence")):
        raise ValueError("Native move result lacks the complete original evidence digest")
    for name, digest in transcripts.items():
        path = plain_file(report_path.parent.joinpath(*relative_name(name).parts))
        if not isinstance(digest, str) or not HEX.fullmatch(digest) or sha(path) != digest:
            raise ValueError("Native move retained transcript changed")
    phases = result["phases"]
    names = ("before-move", "after-move-old-absent", "after-move-old-reused")
    if (not isinstance(phases, dict) or set(phases) != set(names)
            or any(not isinstance(row, dict) or type(row.get("passed")) is not bool for row in phases.values())
            or type(result["unrelated_replacement_unchanged"]) is not bool
            or type(result["model_calls"]) is not int or result["model_calls"] != 0
            or result["limits"] != report.get("limits")
            or result["verdict"] not in ("PASS", "FAIL")):
        raise ValueError("Native move result scope or phase inventory changed")
    passed = all(row["passed"] for row in phases.values()) and result["unrelated_replacement_unchanged"] and report.get("error") is None
    if result["verdict"] != ("PASS" if passed else "FAIL"):
        raise ValueError("Native move verdict contradicts its phase observations")
    processes = result["process_proof"]
    if not isinstance(processes, dict) or set(processes) != set(names):
        raise ValueError("Native move result lacks all phase process observations")
    for row in processes.values():
        if (not isinstance(row, dict) or set(row) != {"root_pid", "observed_children", "all_observed_stopped", "installed_launcher_pids", "tool_calls"}
                or type(row["root_pid"]) is not int or row["root_pid"] <= 0 or row["all_observed_stopped"] is not True
                or type(row["observed_children"]) is not int or row["observed_children"] < 0
                or type(row["tool_calls"]) is not int or not 0 <= row["tool_calls"] <= 7
                or not isinstance(row["installed_launcher_pids"], list)
                or any(type(pid) is not int or pid <= 0 for pid in row["installed_launcher_pids"])):
            raise ValueError("Native move result process shutdown proof is malformed")
    checks = result["checks"]
    rubric = parse_json(plain_file(ROOT / ".agents/skills/verify-twinaatma/references/acceptance-rubric.json").read_text(encoding="utf-8-sig"))
    expected = next(row["expected"] for row in rubric["outcomes"] if row["id"] == "PORT.same_device_move")
    wanted = {"port.same_device_move": {"id": "port.same_device_move", "verdict": result["verdict"],
              "expected": expected, "observed": {"phases": phases, "unrelated_unchanged": result["unrelated_replacement_unchanged"]},
              "evidence": sorted(report["evidence"])}}
    if checks != wanted:
        raise ValueError("Native move result must prove exactly one fixed portability outcome")


def validate_packet(packet, request, started_ns, ended_ns):
    if (request.get("operation") not in OPERATIONS
            or not isinstance(packet, dict) or set(packet) != {"schema", "operation", "nonce", "binding", "native", "result"}
            or packet["schema"] != SCHEMA + ".response" or packet["operation"] != request["operation"]
            or packet["nonce"] != request["nonce"] or packet["binding"] != request["binding"]):
        raise ValueError("Native bridge response schema, nonce or complete source binding differs")
    native = packet["native"]
    if (not isinstance(native, dict) or set(native) != {"pid", "parent_pid", "platform", "os_name", "executable", "started_ns", "ended_ns",
                                                     "interpreter_sha256", "version", "sys_version", "implementation"}
            or native["platform"] != "win32" or native["os_name"] != "nt" or native["executable"] != str(INTERPRETER)
            or native["interpreter_sha256"] != INTERPRETER_SHA256 or native["version"] != INTERPRETER_VERSION
            or native["implementation"] != "CPython" or not isinstance(native["sys_version"], str)
            or not native["sys_version"].startswith(INTERPRETER_VERSION + " ")
            or any(type(native[key]) is not int or native[key] <= 0 for key in ("pid", "parent_pid", "started_ns", "ended_ns"))
            or not started_ns <= native["started_ns"] <= native["ended_ns"] <= ended_ns):
        raise ValueError("Native bridge did not execute freshly under the exact Windows interpreter")
    if request["operation"] == "score":
        validate_result(packet["result"], request["binding"], native)
    elif request["operation"] == "installed-move":
        validate_move_result(packet["result"], request["binding"])
    elif packet["result"] != INFRASTRUCTURE_RESULT:
        raise ValueError("Infrastructure probe response is malformed")
    return packet


class BridgeFailure(ValueError):
    def __init__(self, message, process):
        super().__init__(message + "; bridge process=" + json.dumps(process, sort_keys=True))
        self.process = process


def invoke_windows(path, current, operation="score"):
    require_wsl()
    request = make_request(path, current, operation)
    raw = json.dumps(request, sort_keys=True, allow_nan=False).encode("utf-8")
    command = [WSL_INTERPRETER, "-I", "-B", request["binding"]["helper"],
               NATIVE_FLAGS[operation]]
    started_ns = time.time_ns()
    child = subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process = {"pid": child.pid, "pid_namespace": "linux", "exit_code": None, "stopped": False,
               "windows_pid": None, "windows_exit_code": None, "windows_stopped": None}
    try:
        stdout, stderr = child.communicate(raw, timeout=60)
    except subprocess.TimeoutExpired as error:
        child.kill()
        child.communicate()
        process.update(exit_code=child.returncode, stopped=child.poll() is not None)
        raise BridgeFailure("Native host bridge timed out; Windows helper shutdown is unknown", process) from error
    process.update(exit_code=child.returncode, stopped=child.poll() is not None)
    ended_ns = time.time_ns()
    if child.returncode != 0 or stderr or not stdout or len(stdout) > 16 * 1024 * 1024:
        detail = stderr.decode("utf-8", errors="replace")[:2048]
        raise BridgeFailure("Native host bridge failed or returned unexpected output: " + detail, process)
    try:
        packet = validate_packet(parse_json(stdout.decode("utf-8")), request, started_ns, ended_ns)
        if binding(path, current, operation) != request["binding"]:
            raise ValueError("Bridge source or report changed during the native inspection")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise BridgeFailure("Native host bridge response rejected: " + str(error), process) from error
    process.update(windows_pid=packet["native"]["pid"], windows_exit_code=child.returncode, windows_stopped=True)
    evidence = {"schema": SCHEMA, "mode": "wsl-to-windows", "operation": operation,
                "command": command, "request_sha256": hashlib.sha256(raw).hexdigest(),
                "response_sha256": hashlib.sha256(stdout).hexdigest(), "native": packet["native"],
                "process": process, "binding": packet["binding"]}
    return packet["result"], evidence


def advanced_host_report(path, current, *, rendezvous=None):
    if os.name == "nt":
        require_windows()
        started_ns = time.time_ns()
        bound = binding(path, current)
        load_grading_dependency()
        adapter = load_module(SCRIPTS / "advanced_host_acceptance.py", "_native_bridge_adapter")
        result = adapter.advanced_host_report(path, current)
        native = native_process(started_ns)
        if binding(path, current) != bound:
            raise ValueError("Native grader source or report changed during inspection")
        validate_result(result, bound, native)
        result["native_bridge"] = {"schema": SCHEMA, "mode": "windows-direct", "operation": "score",
                                   "native": native, "binding": bound,
                                   "process": {"pid": os.getpid(), "pid_namespace": "windows", "new_process": False,
                                               "exit_code": None, "stopped": False, "caller_running": True}}
        return result
    if rendezvous is None:
        result, evidence = invoke_windows(path, current)
    else:
        from native_grader_rendezvous import invoke_windows as exchange
        result, evidence = exchange(path, current, rendezvous, bridge=sys.modules[__name__])
    result["native_bridge"] = evidence
    return result


def load_move_adapter():
    names = ("native_process", "installed_move")
    if any(name in sys.modules for name in names):
        raise ValueError("Native move grader refuses preloaded undeclared support modules")
    try:
        for name in names:
            module = load_module(SCRIPTS / (name + ".py"), name)
            sys.modules[name] = module
        return load_module(SCRIPTS / "grade_installed_move.py", "_native_move_adapter")
    finally:
        for name in names:
            sys.modules.pop(name, None)


def installed_move_report(path, current, *, rendezvous=None):
    if os.name == "nt":
        require_windows()
        started_ns = time.time_ns()
        bound = binding(path, current, "installed-move")
        result = load_move_adapter().grade(path, bound["report_sha256"])
        native = native_process(started_ns)
        if binding(path, current, "installed-move") != bound:
            raise ValueError("Native move source or report changed during inspection")
        validate_move_result(result, bound)
        result["native_bridge"] = {"schema": SCHEMA, "mode": "windows-direct", "operation": "installed-move",
                                   "native": native, "binding": bound,
                                   "process": {"pid": os.getpid(), "pid_namespace": "windows", "new_process": False,
                                               "exit_code": None, "stopped": False, "caller_running": True}}
        return result
    if rendezvous is None:
        result, evidence = invoke_windows(path, current, "installed-move")
    else:
        from native_grader_rendezvous import invoke_windows as exchange
        channel = Path(rendezvous) / ("installed-move-" + sha(plain_file(path)))
        result, evidence = exchange(path, current, channel, bridge=sys.modules[__name__], operation="installed-move")
    result["native_bridge"] = evidence
    return result


def native_main(operation):
    started_ns = time.time_ns()
    require_windows()
    raw = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Native bridge request exceeds its bounded schema")
    request = parse_json(raw.decode("utf-8"))
    if (not isinstance(request, dict) or set(request) != {"schema", "operation", "nonce", "binding"}
            or request["schema"] != SCHEMA + ".request" or request["operation"] != operation
            or not isinstance(request["nonce"], str) or not HEX.fullmatch(request["nonce"])
            or not isinstance(request["binding"], dict)):
        raise ValueError("Native bridge request schema is malformed")
    supplied = request["binding"]
    report = ROOT.joinpath(*relative_name(supplied.get("report")).parts)
    current = supplied.get("current_hashes")
    actual = binding(report, current, operation)
    if supplied != actual:
        raise ValueError("Native bridge independently recomputed different source/report/helper hashes")
    if operation != "installed-move":
        load_grading_dependency()
    if operation == "score":
        adapter = load_module(SCRIPTS / "advanced_host_acceptance.py", "_native_bridge_adapter")
        result = adapter.advanced_host_report(report, current)
    elif operation == "installed-move":
        result = load_move_adapter().grade(report, supplied["report_sha256"])
    else:
        adapter = load_module(SCRIPTS / "advanced_host_acceptance.py", "_native_bridge_adapter")
        producer_path = ROOT / "work/gc-artifacts/.knowledgeos/advanced-host-c-20261020/advanced_host.py"
        if sha(plain_file(producer_path)) != adapter.PINNED_SUPPORT["advanced_host.py"]:
            raise ValueError("Bridge infrastructure probe found changed retained producer bytes")
        producer = load_module(producer_path, "_native_bridge_producer_import_only")
        sample = "---\ntitle: native bridge infrastructure only\naccepted_host_outcomes: 0\n---\n"
        if producer.frontmatter(sample) != {"title": "native bridge infrastructure only", "accepted_host_outcomes": 0}:
            raise ValueError("Declared YAML dependency did not parse the literal infrastructure sample")
        result = INFRASTRUCTURE_RESULT
    native = native_process(started_ns)
    if binding(report, current, operation) != actual:
        raise ValueError("Native bridge source or report changed during inspection")
    packet = {"schema": SCHEMA + ".response", "operation": operation, "nonce": request["nonce"],
              "binding": actual, "native": native, "result": result}
    validate_packet(packet, request, started_ns, time.time_ns())
    print(json.dumps(packet, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in NATIVE_FLAGS.values():
            raise ValueError("Use only the trusted native bridge entry point")
        raise SystemExit(native_main(next(operation for operation, flag in NATIVE_FLAGS.items() if flag == sys.argv[1])))
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        print("Native host bridge rejected: " + str(error), file=sys.stderr)
        raise SystemExit(2)
