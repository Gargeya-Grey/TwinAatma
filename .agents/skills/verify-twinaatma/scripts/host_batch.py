"""Prepare, and only on explicit request run, the single host-chat batch for one product freeze.

`prepare` makes zero model calls. In order it writes the freeze manifest, stages the producer
and controls, prepares the advanced-source inputs, runs the offline controls (proxy, date and
grader controls), starts one init-only synthetic vault, builds the payload inventory, seals the
folder and proposes the pin. It stops there and prints the commands for the nine chats.

`chats --allow-model-calls` is the only step that can reach a model. It refuses unless a human
trial authorization bound to this exact freeze and payload inventory exists, and it refuses a
second run. Read references/host-batch.md for the full runbook.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from urllib.parse import urlsplit

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import host_freeze as fz  # noqa: E402

KNOWLEDGE = "work/gc-artifacts/.knowledgeos"
RUBRIC_RELATIVE = ".agents/skills/verify-twinaatma/references/acceptance-rubric.json"
TEMPLATES = SCRIPTS / "staged"
AUTHORIZATION = "human-trial-authorization.json"
SCHEMA = "verify-twinaatma.host-batch/v1"
PRODUCT_PATHS = ("knowledgeos", "scripts", "Templates", ".cursor/hooks", *fz.ROOT_INPUTS)
MODEL_FLAG = "--allow-model-calls"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create(path, value):
    """Write a new JSON file. An existing file is an error, so a claim is single use."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def refuse_model_argv(argv):
    """Belt and braces: the zero-model helper never starts a Codex chat."""
    words = [str(item) for item in argv]
    first = Path(words[0]).name.casefold() if words else ""
    if first.startswith("codex") and words[1:] != ["--version"]:
        raise ValueError("Only `codex --version` may run outside the model step")
    if "exec" in words and any(Path(word).name.casefold().startswith("codex") for word in words):
        raise ValueError("A Codex exec command is a model call and cannot run here")


