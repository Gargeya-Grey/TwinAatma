"""Execute exact generated hooks from retained installations on real Python runtimes."""
import argparse
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("runtime_hook_artifact", HERE / "artifact.py")
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)
ROOT = artifact.ROOT
PRODUCER = "verify-twinaatma.runtime-hooks/v1"
sha = artifact.sha
LIFECYCLE_KEYS = ("real_sessions", "sessions", "soft_prompts_asked", "orphan_unsaved_session",
                  "session_open", "session_ended", "sessions_completed")


def lifecycle(state):
    return {key: state.get(key) for key in LIFECYCLE_KEYS}


def generated_commands(config):
    groups = config.get("hooks") if isinstance(config, dict) else None
    if not isinstance(groups, dict):
        raise ValueError("Generated hooks must be an object")
    commands = {}
    for event in ("sessionStart", "sessionEnd"):
        entries = groups.get(event)
        if (not isinstance(entries, list) or len(entries) != 1 or
                not isinstance(entries[0], dict) or not isinstance(entries[0].get("command"), str) or
                not entries[0]["command"].strip()):
            raise ValueError("Generated " + event + " must contain one executable command")
        commands[event] = entries[0]["command"]
    return commands


def indexed_note(database, relative):
    if not Path(database).is_file():
        return []
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as connection:
        return [list(row) for row in connection.execute(
            "SELECT path, title, body FROM notes_fts WHERE path = ?", (relative,))]


def prewarm_observation(output, state_before, state_after, rows, token):
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        payload = {}
    context = payload.get("additional_context", "") if isinstance(payload, dict) else ""
    return {
        "ran": isinstance(context, str) and "Pre-warm unavailable" not in context and
               "rebuilt_index" in context and any(token in row[2] for row in rows),
        "no_session": lifecycle(state_before) == lifecycle(state_after),
        "context": context, "indexed_rows": rows,
    }


