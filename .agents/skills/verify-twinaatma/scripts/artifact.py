"""Retain and smoke-test the exact installed wheel or frozen distribution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[4]
PRODUCER = "verify-twinaatma.artifact/v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def product_hashes():
    paths = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT / "AGENTS.md"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def plain(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Linked artifact or installation paths are not accepted")
    return path.resolve(strict=True)



def _fixture_vault_id(vault):
    root = Path(vault).absolute()
    if not root.exists():
        return None
    observed = {}
    for directory in (root, *root.parents):
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("Fixture vault contains a linked or non-directory parent")
        observed[directory] = info
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Fixture vault marker contains duplicate JSON keys")
            result[key] = value
        return result
    values = set()
    for name in (".knowledgeos-vault.json", "knowledgeos.config.json"):
        path = root / name
        try:
            before = path.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or getattr(before, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                or before.st_size > 65536):
            raise ValueError("Fixture vault marker must be a bounded plain single-link file")
        def identity(info):
            return info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if identity(before) != identity(opened):
                raise ValueError("Fixture vault marker changed while opening")
            raw = stream.read(65537)
            after = os.fstat(stream.fileno())
            if (len(raw) > 65536 or identity(opened) != identity(after)
                    or opened.st_ctime_ns != after.st_ctime_ns):
                raise ValueError("Fixture vault marker changed while reading")
        current = path.lstat()
        if identity(current) != identity(before) or current.st_ctime_ns != before.st_ctime_ns:
            raise ValueError("Fixture vault marker changed after reading")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Fixture vault marker must be a JSON object")
        if "vault_id" in value:
            identifier = value["vault_id"]
            if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-fA-F]{16,64}", identifier) is None:
                raise ValueError("Fixture vault marker needs a complete hexadecimal vault ID")
            values.add(identifier.lower())
    for directory, before in observed.items():
        after = directory.lstat()
        if (after.st_dev, after.st_ino, after.st_mode) != (before.st_dev, before.st_ino, before.st_mode):
            raise ValueError("Fixture vault directory changed during observation")
    if len(values) > 1:
        raise ValueError("Fixture vault markers disagree")
    return next(iter(values)) if values else None


def _bound_environment(server, vault, source_root=None):
    env = server.get("env", {})
    if not isinstance(env, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
        return False
    folded = [key.upper() for key in env]
    if len(folded) != len(set(folded)) or env.get("KNOWLEDGEOS_VAULT") != str(vault):
        return False
    if source_root is None:
        return "PYTHONPATH" not in folded
    return env.get("PYTHONPATH") == str(source_root) and "pythonpath" not in env


def installed_server_binding(server, executable, vault):
    try:
        if not isinstance(server, dict):
            return False
        identifier = _fixture_vault_id(vault)
        args = ["mcp"]
        if identifier is not None:
            args += ["--host-vault-id", identifier]
        args += ["--vault", str(vault)]
        if server.get("command") != str(executable) or server.get("args") != args:
            return False
        if identifier is None:
            return not any(str(key).upper() == "PYTHONPATH" for key in server.get("env", {}))
        return (Path(vault).is_absolute() and "cwd" not in server
                and server.get("required") is True and server.get("default_tools_approval_mode") == "approve"
                and _bound_environment(server, vault))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def wheel_binding(path, current):
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate wheel members")
        if any(Path(n).is_absolute() or ".." in Path(n).parts or "\\" in n for n in names):
            raise ValueError("Unsafe wheel member path")
        hook_members = {n for n in names if n.startswith("knowledgeos/_assets/.cursor/hooks/") and n.endswith(".py")}
        expected_hooks = {"knowledgeos/_assets/" + p for p in current if p.startswith(".cursor/hooks/")}
        if hook_members != expected_hooks:
            raise ValueError("Wheel hook inventory does not match current product")
        modules = {n for n in names if n.startswith("knowledgeos/") and n.count("/") == 1 and n.endswith(".py")}
        expected = {p for p in current if p.startswith("knowledgeos/")}
        if modules != expected:
            raise ValueError("Wheel module inventory does not match current product")
        for relative, digest in current.items():
            member = relative if relative.startswith("knowledgeos/") else "knowledgeos/_assets/" + relative
            if member not in names or hashlib.sha256(wheel.read(member)).hexdigest() != digest:
                raise ValueError("Stale or missing wheel product bytes: " + relative)
        if any(n.startswith("tests/") for n in names):
            raise ValueError("Wheel unexpectedly ships tests")
    return True


def distribution_links(root):
    links = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("Dangling or cyclic distribution link: " + str(path)) from exc
            if not target.is_relative_to(root):
                raise ValueError("Distribution link escapes retained distribution: " + str(path))
            links[path.relative_to(root).as_posix()] = os.readlink(path)
    return links


def distribution_files(root):
    distribution_links(root)
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def binary_binding(path, manifest_path, current):
    if manifest_path is None:
        raise ValueError("Frozen distributions require an exact current build manifest")
    manifest = json.loads(plain(manifest_path).read_text(encoding="utf-8-sig"))
    if manifest.get("producer") != "verify-twinaatma.build/v1" or manifest.get("product_hashes") != current:
        raise ValueError("Build manifest does not bind the current product")
    inputs = manifest.get("inputs", {})
    if any(inputs.get(p) != h for p, h in current.items()):
        raise ValueError("Build manifest inputs do not match current source")
    commands = manifest.get("build_commands", [])
    if not commands or any(not r.get("command") or r.get("exit_code") != 0 for r in commands):
        raise ValueError("Build manifest lacks successful build command records")
    root = plain(manifest["distribution_root"])
    executable = plain(manifest["executable"])
    if executable != path or not executable.is_relative_to(root):
        raise ValueError("Build manifest executable does not match requested artifact")
    files = distribution_files(root)
    if not files or files != manifest.get("outputs") or distribution_links(root) != manifest.get("links", {}):
        raise ValueError("Frozen distribution bytes differ from build manifest")
    return root, files


def installed_origin(origin, environment, current):
    origin = plain(origin)
    environment = plain(environment)
    if not origin.is_relative_to(environment) or "site-packages" not in origin.parts or origin.name != "__init__.py":
        raise ValueError("Import did not originate in the retained isolated installation")
    package = origin.parent
    expected = {Path(p).name: h for p, h in current.items() if p.startswith("knowledgeos/")}
    actual = {p.name: sha(plain(p)) for p in package.glob("*.py")}
    if actual != expected:
        raise ValueError("Installed modules differ from current product")
    for relative, digest in current.items():
        if not relative.startswith("knowledgeos/") and sha(plain(package / "_assets" / relative)) != digest:
            raise ValueError("Installed asset differs from current product: " + relative)
    return origin


class ArtifactRun:
    def __init__(self, output, artifact, kind, manifest=None):
        base = Path(output).resolve()
        generated = (ROOT / "work/gc-artifacts").resolve()
        if not base.is_relative_to(generated) or ".knowledgeos" not in base.relative_to(generated).parts:
            raise ValueError("Output must be below work/gc-artifacts and contain .knowledgeos")
        self.directory = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True)
        self.neutral = self.directory / "neutral"
        self.neutral.mkdir()
        self.artifact = plain(artifact)
        self.kind = kind
        self.manifest = manifest
        self.sources = product_hashes()
        self.artifact_hash = sha(self.artifact)
        self.files = {self.artifact.name: self.artifact_hash}
        self.links = {}
        self.distribution_root = self.artifact.parent
        self.vault = self.directory / "vault"
        self.state = self.directory / "gate-state"
        self.env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(self.state), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        for key in ("PYTHONPATH", "KNOWLEDGEOS_VAULT", "PYTHONHOME", "VIRTUAL_ENV"):
            self.env.pop(key, None)
        self.processes = []
        self.cases = []
        self.installation = {"vault": str(self.vault), "state_dir": str(self.state), "platform": platform.platform(), "python_version": sys.version}
        self.protected = [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json", Path.home() / ".codex/config.toml"]
        self.before = self.sentinels()
        self.source_bound = False
        self.identity = None

    def sentinels(self):
        return {str(p): sha(p) if p.is_file() else None for p in self.protected}

    def check(self, identifier, condition, expected, observed, evidence):
        self.cases.append({"id": identifier, "verdict": "PASS" if condition else "FAIL", "expected": expected, "observed": observed, "evidence": evidence})
        if not condition:
            raise ValueError(identifier)

    def command(self, label, command, timeout=180):
        command = list(map(str, command))
        child = subprocess.Popen(command, cwd=self.neutral, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        record = {"pid": child.pid, "role": label, "stopped": False}
        self.processes.append(record)
        started = time.monotonic()
        error = None
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except BaseException as exc:
            error = exc
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=20)
            else:
                child.kill()
            stdout, stderr = child.communicate(timeout=20)
        finally:
            record.update(stopped=child.poll() is not None, exit_code=child.returncode)
        (self.directory / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (self.directory / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        (self.directory / (label + ".command.json")).write_text(json.dumps({"command": command, "cwd": str(self.neutral), "exit_code": child.returncode, "seconds": time.monotonic() - started, "cleared_environment": ["PYTHONPATH", "KNOWLEDGEOS_VAULT", "PYTHONHOME", "VIRTUAL_ENV"]}, indent=2), encoding="utf-8")
        if error:
            raise error
        if child.returncode:
            raise RuntimeError(label + " failed: " + stderr[-2000:])
        return stdout

    def drive(self):
        if self.kind == "wheel":
            wheel_binding(self.artifact, self.sources)
            environment = self.directory / "venv"
            self.command("create-venv", [sys.executable, "-I", "-m", "venv", "--without-pip", environment], timeout=300)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            self.command("install", [sys.executable, "-I", "-m", "pip", "--python", python, "install", "--no-index", "--no-deps", self.artifact], timeout=300)
            origin = self.command("import-origin", [python, "-I", "-c", "import knowledgeos,sys,json;print(json.dumps({'origin':knowledgeos.__file__,'version':sys.version}))"])
            details = json.loads(origin)
            origin = installed_origin(details["origin"], environment, self.sources)
            self.executable = python.with_name("twinaatma.exe" if os.name == "nt" else "twinaatma")
            self.installation.update(python=str(python), import_origin=str(origin), python_version=details["version"])
            retained = [self.executable, *origin.parent.rglob("*")]
            self.installation["file_hashes"] = {str(p): sha(plain(p)) for p in sorted(retained) if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
            self.check("artifact.isolated_import", True, "Current installed modules imported from isolated site-packages", str(origin), ["import-origin.stdout.txt"])
        else:
            self.distribution_root, self.files = binary_binding(self.artifact, self.manifest, self.sources)
            self.links = distribution_links(self.distribution_root)
            self.executable = self.artifact
            (self.directory / "build-manifest.json").write_bytes(plain(self.manifest).read_bytes())
        self.source_bound = True
        self.installation["executable"] = str(self.executable)
        (self.directory / "binding.json").write_text(json.dumps({"product_hashes": self.sources, "artifact_sha256": self.artifact_hash}, indent=2), encoding="utf-8")
        self.check("artifact.current_product", True, "Artifact product bytes match the complete current product namespace", self.sources, ["binding.json"])
        self.command("version", [self.executable, "version"])
        created = json.loads(self.command("init", [self.executable, "init", self.vault, "--name", "Installed package fixture", "--non-interactive"]))
        self.identity = sha(self.vault / "People/Self.md")
        self.check("artifact.init", '"ok": false' not in json.dumps(created), "Initialization creates Self and reports no post-init failures", created, ["init.stdout.txt"])
        doctor = self.command("doctor", [self.executable, "doctor", "--vault", self.vault])
        self.check("artifact.doctor", True, "Installed doctor succeeds", doctor, ["doctor.stdout.txt"])
        capture = json.loads(self.command("capture", [self.executable, "memory", "memory_capture", "--vault", self.vault, "--title", "Installed Seaglass fixture", "--content", "The installed Seaglass cabin luggage allowance is 7 kg. Verification token quartzite-installed."]))
        note = capture.get("path")
        if not note:
            raise ValueError("Capture did not return a stored note path")
        self.check("artifact.capture", (self.vault / note).is_file(), "Installed capture persists its literal fact", capture, ["capture.stdout.txt"])
        recall = json.loads(self.command("recall", [self.executable, "memory", "memory_search", "--vault", self.vault, "--query", "quartzite-installed"]))
        self.check("artifact.recall_after_restart", any(r.get("path") == note for r in recall.get("ranked", [])), "A new installed process recalls the exact captured note", recall, ["recall.stdout.txt"])
        self.command("setup", [self.executable, "setup-host", "--host", "codex", "--vault", self.vault, "--write"])
        import tomllib
        config = self.vault / ".codex/config.toml"
        server = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]["knowledgeos"]
        copied = self.directory / "generated-config.toml"
        copied.write_bytes(config.read_bytes())
        self.installation["generated_config"] = str(copied)
        self.check("artifact.installed_host_config", installed_server_binding(server, self.executable, self.vault), "Native host configuration launches the exact installed executable without checkout imports", server, ["generated-config.toml"])
        self.check("artifact.identity_unchanged", sha(self.vault / "People/Self.md") == self.identity, "Smoke operations preserve synthetic identity", {"before": self.identity, "after": sha(self.vault / "People/Self.md")}, ["init.stdout.txt", "capture.stdout.txt"])

    def finish(self, error=None):
        after = self.sentinels()
        try:
            unchanged = sha(self.artifact) == self.artifact_hash and (self.kind == "wheel" or not self.source_bound or (distribution_files(self.distribution_root) == self.files and distribution_links(self.distribution_root) == self.links))
        except (OSError, ValueError):
            unchanged = False
        if error:
            self.cases.append({"id": "artifact.execution", "verdict": "FAIL", "expected": "Installed artifact proof completes", "observed": str(error), "evidence": []})
        transcripts = {p.name: sha(p) for p in sorted(self.directory.iterdir()) if p.is_file() and p.suffix in (".txt", ".json", ".toml") and p.name not in ("report.json", "acceptance.json")}
        data = {"producer": PRODUCER, "producer_sha256": sha(__file__), "product_hashes": self.sources, "artifact": {"kind": self.kind, "path": str(self.artifact), "sha256": self.artifact_hash, "distribution_root": str(self.distribution_root), "distribution_files": self.files, "distribution_links": self.links}, "installation": self.installation, "cases": self.cases, "processes": self.processes, "all_started_processes_stopped": all(p["stopped"] for p in self.processes), "isolation": {"before": self.before, "after": after, "unchanged": self.before == after}, "artifact_unchanged": unchanged, "product_unchanged": product_hashes() == self.sources, "source_bound": self.source_bound, "transcript_files": transcripts, "scope": "Exact installed artifact CLI and native host configuration; no model conversation or other platform acceptance", "verdict": "PASS" if not error and all(r["verdict"] == "PASS" for r in self.cases) and self.before == after and unchanged and product_hashes() == self.sources else "FAIL"}
        (self.directory / "report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(self.directory, flush=True)
        return 0 if data["verdict"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    artifact = parser.add_mutually_exclusive_group(required=True)
    artifact.add_argument("--wheel", type=Path)
    artifact.add_argument("--binary", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = ArtifactRun(args.output, args.wheel or args.binary, "wheel" if args.wheel else "binary", args.build_manifest)
    error = None
    try:
        run.drive()
    except Exception as exc:
        error = exc
    return run.finish(error)


if __name__ == "__main__":
    raise SystemExit(main())