def run_local(base, label, argv, *, timeout=600):
    """Run one zero-model local command and keep its streams beside the batch."""
    refuse_model_argv(argv)
    logs = Path(base) / "batch-logs"
    logs.mkdir(exist_ok=True)
    started = time.monotonic()
    with (logs / (label + ".stdout.txt")).open("xb") as out, (logs / (label + ".stderr.txt")).open("xb") as err:
        child = subprocess.Popen([str(item) for item in argv], cwd=ROOT, stdout=out, stderr=err,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
        try:
            child.wait(timeout=timeout)
        except BaseException:
            child.kill()
            child.wait(timeout=20)
            raise
    record = {"label": label, "command": [str(item) for item in argv], "pid": child.pid,
              "exit_code": child.returncode, "stopped": child.poll() is not None,
              "seconds": round(time.monotonic() - started, 3), "model_conversations_started": 0}
    create(logs / (label + ".command.json"), record)
    return record


def git(*args):
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        raise RuntimeError("git " + " ".join(args) + " failed: " + done.stderr.strip())
    return done.stdout


def dirty_product():
    lines = git("status", "--porcelain", "--untracked-files=all", "--", *PRODUCT_PATHS).splitlines()
    return [line for line in lines if line.strip()]


def freeze_directory(value, root=ROOT):
    """A freeze folder is a direct child of work/gc-artifacts/.knowledgeos inside this checkout."""
    path = Path(value)
    path = (path if path.is_absolute() else Path(root) / path).absolute()
    try:
        relative = path.relative_to(Path(root).absolute()).as_posix()
    except ValueError as error:
        raise ValueError("The freeze folder is outside this checkout") from error
    if not fz.FREEZE_FOLDER.fullmatch(relative):
        raise ValueError("The freeze folder must be work/gc-artifacts/.knowledgeos/<name>")
    return path, relative


def write_freeze(base, *, root=ROOT, baseline=None, revision=None, allow_dirty=False, dirty=()):
    """Write product-freeze.json in the C-freeze schema, from the live tree."""
    if dirty and not allow_dirty:
        raise ValueError("Product files differ from the commit; commit them or pass --allow-dirty-product: "
                         + "; ".join(dirty[:6]))
    product = fz.toolkit_inputs(root)
    revision = revision or "unknown"
    receipt = create(Path(base) / "product-integration.json", {
        "schema": "verify-twinaatma.product-integration/v1", "source_revision": revision,
        "dirty_allowed": bool(dirty), "files": {name: {"candidate_sha256": digest} for name, digest in product.items()}})
    self_path = Path(root) / "People/Self.md"
    baseline = Path(baseline).resolve() if baseline else None
    record = {"schema": fz.FREEZE_SCHEMA, "source_revision": revision, "frozen_at_ns": time.time_ns(),
              "product": product, "fixed_target": 54, "rubric_sha256": sha(Path(root) / RUBRIC_RELATIVE),
              "integration_receipt_sha256": sha(receipt),
              "historical_baseline": str(baseline) if baseline else None,
              "historical_baseline_sha256": sha(baseline) if baseline else None,
              "root_Self_sha256": sha(self_path) if self_path.is_file() else None,
              "new_live_model_authorization": False}
    return create(Path(base) / fz.FREEZE_NAME, record), len(product)


def stage_producer(base):
    """Copy the committed producer and controls beside the freeze under the names the grader pins."""
    for name in ("advanced_host.py", "controls.py"):
        shutil.copyfile(TEMPLATES / name, Path(base) / name)
    return {name: sha(Path(base) / name) for name in ("advanced_host.py", "controls.py")}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protected_paths():
    return [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json",
            Path.home() / ".codex/config.toml"]


def protected_state():
    return {str(path): sha(path) if path.is_file() else None for path in protected_paths()}


def initialize_only(base):
    """Run init, doctor, setup-host and `codex --version` in a throwaway vault. No chat."""
    module = load_module(Path(base) / "advanced_host.py", "_host_batch_advanced_preflight")
    before = protected_state()
    trial = module.Journey(Path(base) / fz.FREEZE_NAME, "PREPARATION ONLY; no model authorization")
    failure = None
    try:
        trial.initialize()
    except BaseException as error:
        failure = repr(error)
        raise
    finally:
        trial.shutdown()
        record = {"scope": "Local CLI initialization, doctor, native config and host version only",
                  "model_conversations_started": 0, "authorization_consumed": False,
                  "directory": str(trial.directory), "processes": trial.processes,
                  "all_direct_processes_stopped": all(row["stopped"] for row in trial.processes),
                  "product_unchanged": module.product_hashes() == trial.sources,
                  "protected_unchanged": before == protected_state(),
                  "host": trial.host, "failure": failure, "fixed54_credit": 0}
        create(Path(base) / "advanced-initialize-only.json", record)
    if (failure or not record["all_direct_processes_stopped"] or not record["product_unchanged"]
            or not record["protected_unchanged"]):
        raise RuntimeError("Init-only preparation failed or changed a protected file: " + json.dumps(record["host"]))
    return record


def run_controls(base):
    """Run the grader controls: literal positives, corruptions, proxy control and date control."""
    record = run_local(base, "controls", [sys.executable, "-B", "-X", "utf8", Path(base) / "advanced_host.py", "--controls"])
    base = Path(base)
    if (record["exit_code"] != 0 or not list(base.glob("controls-*.json"))
            or not list(base.glob("date-control-*.json")) or not list(base.glob("proxy-control-*/wire.jsonl"))):
        raise RuntimeError("Offline controls failed or produced no proxy or date control: see batch-logs/controls.*")
    return record


def notes(vault):
    result = {}
    for path in sorted(Path(vault).rglob("*.md")):
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError("Payload fixture contains a linked note")
        result[path.relative_to(vault).as_posix()] = {"sha256": sha(path), "text": path.read_text(encoding="utf-8")}
    return result


def literal_basic_prompts():
    """The installed-host prompts, read from host.py source as literals."""
    found = []
    for item in ast.walk(ast.parse((SCRIPTS / "host.py").read_text(encoding="utf-8"))):
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Attribute):
            continue
        if item.func.attr == "chat" and len(item.args) == 2 and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in item.args):
            found.append({"label": item.args[0].value, "text": item.args[1].value})
        if item.func.attr == "submit" and len(item.args) == 3 and isinstance(item.args[0], ast.Attribute) and item.args[0].attr == "chat":
            found.append({"label": ast.literal_eval(item.args[1]), "text": ast.literal_eval(item.args[2])})
    if {row["label"] for row in found} != {"capture", "recall", "parallel"} or len(found) != 3:
        raise ValueError("The literal three-chat installed-host prompt set differs")
    return found


def destination():
    path = Path.home() / ".codex/config.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    name = config.get("model_provider")
    provider = config.get("model_providers", {}).get(name, {}) if name else {}
    endpoint = provider.get("base_url")
    return {"application": "signed-in native Codex CLI", "model": config.get("model"), "configured_provider": name,
            "explicit_endpoint_hostname": urlsplit(endpoint).hostname if isinstance(endpoint, str) else None,
            "endpoint_limit": "The CLI selects its configured service endpoint. An actual network hostname has not been observed.",
            "authentication": "Existing signed-in host session; no credentials copied into task fixtures or this inventory",
            "user_configuration_sha256": sha(path)}