def wheel_manifest(wheel, supplied, current):
    path = artifact.plain(supplied or wheel.parent.parent / "build-manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if manifest.get("producer") != "verify-twinaatma.build/v1" or manifest.get("product_hashes") != current:
        raise ValueError("Wheel build manifest does not bind current product")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Wheel build manifest lacks enumerated inputs")
    for relative, digest in inputs.items():
        member = Path(relative)
        if member.is_absolute() or ".." in member.parts or "\\" in relative:
            raise ValueError("Unsafe build input path")
        if sha(artifact.plain(ROOT / member)) != digest:
            raise ValueError("Build input changed: " + relative)
    commands = manifest.get("build_commands", [])
    if not commands or any(not row.get("command") or row.get("exit_code") != 0 for row in commands):
        raise ValueError("Wheel build manifest lacks successful commands")
    if Path(manifest.get("wheel", "")).name != wheel.name:
        raise ValueError("Build manifest names a different wheel")
    return path


class HookRun(artifact.ArtifactRun):
    def __init__(self, output, package, kind, python=None, manifest=None):
        super().__init__(output, package, kind, manifest)
        self.vault = self.directory / "vault&runtime"
        self.target = Path(python).resolve(strict=True) if python else None
        self.requested_python = str(python) if python else None
        self.runtime = {"platform": platform.system(), "kind": kind}
        self.generated = None
        self.executable = None
        self.manifest_path = None
        self.identity = None
        self.installation = {"vault": str(self.vault), "state_dir": str(self.state), "platform": platform.platform()}
        self.marker = self.directory / "vault-code-executed.txt"
        self.env.update(TEMP=str(self.directory / "tmp"), TMP=str(self.directory / "tmp"))
        (self.directory / "tmp").mkdir()

    def command(self, label, command, timeout=180, *, cwd=None, env=None, shell=False, stdin=None):
        launch = str(command) if shell else list(map(str, command))
        location = Path(cwd or self.neutral)
        environment = dict(self.env if env is None else env)
        started = time.monotonic()
        process = subprocess.Popen(launch, shell=shell, cwd=location, env=environment,
                                   stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", start_new_session=os.name != "nt")
        record = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(record)
        error = None
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except BaseException as exc:
            error = exc
            if os.name == "nt":
                subprocess.run([os.path.join(os.environ.get("SYSTEMROOT", "C:/Windows"), "System32/taskkill.exe"),
                                "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=20)
        finally:
            record.update(stopped=process.poll() is not None, exit_code=process.returncode)
        (self.directory / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (self.directory / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        details = {"command": launch, "shell": shell,
                   "shell_executable": os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else "/bin/sh",
                   "cwd": str(location), "stdin": stdin, "exit_code": process.returncode,
                   "seconds": time.monotonic() - started,
                   "environment": {key: environment.get(key) for key in
                                   ("PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
                                    "KNOWLEDGEOS_VAULT", "KNOWLEDGEOS_STATE_DIR",
                                    "PYTHONDONTWRITEBYTECODE")}}
        (self.directory / (label + ".command.json")).write_text(json.dumps(details, indent=2), encoding="utf-8")
        if error:
            raise error
        if process.returncode:
            raise RuntimeError(label + " failed: " + stderr[-2000:])
        return stdout

    def state_snapshot(self, label):
        path = self.vault / ".knowledgeos/autopilot.json"
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        (self.directory / (label + ".state.json")).write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state

    def memory(self, label, tool, **args):
        return json.loads(self.command(label, [self.executable, "memory", tool, "--vault", self.vault,
                                               "--args", json.dumps(args)]))

    def hook(self, label, event, payload):
        environment = dict(self.env, PATH="", PYTHONPATH=os.pathsep.join(
            map(str, (self.vault, self.vault / ".cursor/hooks", self.vault / "poison"))))
        return self.command(label, self.generated["commands"][event], shell=True, cwd=self.vault,
                            env=environment, stdin=json.dumps(payload))

    def poison_vault(self):
        code = ("open(" + repr(str(self.marker)) + ", 'a', encoding='utf-8').write('vault code executed\\n')\n"
                "raise RuntimeError('Vault content must never execute')\n")
        paths = []
        for folder in (self.vault, self.vault / ".cursor/hooks", self.vault / "poison"):
            for name in ("json.py", "pathlib.py", "subprocess.py", "sitecustomize.py", "re.py"):
                paths.append(folder / name)
            paths += [folder / "knowledgeos/__init__.py", folder / "knowledgeos/__main__.py"]
        paths += [self.vault / ".cursor/hooks/twin_session_start.py",
                  self.vault / ".cursor/hooks/twin_session_end.py"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding="utf-8")

    def retain_installation(self, origin):
        package = origin.parent
        retained = [self.executable, *package.rglob("*")]
        self.installation["file_hashes"] = {
            str(path): sha(artifact.plain(path)) for path in sorted(retained)
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        self.installation["module_hashes"] = {
            path.name: sha(path) for path in sorted(package.glob("*.py"))
        }
        self.installation["asset_hashes"] = {
            path.relative_to(package / "_assets").as_posix(): sha(path)
            for path in sorted((package / "_assets").rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }

    def prepare(self):
        if self.kind == "wheel":
            if self.target is None:
                raise ValueError("Wheel hooks require --python naming a real target runtime")
            artifact.wheel_binding(self.artifact, self.sources)
            self.manifest_path = wheel_manifest(self.artifact, self.manifest, self.sources)
            environment = self.directory / "installed environment"
            self.command("create-venv", [self.target, "-I", "-m", "venv", "--without-pip", environment], timeout=300)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            self.command("install", [sys.executable, "-I", "-m", "pip", "--python", python,
                                     "install", "--no-index", "--no-deps", self.artifact], timeout=300)
            self.executable = python.with_name("twinaatma.exe" if os.name == "nt" else "twinaatma")
            identity = json.loads(self.command("runtime-identity", [python, "-I", "-c",
                "import sys,platform,knowledgeos,json;print(json.dumps({'version':sys.version,"
                "'version_info':list(sys.version_info[:3]),'implementation':platform.python_implementation(),"
                "'executable':sys.executable,'base_executable':getattr(sys,'_base_executable',''),"
                "'prefix':sys.prefix,'base_prefix':sys.base_prefix,'origin':knowledgeos.__file__}))"]))
            version = identity["version_info"]
            self.runtime.update(identity=identity, major_minor=".".join(map(str, version[:2])),
                                requested_python=self.requested_python)
            self.check("hook.runtime_identity", identity["implementation"] == "CPython" and version[:2] >= [3, 9]
                       and identity["prefix"] != identity["base_prefix"],
                       "A real isolated supported CPython runtime executes the installed artifact",
                       identity, ["runtime-identity.stdout.txt"])
            origin = artifact.installed_origin(identity["origin"], environment, self.sources)
            self.installation.update(environment=str(environment), python=str(python),
                                     executable=str(self.executable), import_origin=str(origin))
            self.retain_installation(origin)
            self.check("hook.isolated_import", True, "Exact installed modules and hooks match current product",
                       str(origin), ["runtime-identity.stdout.txt"])
        else:
            self.distribution_root, self.files = artifact.binary_binding(self.artifact, self.manifest, self.sources)
            self.links = artifact.distribution_links(self.distribution_root)
            self.manifest_path = artifact.plain(self.manifest)
            self.executable = self.artifact
            self.installation.update(executable=str(self.executable),
                                     distribution_files=self.files, distribution_links=self.links)
            self.runtime.update(embedded=True, embedded_version="UNAVAILABLE", build_manifest=str(self.manifest_path))
            self.check("hook.runtime_identity", True, "A manifest-bound native binary runs its bundled interpreter",
                       str(self.executable), ["build-manifest.json"])
            self.check("hook.isolated_import", True, "The complete frozen distribution matches current build bytes",
                       {"files": len(self.files), "links": self.links}, ["build-manifest.json"])
        (self.directory / "build-manifest.json").write_bytes(self.manifest_path.read_bytes())
        self.source_bound = True
        self.check("hook.current_product", True, "Installed artifact binds current modules and shipped hook bytes",
                   self.sources, ["build-manifest.json"])
        initialized = json.loads(self.command("init", [self.executable, "init", self.vault, "--name",
                                                       "Runtime hook fixture", "--non-interactive"]))
        self.identity = sha(self.vault / "People/Self.md")
        self.check("hook.init", '"ok": false' not in json.dumps(initialized),
                   "Installed init finishes without post-init failure", initialized, ["init.stdout.txt"])
        self.command("doctor", [self.executable, "doctor", "--vault", self.vault])
        config = self.vault / ".cursor/hooks.json"
        copied = self.directory / "generated-hooks.json"
        copied.write_bytes(config.read_bytes())
        commands = generated_commands(json.loads(config.read_text(encoding="utf-8")))
        self.generated = {"path": str(copied), "sha256": sha(copied), "commands": commands,
                          "fixture_path": str(config)}
        self.check("hook.generated_commands", all(str(self.vault) in value for value in commands.values()),
                   "Both exact generated shell commands explicitly name the intended fixture vault",
                   commands, ["generated-hooks.json"])

    def drive(self):
        self.prepare()
        self.poison_vault()
        token = "quartzite-older-runtime-" + self.directory.name
        note = self.vault / "Inbox/Runtime hook prewarm.md"
        note.write_text("---\ntype: concept\ntitle: Runtime hook prewarm\nstatus: active\n"
                        "schema: knowledgeos-v0.2\n---\n\n" + token + "\n", encoding="utf-8")
        rows_before = indexed_note(self.vault / "knowledge_index.db", "Inbox/Runtime hook prewarm.md")
        before = self.state_snapshot("before-start")
        output = self.hook("session-start", "sessionStart", {"conversation_id": "hook-host-fixture"})
        warmed = self.state_snapshot("after-start")
        rows = indexed_note(self.vault / "knowledge_index.db", "Inbox/Runtime hook prewarm.md")
        observed = prewarm_observation(output, before, warmed, rows, token)
        self.check("hook.prewarm_runs", not rows_before and observed["ran"],
                   "Generated start hook rebuilds the intended index and indexes the new literal note",
                   observed, ["session-start.stdout.txt", "before-start.state.json", "after-start.state.json"])
        self.check("hook.prewarm_no_session", observed["no_session"],
                   "Prewarm consumes no genuine session or pending prompt",
                   {"before": lifecycle(before), "after": lifecycle(warmed)},
                   ["before-start.state.json", "after-start.state.json"])
        repeat = json.loads(self.hook("session-start-repeat", "sessionStart", {"conversation_id": "hook-host-fixture"}))
        repeated = self.state_snapshot("after-start-repeat")
        self.check("hook.start_idempotent", lifecycle(warmed) == lifecycle(repeated)
                   and "Pre-warm unavailable" not in repeat.get("additional_context", ""),
                   "Repeated start hooks keep session and prompt state unchanged",
                   {"before": lifecycle(warmed), "after": lifecycle(repeated)}, ["session-start-repeat.stdout.txt"])
        first, second = "runtime-hook-first", "runtime-hook-second"
        opened = self.memory("genuine-first", "memory_session_start", session_id=first, task_hint="First hook fixture chat")
        other = self.memory("genuine-second", "memory_session_start", session_id=second, task_hint="Concurrent hook fixture chat")
        self.check("hook.genuine_session_ids", opened.get("session_id") == first and other.get("session_id") == second,
                   "Installed public memory calls return both explicit stable session IDs",
                   [opened.get("session_id"), other.get("session_id")],
                   ["genuine-first.stdout.txt", "genuine-second.stdout.txt"])
        self.hook("session-end", "sessionEnd", {"memory_session_id": first, "conversation_id": "hook-host-fixture"})
        ended = self.state_snapshot("after-end")
        sessions = ended.get("sessions", {})
        self.check("hook.event_targets_session", set(sessions) == {first, second} and
                   sessions[first].get("status") == "orphaned" and sessions[second].get("status") == "open" and
                   ended.get("real_sessions") == 2,
                   "End hook marks only the named genuine chat recoverable while its concurrent chat stays open",
                   lifecycle(ended), ["session-end.stdout.txt", "after-end.state.json"])
        self.hook("session-end-repeat", "sessionEnd", {"memory_session_id": first})
        repeated_end = self.state_snapshot("after-end-repeat")
        self.check("hook.end_idempotent", ended == repeated_end,
                   "Repeated end event does not rewrite or recount an already recoverable chat",
                   lifecycle(repeated_end), ["after-end.state.json", "after-end-repeat.state.json"])
        self.hook("recovery-prewarm", "sessionStart", {"conversation_id": "next-host-chat"})
        recovery = self.state_snapshot("after-recovery-prewarm")
        self.check("hook.prewarm_retains_recovery", lifecycle(recovery) == lifecycle(ended)
                   and recovery.get("orphan_unsaved_session") is True,
                   "Background prewarm preserves the unfinished chat and its unconsumed recovery prompt",
                   lifecycle(recovery), ["after-recovery-prewarm.state.json"])
        resumed = self.memory("genuine-recovery", "memory_session_start", session_id=second,
                              task_hint="Resume the concurrent chat")
        recovered = self.state_snapshot("after-genuine-recovery")
        self.check("hook.recovery_prompt", isinstance(resumed.get("soft_prompt"), str)
                   and "Last time" in resumed["soft_prompt"] and recovered.get("real_sessions") == 2
                   and recovered.get("sessions", {}).get(first, {}).get("orphan_prompted") is True,
                   "The next genuine tool call receives the deferred recovery prompt without recounting",
                   {"soft_prompt": resumed.get("soft_prompt"), "state": lifecycle(recovered)},
                   ["genuine-recovery.stdout.txt", "after-genuine-recovery.state.json"])
        self.check("hook.vault_code_not_executed", not self.marker.exists(),
                   "Vault-local hook, package, startup and standard-library shadows never execute",
                   {"marker_exists": self.marker.exists(), "poisoned_pythonpath": True, "path_empty": True},
                   ["session-start.command.json", "session-end.command.json"])
        self.check("hook.identity_unchanged", sha(self.vault / "People/Self.md") == self.identity,
                   "All hook and genuine session actions preserve fixture identity bytes",
                   {"before": self.identity, "after": sha(self.vault / "People/Self.md")},
                   ["init.stdout.txt", "after-genuine-recovery.state.json"])

    def finish(self, error=None):
        after = self.sentinels()
        binding_error = None
        try:
            unchanged = sha(self.artifact) == self.artifact_hash
            if self.kind == "binary" and self.source_bound:
                unchanged = unchanged and artifact.distribution_files(self.distribution_root) == self.files
                unchanged = unchanged and artifact.distribution_links(self.distribution_root) == self.links
            if self.kind == "wheel" and self.source_bound:
                origin = artifact.installed_origin(self.installation["import_origin"],
                                                   self.installation["environment"], self.sources)
                package_files = self.installation["file_hashes"]
                unchanged = unchanged and all(Path(path).is_file() and sha(path) == digest
                                               for path, digest in package_files.items())
                actual = {str(path) for path in [self.executable, *origin.parent.rglob("*")]
                          if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
                unchanged = unchanged and actual == set(package_files)
        except (OSError, ValueError) as exc:
            binding_error = str(exc)
            unchanged = False
        if binding_error:
            error = ValueError(str(error) + "; " + binding_error) if error else ValueError(binding_error)
        if error:
            (self.directory / "execution-error.json").write_text(json.dumps({"error": str(error)}, indent=2), encoding="utf-8")
            self.cases.append({"id": "hook.execution", "verdict": "FAIL",
                               "expected": "Generated installed hook journey completes",
                               "observed": str(error), "evidence": ["execution-error.json"]})
        else:
            self.cases.append({"id": "hook.execution", "verdict": "PASS",
                               "expected": "Generated installed hook journey completes",
                               "observed": "Completed", "evidence": ["generated-hooks.json"]})
        (self.directory / "processes.json").write_text(json.dumps(self.processes, indent=2), encoding="utf-8")
        stopped = all(row["stopped"] for row in self.processes)
        self.cases.append({"id": "hook.all_owned_processes_stopped", "verdict": "PASS" if stopped else "FAIL",
                           "expected": "Every driver-owned child exited", "observed": self.processes, "evidence": ["processes.json"]})
        transcripts = {path.name: sha(path) for path in sorted(self.directory.iterdir())
                       if path.is_file() and path.suffix in (".txt", ".json") and path.name != "report.json"}
        product_unchanged = artifact.product_hashes() == self.sources
        data = {
            "producer": PRODUCER, "producer_sha256": sha(__file__),
            "support_sha256": {"artifact.py": sha(HERE / "artifact.py")},
            "product_hashes": self.sources, "product_unchanged": product_unchanged,
            "artifact": {"kind": self.kind, "path": str(self.artifact), "sha256": self.artifact_hash,
                         "build_manifest": str(self.manifest_path) if self.manifest_path else None,
                         "build_manifest_sha256": sha(self.manifest_path) if self.manifest_path else None,
                         "distribution_root": str(self.distribution_root),
                         "distribution_files": self.files, "distribution_links": self.links},
            "runtime": self.runtime, "installation": self.installation,
            "generated_config": self.generated, "cases": self.cases, "processes": self.processes,
            "all_started_processes_stopped": stopped, "source_bound": self.source_bound,
            "isolation": {"before": self.before, "after": after, "unchanged": self.before == after},
            "artifact_unchanged": unchanged, "transcript_files": transcripts,
            "scope": "Actual generated shell hooks from an exact installation; no claim that a host UI invoked hooks",
            "verdict": "PASS" if not error and all(row["verdict"] == "PASS" for row in self.cases)
                       and stopped and unchanged and product_unchanged and self.before == after else "FAIL",
        }
        (self.directory / "report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(self.directory, flush=True)
        return 0 if data["verdict"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    package = parser.add_mutually_exclusive_group(required=True)
    package.add_argument("--wheel", type=Path)
    package.add_argument("--binary", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.wheel and args.python is None:
        parser.error("--wheel requires --python naming a real target interpreter")
    run = HookRun(args.output, args.wheel or args.binary, "wheel" if args.wheel else "binary",
                  args.python, args.build_manifest)
    error = None
    try:
        run.drive()
    except Exception as exc:
        error = exc
    return run.finish(error)


if __name__ == "__main__":
    raise SystemExit(main())