def validate_artifact_report(path):
    """Use the installed-host validator, which refuses a stale product or a changed artifact."""
    import installed_host
    report, _server = installed_host.validate_installation(Path(path))
    return report


def payload_inventory(base, *, wheel_report, binary_report, initial):
    base = Path(base)
    prompts = literal_basic_prompts()
    units = []
    for kind, path in (("wheel", wheel_report), ("binary", binary_report)):
        path = Path(path).resolve()
        report = validate_artifact_report(path)
        if report["artifact"]["kind"] != kind:
            raise ValueError("The " + kind + " report describes a " + str(report["artifact"]["kind"]) + " artifact")
        units.append({"unit": "installed-" + kind, "maximum_model_conversations": 3,
                      "producer": str(SCRIPTS / "installed_host.py"), "artifact_report": str(path),
                      "artifact_report_sha256": sha(path), "artifact_sha256": report["artifact"]["sha256"],
                      "prompts": prompts, "initial_synthetic_notes": notes(report["installation"]["vault"]),
                      "additional_output": "The model may generate ordinary synthetic memory captures and session summaries, which the two restarted chats can recall."})
    expectations = fz.read_json(base / "expectations.json")
    private = fz.read_json(base / "private/input.json")
    units.append({"unit": "advanced-source", "maximum_model_conversations": 3, "producer": str(base / "advanced_host.py"),
                  "expectations_sha256": sha(base / "expectations.json"), "private_input_sha256": sha(base / "private/input.json"),
                  "prompts": [{**row, "text": row["text"].replace("{private_segment}", private["segment"])} for row in expectations["prompts"]],
                  "initial_synthetic_notes": notes(Path(initial["directory"]) / "vault"),
                  "private_payload_class": "Generated fake credential and fictional sensitive third-party detail, deliberately supplied to test exclusion",
                  "additional_output": "The model may generate synthetic notes, session summaries, reviewed outcome records and corrections, which later chats can recall."})
    inventory = {"schema": "twinaatma.proposed-host-trial/v1",
                 "status": "PROPOSED; no authorization and no model conversation started",
                 "product_freeze": str(base / fz.FREEZE_NAME), "product_freeze_sha256": sha(base / fz.FREEZE_NAME),
                 "maximum_model_conversations": 9, "allowed_units": {row["unit"]: row["maximum_model_conversations"] for row in units},
                 "destination": destination(), "units": units,
                 "exclusions": ["Real personal vault notes", "Real identity file contents", "Real credentials", "Unrelated user configuration contents"],
                 "limits": ["Short synthetic CLI chats do not establish desktop, clean-device, owner approval or representative week acceptance.",
                            "Each unit is single use. Failures are retained and are not automatically retried."]}
    return create(base / "outbound-payload-review.json", inventory)


def host_identity(initial):
    """The host identity to pin, from the init-only run: resolved executable, version, configured model."""
    found = shutil.which("codex")
    if not found:
        raise ValueError("No codex executable on PATH")
    cli = Path(found).resolve(strict=True)
    host = initial["host"]
    if not host.get("version") or not host.get("configured_model"):
        raise ValueError("Init-only run did not observe the Codex version and configured model")
    return {"cli": str(cli), "cli_sha256": sha(cli), "version": host["version"], "configured_model": host["configured_model"]}


def seal(base):
    base = Path(base)
    support = {name: sha(base / name) for name in fz.SUPPORT_NAMES}
    product = fz.freeze_product(base / fz.FREEZE_NAME)
    path = create(base / fz.SEAL_NAME, {"schema": fz.SEAL_SCHEMA, "product_freeze_sha256": sha(base / fz.FREEZE_NAME),
                                        "source_input_count": len(product), "support": support})
    return path, sha(path)


def prepare(args, *, root=ROOT):
    base, relative = freeze_directory(args.freeze_dir or default_name(), root)
    if base.exists():
        raise ValueError("The freeze folder already exists; a freeze is written once: " + str(base))
    if not args.wheel_report or not args.binary_report:
        raise ValueError("Both --wheel-report and --binary-report are required (zero-model artifact reports)")
    base.mkdir(parents=True)
    try:
        steps = prepare_into(base, relative, args, root)
    except BaseException:
        # Keep the evidence of a failed preparation, but never reuse the folder or its name.
        base.rename(base.with_name(base.name + ".failed-" + str(time.time_ns())))
        raise
    return base, steps[-1]["pin_path"], steps


def prepare_into(base, relative, args, root):
    steps = []
    revision = git("rev-parse", "HEAD").strip()
    dirty = dirty_product()
    _freeze, count = write_freeze(base, root=root, baseline=args.baseline, revision=revision,
                                  allow_dirty=args.allow_dirty_product, dirty=dirty)
    steps.append({"step": "freeze", "source_inputs": count, "source_revision": revision, "dirty_files": len(dirty)})
    staged = stage_producer(base)
    steps.append({"step": "stage", "hashes": staged})
    steps.append({"step": "prepare-inputs", **run_local(base, "prepare", [sys.executable, "-B", "-X", "utf8", base / "advanced_host.py", "--prepare"])})
    if steps[-1]["exit_code"] != 0 or not (base / "prepared.json").is_file():
        raise RuntimeError("Advanced-source preparation failed: see batch-logs/prepare.*")
    initial = initialize_only(base)
    steps.append({"step": "init-only", "directory": initial["directory"], "host": initial["host"]})
    controls = run_controls(base)
    steps.append({"step": "controls", "seconds": controls["seconds"], "exit_code": controls["exit_code"]})
    inventory = payload_inventory(base, wheel_report=args.wheel_report, binary_report=args.binary_report, initial=initial)
    steps.append({"step": "inventory", "sha256": sha(inventory)})
    create(base / "preparation-provenance.json", {
        "schema": SCHEMA + "/preparation", "product_freeze": str(base / fz.FREEZE_NAME), "product_freeze_sha256": sha(base / fz.FREEZE_NAME),
        "templates": {name: sha(TEMPLATES / name) for name in ("advanced_host.py", "controls.py")},
        "model_conversations_started": 0, "status": "PENDING direct human authorization"})
    host = host_identity(initial)
    _seal_path, seal_sha = seal(base)
    steps.append({"step": "seal", "seal_sha256": seal_sha})
    if fz.toolkit_inputs(root) != fz.freeze_product(base / fz.FREEZE_NAME):
        raise RuntimeError("The product changed while preparing; the freeze is void")
    pin_path = Path(args.pin_file) if args.pin_file else (fz.PIN_PATH if args.write_pin else base / "host-freeze-pin.proposed.json")
    fz.write_pin(pin_path, relative, seal_sha, host)
    binding = fz.load_binding(root, pin_path)
    fz.check_support(binding)
    steps.append({"step": "pin", "path": str(pin_path), "live": pin_path == fz.PIN_PATH, "verified": True})
    create(base / "batch-prepare.json", {"schema": SCHEMA, "steps": steps, "model_conversations_started": 0, "fixed54_credit": 0})
    steps.append({"step": "done", "pin_path": pin_path})
    return steps


def default_name():
    return "{}/host-batch-{}-{}".format(KNOWLEDGE, time.strftime("%Y%m%d"), git("rev-parse", "--short=7", "HEAD").strip())


# ---------------------------------------------------------------- model step

def read_inventory(binding):
    inventory = fz.read_json(binding.base / "outbound-payload-review.json")
    if (not isinstance(inventory, dict) or inventory.get("product_freeze_sha256") != binding.frozen_sha256
            or inventory.get("allowed_units") != {unit: 3 for unit in fz.UNITS}
            or inventory.get("maximum_model_conversations") != 9
            or [row.get("unit") for row in inventory.get("units", [])] != list(fz.UNITS)):
        raise fz.BindingError("The payload inventory is not the three bounded units for this freeze")
    return inventory


def common_check(*, root=ROOT, pin_path=None, require_authorization=True):
    """Everything that must hold before one model conversation starts. Starts no process."""
    binding = fz.load_binding(root, pin_path)
    fz.check_support(binding)
    fz.check_product(binding.product, root)
    inventory = read_inventory(binding)
    user_config = Path.home() / ".codex/config.toml"
    if sha(user_config) != inventory["destination"]["user_configuration_sha256"]:
        raise fz.BindingError("The configured model or destination changed after the inventory was written")
    if tomllib.loads(user_config.read_text(encoding="utf-8")).get("model") != binding.host["configured_model"]:
        raise fz.BindingError("The configured model differs from the pinned host identity")
    authorization = None
    if require_authorization:
        path = binding.base / AUTHORIZATION
        if not path.is_file():
            raise fz.BindingError("No human trial authorization exists for this freeze: " + AUTHORIZATION)
        authorization = fz.read_json(fz.plain_file(path, binding.root))
        problem = fz.authorization_problem(authorization, binding.frozen_sha256, binding.inventory_sha256,
                                           fz.UNITS, 9, model=binding.host["configured_model"])
        if problem:
            raise fz.BindingError(problem)
    return binding, inventory, authorization


def exec_argv(cli, project, model):
    """The one Codex chat invocation shape that both drivers use."""
    return [cli, "--disable", "apps", "--disable", "plugins", "--disable", "remote_plugin", "exec", "--strict-config",
            "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
            "--color", "never", "-C", str(project), "-c", 'project_root_markers=[".twinaatma-host-profile"]',
            "-c", "projects={" + json.dumps(str(project)) + '={trust_level="trusted"}}', "-m", model]


def claim_name(unit):
    return unit + ".unit-claim.json"


class LaunchGuard:
    """Check every model launch against the reviewed inventory, then reserve it."""

    def __init__(self, binding, inventory, authorization_sha256, unit):
        self.binding, self.unit = binding, unit
        self.payload = next(row for row in inventory["units"] if row["unit"] == unit)
        self.prompts = {row["label"]: row["text"] for row in self.payload["prompts"]}
        self.model = binding.host["configured_model"]
        self.authorization_sha256 = authorization_sha256
        self.lock = threading.Lock()
        self.started = []
        self.server = self.directory = None
        self.reserved()

    def reserved(self):
        path = self.binding.base / claim_name(self.unit)
        claim = fz.read_json(path)
        expected = {"authorization_sha256": self.authorization_sha256, "product_freeze_sha256": self.binding.frozen_sha256,
                    "payload_inventory_sha256": self.binding.inventory_sha256, "unit": self.unit,
                    "maximum_model_conversations": 3, "wrapper_sha256": sha(__file__)}
        if any(claim.get(key) != value for key, value in expected.items()):
            raise ValueError("The single-use unit claim is mismatched")
        return path

    def validate_initial_notes(self, vault):
        if notes(vault) != self.payload["initial_synthetic_notes"]:
            raise ValueError("Actual initial outbound notes differ from the reviewed inventory")

    def before_command(self, label, argv, stdin, cwd):
        argv = [str(item) for item in argv]
        if "exec" not in argv:
            return
        with self.lock:
            self.reserved()
            if len(self.started) >= 3 or label in self.started or self.prompts.get(label) != stdin:
                raise ValueError("The unit is exhausted, repeated, or its exact outbound prompt changed")
            project = Path(cwd)
            expected = exec_argv(str(Path(self.binding.host["cli"])), project, self.model)
            if argv != expected:
                raise ValueError("The actual host invocation differs from the isolated approved scope")
            profile = project / ".codex/config.toml"
            config = tomllib.loads(profile.read_text(encoding="utf-8"))
            if set(config.get("mcp_servers", {})) != {"knowledgeos"}:
                raise ValueError("The outbound profile contains an unrelated server")
            server = dict(self.server)
            server["env"] = {**server.get("env", {}), "KNOWLEDGEOS_STATE_DIR": str(self.directory / "gate-state"),
                             "PYTHONDONTWRITEBYTECODE": "1"}
            proxy = self.binding.base / "advanced_host.py" if self.unit == "advanced-source" else SCRIPTS / "host.py"
            arguments = ["-B", "-P", str(proxy), "--proxy", str(self.directory / (label + ".wire.jsonl"))]
            if self.unit == "advanced-source":
                arguments.append(str(self.binding.base / "private/input.json"))
            server["command"] = sys.executable
            server["args"] = [*arguments, "--", self.server["command"], *self.server.get("args", [])]
            if config["mcp_servers"]["knowledgeos"] != server:
                raise ValueError("The actual outbound proxy/config does not bind the exact approved server")
            if sha(project / "AGENTS.md") != self.payload["initial_synthetic_notes"]["AGENTS.md"]["sha256"]:
                raise ValueError("The actual project instructions differ from the approved notes")
            current, _inventory, _authorization = common_check(root=self.binding.root, pin_path=self.binding.pin_path)
            if (current.pin_sha256 != self.binding.pin_sha256
                    or current.seal_sha256 != self.binding.seal_sha256
                    or sha(current.base / AUTHORIZATION) != self.authorization_sha256):
                raise fz.BindingError("The pinned batch or authorization changed after the unit initialized")
            executable = Path(current.host["cli"]).resolve(strict=True)
            if executable != Path(current.host["cli"]) or sha(executable) != current.host["cli_sha256"]:
                raise fz.BindingError("The Codex executable differs from the pinned host identity")
            create(self.binding.base / (self.unit + "-" + label + ".model-reservation.json"), {
                "unit": self.unit, "label": label, "authorization_sha256": self.authorization_sha256,
                "unit_claim_sha256": sha(self.reserved()), "payload_inventory_sha256": self.binding.inventory_sha256,
                "product_freeze_sha256": self.binding.frozen_sha256, "prompt_sha256": hashlib.sha256(stdin.encode("utf-8")).hexdigest(),
                "command": argv, "cwd": str(project), "profile_sha256": sha(profile), "reserved_ns": time.time_ns(),
                "scope": "Reserved before the producer Popen; not proof that a model started"})
            self.started.append(label)


def finish_unit(binding, unit, report, code, guard, authorization_sha256):
    create(binding.base / (unit + ".unit-result.json"), {
        "unit": unit, "report": str(report), "report_sha256": sha(report), "exit_code": code,
        "model_reservations": guard.started, "model_reservation_count": len(guard.started),
        "authorization_sha256": authorization_sha256, "unit_claim_sha256": sha(guard.reserved())})


def installed_unit(binding, inventory, authorization_sha256, unit, codex):
    import installed_host

    guard = LaunchGuard(binding, inventory, authorization_sha256, unit)
    if literal_basic_prompts() != guard.payload["prompts"]:
        raise ValueError("The actual literal installed prompts differ from the approved inventory")
    artifact_path = Path(guard.payload["artifact_report"])
    if sha(artifact_path) != guard.payload["artifact_report_sha256"]:
        raise ValueError("The approved original artifact report changed")

    class GuardedInstalled(installed_host.InstalledHostRun):
        def initialize(self):
            super().initialize()
            guard.validate_initial_notes(self.vault)
            guard.server, guard.directory = self.server, self.directory

        def command(self, label, argv, cwd=None, stdin="", timeout=120):
            guard.before_command(label, argv, stdin, cwd)
            return super().command(label, argv, cwd=cwd, stdin=stdin, timeout=timeout)

    run = GuardedInstalled(binding.base / unit, codex, artifact_path)
    error = None
    try:
        run.initialize()
        run.drive()
    except Exception as failure:
        error = type(failure).__name__ + ": " + str(failure)
    code = run.finish(error)
    finish_unit(binding, unit, run.directory / "report.json", code, guard, authorization_sha256)
    return code


def advanced_unit(binding, inventory, authorization_sha256, codex):
    module = load_module(binding.base / "advanced_host.py", "_host_batch_advanced_producer")
    guard = LaunchGuard(binding, inventory, authorization_sha256, "advanced-source")
    expected = module.read_json(binding.base / "expectations.json")
    private = module.read_json(binding.base / "private/input.json")
    if [{**row, "text": row["text"].replace("{private_segment}", private["segment"])} for row in expected["prompts"]] != guard.payload["prompts"]:
        raise ValueError("Actual advanced prompts differ from the reviewed inventory")

    class GuardedAdvanced(module.Journey):
        def initialize(self):
            super().initialize()
            guard.validate_initial_notes(self.vault)
            guard.server, guard.directory = self.server, self.directory

        def command(self, label, argv, stdin="", cwd=None, timeout=120):
            guard.before_command(label, argv, stdin, cwd)
            return super().command(label, argv, stdin=stdin, cwd=cwd, timeout=timeout)

    run = GuardedAdvanced(binding.freeze, authorization_sha256, codex)
    code = run.run()
    finish_unit(binding, "advanced-source", run.directory / "report.json", code, guard, authorization_sha256)
    return code


def check_codex(binding, codex):
    resolved = Path(codex).resolve(strict=True)
    if resolved != Path(binding.host["cli"]) or sha(resolved) != binding.host["cli_sha256"]:
        raise fz.BindingError("The Codex executable differs from the pinned host identity")
    version = subprocess.run([str(resolved), "--version"], capture_output=True, text=True, timeout=60)
    if version.returncode or version.stdout.strip() != binding.host["version"]:
        raise fz.BindingError("The Codex version differs from the pinned host identity")
    return str(resolved)


def run_unit(unit, codex, *, root=ROOT, pin_path=None):
    binding, inventory, authorization = common_check(root=root, pin_path=pin_path)
    authorization_sha256 = sha(binding.base / AUTHORIZATION)
    codex = check_codex(binding, codex)
    if unit == "advanced-source":
        return advanced_unit(binding, inventory, authorization_sha256, codex)
    return installed_unit(binding, inventory, authorization_sha256, unit, codex)


def run_batch(codex, *, root=ROOT, pin_path=None):
    """Run the three bounded units once, in order. Needs the flag and a bound authorization."""
    binding, _inventory, _authorization = common_check(root=root, pin_path=pin_path)
    codex = check_codex(binding, codex)
    authorization_sha256 = sha(binding.base / AUTHORIZATION)
    base = binding.base
    create(base / "batch-claim.json", {
        "authorization_sha256": authorization_sha256, "payload_inventory_sha256": binding.inventory_sha256,
        "product_freeze_sha256": binding.frozen_sha256, "wrapper_sha256": sha(__file__),
        "script_hashes": {name: sha(SCRIPTS / name) for name in ("host_freeze.py", "advanced_host_acceptance.py", "advanced_host_native.py",
                                                                  "native_grader_rendezvous.py", "installed_host.py", "host.py",
                                                                  "artifact.py", "acceptance.py", "native_process.py")},
        "maximum_model_conversations": 9, "pid": os.getpid(), "claimed_ns": time.time_ns()})
    from native_process import Tree

    before = protected_state()
    rows = []
    for unit in fz.UNITS:
        binding, _inventory, _authorization = common_check(root=root, pin_path=pin_path)
        create(base / claim_name(unit), {"authorization_sha256": authorization_sha256, "product_freeze_sha256": binding.frozen_sha256,
                                         "payload_inventory_sha256": binding.inventory_sha256, "unit": unit,
                                         "maximum_model_conversations": 3, "wrapper_sha256": sha(__file__),
                                         "claimed_ns": time.time_ns(), "parent_pid": os.getpid()})
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "unit", unit, MODEL_FLAG, "--codex", codex]
        started_ns, started = time.time_ns(), time.monotonic()
        failure = None
        with (base / (unit + ".stdout.txt")).open("xb") as out, (base / (unit + ".stderr.txt")).open("xb") as err:
            child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err,
                                     env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"))
            tree = Tree(child.pid, os.getpid())
            try:
                child.wait(timeout=1400)
            except BaseException as error:
                failure = type(error).__name__
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=20)
            finally:
                native = tree.finish()
        result_path = base / (unit + ".unit-result.json")
        result = fz.read_json(result_path) if result_path.is_file() else None
        row = {"unit": unit, "command": command, "pid": child.pid, "parent_pid": os.getpid(), "started_ns": started_ns,
               "ended_ns": time.time_ns(), "seconds": time.monotonic() - started, "exit_code": child.returncode,
               "stopped": child.poll() is not None, "error": failure, "native_processes": native,
               "unit_result": result, "unit_result_sha256": sha(result_path) if result else None}
        create(base / (unit + ".parent-command.json"), row)
        rows.append(row)
        print(json.dumps({"unit": unit, "exit_code": child.returncode, "stopped": row["stopped"],
                          "report": result.get("report") if result else None}), flush=True)
        after = protected_state()
        if before != after or any(not item.get("stopped") for item in native["processes"]) or not native["monitor_stopped"]:
            break
    after = protected_state()
    reservations = list(base.glob("*.model-reservation.json"))
    create(base / "batch-result.json", {
        "schema": SCHEMA + "/result", "rows": rows, "authorization_sha256": authorization_sha256,
        "payload_inventory_sha256": binding.inventory_sha256, "product_freeze_sha256": binding.frozen_sha256,
        "wrapper_sha256": sha(__file__), "maximum_model_conversations": 9, "model_reservation_count": len(reservations),
        "unit_count": len(rows), "isolation": {"before": before, "after": after}, "platform": platform.platform(),
        "python": sys.executable, "codex": codex, "fixed54_credit": 0,
        "scope": "Original live observations for independent grading. No retries, owner approval, clean-device or representative-week claim."})
    return int(len(rows) != 3 or before != after or any(row["exit_code"] != 0 for row in rows) or len(reservations) > 9)


# ---------------------------------------------------------------- printing

def command_plan(binding, inventory):
    """The exact commands for the nine chats and for grading, from the sealed inventory."""
    py = sys.executable
    cli = binding.host["cli"]
    base = binding.base
    me = str(Path(__file__).resolve())
    units = {row["unit"]: row for row in inventory["units"]}
    plan = {"model_step": [py, "-B", "-X", "utf8", me, "chats", MODEL_FLAG, "--codex", cli], "units": []}
    for unit in fz.UNITS:
        row = units[unit]
        entry = {"unit": unit, "labels": [p["label"] for p in row["prompts"]],
                 "launcher": [py, "-B", "-X", "utf8", me, "unit", unit, MODEL_FLAG, "--codex", cli],
                 "codex_chat_argv_shape": exec_argv(cli, "<project>", binding.host["configured_model"])}
        if unit == "advanced-source":
            entry["producer_module"] = str(base / "advanced_host.py")
        else:
            entry["producer_module"] = str(SCRIPTS / "installed_host.py")
        plan["units"].append(entry)
    acceptance = SCRIPTS / "acceptance.py"
    native = load_module(SCRIPTS / "advanced_host_native.py", "_host_batch_native_names")
    plan["grade"] = [str(native.INTERPRETER), "-B", str(acceptance),
                     "--host-report", str(base / "installed-wheel/<run>/report.json"),
                     "--host-report", str(base / "installed-binary/<run>/report.json"),
                     "--advanced-host-report", str(base / "native-<run>/report.json"),
                     "<plus the source, artifact, baseline and --output options from SKILL.md>"]
    return plan


def print_plan(plan):
    print("Nine chats: three bounded units of three. Run only the MODEL STEP command; it calls each launcher once.")
    print("MODEL STEP (calls a model, once, needs a bound authorization):")
    print("  " + " ".join(plan["model_step"]))
    for entry in plan["units"]:
        print("Unit {} (labels {}):".format(entry["unit"], ", ".join(entry["labels"])))
        print("  launcher: " + " ".join(entry["launcher"]))
        print("  guarded producer module: " + entry["producer_module"])
        print("  codex argv: " + " ".join(entry["codex_chat_argv_shape"]))
    print("GRADING (zero model, native Windows, main checkout):")
    print("  " + " ".join(plan["grade"]))


def authorization_template(binding):
    return {"schema": "twinaatma.direct-human-trial-authorization/v1", "status": None,
            "direct_user_reply": None, "source": None, "question_item_id": None,
            "approved_scope": "Three Windows wheel chats, three Windows executable chats and three advanced source correction, outcome and privacy chats",
            "product_freeze_sha256": binding.frozen_sha256, "payload_inventory_sha256": binding.inventory_sha256,
            "allowed_units": {unit: 3 for unit in fz.UNITS}, "maximum_model_conversations": 9,
            "model": binding.host["configured_model"],
            "destination": "Signed-in native Codex CLI configured service endpoint; exact network hostname unobserved",
            "single_use": True, "automatic_retries": False,
            "owner_terminal_gate": "Pending by direct human instruction; this authorization does not approve identity changes",
            "recorded_ns": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="all zero-model preparation; stops before the first model call")
    p.add_argument("--freeze-dir", help="new folder work/gc-artifacts/.knowledgeos/<name> (default: host-batch-<date>-<revision>)")
    p.add_argument("--wheel-report", type=Path)
    p.add_argument("--binary-report", type=Path)
    p.add_argument("--baseline", type=Path, help="historical baseline JSON recorded in the freeze (optional)")
    p.add_argument("--allow-dirty-product", action="store_true")
    p.add_argument("--write-pin", action="store_true", help="write scripts/host-freeze-pin.json (else a proposed pin in the freeze folder)")
    p.add_argument("--pin-file", type=Path, help=argparse.SUPPRESS)
    sub.add_parser("check", help="check pin, seal, product, inventory and authorization; start nothing")
    sub.add_parser("commands", help="print the exact commands for the nine chats and for grading")
    sub.add_parser("authorization-template", help="print the authorization record to fill in; writes nothing")
    for name, text in (("chats", "run the nine chats once (CALLS A MODEL)"), ("unit", "run one unit (internal; CALLS A MODEL)")):
        c = sub.add_parser(name, help=text)
        if name == "unit":
            c.add_argument("unit", choices=fz.UNITS)
        c.add_argument(MODEL_FLAG, dest="allow_model", action="store_true", help="required: acknowledge that this starts model conversations")
        c.add_argument("--codex", required=True, help="the pinned native Codex executable")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            base, pin_path, steps = prepare(args)
            for step in steps[:-1]:
                print(json.dumps(step))
            print("STOPPED before the first model call. Model conversations started: 0.")
            if pin_path != fz.PIN_PATH:
                print("Proposed pin: {}\nCopy it to {} to bind the freeze, then run `commands`.".format(pin_path, fz.PIN_PATH))
            else:
                binding, inventory, _ = common_check(require_authorization=False)
                print_plan(command_plan(binding, inventory))
            return 0
        if args.command in ("chats", "unit") and not args.allow_model:
            parser.error(MODEL_FLAG + " is required")
        if args.command == "chats":
            return run_batch(args.codex)
        if args.command == "unit":
            return run_unit(args.unit, args.codex)
        binding, inventory, authorization = common_check(require_authorization=args.command == "check")
        if args.command == "check":
            print(json.dumps({"ready": True, "freeze": str(binding.freeze), "source_inputs": binding.source_input_count,
                              "units": inventory["allowed_units"], "model_processes_started": 0,
                              "authorization_sha256": sha(binding.base / AUTHORIZATION)}))
        elif args.command == "commands":
            print_plan(command_plan(binding, inventory))
        else:
            print(json.dumps(authorization_template(binding), indent=2))
        return 0
    except (fz.BindingError, ValueError, OSError, RuntimeError) as error:
        print("host_batch refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
