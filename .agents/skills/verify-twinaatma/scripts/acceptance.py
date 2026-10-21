"""Measure verified fulfillment of the fixed ideal contract, never regression-test counts."""
import argparse
import ast
from collections import Counter
import datetime
import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
RUBRIC = Path(__file__).resolve().parents[1] / "references/acceptance-rubric.json"
STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT CHECKED")
HOST_IDS = {"host.discovery", "host.first_memory_call", "host.capture_from_chat",
            "host.recall_after_restart", "host.grounded_answer", "host.unknown_abstains",
            "host.session_id_propagated", "host.summary_persisted", "host.no_user_ops",
            "host.identity_unchanged"}

ARTIFACT_MATRIX = frozenset((platform, kind) for platform in ("Windows", "Linux") for kind in ("wheel", "binary"))
ARTIFACT_IDS = {"artifact.isolated_import", "artifact.current_product", "artifact.init", "artifact.doctor",
                "artifact.capture", "artifact.recall_after_restart", "artifact.installed_host_config",
                "artifact.identity_unchanged", "artifact.execution"}
ADAPTER_REQUIREMENTS = {"version": "verify-twinaatma.adapters/v1", "outcomes": {
    "SETUP.artifact_install": ["artifact.release_matrix_complete", "artifact.isolated_install_usable"]},
    "release_matrix": sorted([list(cell) for cell in ARTIFACT_MATRIX])}

RUNTIME_MINORS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")
RUNTIME_MATRIX = frozenset((platform, "wheel", minor) for platform in ("Windows", "Linux")
                           for minor in RUNTIME_MINORS) | frozenset(
                               (platform, "binary", "embedded") for platform in ("Windows", "Linux"))
HOOK_IDS = {"hook.runtime_identity", "hook.isolated_import", "hook.current_product", "hook.init",
            "hook.generated_commands", "hook.prewarm_runs", "hook.prewarm_no_session",
            "hook.start_idempotent", "hook.genuine_session_ids", "hook.event_targets_session",
            "hook.end_idempotent", "hook.prewarm_retains_recovery", "hook.recovery_prompt",
            "hook.vault_code_not_executed", "hook.identity_unchanged", "hook.execution",
            "hook.all_owned_processes_stopped"}
ADAPTER_REQUIREMENTS["version"] = "verify-twinaatma.adapters/v2"
ADAPTER_REQUIREMENTS["outcomes"]["SETUP.runtime_hooks"] = ["hook.runtime_matrix_complete", "hook.runtime_matrix_usable"]
ADAPTER_REQUIREMENTS["outcomes"]["SETUP.config_preserved"] = ["setup.config_preserved"]
ADAPTER_REQUIREMENTS["outcomes"]["SETUP.post_init_failure"] = ["setup.post_init_failure"]
ADAPTER_REQUIREMENTS["runtime_hook_matrix"] = sorted([list(cell) for cell in RUNTIME_MATRIX])


DATA_PRODUCERS = {
    "verify-twinaatma.data-preservation/v1": {
        "file": "data_preservation.py", "support": (), "aggregate": "data.export.complete",
        "outcome": "DATA.safe_export", "cases": frozenset("data.export." + name for name in (
            "existing_directory", "existing_file", "identity_directory", "equal_source", "nested_output",
            "outside_prefix_sibling", "linked_source_file", "linked_source_directory", "linked_output_file",
            "linked_output_parent", "hardlinked_source", "hardlinked_output", "fresh_bundle", "source_prefix_sibling"))},
    "verify-twinaatma.generated-writers/v2": {
        "file": "generated_writers.py", "support": ("data_preservation.py",), "aggregate": "data.generated.complete",
        "outcome": "DATA.atomic_generated", "cases": frozenset("data.generated." + writer + "-" + scenario
            for writer in ("trajectory", "weekly", "views", "experiments", "outcomes", "draft")
            for scenario in ("regenerate", "unowned", "edited", "linked_target", "hardlinked_target", "linked_parent", "receipt_fault", "report_fault"))},
    "verify-twinaatma.memory-census/v2": {
        "file": "memory_census.py", "support": ("data_preservation.py", "generated_writers.py"), "aggregate": "data.census.complete",
        "outcome": "DATA.memory_census", "cases": frozenset("data.census." + name for name in (
            "instructions_excluded", "toolkit_excluded", "fixtures_excluded", "generated_excluded",
            "personal_preserved", "edited_generated_preserved", "identity_unchanged"))},
}
MAINTENANCE_PRODUCERS = {
    "verify-twinaatma.maintenance/v1": {
        "file": "maintenance.py", "support": ("data_preservation.py",), "aggregate": "data.maintenance.complete",
        "outcome": "DATA.safe_maintenance", "journey": "maintenance", "cases": frozenset("data.maintenance." + name for name in (
            "ids_dry_run", "ids_write", "ids_schema", "ids_replace_fault", "ids_write_fault", "ids_hardlink_self",
            "ids_hardlink_proposal", "ids_linked_directory", "links_write", "links_replace_fault", "maps_write",
            "maps_edited", "maps_replace_fault"))},
    "verify-twinaatma.hooks-preservation/v1": {
        "file": "maintenance.py", "support": ("data_preservation.py",), "aggregate": "data.hooks.complete",
        "outcome": "DATA.preserve_hooks", "journey": "hooks", "cases": frozenset("data.hooks." + name for name in (
            "existing", "custom", "external", "linked_directory", "linked_file", "hardlinked_file", "write_fault", "chmod_fault"))},
    "verify-twinaatma.validation/v1": {
        "file": "maintenance.py", "support": ("data_preservation.py",), "aggregate": "data.validation.complete",
        "outcome": "DATA.honest_validation", "journey": "validation", "cases": frozenset("data.validation." + name for name in (
            "good", "missing", "status", "date", "tags", "schema", "id", "duplicate", "broken", "ambiguous"))},
}
ALL_DATA_PRODUCERS = {**DATA_PRODUCERS, **MAINTENANCE_PRODUCERS}
DATA_COPY_PREFIXES = {"data_preservation.py": ("data.export.", ""), "generated_writers.py": ("data.generated.", ""),
                      "maintenance": ("data.maintenance.", "maintenance-"), "hooks": ("data.hooks.", "hooks-"),
                      "validation": ("data.validation.", "validation-")}
ADAPTER_REQUIREMENTS["version"] = "verify-twinaatma.adapters/v5"
ADAPTER_REQUIREMENTS["outcomes"].update({spec["outcome"]: [spec["aggregate"]] for spec in ALL_DATA_PRODUCERS.values()})
ADAPTER_REQUIREMENTS["data_producers"] = {name: {"file": spec["file"], "support": list(spec["support"]),
    "cases": sorted(spec["cases"]), "aggregate": spec["aggregate"], "outcome": spec["outcome"]}
    for name, spec in ALL_DATA_PRODUCERS.items()}

IDENTITY_PRODUCERS = {
    "verify-twinaatma.identity-unknown/v1": {"journey": "unknown", "fixtures": ("cold",),
        "outcome": "IDENTITY.unknown_stays_unknown", "cases": (
            "cold_init", "cold_self_get", "cold_session_start", "restart_self_get", "identity_preserved")},
    "verify-twinaatma.identity-canonical/v1": {"journey": "canonical", "fixtures": ("marked", "aliases", "duplicate"),
        "outcome": "IDENTITY.canonical_sections", "cases": (
            "marked_self_get", "marked_session_start", "marked_proposals", "aliases_self_get", "aliases_session_start",
            "aliases_proposals", "duplicate_self_get", "duplicate_session_start", "duplicate_proposal", "identity_preserved")},
}
IDENTITY_SECTIONS = ("heuristics", "values", "mental_models", "anti_goals", "active_bets", "drift_log")
IDENTITY_CONTENTS = {
    "heuristics": "- Synthetic rule HX41. Compare one reversible option before choosing.\n- Synthetic rule HX42. Record evidence before generalizing.",
    "values": "1. Synthetic priority VX41. Keep explicit evidence above untested confidence.\n2. Synthetic priority VX42. Preserve time for careful review.",
    "mental_models": "- Synthetic model MX41. Separate observations from interpretations.\n- Synthetic model MX42. Consider the cost of reversing a decision.",
    "anti_goals": "- Synthetic limit AX41. Avoid irreversible changes based only on guesses.\n- Synthetic limit AX42. Avoid ranking another person's unstated values.",
    "active_bets": "- Synthetic bet BX41. Test a small local prototype this week.\n- Synthetic bet BX42. Reassess the prototype after measured feedback.",
    "drift_log": "| Topic | Shift Observed | Date Flagged | Evidence |\n|---|---|---|---|\n| Synthetic DX41 | Revised one prototype estimate | 2026-10-19 | fixture evidence DX42 |",
}
IDENTITY_UNKNOWNS = {
    "heuristics": "Unknown. No owner-confirmed heuristics recorded yet.",
    "values": "Unknown. No owner-confirmed values or ranking recorded yet.",
    "mental_models": "Unknown. No owner-confirmed mental models recorded yet.",
    "anti_goals": "Unknown. No owner-confirmed anti-goals recorded yet.",
    "active_bets": "Unknown. No owner-confirmed strategic bets recorded yet.",
}
QUALITY_PRODUCER = "verify-twinaatma.quality/v1"
QUALITY_CORPUS = "tests/fixtures/quality-v1.json"
QUALITY_CORPUS_SHA256 = "787de4674bb0a51fceee87acb7ee7e9b8872068e1fab8af24de3e729bcbac379"
QUALITY_CASE_IDS = tuple("quality-v1-" + str(index).zfill(3) for index in range(1, 37))
QUALITY_SPLITS = ("development", "held_out")
QUALITY_SELF_SHA256 = "b169fd580ef507cc3e1e2655eb6b67b19a9a5b00420f220f46b7e470645598c1"
ADAPTER_REQUIREMENTS["identity_producers"] = {producer: {"file": "identity.py", "support": ["data_preservation.py"],
    "cases": ["identity." + spec["journey"] + "." + name for name in spec["cases"]], "outcome": spec["outcome"]}
    for producer, spec in IDENTITY_PRODUCERS.items()}
ADAPTER_REQUIREMENTS["quality_producer"] = {"producer": QUALITY_PRODUCER, "file": "quality.py", "support": ["data_preservation.py"],
    "cases": list(QUALITY_CASE_IDS), "corpus": QUALITY_CORPUS, "corpus_sha256": QUALITY_CORPUS_SHA256,
    "source_top_k": 8, "critical_source_target": 1, "critical_claim_target": 1, "noncritical_source_target": 0.9}
ADAPTER_REQUIREMENTS["outcomes"].update({spec["outcome"]: ["identity." + spec["journey"] + ".complete"]
                                           for spec in IDENTITY_PRODUCERS.values()})
ADAPTER_REQUIREMENTS["outcomes"].update({"QUALITY.fixed_corpus": ["quality.fixed_corpus"],
                                        "QUALITY.retrieval_target": ["quality.retrieval_target"]})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"Unreadable JSON {path}: {exc}") from exc


def product_hashes():
    paths = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT / "AGENTS.md"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file()}


def file_evidence(directory, relative):
    candidate = directory / relative
    try:
        candidate.resolve().relative_to(directory.resolve())
    except ValueError:
        raise ValueError(f"Evidence escapes report directory: {relative}")
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"Missing or linked evidence: {relative}")
    return candidate


def check_product(data, field, current):
    declared = data.get(field)
    if not isinstance(declared, dict):
        raise ValueError("Report product hashes do not match this exact current product")
    # Source manifests also include docs and tests. Compare the entire product
    # namespace so deleting a module invalidates old proof just as editing it does.
    product = {p: h for p, h in declared.items() if p in current or
               (Path(p).suffix == ".py" and Path(p).parent.as_posix() in ("knowledgeos", ".cursor/hooks"))}
    if product != current:
        raise ValueError("Report product hashes do not match this exact current product")


def checked_rows(rows, allowed=None, host=False):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Report needs observed executable checks")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid check")
        identifier = row.get("id")
        if not isinstance(identifier, str) or identifier in result:
            raise ValueError(f"Invalid or duplicate check: {identifier}")
        if allowed is not None and identifier not in allowed:
            raise ValueError(f"Unknown producer check: {identifier}")
        if row.get("verdict") not in STATUSES or "observed" not in row:
            raise ValueError(f"Check requires verdict and observed result: {identifier}")
        if row.get("verdict") == "PASS" and (row["observed"] is None or row["observed"] == "" or row["observed"] == {} or row["observed"] == []):
            raise ValueError(f"PASS needs a literal observed result: {identifier}")
        if host and ("expected" not in row or not row.get("evidence")):
            raise ValueError(f"Host check requires expected result and retained evidence: {identifier}")
        result[identifier] = row
    return result


def source_report(path, current):
    data = read_json(path)
    if data.get("journey") not in ("core", "failure", "concurrency") or not str(data.get("scope", "")).startswith("Source CLI/MCP"):
        raise ValueError("Unsupported source producer; use the verification driver report")
    check_product(data, "source_hashes", current)
    producer = Path(__file__).with_name("verify.py")
    producer_relative = producer.relative_to(ROOT).as_posix()
    if data["source_hashes"].get(producer_relative) != sha(producer):
        raise ValueError("Source producer hash missing or stale")
    directory = path.parent
    transcript = file_evidence(directory, "transcript.jsonl")
    records = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or not any(r.get("kind") in ("cli", "mcp") for r in records):
        raise ValueError("Missing executable transcript observations")
    tree = ast.parse(producer.read_text(encoding="utf-8-sig"))
    allowed = {node.args[0].value for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "check" and node.args
               and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
    rows = checked_rows(data.get("checks"), allowed=allowed)
    for check in ("evidence.source_unchanged", "isolation.real_vault_sentinels_unchanged"):
        if rows.get(check, {}).get("verdict") != "PASS":
            raise ValueError(f"Unusable evidence prerequisite: {check}")
    processes = data.get("processes")
    if (not data.get("all_started_mcp_processes_stopped") or not isinstance(processes, list)
            or not processes or any(p.get("stopped") is not True for p in processes)):
        raise ValueError("Source process shutdown is not substantiated")
    return {"path": str(path), "report_sha256": sha(path), "scope": "source",
            "producer": "verify-twinaatma.verify/v1", "producer_sha256": sha(producer), "transcript_sha256": sha(transcript),
            "checks": rows}



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


def checked_installed_host_config(server, installation):
    executable = retained_file(installation.get("executable"))
    if retained_file(server.get("command")) != executable:
        raise ValueError("Installed host native configuration does not bind artifact launcher")
    vault_text = installation.get("vault")
    if not isinstance(vault_text, str) or not vault_text:
        raise ValueError("Installed host fixture vault path is missing")
    vault = retained_path(vault_text)
    identifier = _fixture_vault_id(vault)
    args = ["mcp"]
    if identifier is not None:
        args += ["--host-vault-id", identifier]
    args += ["--vault", vault_text]
    if server.get("args") != args:
        raise ValueError("Installed host native configuration does not bind the full fixture vault ID")
    if identifier is None:
        if any(str(key).upper() == "PYTHONPATH" for key in server.get("env", {})):
            raise ValueError("Installed host native configuration imports source checkout code")
        return
    if (not vault.is_absolute() or "cwd" in server or server.get("required") is not True
            or server.get("default_tools_approval_mode") != "approve"
            or not _bound_environment(server, vault_text)):
        raise ValueError("Installed host native vault binding has unsafe cwd, environment or startup policy")


def host_report(path, current):
    data = read_json(path)
    installed = data.get("producer") == "verify-twinaatma.installed-host/v1"
    if data.get("producer") not in ("verify-twinaatma.host/v1", "verify-twinaatma.installed-host/v1"):
        raise ValueError("Unsupported host producer; manual status claims cannot award acceptance")
    producer = Path(__file__).with_name("installed_host.py" if installed else "host.py")
    if not producer.is_file() or data.get("producer_sha256") != sha(producer):
        raise ValueError("Host producer hash missing or stale")
    check_product(data, "product_hashes", current)
    if data.get("product_unchanged") is not True:
        raise ValueError("Host product changed during observation or lacks stability proof")
    if installed:
        if data.get("server_artifact_bound") is not True:
            raise ValueError("Host server artifact binding is not substantiated")
        support = data.get("support_sha256", {})
        if any(support.get(name) != sha(Path(__file__).with_name(name)) for name in ("host.py", "artifact.py")):
            raise ValueError("Installed host support producer hash missing or stale")
        reference = data.get("artifact_evidence", {})
        artifact_path = retained_file(reference.get("report"))
        if sha(artifact_path) != reference.get("sha256"):
            raise ValueError("Installed host artifact report hash mismatch")
        artifact_report(artifact_path, current)
        artifact_data = read_json(artifact_path)
        try:
            import tomllib
        except ImportError as exc:
            raise ValueError("Installed host grading requires Python 3.11 or newer") from exc
        config = file_evidence(path.parent, "generated-config.toml")
        try:
            server = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]["knowledgeos"]
        except (ValueError, KeyError) as exc:
            raise ValueError("Invalid installed host native configuration") from exc
        installation = artifact_data["installation"]
        checked_installed_host_config(server, installation)
        if "generated-config.toml" not in data.get("transcript_files", {}):
            raise ValueError("Installed host native configuration is not hashed")
    elif data.get("server_source_bound") is not True:
        raise ValueError("Host server source binding is not substantiated")
    host = data.get("host", {})
    if not all(host.get(k) for k in ("name", "version", "mode")):
        raise ValueError("Actual host name, version and execution mode are required")
    transcripts = data.get("transcript_files")
    if not isinstance(transcripts, dict) or not transcripts:
        raise ValueError("Host report needs hashed transcripts")
    for name, expected_hash in transcripts.items():
        if sha(file_evidence(path.parent, name)) != expected_hash:
            raise ValueError(f"Host transcript hash mismatch: {name}")
    rows = checked_rows(data.get("cases"), allowed=HOST_IDS, host=True)
    for row in rows.values():
        for name in row["evidence"]:
            if name not in transcripts:
                raise ValueError(f"Unhashed host evidence: {name}")
    processes = data.get("processes")
    if not isinstance(processes, list) or not processes or any(p.get("stopped") is not True for p in processes):
        raise ValueError("Host process shutdown is not substantiated")
    isolation = data.get("isolation", {})
    if not isolation.get("before") or isolation.get("before") != isolation.get("after"):
        raise ValueError("Host isolation sentinels absent or changed")
    return {"path": str(path), "report_sha256": sha(path), "scope": "real_host",
            "producer": data["producer"], "producer_sha256": sha(producer), "host": host, "transcript_files": transcripts, "checks": rows}



def retained_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing retained artifact path")
    prefix = "/mnt/w/AI-Projects/TwinAatma"
    windows = "W:/AI-Projects/TwinAatma/"
    normalized = value.replace("\\", "/")
    if value.startswith(prefix + "/"):
        path = ROOT / value[len(prefix) + 1:]
    elif normalized.startswith(windows):
        path = ROOT / normalized[len(windows):]
    elif value.startswith("/") and os.name == "nt":
        raise ValueError("Unsupported foreign artifact path")
    else:
        path = Path(value)
    try:
        path.absolute().relative_to(ROOT.absolute())
        path.resolve(strict=True).relative_to(ROOT.resolve())
    except (ValueError, OSError) as exc:
        raise ValueError("Artifact path is missing or escapes retained workspace") from exc
    return path


def retained_file(value):
    path = retained_path(value)
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Retained artifact file is missing or linked")
    return path


def distribution_inventory(root):
    files, links = {}, {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            try:
                path.resolve(strict=True).relative_to(root.resolve())
            except (ValueError, OSError, RuntimeError) as exc:
                raise ValueError("Distribution link escapes or is unreadable") from exc
            links[relative] = os.readlink(path)
        elif path.is_file():
            files[relative] = sha(path)
    return files, links


def shipped_assets():
    """Independent inventory of the starter kit that setup.py stages into a wheel."""
    ignored = {"__pycache__", ".git", ".knowledgeos", "node_modules"}
    paths = [p for directory in ("Templates", ".cursor") for p in (ROOT / directory).rglob("*")
             if p.is_file() and not any(part in ignored for part in p.relative_to(ROOT).parts)
             and not p.name.endswith(".pyc")]
    paths.extend(ROOT / name for name in ("AGENTS.md", "LICENSE"))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def build_inputs():
    """The complete source kit consumed by the isolated release builder."""
    inputs = shipped_assets()
    inputs.update({p.relative_to(ROOT).as_posix(): sha(p) for p in ROOT.glob("knowledgeos/*.py") if p.is_file()})
    inputs.update({name: sha(ROOT / name) for name in
                   ("knowledgeos/py.typed", "setup.py", "pyproject.toml", "pyinstaller.spec",
                    "MANIFEST.in", "README.md", "knowledgeos.config.example.json")})
    return inputs


def checked_build_manifest(path, current):
    manifest = read_json(path)
    if manifest.get("producer") != "verify-twinaatma.build/v1" or manifest.get("product_hashes") != current:
        raise ValueError("Artifact build manifest product binding mismatch")
    if manifest.get("inputs") != build_inputs():
        raise ValueError("Artifact build input inventory or hash mismatch")
    commands = manifest.get("build_commands", [])
    if not commands or any(not r.get("command") or r.get("exit_code") != 0 for r in commands):
        raise ValueError("Artifact build commands are not substantiated")
    return manifest


def checked_artifact_binding(data, path, current, transcripts):
    installation, artifact = data.get("installation", {}), data.get("artifact", {})
    platform = next((name for name in ("Windows", "Linux")
                     if str(installation.get("platform", "")).startswith(name + "-")), None)
    cell = (platform, artifact.get("kind"))
    if cell not in ARTIFACT_MATRIX:
        raise ValueError("Unsupported artifact release matrix cell")
    executable = retained_file(installation.get("executable"))
    artifact_path = retained_file(artifact.get("path"))
    if sha(artifact_path) != artifact.get("sha256"):
        raise ValueError("Artifact file hash mismatch")
    root = retained_path(artifact.get("distribution_root"))
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Invalid retained distribution directory")
    assets = shipped_assets()
    if cell[1] == "binary":
        files, links = distribution_inventory(root)
        if not files or files != artifact.get("distribution_files") or links != artifact.get("distribution_links"):
            raise ValueError("Frozen distribution inventory or dependency hash mismatch")
        expected_assets = {"_internal/" + p: h for p, h in assets.items()}
        expected_assets.update({"_internal/" + name: sha(ROOT / name)
                                for name in ("README.md", "knowledgeos.config.example.json")})
        observed_assets = {p: h for p, h in files.items() if p in expected_assets or
                           p.startswith(("_internal/Templates/", "_internal/.cursor/"))}
        asset_links = {p for p in links if p in expected_assets or
                       p.startswith(("_internal/Templates/", "_internal/.cursor/"))}
        if observed_assets != expected_assets or asset_links:
            raise ValueError("Frozen shipped assets inventory or current source bytes mismatch")
        if executable != artifact_path or not executable.is_relative_to(root):
            raise ValueError("Installed launcher does not match frozen artifact")
        if "build-manifest.json" not in transcripts:
            raise ValueError("Frozen artifact lacks hashed build manifest")
        manifest_path = file_evidence(path.parent, "build-manifest.json")
        manifest = checked_build_manifest(manifest_path, current)
        if (manifest.get("outputs") != files or manifest.get("links", {}) != links
                or retained_path(manifest.get("distribution_root")) != root
                or retained_file(manifest.get("executable")) != executable):
            raise ValueError("Frozen build manifest binding mismatch")
    else:
        if artifact.get("distribution_files") != {artifact_path.name: sha(artifact_path)} or artifact.get("distribution_links") != {}:
            raise ValueError("Wheel artifact inventory mismatch")
        # The builder retains its provenance next to wheel/, independent of the
        # runtime observer. Reject externally built wheels without that binding.
        manifest_path = retained_file(str(artifact_path.parent.parent / "build-manifest.json"))
        manifest = checked_build_manifest(manifest_path, current)
        if retained_file(manifest.get("wheel")) != artifact_path:
            raise ValueError("Wheel build manifest does not bind the observed artifact")
        with zipfile.ZipFile(artifact_path) as wheel:
            names = wheel.namelist()
            expected = {p: h for p, h in current.items() if p.startswith("knowledgeos/")}
            expected["knowledgeos/py.typed"] = sha(ROOT / "knowledgeos/py.typed")
            expected.update({"knowledgeos/_assets/" + p: h for p, h in assets.items()})
            package_members = {n for n in names if n.startswith("knowledgeos/") and not n.endswith("/")}
            if (len(names) != len(set(names)) or package_members != set(expected)
                    or any(n not in names or hashlib.sha256(wheel.read(n)).hexdigest() != h for n, h in expected.items())):
                raise ValueError("Wheel product bytes or shipped assets differ from current product")
        origin = retained_file(installation.get("import_origin"))
        if origin.name != "__init__.py" or "site-packages" not in origin.parts:
            raise ValueError("Wheel import origin is not an isolated installed package")
        installed = installation.get("file_hashes")
        if not isinstance(installed, dict) or not installed:
            raise ValueError("Installed launcher and package hashes are required")
        bound = {retained_file(p): digest for p, digest in installed.items()}
        required = {executable}
        package = origin.parent
        installed_members = {p.relative_to(package.parent).as_posix() for p in package.rglob("*")
                             if p.is_file() and "__pycache__" not in p.relative_to(package).parts
                             and not p.name.endswith(".pyc")}
        if installed_members != set(expected):
            raise ValueError("Installed product module or shipped assets inventory mismatch")
        for relative, digest in expected.items():
            module = package.parent / relative
            required.add(module)
            if sha(retained_file(str(module))) != digest:
                raise ValueError("Installed package or shipped assets differ from current product")
        if not required <= set(bound) or any(sha(p) != digest for p, digest in bound.items()):
            raise ValueError("Installed launcher or dependency hash mismatch")
    return cell, manifest_path


def artifact_report(path, current):
    data = read_json(path)
    producer = Path(__file__).with_name("artifact.py")
    if data.get("producer") != "verify-twinaatma.artifact/v1":
        raise ValueError("Unsupported artifact producer")
    if not producer.is_file() or data.get("producer_sha256") != sha(producer):
        raise ValueError("Artifact producer hash missing or stale")
    check_product(data, "product_hashes", current)
    for field in ("source_bound", "product_unchanged", "artifact_unchanged"):
        if data.get(field) is not True:
            raise ValueError("Artifact binding or stability is not substantiated: " + field)
    installation, artifact = data.get("installation", {}), data.get("artifact", {})
    observed_platform = str(installation.get("platform", ""))
    platform = next((name for name in ("Windows", "Linux") if observed_platform.startswith(name + "-")), None)
    cell = (platform, artifact.get("kind"))
    if cell not in ARTIFACT_MATRIX:
        raise ValueError("Unsupported artifact release matrix cell")
    transcripts = data.get("transcript_files")
    if not isinstance(transcripts, dict) or not transcripts:
        raise ValueError("Artifact report needs hashed transcripts")
    for name, digest in transcripts.items():
        if sha(file_evidence(path.parent, name)) != digest:
            raise ValueError("Artifact transcript hash mismatch: " + name)
    rows = checked_rows(data.get("cases"), allowed=ARTIFACT_IDS)
    for row in rows.values():
        if row["verdict"] == "PASS" and (not row.get("expected") or not row.get("evidence")):
            raise ValueError("Artifact PASS needs expected result and retained evidence")
        if any(name not in transcripts for name in row.get("evidence", [])):
            raise ValueError("Unhashed artifact evidence")
    processes = data.get("processes")
    if (data.get("all_started_processes_stopped") is not True or not isinstance(processes, list)
            or not processes or any(p.get("stopped") is not True for p in processes)):
        raise ValueError("Artifact process shutdown is not substantiated")
    isolation = data.get("isolation", {})
    if not isolation.get("before") or isolation.get("before") != isolation.get("after") or isolation.get("unchanged") is not True:
        raise ValueError("Artifact isolation absent or changed")
    cell, manifest_path = checked_artifact_binding(data, path, current, transcripts)
    return {"path": str(path), "report_sha256": sha(path), "scope": "artifact",
            "producer": data["producer"], "producer_sha256": sha(producer), "cell": list(cell),
            "build_manifest": {"path": str(manifest_path), "sha256": sha(manifest_path)},
            "transcript_files": transcripts, "checks": rows}


def checked_runtime_location(observed, installed, platform):
    environment = retained_path(installed.get("environment"))
    def recorded(value):
        text = value.replace("\\", "/").rstrip("/")
        return text.casefold() if platform == "Windows" else text
    if (recorded(observed["prefix"]) != recorded(installed["environment"])
            or recorded(observed["origin"]) != recorded(installed["import_origin"])
            or not retained_path(observed.get("prefix")).samefile(environment)
            or not retained_path(observed.get("origin")).samefile(retained_path(installed.get("import_origin")))):
        raise ValueError("Runtime hook identity does not name its retained installation")
    suffix = "Scripts/python.exe" if platform == "Windows" else "bin/python"
    expected = observed["prefix"].replace("\\", "/").rstrip("/") + "/" + suffix
    executable = observed.get("executable", "")
    # A standard POSIX venv links its interpreter to the system installation.
    # Bind its lexical location to the retained venv, without banning that link.
    if (not executable or executable != installed.get("python")
            or executable.replace("\\", "/") != expected or not (environment / suffix).is_file()):
        raise ValueError("Runtime hook interpreter is not the recorded venv executable")


def runtime_hook_report(path, current):
    data = read_json(path)
    producer = Path(__file__).with_name("runtime_hooks.py")
    if data.get("producer") != "verify-twinaatma.runtime-hooks/v1" or data.get("producer_sha256") != sha(producer):
        raise ValueError("Runtime hook producer missing or stale")
    if data.get("support_sha256") != {"artifact.py": sha(Path(__file__).with_name("artifact.py"))}:
        raise ValueError("Runtime hook support producer missing or stale")
    check_product(data, "product_hashes", current)
    if any(data.get(key) is not True for key in ("source_bound", "product_unchanged", "artifact_unchanged")):
        raise ValueError("Runtime hook artifact or product binding changed")
    transcripts = data.get("transcript_files")
    if not isinstance(transcripts, dict) or not transcripts:
        raise ValueError("Runtime hook needs hashed command transcripts")
    for name, digest in transcripts.items():
        if sha(file_evidence(path.parent, name)) != digest:
            raise ValueError("Runtime hook transcript hash mismatch: " + name)
    rows = checked_rows(data.get("cases"), allowed=HOOK_IDS, host=True)
    if any(name not in transcripts for row in rows.values() for name in row.get("evidence", [])):
        raise ValueError("Runtime hook evidence was not hashed")
    processes = data.get("processes")
    if (data.get("all_started_processes_stopped") is not True or not isinstance(processes, list)
            or not processes or any(p.get("stopped") is not True for p in processes)):
        raise ValueError("Runtime hook shutdown not substantiated")
    isolation = data.get("isolation", {})
    if not isolation.get("before") or isolation.get("before") != isolation.get("after") or isolation.get("unchanged") is not True:
        raise ValueError("Runtime hook isolation absent or changed")
    artifact_cell, manifest = checked_artifact_binding(data, path, current, transcripts)
    runtime = data.get("runtime", {})
    if runtime.get("platform") != artifact_cell[0] or runtime.get("kind") != artifact_cell[1]:
        raise ValueError("Runtime hook platform or artifact kind mismatch")
    minor = "embedded"
    if artifact_cell[1] == "wheel":
        observed = read_json(file_evidence(path.parent, "runtime-identity.stdout.txt"))
        if observed != runtime.get("identity"):
            raise ValueError("Runtime hook identity differs from actual interpreter output")
        version = observed.get("version_info")
        if (not isinstance(version, list) or len(version) != 3 or any(type(v) is not int for v in version)
                or observed.get("implementation") != "CPython" or observed.get("prefix") == observed.get("base_prefix")):
            raise ValueError("Runtime hook requires actual isolated CPython identity")
        minor = ".".join(map(str, version[:2]))
        if runtime.get("major_minor") != minor:
            raise ValueError("Runtime hook declared minor differs from actual interpreter")
        installed = data["installation"]
        checked_runtime_location(observed, installed, artifact_cell[0])
        identity_command = read_json(file_evidence(path.parent, "runtime-identity.command.json"))
        command = identity_command.get("command")
        if (not isinstance(command, list) or command[:3] != [observed["executable"], "-I", "-c"]
                or identity_command.get("exit_code") != 0 or identity_command.get("shell") is not False):
            raise ValueError("Runtime hook identity was not observed through its isolated interpreter")
    elif runtime.get("embedded") is not True:
        raise ValueError("Frozen hook must declare its manifest-bound embedded runtime")
    cell = (*artifact_cell, minor)
    if cell not in RUNTIME_MATRIX:
        raise ValueError("Unsupported runtime hook matrix cell")
    generated = data.get("generated_config", {})
    config_path = file_evidence(path.parent, "generated-hooks.json")
    if sha(config_path) != generated.get("sha256") or "generated-hooks.json" not in transcripts:
        raise ValueError("Generated hook configuration hash missing or changed")
    config = read_json(config_path)
    commands = generated.get("commands", {})
    for event, label in (("sessionStart", "session-start"), ("sessionEnd", "session-end")):
        entries = config.get("hooks", {}).get(event)
        if (not isinstance(entries, list) or len(entries) != 1 or
                entries[0].get("command") != commands.get(event)):
            raise ValueError("Generated hook command mismatch")
        record = read_json(file_evidence(path.parent, label + ".command.json"))
        if (record.get("command") != commands[event] or record.get("shell") is not True
                or record.get("exit_code") != 0 or not record.get("stdin")
                or retained_path(record.get("cwd")) != retained_path(data["installation"].get("vault"))
                or record.get("environment", {}).get("PATH") != ""
                or not record.get("environment", {}).get("PYTHONPATH")):
            raise ValueError("Generated hook was not exercised literally in the hostile unactivated fixture")
    return {"path": str(path), "report_sha256": sha(path), "scope": "artifact", "cell": list(cell),
            "producer": data["producer"], "producer_sha256": sha(producer),
            "build_manifest": {"path": str(manifest), "sha256": sha(manifest)},
            "transcript_files": transcripts, "checks": rows}


def runtime_hook_matrix(reports):
    cells = [tuple(report["cell"]) for report in reports]
    if len(cells) != len(set(cells)):
        raise ValueError("Duplicate runtime hook matrix cell")
    complete = set(cells) == RUNTIME_MATRIX
    usable = complete and all(HOOK_IDS <= report["checks"].keys() and
                              all(row["verdict"] == "PASS" for row in report["checks"].values()) for report in reports)
    rows = [{"id": "hook.runtime_matrix_complete", "verdict": "PASS" if complete else "NOT CHECKED",
             "observed": {"cells": sorted([list(cell) for cell in cells]), "required": len(RUNTIME_MATRIX)}},
            {"id": "hook.runtime_matrix_usable", "verdict": "PASS" if usable else "FAIL" if complete else "NOT CHECKED",
             "observed": {"complete": complete, "usable": usable}}]
    return {"path": "generated-hook-runtime-matrix", "report_sha256": hashlib.sha256(json.dumps(reports, sort_keys=True).encode()).hexdigest(),
            "scope": "artifact", "producer": ADAPTER_REQUIREMENTS["version"], "checks": checked_rows(rows)}


def artifact_matrix(reports):
    cells = [tuple(r["cell"]) for r in reports]
    if len(cells) != len(set(cells)):
        raise ValueError("Duplicate artifact release matrix cell")
    complete = set(cells) == ARTIFACT_MATRIX
    required = ARTIFACT_IDS - {"artifact.isolated_import", "artifact.execution"}
    usable = complete and all(required <= r["checks"].keys() and all(c["verdict"] == "PASS" for c in r["checks"].values())
                              and (r["cell"][1] != "wheel" or r["checks"].get("artifact.isolated_import", {}).get("verdict") == "PASS") for r in reports)
    rows = [{"id": "artifact.release_matrix_complete", "verdict": "PASS" if complete else "NOT CHECKED", "observed": sorted([list(c) for c in cells])},
            {"id": "artifact.isolated_install_usable", "verdict": "PASS" if usable else "FAIL" if complete else "NOT CHECKED", "observed": {"complete": complete, "usable": usable}}]
    return {"path": "artifact-release-matrix", "report_sha256": hashlib.sha256(json.dumps(reports, sort_keys=True).encode()).hexdigest(),
            "scope": "artifact", "producer": ADAPTER_REQUIREMENTS["version"], "checks": checked_rows(rows)}


def data_toolkit_hashes():
    paths = []
    for relative in ("knowledgeos", "scripts", "Templates", ".cursor/hooks"):
        paths.extend(path for path in (ROOT / relative).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"))
    paths.extend(ROOT / name for name in ("AGENTS.md", "README.md", "pyproject.toml", "setup.py", "MANIFEST.in",
                                        "LICENSE", "knowledgeos.config.example.json", "mcp.cursor.example.json"))
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(set(paths))}


def data_evidence(directory, name):
    if (not isinstance(name, str) or not name or name in (".", "..")
            or Path(name).name != name or "/" in name or "\\" in name or ":" in name):
        raise ValueError("Data evidence must name a contained retained file")
    path = file_evidence(directory, name)
    for component in (path, *path.parents):
        info = component.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))):
            raise ValueError("Data evidence may not traverse linked or reparse components")
    if path.stat().st_nlink != 1:
        raise ValueError("Data evidence may not be hardlinked")
    return path


def data_repository_location(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing data observation location")
    normalized = value.replace("\\", "/").rstrip("/")
    for root in (ROOT.as_posix().rstrip("/"), "W:/AI-Projects/TwinAatma", "/mnt/w/AI-Projects/TwinAatma"):
        if normalized == root:
            return ""
        if normalized.startswith(root + "/"):
            relative = normalized[len(root) + 1:]
            if any(part in (".", "..", "") for part in relative.split("/")):
                break
            return relative
    raise ValueError("Data observation location is outside the retained repository")


def maintenance_roles(spec):
    roles = {}
    for identifier in spec["cases"]:
        name = identifier.split(".", 2)[2]
        label = spec["journey"] + "-" + name
        if spec["journey"] == "validation":
            roles[label + "-cli"] = ("validate", identifier)
            roles[label + "-script"] = ("validate_script", identifier)
        elif spec["journey"] == "hooks":
            roles[label] = ("hook_script", identifier)
            roles[label + "-git-init"] = ("git_init", identifier)
            if name in ("custom", "external", "linked_directory"):
                roles[label + "-git-config"] = ("git_config", identifier)
            if name == "custom":
                roles[label + "-repeat"] = ("hook_script", identifier)
                roles[label + "-run"] = ("git_run", identifier)
            if name == "linked_directory":
                roles[label + "-junction"] = ("junction", identifier)
        elif name.startswith("ids_"):
            roles[label] = ("ids", identifier)
            if name == "ids_linked_directory":
                roles[label + "-junction"] = ("junction", identifier)
        elif name.startswith("links_"):
            roles[label] = ("links", identifier)
        else:
            roles[label] = ("maps", identifier)
            roles[label + "-index"] = ("index", identifier)
            if name == "maps_write":
                roles[label + "-repeat"] = ("maps", identifier)
            if name == "maps_replace_fault":
                roles[label + "-initial"] = ("maps", identifier)
                roles[label + "-changed-index"] = ("index", identifier)
    return roles


def maintenance_operation(record, kind, identifier):
    command, vault = record["command"], record["cwd"]
    if (len(command) != 4 or command[1:3] != ["-B", "-c"]
            or not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", command[0].replace("\\", "/").rsplit("/", 1)[-1])):
        raise ValueError("Maintenance command is not the known Python invocation")
    try:
        tree = ast.parse(command[3])
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        if kind in ("ids", "validate"):
            expected = (["validate", "--vault", vault] if kind == "validate" else
                        ["ids", "assign", "--vault", vault] + ([] if identifier.endswith(".ids_dry_run") else ["--write"]))
            actual = [ast.literal_eval(node.args[0]) for node in calls
                      if isinstance(node.func, ast.Name) and node.func.id == "main" and len(node.args) == 1]
            imported = any(isinstance(node, ast.ImportFrom) and node.module == "knowledgeos.__main__"
                           and any(alias.name == "main" for alias in node.names) for node in ast.walk(tree))
            valid = imported and actual == [expected]
        elif kind == "index":
            actual = [ast.literal_eval(node.args[0]) for node in calls
                      if isinstance(node.func, ast.Name) and node.func.id == "rebuild_index" and len(node.args) == 1]
            imported = any(isinstance(node, ast.ImportFrom) and node.module == "knowledgeos.indexer"
                           and any(alias.name == "rebuild_index" for alias in node.names) for node in ast.walk(tree))
            valid = imported and actual == ["."]
        else:
            script = {"links": "refactor_links.py", "maps": "update_mocs.py", "hook_script": "setup_git_hooks.py",
                      "validate_script": "validate_schema.py"}[kind]
            actual = [(ast.literal_eval(node.args[0]), {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords})
                      for node in calls if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                      and node.func.value.id == "runpy" and node.func.attr == "run_path" and len(node.args) == 1]
            valid = actual == [("scripts/" + script, {"run_name": "__main__"})]
            if kind == "validate_script":
                arguments = [ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                             and any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                                     and target.value.id == "sys" and target.attr == "argv" for target in node.targets)]
                valid = valid and arguments == [["validate_schema.py", "--vault", vault]]
    except (ValueError, TypeError, KeyError, SyntaxError, IndexError) as error:
        raise ValueError("Maintenance command does not retain its known public operation") from error
    if not valid:
        raise ValueError("Maintenance command does not retain its known public operation and fixture arguments")


def maintenance_nested(data, directory, evidence, rows, records, spec):
    if (data.get("nested_process_tracking_complete") is not True or not isinstance(data.get("nested_processes"), list)
            or not isinstance(data.get("nested_expectations"), list)):
        raise ValueError("Maintenance nested shutdown tracking is missing or incomplete")
    identifiers = set()
    for child in data["nested_processes"]:
        if (not isinstance(child, dict) or not isinstance(child.get("id"), str) or not child["id"] or child["id"] in identifiers
                or type(child.get("pid")) is not int or child["pid"] <= 0 or type(child.get("parent_pid")) is not int
                or child.get("stopped") is not True or type(child.get("exit_code")) is not int):
            raise ValueError("Maintenance nested report lacks unique IDs, typed PIDs or final stopped status")
        identifiers.add(child["id"])
    if any(not isinstance(expectation, dict) or expectation.get("complete") is not True for expectation in data["nested_expectations"]):
        raise ValueError("Maintenance nested script expectation is incomplete")
    definitions = maintenance_roles(spec)
    nested, expectations, traced_roles, interpreters = [], [], set(), set()
    for role, record in records.items():
        if role == "revision":
            continue
        if role not in definitions:
            raise ValueError("Unknown maintenance process role")
        kind, identifier = definitions[role]
        command, vault = record["command"], record["cwd"]
        name = identifier.split(".", 2)[2]
        if kind.startswith("git_"):
            location = ".custom-hooks" if name == "custom" else ".linked-hooks" if name == "linked_directory" else vault.rsplit("\\" if "\\" in vault else "/", 1)[0] + ("\\" if "\\" in vault else "/") + "outside"
            expected = {"git_init": ["git", "init", "--quiet", vault],
                        "git_config": ["git", "-C", vault, "config", "core.hooksPath", location],
                        "git_run": ["git", "-C", vault, "hook", "run", "pre-commit"]}[kind]
            if command != expected:
                raise ValueError("Maintenance Git command differs from the known fixture operation")
            continue
        if kind == "junction":
            if not str(data["platform"]).startswith("Windows"):
                raise ValueError("Maintenance junction record is not a Windows observation")
            slash = "\\" if "\\" in vault else "/"
            linked = "LinkedNotes" if spec["journey"] == "maintenance" else ".linked-hooks"
            if record["vault"] is not None or command != ["cmd", "/c", "mklink", "/J", vault + slash + "vault" + slash + linked, vault + slash + "outside"]:
                raise ValueError("Maintenance junction command differs from its known fixture")
            continue
        maintenance_operation(record, kind, identifier)
        interpreters.add(command[0])
        traced_roles.add(role)
        stderr_name, trace_name = role + ".stderr.txt", role + ".nested.json"
        if trace_name not in evidence:
            raise ValueError("Maintenance nested trace file is missing")
        stderr = data_evidence(directory, stderr_name).read_text(encoding="utf-8")
        markers = [line[len("MAINTENANCE_CHILDREN="):] for line in stderr.splitlines() if line.startswith("MAINTENANCE_CHILDREN=")]
        try:
            trace = json.loads(markers[0]) if len(markers) == 1 else None
        except ValueError as error:
            raise ValueError("Maintenance nested stderr trace is malformed") from error
        if (not isinstance(trace, dict) or set(trace) != {"parent_pid", "children"}
                or type(trace["parent_pid"]) is not int or trace["parent_pid"] != record["pid"]
                or not isinstance(trace["children"], list)):
            raise ValueError("Maintenance nested stderr trace lacks its actual parent PID or child list")
        retained = read_json(data_evidence(directory, trace_name))
        if (not isinstance(retained, dict) or retained.get("complete") is not True
                or retained != {"trace": trace, "complete": True}):
            raise ValueError("Maintenance nested retained trace disagrees with parent stderr")
        expected_scripts = (["experiment_dashboard.py"] if role == "maintenance-maps_edited" else
                            ["experiment_dashboard.py", "outcomes_dashboard.py"]) if kind == "maps" else []
        child_commands = [[command[0], vault + ("\\" if "\\" in vault else "/") + "scripts" +
                           ("\\" if "\\" in vault else "/") + script] for script in expected_scripts]
        if kind == "hook_script":
            child_commands = [["git", "-C", vault, "rev-parse", "--path-format=absolute", "--git-path", "hooks"]]
        if len(trace["children"]) != len(child_commands):
            raise ValueError("Maintenance nested child command inventory is incomplete")
        child_pids = set()
        for index, child in enumerate(trace["children"]):
            expected_exit = 1 if role == "maintenance-maps_edited" else 0
            if (not isinstance(child, dict) or set(child) != {"pid", "argv", "stopped", "exit_code"}
                    or type(child.get("pid")) is not int or child["pid"] <= 0 or child["pid"] == record["pid"]
                    or child["pid"] in child_pids or child.get("stopped") is not True
                    or type(child.get("exit_code")) is not int or child["exit_code"] != expected_exit
                    or child.get("argv") != child_commands[index]):
                raise ValueError("Maintenance nested child lacks known argv, unique PID or substantiated final exit")
            child_pids.add(child["pid"])
            nested.append(dict(child, id=role + "-nested-" + str(index), parent_role=role, parent_pid=record["pid"],
                               evidence=stderr_name, evidence_sha256=evidence[stderr_name]))
        if kind == "maps":
            expectations.append({"parent_role": role, "expected_scripts": expected_scripts,
                                 "observed_scripts": expected_scripts, "complete": True})
    if len(interpreters) != 1:
        raise ValueError("Maintenance commands do not bind one source interpreter")
    if {name for name in evidence if name.endswith(".nested.json")} != {role + ".nested.json" for role in traced_roles}:
        raise ValueError("Maintenance nested evidence contains untracked or missing parent traces")
    if (data["nested_processes"] != nested or data["nested_expectations"] != expectations):
        raise ValueError("Maintenance nested process or expectation records differ from retained parent traces")
    for identifier, row in rows.items():
        if row["verdict"] not in ("PASS", "FAIL"):
            continue
        required = {role for role, (kind, case) in definitions.items() if case == identifier
                    and (kind != "junction" or str(data["platform"]).startswith("Windows"))}
        if not required <= records.keys():
            raise ValueError("Maintenance case is missing a required owned command")
        main = (identifier.replace("data.", "", 1).replace(".", "-", 1) + "-cli"
                if spec["journey"] == "validation" else identifier.replace("data.", "", 1).replace(".", "-", 1))
        referenced = [main, main[:-len("-cli")] + "-script"] if spec["journey"] == "validation" else [main]
        if any(role + ".command.json" not in row["evidence"] for role in referenced):
            raise ValueError("Maintenance case does not reference its actual public commands")
    return {"nested_launch_records": len(nested), "nested_tracking_substantiated": True}


def data_report(path, current):
    if ".." in Path(path).parts:
        raise ValueError("Data report may not traverse lexical parent components")
    path = Path(path).absolute()
    relative = path.parent.relative_to(ROOT.absolute())
    if relative.parts[:2] != ("work", "gc-artifacts") or ".knowledgeos" not in relative.parts[2:]:
        raise ValueError("Data report must remain in a contained synthetic evidence directory")
    data_evidence(path.parent, path.name)
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Data report must contain an executable producer object")
    spec = ALL_DATA_PRODUCERS.get(data.get("producer"))
    if spec is None:
        raise ValueError("Unsupported data producer; manual claims cannot award acceptance")
    producer = Path(__file__).with_name(spec["file"])
    if data.get("producer_sha256") != sha(producer):
        raise ValueError("Data producer hash missing or stale")
    support = {name: sha(Path(__file__).with_name(name)) for name in spec["support"]}
    if data.get("support_sha256", {}) != support:
        raise ValueError("Data support producer hash missing or stale")
    check_product(data, "product_hashes", current)
    toolkit = data_toolkit_hashes()
    if data.get("product_hashes") != toolkit or data.get("product_hashes_after") != toolkit:
        raise ValueError("Data complete copied-toolkit input inventory is missing or stale")
    if data.get("product_and_producer_unchanged") is not True:
        raise ValueError("Data product or producer changed during observation")
    if (not str(data.get("scope", "")).startswith("source-only ") or not data.get("platform") or not data.get("python")
            or data.get("verdict") not in STATUSES):
        raise ValueError("Data report lacks an actual source-only execution identity")
    evidence = data.get("evidence_files")
    if not isinstance(evidence, dict) or not evidence or path.name in evidence:
        raise ValueError("Data report needs independently hashed retained evidence")
    for name, digest in evidence.items():
        if sha(data_evidence(path.parent, name)) != digest:
            raise ValueError("Data evidence hash mismatch: " + str(name))
    cases = data.get("cases")
    if spec["file"] == "maintenance.py" and isinstance(cases, list):
        cases = [dict(row, verdict="NOT CHECKED", reported_verdict="NOT APPLICABLE")
                 if isinstance(row, dict) and row.get("id") == "data.hooks.chmod_fault"
                 and row.get("verdict") == "NOT APPLICABLE" and str(data["platform"]).startswith("Windows") else row for row in cases]
    rows = checked_rows(cases, allowed=spec["cases"])
    for row in rows.values():
        references = row.get("evidence")
        if (not isinstance(row.get("expected"), str) or not row["expected"].strip()
                or not isinstance(references, list) or any(not isinstance(name, str) or name not in evidence for name in references)
                or (row["verdict"] in ("PASS", "FAIL") and not references)):
            raise ValueError("Data check requires expected result and hashed retained evidence")
        if row["verdict"] in ("PASS", "FAIL") and not any(name.endswith(".command.json") for name in references):
            raise ValueError("Data check lacks an actual retained command record")
    processes = data.get("processes")
    if (data.get("all_started_processes_stopped") is not True or not isinstance(processes, list) or not processes):
        raise ValueError("Data process shutdown is not substantiated")
    roles, records = set(), {}
    for process in processes:
        if (not isinstance(process, dict) or type(process.get("pid")) is not int or process["pid"] <= 0
                or not isinstance(process.get("role"), str) or not process["role"] or process["role"] in roles
                or process.get("stopped") is not True or type(process.get("exit_code")) is not int):
            raise ValueError("Data process shutdown lacks owned PID, unique role or final exit status")
        role = process["role"]
        roles.add(role)
        names = [role + suffix for suffix in (".command.json", ".stdout.txt", ".stderr.txt")]
        if any(name not in evidence for name in names):
            raise ValueError("Data process lacks hashed command and output records")
        record = read_json(data_evidence(path.parent, names[0]))
        if not isinstance(record, dict):
            raise ValueError("Data command record is not an observation object")
        records[role] = record
        command = record.get("command")
        if (record.get("pid") != process["pid"] or record.get("exit_code") != process["exit_code"]
                or record.get("stopped") is not True or record.get("shell") is not False
                or not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command)
                or not isinstance(record.get("seconds"), (int, float)) or record["seconds"] < 0
                or "error" not in record or record["error"] is not None):
            raise ValueError("Data process command observation disagrees with its owned shutdown record")
        if data_repository_location(record.get("state_dir")) != relative.as_posix() + "/gate-state":
            raise ValueError("Data process did not use the retained isolated state location")
        cwd = data_repository_location(record.get("cwd"))
        if role == "revision":
            if cwd or record.get("vault") is not None or command != ["git", "rev-parse", "HEAD"]:
                raise ValueError("Data revision command differs from the known producer")
        elif spec["file"] == "maintenance.py" and role.endswith("-junction"):
            if not cwd.startswith(relative.as_posix() + "/fixtures/") or record.get("vault") is not None:
                raise ValueError("Maintenance junction does not target its synthetic fixture")
        elif (not cwd.startswith(relative.as_posix() + "/fixtures/") or not cwd.endswith("/vault")
              or data_repository_location(record.get("vault")) != cwd):
            raise ValueError("Data command does not target its retained synthetic vault")
    if {name for name in evidence if name.endswith(".command.json")} != {role + ".command.json" for role in roles}:
        raise ValueError("Data command evidence contains untracked owned processes")
    nested = maintenance_nested(data, path.parent, evidence, rows, records, spec) if spec["file"] == "maintenance.py" else {}
    isolation = data.get("isolation", {})
    before, after = isolation.get("before"), isolation.get("after")
    if (not isinstance(before, dict) or not before or before != after
            or isolation.get("selected_sentinels_unchanged") is not True
            or {data_repository_location(name) for name in before} != {"People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json"}
            or any(value is not None and (not isinstance(value, str) or len(value) != 64
                   or any(character not in "0123456789abcdef" for character in value)) for value in before.values())):
        raise ValueError("Data selected real-vault isolation sentinels absent or changed")
    if spec["file"] == "memory_census.py":
        if data.get("toolkit_copy_evidence") != "toolkit-copy.before.json":
            raise ValueError("Data census requires pre-probe copied-toolkit evidence")
        copies = [data["toolkit_copy_evidence"]]
    else:
        prefix, filename_prefix = DATA_COPY_PREFIXES[spec.get("journey", spec["file"])]
        copies = []
        for identifier, row in rows.items():
            if row["verdict"] in ("PASS", "FAIL"):
                name = filename_prefix + identifier[len(prefix):] + ".before.json"
                if name not in row["evidence"]:
                    raise ValueError("Data copied-toolkit inventory was not referenced by its actual case")
                copies.append(name)
    for name in copies:
        if name not in evidence:
            raise ValueError("Data copied-toolkit inventory is not hashed")
        copied = read_json(data_evidence(path.parent, name))
        if not isinstance(copied, dict):
            raise ValueError("Data copied-toolkit inventory is not an observation object")
        if any(not isinstance(copied.get("vault/" + member), dict)
               or copied["vault/" + member].get("kind") != "file"
               or copied["vault/" + member].get("links") != 1
               or copied["vault/" + member].get("sha256") != digest for member, digest in toolkit.items()):
            raise ValueError("Data copied-toolkit bytes do not match exact current input inventory")
    statuses = {row["verdict"] for row in rows.values()}
    complete = spec["cases"] <= rows.keys()
    verdict = ("FAIL" if "FAIL" in statuses or data.get("error") is not None or (complete and data["verdict"] == "FAIL")
               else "BLOCKED" if "BLOCKED" in statuses or data["verdict"] == "BLOCKED"
               else "PASS" if complete and statuses == {"PASS"} and data["verdict"] == "PASS"
               else "NOT CHECKED")
    aggregate = {"id": spec["aggregate"], "verdict": verdict, "expected": "Every fixed producer case passes with complete current source and retained observations",
                 "observed": {"present": len(rows), "required": len(spec["cases"]), "complete": complete, "producer_verdict": data["verdict"]},
                 "evidence": list(evidence)}
    return {"path": str(path), "report_sha256": sha(path), "scope": "source", "producer": data["producer"],
            "producer_sha256": sha(producer), "support_sha256": support, "evidence_files": evidence,
            "checks": {**rows, spec["aggregate"]: aggregate}, **nested}


def observed_source_report(path, current, filename, producers, scope):
    if ".." in Path(path).parts:
        raise ValueError("Observation report may not traverse lexical parent components")
    path = Path(path).absolute()
    relative = path.parent.relative_to(ROOT.absolute())
    if relative.parts[:2] != ("work", "gc-artifacts") or ".knowledgeos" not in relative.parts[2:]:
        raise ValueError("Observation report must remain in contained synthetic evidence")
    data_evidence(path.parent, path.name)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("producer") not in producers:
        raise ValueError("Unsupported observation producer")
    producer = Path(__file__).with_name(filename)
    support = {"data_preservation.py": sha(Path(__file__).with_name("data_preservation.py"))}
    if data.get("producer_sha256") != sha(producer) or data.get("support_sha256") != support:
        raise ValueError("Observation producer or support hash is stale")
    check_product(data, "product_hashes", current)
    toolkit = data_toolkit_hashes()
    if (data.get("product_hashes") != toolkit or data.get("product_hashes_after") != toolkit
            or data.get("product_and_producer_unchanged") is not True):
        raise ValueError("Observation complete toolkit inventory is stale or changed")
    if (not str(data.get("scope", "")).startswith(scope) or not data.get("platform") or not data.get("python")
            or data.get("verdict") not in STATUSES or data.get("error") is not None):
        raise ValueError("Observation lacks completed scoped execution identity")
    evidence = data.get("evidence_files")
    if not isinstance(evidence, dict) or not evidence or path.name in evidence:
        raise ValueError("Observation needs retained hashed evidence")
    for name, digest in evidence.items():
        if sha(data_evidence(path.parent, name)) != digest:
            raise ValueError("Observation evidence hash mismatch: " + name)
    processes = data.get("processes")
    if data.get("all_started_processes_stopped") is not True or not isinstance(processes, list) or not processes:
        raise ValueError("Observation process shutdown is incomplete")
    records = {}
    for process in processes:
        if (not isinstance(process, dict) or type(process.get("pid")) is not int or process["pid"] <= 0
                or not isinstance(process.get("role"), str) or not process["role"] or process["role"] in records
                or process.get("stopped") is not True or type(process.get("exit_code")) is not int):
            raise ValueError("Observation needs typed owned PIDs, unique roles and final shutdown")
        role = process["role"]
        names = [role + suffix for suffix in (".command.json", ".stdout.txt", ".stderr.txt")]
        if any(name not in evidence for name in names):
            raise ValueError("Observation process lacks retained command or output")
        record = read_json(data_evidence(path.parent, names[0]))
        if (not isinstance(record, dict) or type(record.get("pid")) is not int or record["pid"] != process["pid"]
                or type(record.get("exit_code")) is not int or record["exit_code"] != process["exit_code"]
                or record["exit_code"] != 0 or record.get("stopped") is not True or record.get("shell") is not False
                or record.get("error", "missing") is not None or type(record.get("seconds")) not in (int, float)
                or not 0 <= record["seconds"] < float("inf")
                or not isinstance(record.get("command"), list) or not record["command"]
                or any(not isinstance(part, str) or not part for part in record["command"])):
            raise ValueError("Observation command lacks matching PID, successful final exit or literal argv")
        records[role] = record
    if {name for name in evidence if name.endswith(".command.json")} != {role + ".command.json" for role in records}:
        raise ValueError("Observation contains missing or untracked command records")
    revision = records.get("revision", {})
    if (revision.get("command") != ["git", "rev-parse", "HEAD"] or revision.get("vault") is not None
            or data_repository_location(revision.get("cwd")) != ""
            or data_repository_location(revision.get("state_dir")) != relative.as_posix() + "/gate-state"
            or not re.fullmatch(r"[0-9a-f]{40}", str(data.get("revision", "")))
            or data_evidence(path.parent, "revision.stdout.txt").read_text(encoding="utf-8").strip() != data["revision"]):
        raise ValueError("Observation revision does not bind its actual command")
    isolation = data.get("isolation", {})
    before, after = isolation.get("before"), isolation.get("after")
    if (not isinstance(before, dict) or not before or before != after or isolation.get("selected_sentinels_unchanged") is not True
            or {data_repository_location(name) for name in before} != {"People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json"}
            or any(value is not None and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None) for value in before.values())):
        raise ValueError("Observation selected isolation sentinels are missing or changed")
    return path, data, toolkit, evidence, records


def observed_json(directory, evidence, name):
    if name not in evidence:
        raise ValueError("Observation lacks hashed retained evidence: " + name)
    return read_json(data_evidence(directory, name))


def observed_fixture_file(directory, relative):
    if (not isinstance(relative, str) or "\\" in relative or ":" in relative
            or any(part in ("", ".", "..") for part in relative.split("/")) or not relative.startswith("fixtures/")):
        raise ValueError("Observation fixture file escapes its known fixture")
    path = directory / relative
    data_evidence(path.parent, path.name)
    return path


def observed_inventory(directory, evidence, name, expected, prefix=""):
    inventory = observed_json(directory, evidence, name)
    if not isinstance(inventory, dict):
        raise ValueError("Observation inventory is not a complete object")
    for member, digest in expected.items():
        row = inventory.get(prefix + member)
        if (not isinstance(row, dict) or row.get("kind") != "file" or type(row.get("links")) is not int
                or row["links"] != 1 or row.get("sha256") != digest):
            raise ValueError("Observation inventory has missing, linked or changed input bytes")
    return inventory


def observed_command(record, directory, fixture, operation, *, quality=False):
    base = directory.relative_to(ROOT.absolute()).as_posix()
    scope = base + "/fixtures/" + fixture
    vault = scope + "/vault"
    command = record["command"]
    if (not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", command[0].replace("\\", "/").rsplit("/", 1)[-1])
            or command[1:5] != ["-B", "-P", "-m", "knowledgeos"]
            or data_repository_location(record.get("vault")) != vault
            or data_repository_location(record.get("cwd")) != (base if quality else scope)
            or data_repository_location(record.get("state_dir")) != scope + "/gate-state"):
        raise ValueError("Observation command does not bind its real interpreter, fixture vault and isolated state")
    tail = command[5:]
    if operation == "init":
        valid = len(tail) == 5 and tail[0] == "init" and data_repository_location(tail[1]) == vault and tail[2:] == ["--name", "Synthetic Unknown A47", "--non-interactive"]
    else:
        valid = (len(tail) == (5 if operation == "mcp" else 3) and tail[:2] == [operation, "--vault"]
                 and data_repository_location(tail[2]) == vault and (operation != "mcp" or tail[3:] == ["--framing", "ndjson"]))
    if not valid:
        raise ValueError("Observation argv differs from its known public operation")
    if not quality or operation == "mcp":
        if data_repository_location(record.get("pythonpath" if quality else "import_path")) != (vault if quality else scope + "/toolkit"):
            raise ValueError("Observation import path does not bind the complete copied toolkit")


def observed_rpc(directory, evidence, role, calls, *, identity=False):
    requests = observed_json(directory, evidence, role + ".requests.json")
    client = {"name": "verify-twinaatma-identity" if identity else "verify-twinaatma", "version": "1"}
    expected = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": client}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    expected += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                 for index, (name, arguments) in enumerate(calls, 2)]
    if requests != expected:
        raise ValueError("Observation MCP requests do not retain the literal expected tools and arguments")
    try:
        responses = [json.loads(line) for line in data_evidence(directory, role + ".stdout.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
        by_id = {response["id"]: response for response in responses}
        if (len(responses) != len(calls) + 1 or len(by_id) != len(responses) or set(by_id) != set(range(1, len(calls) + 2))
                or any(type(response["id"]) is not int or response.get("jsonrpc") != "2.0" for response in responses)
                or by_id[1].get("result", {}).get("serverInfo", {}).get("name") != "knowledgeos-memory"):
            raise ValueError("Observation MCP response inventory or server identity differs")
        results = []
        for index in range(2, len(calls) + 2):
            result = by_id[index]["result"]
            content = result["content"]
            if (type(result.get("isError")) is not bool or not isinstance(content, list) or len(content) != 1
                    or content[0].get("type") != "text"):
                raise ValueError("Observation MCP response content shape differs")
            payload = json.loads(content[0]["text"])
            if not isinstance(payload, dict):
                raise ValueError("Observation MCP payload is not an object")
            results.append({"payload": payload, "is_error": result["isError"]})
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Observation MCP stdout is not the retained actual response sequence") from error
    if identity and observed_json(directory, evidence, role + ".results.json") != results:
        raise ValueError("Observation parsed results disagree with actual MCP stdout")
    return results


def identity_sections(kind):
    return {name: (("<!-- kos:section=" + name + " -->\n") if kind == "marked" else "") + value
            for name, value in IDENTITY_CONTENTS.items()}


def identity_read_result(result, kind, *, session=False, duplicate=False):
    payload = result["payload"]
    if duplicate:
        message = payload.get("error")
        return result["is_error"] is True and isinstance(message, str) and "duplicate" in message.lower() and "kos:section=values" in message
    if session:
        payload = payload.get("context", {}).get("self")
    if result["is_error"] or not isinstance(payload, dict) or payload.get("path") != "People/Self.md":
        return False
    sections = payload.get("sections")
    if kind != "cold":
        return sections == identity_sections(kind)
    if not isinstance(sections, dict) or set(sections) != set(IDENTITY_SECTIONS):
        return False
    pattern = (r"<!-- kos:section=drift_log -->\n\| Topic \| Shift Observed \| Date Flagged \| Evidence \|\n"
               r"\|---\|---\|---\|---\|\n\| — \| Vault initialized \| \d{4}-\d{2}-\d{2} \| init \|")
    return (all(sections[key] == "<!-- kos:section=" + key + " -->\n" + value for key, value in IDENTITY_UNKNOWNS.items())
            and re.fullmatch(pattern, sections["drift_log"]) is not None)


def identity_report(path, current):
    path, data, toolkit, evidence, records = observed_source_report(path, current, "identity.py", IDENTITY_PRODUCERS, "source-only CLI initialization")
    directory = path.parent
    spec = IDENTITY_PRODUCERS[data["producer"]]
    identifiers = ["identity." + spec["journey"] + "." + name for name in spec["cases"]]
    rows = checked_rows(data.get("cases"), allowed=set(identifiers))
    if list(rows) != identifiers or data.get("expected_case_ids") != identifiers:
        raise ValueError("Identity needs its exact complete literal case registry")
    expected_roles = {"revision"}
    fixtures, preservations = {}, []
    for kind in spec["fixtures"]:
        before = observed_inventory(directory, evidence, kind + ".before.json", toolkit, "toolkit/")
        after = observed_inventory(directory, evidence, kind + ".after.json", toolkit, "toolkit/")
        old_toolkit = observed_inventory(directory, evidence, kind + ".toolkit-before.json", toolkit)
        new_toolkit = observed_inventory(directory, evidence, kind + ".toolkit-after.json", toolkit)
        self_path = observed_fixture_file(directory, "fixtures/" + kind + "/vault/People/Self.md")
        self_key = "vault/People/Self.md"
        original, retained = before.get(self_key), after.get(self_key)
        if (not isinstance(original, dict) or original.get("kind") != "file" or original.get("links") != 1
                or original != retained or sha(self_path) != original.get("sha256")):
            raise ValueError("Identity synthetic Self bytes are missing or changed")
        note_filter = lambda inventory: {name: value for name, value in inventory.items()
            if name.endswith(".md") and not name.startswith("vault/People/Self-Proposals/")}
        proposals = {name.removeprefix("vault/People/Self-Proposals/"): value for name, value in after.items()
                     if name.startswith("vault/People/Self-Proposals/")}
        prior = {name.removeprefix("vault/People/Self-Proposals/"): value for name, value in before.items()
                 if name.startswith("vault/People/Self-Proposals/")}
        preserved = (old_toolkit == new_toolkit and note_filter(before) == note_filter(after)
                     and all(proposals.get(name) == value for name, value in prior.items())
                     and (not proposals if kind in ("cold", "duplicate") else len(proposals) == 6))
        if not preserved:
            raise ValueError("Identity note, proposal or complete toolkit preservation differs")
        fixtures[kind] = {"before": before, "after": after, "self_sha256": original["sha256"], "proposals": proposals}
        preservations.append({"kind": kind, "self_before_sha256": original["sha256"], "self_after_sha256": retained["sha256"],
            "toolkit_matches_product": True, "toolkit_unchanged": True, "all_other_note_bytes_unchanged": True,
            "prior_proposals_unchanged": True, "proposal_inventory": proposals})
        for operation in ("init", "doctor"):
            role = kind + "-" + operation
            expected_roles.add(role)
            if role not in records:
                raise ValueError("Identity initialization or readiness command is missing")
            observed_command(records[role], directory, kind, operation)
        initialized = read_json(data_evidence(directory, kind + "-init.stdout.txt"))
        post = initialized.get("post_init", {})
        if (initialized.get("ok") is not True or initialized.get("owner") != "Synthetic Unknown A47"
                or not {"rebuild", "validate"} <= set(post) or not all(isinstance(value, dict) and value.get("ok") is True for value in post.values())):
            raise ValueError("Identity fresh name-only initialization did not succeed")
    for name in spec["cases"]:
        row = rows["identity." + spec["journey"] + "." + name]
        references = row.get("evidence")
        if (not isinstance(row.get("expected"), str) or not row["expected"].strip() or not isinstance(references, list)
                or not references or any(reference not in evidence for reference in references) or not isinstance(row["observed"], dict)):
            raise ValueError("Identity case lacks literal expectations, observations or hashed evidence")
        observed = row["observed"]
        if name == "identity_preserved":
            if observed != {"fixtures": preservations}:
                raise ValueError("Identity preservation observations differ from actual inventories")
            continue
        if name == "cold_init":
            if (observed.get("initialized") != read_json(data_evidence(directory, "cold-init.stdout.txt"))
                    or observed.get("cli_exit_code") != 0 or observed.get("doctor_exit_code") != 0
                    or observed.get("only_supplied_identity_attribute") != "name" or observed.get("ready") is not True
                    or not {"cold-init.command.json", "cold-doctor.command.json", "cold.before.json"} <= set(references)):
                raise ValueError("Identity cold-init observation disagrees with real initialization")
            continue
        kind = "cold" if spec["journey"] == "unknown" else name.split("_", 1)[0]
        role = spec["journey"] + "-" + name
        expected_roles.add(role)
        if role not in records:
            raise ValueError("Identity case lacks its actual public command")
        observed_command(records[role], directory, kind, "mcp")
        required = [role + suffix for suffix in (".command.json", ".requests.json", ".stdout.txt", ".stderr.txt", ".results.json")]
        if not set(required) <= set(references):
            raise ValueError("Identity case is not bound to its command and actual protocol trace")
        duplicate = kind == "duplicate"
        if name.endswith("proposal") or name.endswith("proposals"):
            keys = ("values",) if duplicate else IDENTITY_SECTIONS
            patches = {key: "- Synthetic addition PX41 for " + key + ". Compare retained evidence before revising this test preference." for key in keys}
            calls = [("memory_propose_self_update", {"summary": "Synthetic canonical target " + key, "section": key,
                "proposed_markdown": patches[key], "rationale": "Synthetic source identity acceptance only.", "mode": "append"}) for key in keys]
            results = observed_rpc(directory, evidence, role, calls, identity=True)
            targets = observed_json(directory, evidence, role + ".proposal-observations.json")
            if not isinstance(targets, list) or len(targets) != len(keys) or observed.get("targets") != targets:
                raise ValueError("Identity proposals lack their exact retained target observations")
            valid = True
            for key, result, target in zip(keys, results, targets):
                if duplicate:
                    valid = valid and identity_read_result(result, kind, duplicate=True) and target.get("payload") == result["payload"] and target.get("proposal_evidence_unchanged") is True
                    continue
                payload = result["payload"]
                relative = payload.get("proposal_path")
                if not isinstance(relative, str) or not re.fullmatch(r"People/Self-Proposals/[^/\\:]+\.md", relative):
                    raise ValueError("Identity proposal path is not a contained plain draft")
                proposal = observed_fixture_file(directory, "fixtures/" + kind + "/vault/" + relative)
                raw = proposal.read_text(encoding="utf-8")
                digest = hashlib.sha256("\n".join(line.rstrip() for line in identity_sections(kind)[key].splitlines() if line.strip()).encode()).hexdigest()[:16]
                frontmatter = raw.split("---\n", 2)[1] if raw.startswith("---\n") and raw.count("---\n") >= 2 else ""
                metadata = ("proposal_section: " + key, "proposal_target: People/Self.md", "proposal_mode: append",
                            "proposal_origin: memory_propose_self_update", "proposal_base_hash: " + digest, "status: draft")
                inventory = fixtures[kind]["proposals"].get(relative.removeprefix("People/Self-Proposals/"), {})
                valid = (valid and result["is_error"] is False and payload.get("ok") is True and payload.get("policy") == "proposal_only"
                    and payload.get("section") == key and payload.get("base_digest") == digest and payload.get("mutated_self") is False
                    and all(frontmatter.splitlines().count(line) == 1 for line in metadata)
                    and "```markdown\n" + patches[key] + "\n```" in raw and inventory.get("kind") == "file" and inventory.get("links") == 1
                    and sha(proposal) == inventory.get("sha256") == target.get("proposal_sha256")
                    and target.get("proposal_text") == raw and target.get("result") == result and target.get("expected_base_digest") == digest)
            before = observed_json(directory, evidence, role + ".before.json")
            after = observed_json(directory, evidence, role + ".after.json")
            valid = valid and before.get("vault/People/Self.md") == after.get("vault/People/Self.md") == fixtures[kind]["before"]["vault/People/Self.md"]
            if duplicate:
                valid = valid and before == after
        else:
            session = name.endswith("session_start")
            arguments = {"task_hint": "What owner-confirmed preferences, ranked values, mental models, anti-goals and live bets do you know?",
                         "session_id": spec["journey"] + "-" + kind + "-section-proof"} if session else {}
            result = observed_rpc(directory, evidence, role, [("memory_session_start" if session else "memory_self_get", arguments)], identity=True)[0]
            if observed.get("public_result", result) != result:
                raise ValueError("Identity observed payload differs from its actual MCP response")
            valid = identity_read_result(result, kind, session=session, duplicate=duplicate)
            if session and not duplicate:
                valid = valid and result["payload"].get("session_id") == arguments["session_id"]
            subject = result["payload"].get("context", {}).get("self") if session and not duplicate else result["payload"]
            valid = valid and observed.get("payload") == subject and observed.get("is_error") == result["is_error"]
        if observed.get("self_bytes_unchanged") is not True or (row["verdict"] == "PASS" and not valid):
            raise ValueError("Identity PASS disagrees with literal section, unknown, proposal or duplicate-marker evidence")
    if set(records) != expected_roles or len({record["command"][0] for role, record in records.items() if role != "revision"}) != 1:
        raise ValueError("Identity has missing or unexpected public process roles or interpreters")
    statuses = {row["verdict"] for row in rows.values()}
    verdict = "FAIL" if "FAIL" in statuses or data["verdict"] == "FAIL" else "BLOCKED" if "BLOCKED" in statuses else "PASS" if statuses == {"PASS"} and data["verdict"] == "PASS" else "NOT CHECKED"
    aggregate = {"id": "identity." + spec["journey"] + ".complete", "verdict": verdict,
                 "expected": "Complete current public identity journey with literal source and protocol observations",
                 "observed": {"cases": len(rows), "required": len(identifiers), "complete": True}, "evidence": list(evidence)}
    return observed_result(path, data, evidence, {**rows, aggregate["id"]: aggregate}, "source")


def quality_corpus():
    path = ROOT / QUALITY_CORPUS
    if sha(path) != QUALITY_CORPUS_SHA256:
        raise ValueError("Quality frozen corpus hash changed")
    corpus = read_json(path)
    if (corpus.get("schema_version") != "twinaatma.quality-corpus/v1" or corpus.get("corpus_id") != "quality-v1-20261019"
            or corpus.get("frozen_before_product_observation") is not True or corpus.get("labels_observed_from_product") is not False
            or not isinstance(corpus.get("label_provenance"), str) or not corpus["label_provenance"].strip()
            or corpus.get("synthetic_subject", {}).get("all_people_and_projects_are_fictional") is not True
            or corpus["synthetic_subject"].get("real_person_data") is not False):
        raise ValueError("Quality corpus lacks pre-observation synthetic label provenance")
    contract = corpus.get("evaluation_contract", {})
    required = {"fixed_rubric_id": "twinaatma-ideal-v1", "fixed_outcome_count": 54, "source_top_k": 8,
                "critical_expected_source_target": 1, "noncritical_expected_source_target": 0.9}
    if any(contract.get(name) != value or isinstance(contract.get(name), bool) for name, value in required.items()):
        raise ValueError("Quality corpus changed the fixed acceptance targets")
    policy = contract.get("capture_policy", {})
    if policy.get("status") != "UNAPPROVED" or policy.get("release_acceptance") != "BLOCKED":
        raise ValueError("Quality corpus cannot approve a privacy policy")
    notes, cases, splits = corpus.get("notes"), corpus.get("cases"), corpus.get("splits")
    if (not isinstance(notes, list) or len(notes) != 38 or not isinstance(cases, list)
            or [case.get("id") for case in cases] != list(QUALITY_CASE_IDS)
            or splits != {"development": list(QUALITY_CASE_IDS[:24]), "held_out": list(QUALITY_CASE_IDS[24:])}):
        raise ValueError("Quality corpus lost its complete notes, cases or authored split inventory")
    by_path, expected = {}, {}
    for note in notes:
        name, content = note.get("path"), note.get("content")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_ /-]+\.md", name)
                or name in by_path or name.casefold() in {key.casefold() for key in by_path}
                or any(part in ("", ".", "..") for part in name.split("/"))
                or not isinstance(content, str) or not content.endswith("\n") or "\r" in content or "\x00" in content
                or note.get("role") not in ("relevant", "distractor")):
            raise ValueError("Quality corpus note path, literal bytes or distractor role is invalid")
        by_path[name] = note
        raw = content.encode("utf-8")
        expected[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "role": note["role"]}
    categories, totals = set(), {split: Counter() for split in QUALITY_SPLITS}
    for case in cases:
        split = "development" if case["id"] in QUALITY_CASE_IDS[:24] else "held_out"
        if (case.get("split") != split or type(case.get("critical")) is not bool
                or any(not isinstance(case.get(name), str) or not case[name].strip() for name in ("task_hint", "question", "conversation_input"))
                or not isinstance(case.get("categories"), list) or not case["categories"]
                or not isinstance(case.get("expected_answer"), dict) or not case["expected_answer"].get("mode")
                or not isinstance(case.get("disallowed_claims"), list) or not case["disallowed_claims"]
                or not isinstance(case.get("expected_capture"), dict) or not case["expected_capture"].get("decision")
                or not isinstance(case.get("expected_sources"), list)):
            raise ValueError("Quality corpus case has missing pre-authored labels")
        categories.update(case["categories"])
        totals[split]["cases"] += 1
        totals[split]["empty_source_cases"] += int(not case["expected_sources"])
        seen = set()
        for source in case["expected_sources"]:
            name = source.get("path")
            if name not in by_path or name in seen or type(source.get("critical")) is not bool or not source.get("claims"):
                raise ValueError("Quality corpus expected-source labels are missing or duplicate")
            seen.add(name)
            claim_ids = set()
            for claim in source["claims"]:
                if (not isinstance(claim.get("id"), str) or not claim["id"] or claim["id"] in claim_ids
                        or any(not isinstance(claim.get(key), str) or not claim[key].strip() for key in ("text", "quote", "temporal_status"))
                        or claim["quote"] not in by_path[name]["content"]):
                    raise ValueError("Quality corpus claim lacks its literal source quote or temporal label")
                claim_ids.add(claim["id"])
            totals[split]["critical_sources" if source["critical"] else "noncritical_sources"] += 1
            if source["critical"]:
                totals[split]["critical_claims"] += len(source["claims"])
    diverse = {"natural_hint", "paraphrase", "contextual_preference", "changed_fact", "multilingual", "ambiguous_names",
               "irrelevant_chatter", "unknown", "unsupported_personal_question"}
    roles = dict(Counter(note["role"] for note in notes))
    if not diverse <= categories or roles != {"relevant": 26, "distractor": 12}:
        raise ValueError("Quality corpus lacks required diversity and distractors")
    summary = {"cases": len(cases), "notes": len(notes), "roles": roles, "categories": sorted(categories),
               "splits": {key: dict(value) for key, value in totals.items()}}
    return corpus, expected, summary


def quality_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, dict)):
        for member in (value.values() if isinstance(value, dict) else value):
            yield from quality_strings(member)


def quality_source_rows(value, path):
    if isinstance(value, dict):
        if value.get("path") == path:
            yield value
        for member in value.values():
            yield from quality_source_rows(member, path)
    elif isinstance(value, list):
        for member in value:
            yield from quality_source_rows(member, path)


def quality_case(case, payload):
    context = payload.get("context") if isinstance(payload, dict) else None
    if (not isinstance(context, dict) or payload.get("error") or context.get("task_hint") != case["task_hint"]
            or not isinstance(payload.get("session_id"), str) or not payload["session_id"]):
        raise ValueError("Quality startup payload lacks the literal hint or genuine session ID")
    relevant = context.get("relevant")
    if not isinstance(relevant, dict) or not isinstance(relevant.get("ranked"), list):
        raise ValueError("Quality startup payload lacks ranked context")
    ranked = relevant["ranked"][:8]
    if any(not isinstance(row, dict) or not isinstance(row.get("path"), str) or not row["path"].strip() for row in ranked):
        raise ValueError("Quality ranked context has a malformed source")
    paths = [row["path"] for row in ranked]
    if len(paths) != len(set(paths)):
        raise ValueError("Quality first eight notes contain duplicate paths")
    sources = []
    for source in case["expected_sources"]:
        found = source["path"] in paths
        fragments = [value for row in quality_source_rows(context, source["path"]) for value in quality_strings(row)] if found else []
        claims = [{"id": claim["id"], "quote": claim["quote"],
                   "available_in_source_context": any(claim["quote"] in value for value in fragments)} for claim in source["claims"]]
        sources.append({"path": source["path"], "critical": source["critical"], "rank": paths.index(source["path"]) + 1 if found else None,
                        "in_first_eight": found, "claims": claims})
    complete = all(source["in_first_eight"] and (not source["critical"] or all(claim["available_in_source_context"] for claim in source["claims"])) for source in sources)
    return {"id": case["id"], "split": case["split"], "categories": case["categories"], "task_hint": case["task_hint"],
            "verdict": ("PASS" if complete else "FAIL") if sources else "NOT APPLICABLE",
            "ranked_paths": paths, "returned_notes": len(paths), "sources": sources, "empty_source_case": not sources,
            "expected_answer_mode": case["expected_answer"]["mode"], "host_answer_verdict": "NOT CHECKED", "capture_verdict": "NOT CHECKED",
            "labeled_source_precision": {"numerator": sum(source["in_first_eight"] for source in sources), "denominator": len(paths),
                "ratio": sum(source["in_first_eight"] for source in sources) / len(paths) if paths else None}}


def quality_metrics(rows):
    result = {}
    for split in (*QUALITY_SPLITS, "combined"):
        selected = [row for row in rows if split == "combined" or row["split"] == split]
        sources = [source for row in selected for source in row["sources"]]
        count = {"cases": len(selected), "source_cases": sum(not row["empty_source_case"] for row in selected),
                 "empty_source_cases": sum(row["empty_source_case"] for row in selected), "case_verdicts": dict(Counter(row["verdict"] for row in selected))}
        for critical, name in ((True, "critical_sources"), (False, "noncritical_sources")):
            members = [source for source in sources if source["critical"] is critical]
            numerator = sum(source["in_first_eight"] for source in members)
            count[name] = {"numerator": numerator, "denominator": len(members), "ratio": numerator / len(members) if members else None}
        claims = [claim for source in sources if source["critical"] for claim in source["claims"]]
        count["critical_claims"] = {"numerator": sum(claim["available_in_source_context"] for claim in claims), "denominator": len(claims)}
        numerator = sum(row["labeled_source_precision"]["numerator"] for row in selected if not row["empty_source_case"])
        denominator = sum(row["returned_notes"] for row in selected if not row["empty_source_case"])
        count["labeled_source_precision"] = {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if denominator else None, "limitation": "Expected-source labels are not exhaustive semantic relevance labels"}
        critical, noncritical = count["critical_sources"], count["noncritical_sources"]
        count["retrieval_target_met"] = (bool(selected) and critical["denominator"] > 0 and critical["numerator"] == critical["denominator"]
            and count["critical_claims"]["denominator"] > 0 and count["critical_claims"]["numerator"] == count["critical_claims"]["denominator"]
            and noncritical["denominator"] > 0 and noncritical["numerator"] * 10 >= noncritical["denominator"] * 9)
        result[split] = count
    return result


def quality_report(path, current):
    path, data, toolkit, evidence, records = observed_source_report(path, current, "quality.py", (QUALITY_PRODUCER,), "evaluation source-only startup MCP retrieval")
    directory = path.parent
    corpus, expected_notes, summary = quality_corpus()
    manifest = observed_json(directory, evidence, "run-manifest.json")
    for field in ("producer", "producer_sha256", "support_sha256", "product_hashes", "corpus_path", "corpus_sha256", "corpus_summary"):
        if data.get(field) != manifest.get(field):
            raise ValueError("Quality freeze manifest disagrees with actual report binding")
    try:
        frozen_at = datetime.datetime.fromisoformat(manifest["frozen_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Quality freeze manifest lacks an actual timestamp") from error
    if (manifest.get("frozen_before_first_product_invocation") is not True or frozen_at.tzinfo is None
            or data.get("corpus_path") != QUALITY_CORPUS or data.get("corpus_sha256") != QUALITY_CORPUS_SHA256
            or data.get("corpus_summary") != summary or manifest.get("complete_note_inventory") != expected_notes
            or manifest.get("case_registry") != list(QUALITY_CASE_IDS) or not isinstance(manifest.get("held_out_status"), str)
            or not manifest["held_out_status"].startswith("Process held out;") or data.get("execution_complete") is not True
            or manifest.get("capture_policy_status") != "UNAPPROVED" or data.get("capture_policy_status") != "UNAPPROVED"):
        raise ValueError("Quality run lacks its complete pre-observation frozen corpus and policy separation")
    cases = data.get("cases")
    if not isinstance(cases, list) or [row.get("id") for row in cases] != list(QUALITY_CASE_IDS):
        raise ValueError("Quality run lacks its exact complete 36-case registry")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, dict) or set(fixtures) != set(QUALITY_CASE_IDS):
        raise ValueError("Quality freeze manifest lacks all independent fixtures")
    expected_roles, computed, binding_checks, sessions = {"revision"}, [], [], set()
    for case, row in zip(corpus["cases"], cases):
        label = case["id"]
        references = [label + suffix for suffix in (".before.json", ".after.json", ".notes.before.json", ".notes.after.json",
            "-doctor.command.json", "-doctor.stdout.txt", "-doctor.stderr.txt", "-startup.requests.json", "-startup.command.json",
            "-startup.stdout.txt", "-startup.stderr.txt", ".context.json")]
        if (not isinstance(row.get("expected"), str) or not row["expected"].strip() or row.get("evidence") != references
                or any(name not in evidence for name in references)):
            raise ValueError("Quality case is missing literal expectations or actual retained evidence")
        location = directory.relative_to(ROOT.absolute()).as_posix() + "/fixtures/" + label + "/vault"
        if data_repository_location(fixtures[label]) != location:
            raise ValueError("Quality manifest fixture location does not match its independent case")
        before = observed_inventory(directory, evidence, label + ".before.json", toolkit)
        after = observed_inventory(directory, evidence, label + ".after.json", toolkit)
        for inventory in (before, after):
            allowed_notes = set(expected_notes) | {"People/Self.md"} | {name for name in toolkit if name.endswith(".md")}
            if {name for name in inventory if name.endswith(".md")} != allowed_notes:
                raise ValueError("Quality complete note census contains missing or unlabelled fixture notes")
            for name, expected in expected_notes.items():
                note = inventory.get(name, {})
                if note != {"kind": "file", "links": 1, "size": expected["size"], "sha256": expected["sha256"]}:
                    raise ValueError("Quality complete frozen notes or distractor inventory changed")
            if inventory.get("People/Self.md", {}).get("sha256") != QUALITY_SELF_SHA256:
                raise ValueError("Quality synthetic identity bytes changed")
        for name, expected in expected_notes.items():
            note = observed_fixture_file(directory, "fixtures/" + label + "/vault/" + name)
            if sha(note) != expected["sha256"] or note.stat().st_size != expected["size"]:
                raise ValueError("Quality actual retained note or distractor bytes changed")
        identity = observed_fixture_file(directory, "fixtures/" + label + "/vault/People/Self.md")
        if sha(identity) != QUALITY_SELF_SHA256:
            raise ValueError("Quality actual synthetic identity bytes changed")
        if (observed_json(directory, evidence, label + ".notes.before.json") != expected_notes
                or observed_json(directory, evidence, label + ".notes.after.json") != expected_notes):
            raise ValueError("Quality complete note inventory labels disagree with retained evidence")
        for suffix, operation in (("-doctor", "doctor"), ("-startup", "mcp")):
            role = label + suffix
            expected_roles.add(role)
            if role not in records:
                raise ValueError("Quality public startup or readiness command is missing")
            observed_command(records[role], directory, label, operation, quality=True)
        result = observed_rpc(directory, evidence, label + "-startup", [("memory_session_start", {"task_hint": case["task_hint"]})])[0]
        if result["is_error"] or observed_json(directory, evidence, label + ".context.json") != result["payload"]:
            raise ValueError("Quality retained context differs from its actual startup MCP response")
        derived = quality_case(case, result["payload"])
        if any(row.get(key) != value for key, value in derived.items()):
            raise ValueError("Quality case labels, ranks, claims or verdict disagree with actual startup context")
        session = result["payload"]["session_id"]
        if session in sessions:
            raise ValueError("Quality cases did not use independent fresh sessions")
        sessions.add(session)
        expected_observed = {"complete_inventory_preserved": True, "literal_hint_used": True, "session_id": session, "fresh_process_and_vault": True}
        if row.get("observed") != expected_observed:
            raise ValueError("Quality literal observation disagrees with actual fixture and context")
        computed.append(derived)
        binding_checks.append({"id": label, "copied_product_unchanged": True, "all_frozen_notes_unchanged": True, "synthetic_self_unchanged": True})
    if (set(records) != expected_roles or data.get("binding_checks") != binding_checks
            or len({record["command"][0] for role, record in records.items() if role != "revision"}) != 1):
        raise ValueError("Quality has missing or unexpected process, interpreter or fixture bindings")
    metrics = quality_metrics(computed)
    if data.get("metrics") != metrics:
        raise ValueError("Quality totals and split counts differ from actual context observations")
    checks = checked_rows(data.get("checks"), allowed={"quality.fixed_corpus", "quality.retrieval_target"})
    if any(not isinstance(row.get("expected"), str) or not row["expected"].strip() for row in checks.values()):
        raise ValueError("Quality aggregate lacks literal expected results")
    retrieval = all(metrics[split]["retrieval_target_met"] for split in (*QUALITY_SPLITS, "combined"))
    fixed, target = checks.get("quality.fixed_corpus", {}), checks.get("quality.retrieval_target", {})
    if (set(checks) != {"quality.fixed_corpus", "quality.retrieval_target"} or fixed.get("verdict") != "PASS"
            or fixed.get("observed") != summary or fixed.get("evidence") != ["run-manifest.json"]
            or target.get("verdict") != ("PASS" if retrieval else "FAIL") or target.get("observed") != metrics
            or target.get("evidence") != [label + ".context.json" for label in QUALITY_CASE_IDS]
            or data["verdict"] != ("PASS" if retrieval else "FAIL")):
        raise ValueError("Quality aggregate verdict is not the independently measured corpus and retrieval result")
    return observed_result(path, data, evidence, checks, "evaluation")


def observed_result(path, data, evidence, checks, scope):
    return {"path": str(path), "report_sha256": sha(path), "scope": scope, "producer": data["producer"],
            "producer_sha256": data["producer_sha256"], "support_sha256": data["support_sha256"],
            "evidence_files": evidence, "checks": checks}


GRAPH_CASES = {
    'markdown_local': ('Projects/A/LocalSource.md', ['Projects/A/Target.md'], 1),
    'markdown_parent': ('Projects/A/Sub/ParentSource.md', ['Projects/A/ParentTarget.md'], 1),
    'markdown_root': ('Projects/A/RootSource.md', ['Target.md'], 1),
    'wikilink_path': ('Projects/A/ExplicitSource.md', ['Projects/B/ExplicitTarget.md'], 1),
    'wikilink_alias_anchor': ('Projects/A/AliasSource.md', ['Projects/B/AnchorTarget.md'], 1),
    'markdown_encoded_anchor': ('Projects/A/EncodedSource.md', ['Concepts/Space Name.md'], 1),
    'unique_basename': ('Projects/A/UniqueSource.md', ['Concepts/UniqueDestination.md'], 1),
    'ambiguous_basename': ('Projects/A/AmbiguousSource.md', [], 1),
    'missing_target': ('Projects/A/MissingSource.md', [], 1),
    'fenced_examples': ('Projects/A/FencedSource.md', ['Concepts/ActualExampleTarget.md'], 1),
    'incoming_links': ('Concepts/IncomingTarget.md', ['Projects/A/IncomingSource.md'], 1),
    'two_hop': ('Concepts/ChainSeed.md', ['Concepts/ChainLeaf.md', 'Concepts/ChainMiddle.md'], 2),
}
GRAPH_IDS = tuple('memory.graph.' + name for name in ('fixture_init', *GRAPH_CASES, 'source_edit_refresh', 'target_move_refresh', 'source_preserved'))
RECOVERY_INDEX = ('missing_index', 'corrupt_index', 'busy_sqlite', 'busy_rebuild', 'blocked_rebuild', 'blocked_manifest')
RECOVERY_KINDS = ('index', 'gate', 'sessions')
RECOVERY_LOCKS = tuple(kind + '_' + scenario for kind in RECOVERY_KINDS for scenario in (
    'live_old_owner', 'dead_owner', 'replacement_marker', 'blocked_marker', 'blocked_guard'))
RECOVERY_FAULTS = tuple(kind + '_partial_marker_write' for kind in RECOVERY_KINDS)
RECOVERY_SPECS = {
    'verify-twinaatma.recovery-index/v1': ('index', RECOVERY_INDEX, 'recovery.index.complete'),
    'verify-twinaatma.recovery-locks/v1': ('locks', RECOVERY_LOCKS, 'recovery.locks.complete'),
    'verify-twinaatma.recovery-write-faults/v1': ('write-faults', RECOVERY_FAULTS, 'recovery.write-faults.complete'),
}
ADAPTER_REQUIREMENTS['version'] = 'verify-twinaatma.adapters/v6'
ADAPTER_REQUIREMENTS['launch_identity'] = 'Unique launch role bound to its hashed stopped command and typed positive PID; sequential OS PID reuse allowed; concurrently live roles remain distinct'
ADAPTER_REQUIREMENTS['outcomes'].update({'MEMORY.correct_links': ['memory.graph.complete'],
    'RECOVERY.index_degradation': ['recovery.index.complete'],
    'RECOVERY.ownership_locks': ['recovery.locks.complete', 'recovery.write-faults.complete']})
ADAPTER_REQUIREMENTS['graph_producer'] = {'producer': 'verify-twinaatma.graph/v1', 'file': 'graph.py',
    'support': ['data_preservation.py', 'identity.py'], 'cases': list(GRAPH_IDS)}
ADAPTER_REQUIREMENTS['recovery_producers'] = {producer: {'file': 'recovery.py', 'support': ['data_preservation.py'],
    'cases': ['recovery.' + journey + '.' + name for name in cases], 'aggregate': aggregate}
    for producer, (journey, cases, aggregate) in RECOVERY_SPECS.items()}


def producer_literal(filename, name):
    tree = ast.parse(Path(__file__).with_name(filename).read_text(encoding='utf-8'))
    rows = [node.value for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    if len(rows) != 1:
        raise ValueError('Known producer literal is absent or duplicated: ' + name)
    return ast.literal_eval(rows[0])


def retained_observation(directory, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Graph/recovery evidence must be a contained lexical file')
    return data_evidence((directory / name).parent, Path(name).name)


def proof_json(directory, evidence, name):
    if name not in evidence:
        raise ValueError('Graph/recovery lacks hashed retained evidence: ' + name)
    return read_json(retained_observation(directory, name))


def require_distinct_live_processes(records, first, second):
    """PIDs can recur after exit, but two simultaneously live roles cannot share one."""
    pids = [records[role].get('pid') for role in (first, second)]
    if any(type(pid) is not int or pid <= 0 for pid in pids) or pids[0] == pids[1]:
        raise ValueError('Simultaneously live roles require distinct typed owned PIDs')


def graph_recovery_source(path, current, *, graph=False):
    if '..' in Path(path).parts:
        raise ValueError('Graph/recovery report traverses parent components')
    path = Path(path).absolute()
    relative = path.parent.relative_to(ROOT.absolute())
    if relative.parts[:2] != ('work', 'gc-artifacts') or '.knowledgeos' not in relative.parts[2:]:
        raise ValueError('Graph/recovery report leaves contained synthetic evidence')
    data_evidence(path.parent, path.name)
    data = read_json(path)
    producers = ('verify-twinaatma.graph/v1',) if graph else RECOVERY_SPECS
    filename = 'graph.py' if graph else 'recovery.py'
    support_names = ('data_preservation.py', 'identity.py') if graph else ('data_preservation.py',)
    support = {name: sha(Path(__file__).with_name(name)) for name in support_names}
    support_field = 'support_sha256' if graph else 'support_producer_hashes'
    toolkit = data_toolkit_hashes()
    if (not isinstance(data, dict) or data.get('producer') not in producers
            or data.get('producer_sha256') != sha(Path(__file__).with_name(filename))
            or data.get(support_field) != support
            or not graph and data.get('support_producer_hashes_after') != support):
        raise ValueError('Graph/recovery producer or support is unsupported or stale')
    check_product(data, 'product_hashes', current)
    if (data.get('product_hashes') != toolkit or data.get('product_hashes_after') != toolkit
            or data.get('product_and_producer_unchanged') is not True or data_repository_location(data.get('source_root')) != ''):
        raise ValueError('Graph/recovery complete current toolkit is stale or changed')
    prefix = 'source-only public CLI initialization and persistent public MCP graph' if graph else 'source CLI/MCP with complete copied toolkit'
    if (not str(data.get('scope', '')).startswith(prefix) or not data.get('platform') or not data.get('python')
            or data.get('verdict') not in ('PASS', 'FAIL') or data.get('error') is not None
            or data.get('ideal_system_verdict') != 'NOT CHECKED' or data.get('acceptance_credit_awarded') is not False):
        raise ValueError('Graph/recovery execution identity is incomplete')
    evidence = data.get('evidence_files')
    if not isinstance(evidence, dict) or not evidence or path.name in evidence:
        raise ValueError('Graph/recovery retained evidence is missing')
    for name, digest in evidence.items():
        if sha(retained_observation(path.parent, name)) != digest:
            raise ValueError('Graph/recovery retained evidence hash differs: ' + name)
    processes = data.get('processes')
    if data.get('all_started_processes_stopped') is not True or not isinstance(processes, list) or not processes:
        raise ValueError('Graph/recovery shutdown is incomplete')
    records = {}
    for process in processes:
        if (not isinstance(process, dict) or type(process.get('pid')) is not int or process['pid'] <= 0
                or not isinstance(process.get('role'), str) or not process['role'] or process['role'] in records
                or process.get('stopped') is not True or type(process.get('exit_code')) is not int):
            raise ValueError('Graph/recovery requires typed owned PIDs and unique stopped launch roles')
        role = process['role']
        record = proof_json(path.parent, evidence, role + '.command.json')
        if any(role + suffix not in evidence for suffix in ('.stdout.txt', '.stderr.txt')):
            raise ValueError('Graph/recovery command outputs are missing')
        if (record.get('pid') != process['pid'] or type(record.get('pid')) is not int
                or type(record.get('exit_code')) is not int or record['exit_code'] != process['exit_code']
                or record.get('stopped') is not True or record.get('shell') is not False
                or record.get('error', None if role.endswith('-holder') else 'missing') is not None or not isinstance(record.get('command'), list) or not record['command']
                or any(not isinstance(part, str) or not part for part in record['command'])):
            raise ValueError('Graph/recovery command is not its recorded stopped literal process')
        if not role.endswith('-holder') and (type(record.get('seconds')) not in (int, float) or not 0 <= record['seconds'] < float('inf')):
            raise ValueError('Graph/recovery command timing is invalid')
        records[role] = record
    if {name for name in evidence if name.endswith('.command.json')} != {name + '.command.json' for name in records}:
        raise ValueError('Graph/recovery contains untracked or missing commands')
    revision = records.get('revision', {})
    if (revision.get('command') != ['git', 'rev-parse', 'HEAD'] or revision.get('exit_code') != 0
            or revision.get('vault') is not None or data_repository_location(revision.get('cwd')) != ''
            or data_repository_location(revision.get('state_dir')) != relative.as_posix() + '/gate-state'
            or not re.fullmatch(r'[0-9a-f]{40}', str(data.get('revision', '')))
            or retained_observation(path.parent, 'revision.stdout.txt').read_text(encoding='utf-8').strip() != data['revision']):
        raise ValueError('Graph/recovery revision command is not bound')
    isolation = data.get('isolation', {})
    before, after = isolation.get('before'), isolation.get('after')
    if (not isinstance(before, dict) or not before or before != after or isolation.get('selected_sentinels_unchanged') is not True
            or {data_repository_location(name) for name in before} != {'People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json'}
            or any(value is not None and (not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)) for value in before.values())):
        raise ValueError('Graph/recovery isolation sentinels changed or are incomplete')
    return path, data, toolkit, evidence, records


def proof_inventory(directory, evidence, name):
    result = proof_json(directory, evidence, name)
    if not isinstance(result, dict) or not result:
        raise ValueError('Graph/recovery source inventory is empty')
    for relative, row in result.items():
        if (not isinstance(relative, str) or '\\' in relative or ':' in relative
                or any(part in ('', '.', '..') for part in relative.split('/')) or not isinstance(row, dict)
                or row.get('kind') not in ('file', 'directory')):
            raise ValueError('Graph/recovery source inventory contains unsafe or unknown entries')
        if row['kind'] == 'file' and (type(row.get('links')) is not int or row['links'] != 1
                or type(row.get('size')) is not int or row['size'] < 0
                or row.get('sha256') is not None and not re.fullmatch(r'[0-9a-f]{64}', str(row['sha256']))):
            raise ValueError('Graph/recovery source inventory has invalid file metadata')
        if row['kind'] == 'file' and row.get('sha256') is None:
            cache = relative in {'vault/knowledge_index.db' + suffix for suffix in ('', '-wal', '-shm', '-journal')}
            guard = relative in ('vault/.knowledgeos/index-rebuild.lock.guard', 'vault/.knowledgeos/sessions.lock.guard')
            guard = guard or bool(re.fullmatch(r'gate-state/vaults/[0-9a-f]+/self-gate.lock.guard', relative))
            if not (cache or guard) or not row.get('observation_error') or not row.get('limitation'):
                raise ValueError('Only native locked derived cache/guard bytes may be unreadable')
    return result


def physical_file(directory, relative, row):
    path = retained_observation(directory, relative)
    if (not isinstance(row, dict) or row.get('kind') != 'file' or row.get('links') != 1
            or row.get('size') != path.stat().st_size or row.get('sha256') != sha(path)):
        raise ValueError('Graph/recovery physical source bytes differ from retained inventory: ' + relative)


def copied_toolkit(directory, evidence, fixture, toolkit, *, after=True):
    before = proof_inventory(directory, evidence, fixture + '.toolkit-before.json')
    actual = {name: row.get('sha256') for name, row in before.items() if row['kind'] == 'file'}
    if actual != toolkit:
        raise ValueError('Graph/recovery copied toolkit omits or changes current input bytes')
    if after and proof_inventory(directory, evidence, fixture + '.toolkit-after.json') != before:
        raise ValueError('Recovery toolkit before and after inventories differ')
    target = directory / 'fixtures' / fixture / 'toolkit'
    actual_names = set()
    def visit(parent):
        for entry in os.scandir(parent):
            member = Path(entry.path)
            info = member.lstat()
            if (stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
                raise ValueError('Graph/recovery copied toolkit contains linked or unknown physical entries')
            actual_names.add(member.relative_to(target).as_posix())
            if stat.S_ISDIR(info.st_mode):
                visit(member)
    visit(target)
    if actual_names != set(before):
        raise ValueError('Graph/recovery physical complete toolkit census differs')
    for name in toolkit:
        physical_file(target, name, before[name])


def exact_case_rows(data, identifiers):
    rows = data.get('cases')
    if (not isinstance(rows, list) or len(rows) != len(identifiers) or any(not isinstance(row, dict) for row in rows)
            or [row.get('id') for row in rows] != list(identifiers)
            or any(row.get('verdict') not in ('PASS', 'FAIL') or not isinstance(row.get('observed'), dict)
                   or not isinstance(row.get('evidence'), list) or not row['evidence'] for row in rows)):
        raise ValueError('Graph/recovery literal complete case registry differs')
    for row in rows:
        if any(name not in data['evidence_files'] for name in row['evidence']):
            raise ValueError('Graph/recovery case evidence is absent from hashed inventory')
    return {row['id']: row for row in rows}


def verified_case(row, valid):
    verdict = 'PASS' if valid else 'FAIL'
    if row['verdict'] != verdict:
        raise ValueError('Graph/recovery declared case verdict contradicts recomputed behavior: ' + row['id'])
    return valid


def proof_rpc(directory, evidence, role, calls, client):
    expected = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05',
        'capabilities': {}, 'clientInfo': {'name': client, 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
    expected += [{'jsonrpc': '2.0', 'id': number, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
                 for number, (name, arguments) in enumerate(calls, 2)]
    if proof_json(directory, evidence, role + '.requests.json') != expected:
        raise ValueError('Graph/recovery actual RPC requests differ from literal inventory')
    responses = [json.loads(line) for line in retained_observation(directory, role + '.stdout.txt').read_text(encoding='utf-8').splitlines() if line.strip()]
    if (len(responses) != len(calls) + 1 or any(not isinstance(row, dict) or type(row.get('id')) is not int
            or row.get('jsonrpc') != '2.0' or 'error' in row for row in responses)
            or [row['id'] for row in responses] != list(range(1, len(calls) + 2)) or not isinstance(responses[0].get('result'), dict)
            or responses[0].get('result', {}).get('serverInfo', {}).get('name') != 'knowledgeos-memory'):
        raise ValueError('Graph/recovery actual RPC response sequence or server identity differs')
    results = []
    for row in responses[1:]:
        result = row.get('result', {})
        if not isinstance(result, dict):
            raise ValueError('Graph/recovery actual RPC result is not an object')
        content = result.get('content')
        if (not isinstance(result, dict) or type(result.get('isError')) is not bool or not isinstance(content, list) or len(content) != 1
                or not isinstance(content[0], dict) or content[0].get('type') != 'text' or not isinstance(content[0].get('text'), str)):
            raise ValueError('Graph/recovery actual RPC response shape differs')
        payload = json.loads(content[0]['text'])
        if not isinstance(payload, dict):
            raise ValueError('Graph/recovery public payload is not an object')
        results.append({'payload': payload, 'is_error': result['isError']})
    if proof_json(directory, evidence, role + '.results.json') != results:
        raise ValueError('Graph/recovery parsed observations disagree with actual wire bytes')
    return results


def proof_operation(record, directory, fixture, operation, *, graph=False, fault=False, kind=None):
    base = directory.relative_to(ROOT.absolute()).as_posix()
    scope = base + '/fixtures/' + fixture
    vault, toolkit = scope + '/vault', scope + '/toolkit'
    command = record['command']
    if (not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?(?:\.exe)?', command[0].replace('\\', '/').rsplit('/', 1)[-1])
            or command[1:3] != ['-B', '-P'] or data_repository_location(record.get('cwd')) != scope
            or data_repository_location(record.get('vault')) != vault
            or data_repository_location(record.get('state_dir')) != scope + '/gate-state'):
        raise ValueError('Graph/recovery command interpreter, fixture or isolated state differs')
    imports = record.get('import_path', '')
    imports = imports.split(';') if ';' in imports else [imports]
    expected_imports = [base + '/tracer', toolkit] if graph else [toolkit]
    if [data_repository_location(value) for value in imports] != expected_imports:
        raise ValueError('Graph/recovery command import path differs from copied toolkit')
    tail = command[3:]
    if operation == 'holder':
        valid = (len(tail) == 4 and tail[:2] == ['-c', producer_literal('recovery.py', 'HOLDER_CODE')]
                 and data_repository_location(tail[2]) == vault and tail[3] == kind)
    elif operation == 'rebuild':
        if fault:
            wrapper = "import resource,runpy,signal,sys; signal.signal(signal.SIGXFSZ,signal.SIG_IGN); resource.setrlimit(resource.RLIMIT_FSIZE,(1,1)); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
            valid = len(tail) == 5 and tail[:2] == ['-c', wrapper]
            tail = tail[2:]
        else:
            valid = len(tail) == 3
        valid = valid and data_repository_location(tail[0]) == toolkit + '/scripts/rebuild_index.py' and tail[1] == '--vault' and data_repository_location(tail[2]) == vault
    else:
        if fault:
            wrapper = "import resource,runpy,signal,sys; signal.signal(signal.SIGXFSZ,signal.SIG_IGN); resource.setrlimit(resource.RLIMIT_FSIZE,(1,1)); sys.argv=['knowledgeos',*sys.argv[1:]]; runpy.run_module('knowledgeos',run_name='__main__')"
            valid = tail[:2] == ['-c', wrapper]
            tail = tail[2:]
        else:
            valid = tail[:2] == ['-m', 'knowledgeos']
            tail = tail[2:]
        if operation == 'init':
            valid = valid and len(tail) == 5 and tail[0] == 'init' and data_repository_location(tail[1]) == vault and tail[2:] == ['--name', 'Synthetic Unknown A47' if graph else 'Synthetic Recovery RQ731', '--non-interactive']
        elif operation in ('mcp', 'doctor'):
            valid = valid and len(tail) == (5 if operation == 'mcp' else 3) and tail[:2] == [operation, '--vault'] and data_repository_location(tail[2]) == vault and (operation != 'mcp' or tail[3:] == ['--framing', 'ndjson'])
        elif operation == 'memory':
            name, arguments = recovery_call(kind)
            valid = valid and len(tail) == 6 and tail[:3] == ['memory', name, '--vault'] and data_repository_location(tail[3]) == vault and tail[4] == '--args' and json.loads(tail[5]) == arguments
        else:
            valid = False
    if not valid or fault and 'RLIMIT_FSIZE=1' not in str(record.get('os_fault', '')):
        raise ValueError('Graph/recovery argv is not its literal public operation or native fault')


def graph_relation(result, source, expected, hops=1, ambiguity=False):
    payload = result.get('payload', {})
    rows = payload.get('related')
    paths = [row.get('path') for row in rows if isinstance(row, dict)] if isinstance(rows, list) else None
    valid = (result.get('is_error') is False and payload.get('seed') == source and type(payload.get('hops')) is int
             and payload['hops'] == hops and paths is not None and len(paths) == len(rows)
             and all(isinstance(path, str) for path in paths) and sorted(paths) == expected and len(set(paths)) == len(paths))
    if ambiguity:
        pending, disclosed = [('', payload)], False
        while pending:
            key, value = pending.pop()
            if isinstance(value, dict):
                kind = str(value.get('issue', value.get('kind', value.get('type', key)))).lower()
                candidates = value.get('candidates')
                disclosed = disclosed or ('ambigu' in kind and value.get('source', value.get('path', value.get('source_path', payload.get('seed')))) == source
                    and value.get('target') == 'Twin' and isinstance(candidates, list) and all(isinstance(item, str) for item in candidates)
                    and sorted(candidates) == ['Concepts/Twin.md', 'Projects/B/Twin.md'])
                pending.extend(value.items())
            elif isinstance(value, list):
                pending.extend((key, item) for item in value)
        valid = valid and disclosed
    return bool(valid)


def initialized_fixture(directory, evidence, records, fixture, toolkit, *, graph=False):
    names = (fixture + '-init', fixture + '-doctor') if graph else (fixture + '-init', fixture + '-bootstrap', fixture + '-doctor')
    for role in names:
        operation = 'init' if role.endswith('-init') else 'doctor' if role.endswith('-doctor') else 'rebuild'
        proof_operation(records[role], directory, fixture, operation, graph=graph)
        if records[role]['exit_code'] != 0:
            raise ValueError('Graph/recovery fixture failed initialization, bootstrap or doctor')
    initialized = read_json(retained_observation(directory, fixture + '-init.stdout.txt'))
    post = initialized.get('post_init', {})
    if (initialized.get('ok') is not True or not {'rebuild', 'validate'} <= set(post)
            or any(not isinstance(row, dict) or row.get('ok') is not True for row in post.values())
            or data_repository_location(initialized.get('vault')) != directory.relative_to(ROOT.absolute()).as_posix() + '/fixtures/' + fixture + '/vault'):
        raise ValueError('Graph/recovery initialization has incomplete actual post-init checks')
    copied_toolkit(directory, evidence, fixture, toolkit, after=not graph)
    return initialized


def graph_report(path, current):
    path, data, toolkit, evidence, records = graph_recovery_source(path, current, graph=True)
    directory = path.parent
    if (data.get('expected_case_ids') != list(GRAPH_IDS) or data.get('execution_complete') is not True
            or data.get('fixed_outcome_candidate') != 'MEMORY.correct_links' or set(records) != {'revision', 'cold-init', 'cold-doctor', 'graph'}):
        raise ValueError('Graph complete literal case or command inventory differs')
    rows = exact_case_rows(data, GRAPH_IDS)
    initialized_fixture(directory, evidence, records, 'cold', toolkit, graph=True)
    checks = [verified_case(rows[GRAPH_IDS[0]], True)]
    frozen = proof_json(directory, evidence, 'frozen-expectations.json')
    bodies = producer_literal('graph.py', 'BODIES')
    edited, moved = producer_literal('graph.py', 'EDITED_BODY'), producer_literal('graph.py', 'MOVED_BODY')
    if (frozen.get('producer') != data['producer'] or frozen.get('outcome') != 'MEMORY.correct_links'
            or frozen.get('expected_case_ids') != list(GRAPH_IDS) or frozen.get('relationships') != {key: list(value) for key, value in GRAPH_CASES.items()}
            or frozen.get('ambiguity') != {'source': 'Projects/A/AmbiguousSource.md', 'target': 'Twin', 'candidates': ['Concepts/Twin.md', 'Projects/B/Twin.md']}
            or frozen.get('note_bodies') != bodies or frozen.get('editor_changes') != {'Concepts/EditSeed.md': edited, 'Concepts/MoveSeed.md': moved,
                'rename': ['Concepts/MoveTarget.md', 'Concepts/Archive/RenamedTarget.md']}):
        raise ValueError('Graph literal frozen relationship/note/editor contract differs')
    before = proof_inventory(directory, evidence, 'graph.before.json')
    after = proof_inventory(directory, evidence, 'graph.after.json')
    def note_bytes(relative, body):
        return ('---\ntype: concept\ntitle: ' + Path(relative).stem + '\ndescription: Frozen synthetic graph evidence\nstatus: active\n'
                'schema: knowledgeos-v0.3\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [synthetic]\n---\n' + body).encode('utf-8')
    expected = {name: dict(row) for name, row in before.items()}
    for relative, body in bodies.items():
        raw = note_bytes(relative, body)
        row = before.get('vault/' + relative, {})
        if row.get('sha256') != hashlib.sha256(raw).hexdigest() or row.get('size') != len(raw) or row.get('links') != 1:
            raise ValueError('Graph frozen literal note bytes differ from actual before inventory')
    for relative, body in (('Concepts/EditSeed.md', edited), ('Concepts/MoveSeed.md', moved)):
        raw = note_bytes(relative, body)
        expected['vault/' + relative].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    expected['vault/Concepts/Archive/RenamedTarget.md'] = expected.pop('vault/Concepts/MoveTarget.md')
    allowed = ('vault/knowledge_index.db', 'vault/.knowledgeos/index-manifest.json')
    preserved = {key: row for key, row in expected.items() if key not in allowed} == {key: row for key, row in after.items() if key not in allowed}
    for name, row in after.items():
        if row['kind'] == 'file' and name not in allowed:
            physical_file(directory / 'fixtures/cold', name, row)
    vault = directory / 'fixtures/cold/vault'
    if ({'vault/' + member.relative_to(vault).as_posix() for member in vault.rglob('*.md') if member.is_file()}
            != {name for name, row in after.items() if name.startswith('vault/') and name.endswith('.md') and row['kind'] == 'file'}):
        raise ValueError('Graph physical note census differs from retained final source inventory')
    mutations = [('edit_source', 'Concepts/EditSeed.md', edited), ('move_target', None, None), ('repair_moved_link', 'Concepts/MoveSeed.md', moved)]
    previous = {name.removeprefix('vault/'): row for name, row in before.items() if name.startswith('vault/')}
    for action, relative, body in mutations:
        old = proof_inventory(directory, evidence, 'editor-' + action + '.before.json')
        new = proof_inventory(directory, evidence, 'editor-' + action + '.after.json')
        target = {name: dict(row) for name, row in old.items()}
        if action == 'move_target':
            target['Concepts/Archive/RenamedTarget.md'] = target.pop('Concepts/MoveTarget.md')
        else:
            raw = note_bytes(relative, body)
            target[relative].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if target != new:
            raise ValueError('Graph actual editor before/after changes differ from frozen action')
        protected = lambda inv: {name: row for name, row in inv.items() if name not in ('knowledge_index.db', '.knowledgeos/index-manifest.json')}
        if protected(previous) != protected(old):
            raise ValueError('Graph editor stages lose or change source truth')
        previous = new
    if protected(previous) != protected({name.removeprefix('vault/'): row for name, row in after.items() if name.startswith('vault/')}):
        raise ValueError('Graph final source inventory does not match editor history')
    proof_operation(records['graph'], directory, 'cold', 'mcp', graph=True)
    if records['graph']['exit_code'] != 0 or records['graph'].get('reader_threads_stopped') is not True:
        raise ValueError('Graph persistent MCP reader/process shutdown is incomplete')
    events = [(source, expected, hops) for source, expected, hops in GRAPH_CASES.values()]
    events += [('Concepts/EditSeed.md', ['Concepts/EditOld.md'], 1), ('Concepts/EditSeed.md', ['Concepts/EditNew.md'], 1),
               ('Concepts/MoveSeed.md', ['Concepts/MoveTarget.md'], 1), ('Concepts/MoveSeed.md', [], 1), ('Concepts/MoveSeed.md', ['Concepts/Archive/RenamedTarget.md'], 1)]
    results = proof_rpc(directory, evidence, 'graph', [('memory_related', {'path_or_id': source, 'hops': hops, 'limit': 30}) for source, _, hops in events], 'verify-twinaatma-graph')
    for index, (name, (source, expected_paths, hops)) in enumerate(GRAPH_CASES.items()):
        observed = rows['memory.graph.' + name]['observed']
        if observed.get('public_result') != results[index]:
            raise ValueError('Graph case observation contradicts actual persistent wire result')
        checks.append(verified_case(rows['memory.graph.' + name], graph_relation(results[index], source, expected_paths, hops, name == 'ambiguous_basename')))
    for name, indices in (('source_edit_refresh', (12, 13)), ('target_move_refresh', (14, 15, 16))):
        row = rows['memory.graph.' + name]
        if row['observed'].get('one_mcp_pid') != records['graph']['pid'] or [stage.get('public_result') for stage in row['observed'].get('stages', [])] != [results[index] for index in indices]:
            raise ValueError('Graph editor refresh is not bound to the single actual MCP process')
        checks.append(verified_case(row, all(graph_relation(results[index], *events[index]) for index in indices)))
    checks.append(verified_case(rows['memory.graph.source_preserved'], preserved))
    trace_hashes = data.get('trace_files', {})
    traces = {proof_json(directory, evidence, name)['pid']: proof_json(directory, evidence, name) for name in trace_hashes}
    direct = {record['pid'] for role, record in records.items() if role != 'revision'}
    if (data.get('nested_process_tracking_complete') is not True or data.get('nested_processes') != []
            or data.get('traced_process_ids') != sorted(direct) or set(traces) != direct
            or set(trace_hashes) != {'child-traces/' + str(pid) + '.json' for pid in direct}
            or {name for name in evidence if name.startswith('child-traces/')} != set(trace_hashes)
            or any(row.get('children') != [] for row in traces.values())
            or any(evidence.get(name) != digest for name, digest in trace_hashes.items())
            or data.get('generated_support_sha256') != {'tracer/sitecustomize.py': sha(retained_observation(directory, 'tracer/sitecustomize.py'))}
            or retained_observation(directory, 'tracer/sitecustomize.py').read_text(encoding='utf-8') != producer_literal('graph.py', 'TRACE_SOURCE')):
        raise ValueError('Graph direct/nested trace or exact generated tracer inventory differs')
    return graph_recovery_result(path, data, evidence, 'memory.graph.complete', all(checks))


def graph_recovery_result(path, data, evidence, aggregate, passed):
    verdict = 'PASS' if passed else 'FAIL'
    if data['verdict'] != verdict:
        raise ValueError('Graph/recovery aggregate contradicts recomputed complete behavior')
    return {'path': str(path), 'report_sha256': sha(path), 'scope': 'source', 'producer': data['producer'],
            'producer_sha256': data['producer_sha256'], 'support_sha256': data.get('support_sha256', data.get('support_producer_hashes')),
            'evidence_files': evidence, 'checks': {aggregate: {'id': aggregate, 'verdict': verdict}}}


def recovery_call(kind):
    if kind == 'gate':
        return ('memory_propose_self_update', {'summary': 'Synthetic recovery check', 'section': 'heuristics',
            'proposed_markdown': '- Synthetic rq731 proposal; no personal claim.', 'mode': 'append'})
    return ('memory_session_start', {'task_hint': 'rq731quote', 'session_id': 'rq731-ownership-session'})


def recovery_search(result, frozen, fresh):
    payload = result.get('payload', {})
    rows = [row for value in payload.values() if isinstance(value, list) for row in value if isinstance(row, dict) and 'path' in row]
    quotes = [str(row.get('snippet', '')) for row in rows if row['path'] == 'Concepts/Recovery.md']
    disclosure = payload.get('index_frozen') is True and isinstance(payload.get('index_frozen_note'), str) and bool(payload['index_frozen_note'].strip())
    return (result.get('is_error') is False and payload.get('query') == 'rq731quote' and bool(quotes)
        and any('rq731quote current evidence after an external edit.' in quote for quote in quotes)
        and all('rq731quote evidence before the editor changes it.' not in quote for quote in quotes)
        and all(row['path'] != 'Concepts/Removed.md' for row in rows)
        and (disclosure if frozen else not payload.get('index_frozen'))
        and (not fresh or any(row['path'] == 'Concepts/Fresh.md' and 'rq731quote new evidence created while indexing is unavailable.' in str(row.get('snippet', '')) for row in rows)))


def recovery_preservation(directory, evidence, fixture, before_name, after_name, observed):
    before = proof_inventory(directory, evidence, before_name + '.inventory.json')
    after = proof_inventory(directory, evidence, after_name + '.inventory.json')
    def protected(name):
        return name.startswith('toolkit/') or name.startswith('vault/') and not name.startswith(('vault/.knowledgeos/', 'vault/knowledge_index.db', 'vault/People/Self-Proposals/'))
    left = {name: row for name, row in before.items() if protected(name)}
    right = {name: row for name, row in after.items() if protected(name)}
    for name, row in after.items():
        if protected(name) and row['kind'] == 'file':
            physical_file(directory / 'fixtures' / fixture, name, row)
    vault = directory / 'fixtures' / fixture / 'vault'
    physical_notes = {'vault/' + path.relative_to(vault).as_posix() for path in vault.rglob('*.md')
                      if path.is_file() and not path.relative_to(vault).as_posix().startswith('People/Self-Proposals/')}
    if physical_notes != {name for name, row in after.items() if name.startswith('vault/') and name.endswith('.md') and protected(name) and row['kind'] == 'file'}:
        raise ValueError('Recovery physical source-note census differs from retained inventory')
    valid = left == right
    if (observed.get('source_and_unrelated_files_unchanged') is not valid
            or observed.get('complete_copied_toolkit_unchanged') is not True
            or observed.get('self_sha256') != after.get('vault/People/Self.md', {}).get('sha256')
            or observed.get('changed_protected_entries') != sorted(name for name, row in left.items() if right.get(name) != row)
            or observed.get('unexpected_new_notes') != sorted(name for name in after if name.startswith('vault/') and name.endswith('.md') and name not in before and not name.startswith('vault/People/Self-Proposals/'))):
        raise ValueError('Recovery source preservation claims contradict retained inventories')
    return valid


def recovery_literal_notes(directory, fixture, *, changed):
    def note(title, body, identifier):
        return ('---\ntype: concept\ntitle: ' + title + '\ndescription: Synthetic recovery acceptance note\nstatus: active\n'
                'schema: knowledgeos-v0.3\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [rq731, synthetic]\nid: kos:concept:'
                + identifier + '\n---\n# ' + title + '\n' + body + '\n').encode()
    expected = {'Concepts/Recovery.md': note('rq731 recovery', 'rq731quote current evidence after an external edit.' if changed else 'rq731quote evidence before the editor changes it.', 'rq731-recovery')}
    if changed:
        expected['Concepts/Fresh.md'] = note('rq731 fresh', 'rq731quote new evidence created while indexing is unavailable.', 'rq731-fresh')
        expected['.knowledgeos/removed-note-by-fixture.bin'] = note('rq731 removed', 'rq731 note later removed by its synthetic editor.', 'rq731-removed')
    else:
        expected['Concepts/Removed.md'] = note('rq731 removed', 'rq731 note later removed by its synthetic editor.', 'rq731-removed')
    vault = directory / 'fixtures' / fixture / 'vault'
    for relative, raw in expected.items():
        if retained_observation(vault, relative).read_bytes() != raw:
            raise ValueError('Recovery actual frozen source note bytes differ from literal evidence')


def recovery_holder(directory, evidence, record, fixture, kind, role):
    proof_operation(record, directory, fixture, 'holder', kind=kind)
    ready = record.get('ready_observation')
    lines = retained_observation(directory, role + '.stdout.txt').read_text(encoding='utf-8').splitlines()
    if (not isinstance(ready, dict) or len(lines) != 1 or json.loads(lines[0]) != ready or ready.get('ready') is not True
            or ready.get('pid') != record['pid'] or ready.get('kind') != kind or record.get('ready_was_observed') is not True):
        raise ValueError('Recovery real holder readiness is not bound to actual stdout and owned PID')
    scope = directory.relative_to(ROOT.absolute()).as_posix() + '/fixtures/' + fixture
    marker = data_repository_location(ready.get('path'))
    expected = {'sqlite': '/vault/knowledge_index.db', 'index': '/vault/.knowledgeos/index-rebuild.lock', 'sessions': '/vault/.knowledgeos/sessions.lock'}
    valid_path = bool(re.fullmatch(re.escape(scope) + r'/gate-state/vaults/[0-9a-f]{16}/self-gate\.lock', marker)) if kind == 'gate' else marker == scope + expected[kind]
    threshold = None
    if kind in ('index', 'gate'):
        tree = ast.parse((ROOT / 'knowledgeos' / ('indexer.py' if kind == 'index' else 'gate.py')).read_text(encoding='utf-8'))
        thresholds = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'LOCK_STALE_SECONDS' for target in node.targets)]
        if len(thresholds) != 1:
            raise ValueError('Recovery current production stale threshold is ambiguous')
        threshold = thresholds[0]
    if not valid_path or ready.get('stale_threshold_seconds') != threshold:
        raise ValueError('Recovery holder path or unchanged production stale threshold differs')
    if kind != 'sqlite':
        try:
            token = json.loads(bytes.fromhex(ready['token']))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Recovery owner marker does not retain its actual token bytes') from error
        if token.get('pid') != ready['pid'] or type(token.get('pid')) is not int or not isinstance(token.get('nonce'), str) or not token['nonce']:
            raise ValueError('Recovery owner token does not bind its actual PID')
    return ready


def recovery_action(directory, evidence, records, role, fixture, kind, observed, *, fault=False):
    record = records[role]
    if kind == 'index' or fault:
        proof_operation(record, directory, fixture, 'rebuild' if kind == 'index' else 'memory', fault=fault, kind=kind)
        stdout = retained_observation(directory, role + '.stdout.txt').read_text(encoding='utf-8')
        stderr = retained_observation(directory, role + '.stderr.txt').read_text(encoding='utf-8')
        if observed.get('command') != record or observed.get('stdout') != stdout or observed.get('stderr') != stderr:
            raise ValueError('Recovery action contradicts its actual retained command/output')
        success = record['exit_code'] == 0
        if fault and kind != 'index':
            try:
                payload = json.loads(stdout)
            except ValueError:
                payload = {}
            if observed.get('payload') != payload:
                raise ValueError('Recovery fault CLI payload differs from actual stdout')
            success = success and 'error' not in payload
        refused = record['exit_code'] != 0 and bool(stderr.strip())
    else:
        proof_operation(record, directory, fixture, 'mcp')
        result = proof_rpc(directory, evidence, role, [recovery_call(kind)], 'verify-twinaatma-recovery')[0]
        if observed.get('result') != result or record['exit_code'] != 0:
            raise ValueError('Recovery action contradicts actual MCP result or clean exit')
        payload = result['payload']
        success = result['is_error'] is False and (payload.get('policy') == 'proposal_only' and payload.get('mutated_self') is False
            and isinstance(payload.get('proposal_path'), str) if kind == 'gate' else payload.get('session_id') == 'rq731-ownership-session' and isinstance(payload.get('context'), dict))
        if success and kind == 'gate':
            retained_observation(directory / 'fixtures' / fixture / 'vault', payload['proposal_path'])
        refused = result['is_error'] is True and isinstance(payload.get('error'), str) and bool(payload['error'].strip())
    if observed.get('success') is not bool(success):
        raise ValueError('Recovery success flag contradicts actual public result')
    return bool(success), bool(refused)


def recovery_report(path, current):
    path, data, toolkit, evidence, records = graph_recovery_source(path, current)
    directory = path.parent
    journey, names, aggregate = RECOVERY_SPECS[data['producer']]
    expected_ids = ['recovery.' + journey + '.' + name for name in names]
    if (data.get('journey') != journey or data.get('case_inventory_complete') is not True or data.get('os_name') not in ('nt', 'posix')
            or data.get('fixed_outcome_candidate') != ('RECOVERY.index_degradation' if journey == 'index' else 'RECOVERY.ownership_locks')
            or journey == 'write-faults' and data.get('os_name') != 'posix'):
        raise ValueError('Recovery journey or native POSIX fault coverage is incomplete')
    rows = exact_case_rows(data, expected_ids)
    contract = proof_json(directory, evidence, 'case-contract.json')
    if contract != {'journey': journey, 'producer': data['producer'], 'outcome': 'RECOVERY.index_degradation' if journey == 'index' else 'RECOVERY.ownership_locks',
        'literal_case_ids': list(names), 'product_hashes': toolkit, 'producer_sha256': data['producer_sha256'],
        'support_producer_hashes': data['support_producer_hashes'], 'contract_frozen_before_any_product_invocation': True}:
        raise ValueError('Recovery frozen case/input contract differs')
    fixtures = list(RECOVERY_INDEX) if journey == 'index' else ['ownership-' + kind for kind in RECOVERY_KINDS] if journey == 'locks' else list(RECOVERY_FAULTS)
    if (not isinstance(data.get('fixtures'), list) or any(not isinstance(row, dict) for row in data['fixtures'])
            or [row.get('label') for row in data['fixtures']] != fixtures):
        raise ValueError('Recovery literal fixture registry differs')
    wanted_roles, checks = {'revision'}, []
    for fixture, declared in zip(fixtures, data['fixtures']):
        initialized = initialized_fixture(directory, evidence, records, fixture, toolkit)
        recovery_literal_notes(directory, fixture, changed=journey == 'index')
        scope = directory.relative_to(ROOT.absolute()).as_posix() + '/fixtures/' + fixture
        if (any(data_repository_location(declared.get(key)) != scope + suffix for key, suffix in (('scope', ''), ('vault', '/vault'), ('toolkit', '/toolkit')))
                or declared.get('complete_toolkit_matches_current_source') is not True
                or declared.get('initialization', {}).get('initialized') != initialized
                or declared['initialization'].get('rebuild_exit') != 0 or declared['initialization'].get('doctor_exit') != 0):
            raise ValueError('Recovery fixture claims differ from actual initialized toolkit')
        wanted_roles.update(fixture + suffix for suffix in ('-init', '-bootstrap', '-doctor'))
        if 'gate' in fixture:
            role = fixture + '-gate-readiness'
            wanted_roles.add(role)
            proof_operation(records[role], directory, fixture, 'mcp')
            calls = [('memory_propose_self_update', {'summary': 'Synthetic gate readiness RQ731', 'section': 'heuristics', 'proposed_markdown': '- Synthetic fixture gate readiness only.', 'mode': 'append'})]
            ready = proof_rpc(directory, evidence, role, calls, 'verify-twinaatma-recovery')[0]
            if records[role]['exit_code'] != 0 or ready['is_error'] or ready['payload'].get('policy') != 'proposal_only' or ready['payload'].get('mutated_self') is not False:
                raise ValueError('Recovery gate readiness failed its public proposal boundary')
    for identifier in names:
        row = rows['recovery.' + journey + '.' + identifier]
        observed = row['observed']
        if journey == 'index':
            fixture = identifier
            stages = []
            for suffix, frozen, fresh in (('-during', identifier not in ('missing_index', 'corrupt_index'), identifier in ('missing_index', 'corrupt_index')), ('-retry', False, True)):
                role = identifier + suffix
                wanted_roles.add(role)
                proof_operation(records[role], directory, fixture, 'mcp')
                result = proof_rpc(directory, evidence, role, [('memory_search', {'query': 'rq731quote', 'limit': 20})], 'verify-twinaatma-recovery')[0]
                value = observed if suffix == '-during' else observed['retry']
                if value.get('payload') != result['payload'] or value.get('is_error') != result['is_error'] or records[role]['exit_code'] != 0:
                    raise ValueError('Recovery search claim differs from actual public wire result')
                valid = bool(recovery_search(result, frozen, fresh))
                if value.get('valid') is not valid:
                    raise ValueError('Recovery search validity contradicts actual current quotes/disclosure')
                stages.append(valid)
                preservation = 'source_preservation_during' if suffix == '-during' else 'source_preservation_after_retry'
                stages.append(recovery_preservation(directory, evidence, fixture, identifier + '-before', role + '-after', observed[preservation]))
            if identifier in ('busy_sqlite', 'busy_rebuild'):
                role = identifier + '-holder'
                wanted_roles.add(role)
                recovery_holder(directory, evidence, records[role], fixture, 'sqlite' if identifier == 'busy_sqlite' else 'index', role)
                require_distinct_live_processes(records, role, identifier + '-during')
                stages.append(observed.get('holder_alive_during') is True)
            required = {'busy_sqlite': ('live_database_not_replaced',), 'corrupt_index': ('corrupt_bytes_retained', 'fixture_retained_database_unchanged'),
                'missing_index': ('fixture_retained_database_unchanged',), 'blocked_rebuild': ('obstruction_preserved',), 'blocked_manifest': ('obstruction_preserved',)}
            stages.extend(observed.get(key) is True for key in required.get(identifier, ()))
            vault = directory / 'fixtures' / fixture / 'vault'
            if identifier.startswith('blocked_'):
                target = '.knowledgeos/index-rebuild.lock.released-by-fixture' if identifier == 'blocked_rebuild' else '.knowledgeos/index-manifest.json.released-by-fixture'
                stages.append(retained_observation(vault, target + '/unrelated-owner.bin').read_bytes() == b'UNRELATED OWNERSHIP RQ731\x00\xff\n')
            if identifier in ('missing_index', 'corrupt_index'):
                target = 'knowledge_index.db.removed-by-fixture' if identifier == 'missing_index' else 'knowledge_index.db.before-corruption'
                before = proof_inventory(directory, evidence, identifier + '-before.inventory.json')
                physical_file(vault, target, before['vault/' + target])
                if identifier == 'corrupt_index':
                    stages.append(any(retained_observation(vault, member.name).read_bytes() == b'NOT A SQLITE DATABASE RQ731\x00\xff\n' for member in vault.glob('knowledge_index.db.corrupt-*') if member.is_file()))
            checks.append(verified_case(row, all(stages)))
        else:
            kind = identifier.split('_', 1)[0]
            fixture = 'ownership-' + kind if journey == 'locks' else identifier
            scenario = identifier[len(kind) + 1:]
            success, _ = recovery_action(directory, evidence, records, identifier + '-retry', fixture, kind, observed['retry'])
            wanted_roles.add(identifier + '-retry')
            valid = success
            if journey == 'write-faults':
                wanted_roles.add(identifier + '-fault')
                failure, _ = recovery_action(directory, evidence, records, identifier + '-fault', fixture, kind, observed['failure'], fault=True)
                diagnostic = retained_observation(directory, identifier + '-fault.stderr.txt').read_text(encoding='utf-8').lower() + retained_observation(directory, identifier + '-fault.stdout.txt').read_text(encoding='utf-8').lower()
                valid = valid and not failure and ('file too large' in diagnostic or 'efbig' in diagnostic) and observed.get('partial_marker_absent_after_failure') is True
            elif scenario in ('live_old_owner', 'dead_owner', 'replacement_marker'):
                role = identifier + '-holder'
                wanted_roles.add(role)
                ready = recovery_holder(directory, evidence, records[role], fixture, kind, role)
                if ready != observed.get('actual_owner'):
                    raise ValueError('Recovery owner claim differs from actual holder readiness')
                token = bytes.fromhex(ready['token'])
                decoded = json.loads(token)
                if decoded.get('pid') != ready['pid'] or not isinstance(decoded.get('nonce'), str) or not decoded['nonce']:
                    raise ValueError('Recovery owner token does not bind its actual PID')
                if scenario == 'live_old_owner':
                    wanted_roles.add(identifier + '-contender')
                    _, refused = recovery_action(directory, evidence, records, identifier + '-contender', fixture, kind, observed['contender'])
                    require_distinct_live_processes(records, role, identifier + '-contender')
                    threshold = ready.get('stale_threshold_seconds') or 0
                    valid = valid and refused and observed.get('live_owner_alive') is True and observed.get('owned_marker_unchanged') is True and observed.get('production_timeout_and_threshold_unchanged') is True and type(observed.get('marker_age_seconds')) in (int, float) and observed['marker_age_seconds'] > max(0, threshold)
                elif scenario == 'dead_owner':
                    valid = valid and observed.get('dead_owner_marker_retained_before_retry') is True and records[role].get('terminated_exact_owned_child') is True and type(observed.get('recovery_seconds')) in (int, float) and 0 <= observed['recovery_seconds'] < 20
                else:
                    valid = valid and observed.get('replacement_marker_preserved') is True and observed.get('original_marker_retained') is True
                    target = ROOT / data_repository_location(ready['path'])
                    valid = valid and retained_observation(target.parent, target.name + '.original-token-retained').read_bytes() == token and retained_observation(target.parent, target.name + '.replacement-retained').read_bytes() == b'{"pid":1,"nonce":"unrelated-replacement-owner-rq731"}'
            else:
                wanted_roles.add(identifier + '-contender')
                _, refused = recovery_action(directory, evidence, records, identifier + '-contender', fixture, kind, observed['contender'])
                valid = valid and refused and observed.get('unrelated_ownership_preserved') is True
            valid = valid and recovery_preservation(directory, evidence, fixture, identifier + '-before', identifier + '-after', observed['source_preservation'])
            scope = directory / 'fixtures' / fixture
            if kind == 'gate':
                guards = list((scope / 'gate-state/vaults').glob('*/self-gate.lock.guard'))
                if len(guards) != 1:
                    raise ValueError('Recovery gate has no unique retained native guard')
                marker = guards[0].with_name('self-gate.lock')
            else:
                marker = scope / 'vault/.knowledgeos' / ('index-rebuild.lock' if kind == 'index' else 'sessions.lock')
            valid = valid and not marker.exists()
            if scenario in ('blocked_marker', 'blocked_guard'):
                target = marker if scenario == 'blocked_marker' else marker.with_name(marker.name + '.guard')
                valid = valid and retained_observation(target.parent, target.name + '.obstruction-retained/unrelated-owner.bin').read_bytes() == b'UNRELATED OWNERSHIP RQ731\x00\xff\n'
            checks.append(verified_case(row, bool(valid)))
    if set(records) != wanted_roles:
        raise ValueError('Recovery complete literal command inventory differs')
    return graph_recovery_result(path, data, evidence, aggregate, all(checks))


LEARNING_CASES = ('initial_views', 'exact_project_filter', 'exact_status_outcome_filter',
    'busy_edited_decision_current', 'busy_pending_closed', 'busy_timeline_current', 'retry_complete',
    'attributed_completed_lesson', 'pending_lesson_refused', 'nondecision_lesson_refused',
    'missing_lesson_refused', 'identity_and_sources_preserved')
LEARNING_IDS = tuple('learning.' + name for name in LEARNING_CASES)
LEARNING_LESSON = 'For the synthetic Nova pilot, keep a reversible checkpoint before scaling; this is one local observation.'
LEARNING_DATE = '2026-10-19'
LEARNING_DECISIONS = {
    'Decisions/NovaPending.md': {'title': 'Synthetic Nova pilot', 'status': 'active', 'project': 'Nova', 'outcome_status': 'pending', 'review_after': '2000-01-01', 'lesson': ''},
    'Decisions/NovaComplete.md': {'title': 'Synthetic Nova checkpoint', 'status': 'archived', 'project': 'Nova', 'outcome_status': 'confirmed', 'review_after': '', 'lesson': LEARNING_LESSON},
    'Decisions/NovaNoLesson.md': {'title': 'Synthetic Nova unassessed', 'status': 'archived', 'project': 'Nova', 'outcome_status': 'confirmed', 'review_after': '', 'lesson': ''},
    'Decisions/SupernovaPending.md': {'title': 'Synthetic Supernova pilot', 'status': 'active', 'project': 'Supernova', 'outcome_status': 'pending', 'review_after': '2000-01-02', 'lesson': 'This premature lesson must not become a proposal.'},
    'Decisions/NovaInvalidated.md': {'title': 'Synthetic Nova rejected route', 'status': 'archived', 'project': 'Nova', 'outcome_status': 'invalidated', 'review_after': '', 'lesson': 'One local route failed; no general identity inference follows.'},
}
LEARNING_EDITED = dict(LEARNING_DECISIONS['Decisions/NovaPending.md'], title='Synthetic Nova resolved externally',
    status='archived', project='Orion', outcome_status='confirmed', lesson='This external local outcome is now closed.')
LEARNING_FRESH = {'title': 'Synthetic fresh Orion pilot', 'status': 'active', 'project': 'Orion',
    'outcome_status': 'pending', 'review_after': '2000-01-03', 'lesson': ''}
LEARNING_DISTRACTOR = {'title': 'Synthetic nondecision', 'status': 'active', 'project': 'Nova',
    'outcome_status': 'confirmed', 'review_after': '', 'lesson': 'A concept is not a decision and cannot justify a lesson proposal.'}
LEARNING_PATHS = {*LEARNING_DECISIONS, 'Decisions/FreshOrion.md', 'Concepts/LearningNondecision.md', 'Concepts/LearningOld.md'}
LEARNING_CALLS = {
    'initial': [('memory_decisions', {}), ('memory_pending_outcomes', {}), ('memory_decisions', {'outcome_status': 'confirmed'}), ('memory_timeline', {'days': 365, 'limit': 100})],
    'filters': [('memory_decisions', {'project': 'nOvA'}), ('memory_decisions', {'status': 'active', 'outcome_status': 'pending'})],
    'busy': [('memory_decisions', {'project': 'Orion', 'status': 'archived', 'outcome_status': 'confirmed'}), ('memory_pending_outcomes', {}), ('memory_timeline', {'days': 365, 'limit': 100})],
    'retry': [('memory_decisions', {'project': 'Orion'}), ('memory_pending_outcomes', {}), ('memory_timeline', {'days': 365, 'limit': 100})],
    'lessons': [('memory_propose_from_lesson', {'path_or_id': 'Decisions/NovaComplete.md'}), ('memory_list_self_proposals', {}),
        ('memory_propose_from_lesson', {'path_or_id': 'Decisions/SupernovaPending.md'}), ('memory_propose_from_lesson', {'path_or_id': 'Concepts/LearningNondecision.md'}),
        ('memory_propose_from_lesson', {'path_or_id': 'Decisions/NovaNoLesson.md'})],
    'final-list': [('memory_list_self_proposals', {})],
}
ADAPTER_REQUIREMENTS['version'] = 'verify-twinaatma.adapters/v7'
ADAPTER_REQUIREMENTS['outcomes'].update({'LEARNING.decision_views': ['learning.decision_views.complete'],
    'LEARNING.attributed_lessons': ['learning.attributed_lessons.complete']})
ADAPTER_REQUIREMENTS['learning_producer'] = {'producer': 'verify-twinaatma.learning-source/v1', 'file': 'learning.py',
    'support': ['data_preservation.py', 'identity.py', 'recovery.py', 'graph.py'], 'cases': list(LEARNING_IDS),
    'scope': 'source', 'outcomes': ['LEARNING.decision_views', 'LEARNING.attributed_lessons']}


def learning_note(relative, values, kind='decision', date=LEARNING_DATE):
    lines = ['---', 'type: ' + kind, 'title: ' + values['title'], 'description: Frozen synthetic learning acceptance evidence',
        'schema: knowledgeos-v0.3', 'created: ' + date, 'updated: ' + date, 'tags: [synthetic, learning731]',
        'id: kos:' + kind + ':learning731-' + Path(relative).stem.lower()]
    lines += [key + ': ' + json.dumps(value) for key, value in values.items() if key != 'title']
    return ('\n'.join(lines) + '\n---\n# ' + values['title'] + '\nSynthetic source record. No asserted owner identity.\n').encode()


def learning_view(result, bucket, expected, *, frozen=False, synthetic_only=False):
    if not isinstance(result, dict) or result.get('is_error') is not False or not isinstance(result.get('payload'), dict):
        return False
    payload = result['payload']
    rows = payload.get(bucket)
    if (not isinstance(rows, list) or type(payload.get('count')) is not int or payload['count'] != len(rows)
            or any(not isinstance(row, dict) or not isinstance(row.get('path'), str) or not row['path'] for row in rows)
            or len({row['path'] for row in rows}) != len(rows)):
        return False
    selected = {row['path']: row for row in rows if not synthetic_only or row['path'] in LEARNING_PATHS}
    if set(selected) != set(expected) or any(any(selected[path].get(key) != value for key, value in fields.items()) for path, fields in expected.items()):
        return False
    if frozen:
        return payload.get('index_frozen') is True and isinstance(payload.get('index_frozen_note'), str) and 'may be missing' in payload['index_frozen_note']
    return not payload.get('index_frozen')


def learning_proposal(result, open_result, proposal_text, source_text):
    if (not isinstance(result, dict) or result.get('is_error') is not False or not isinstance(result.get('payload'), dict)
            or not isinstance(open_result, dict) or open_result.get('is_error') is not False or not isinstance(open_result.get('payload'), dict)):
        return False
    row, opened = result['payload'], open_result['payload'].get('open')
    fragments = ('[Synthetic Nova checkpoint](Decisions/NovaComplete.md)', LEARNING_LESSON,
        'This single recorded outcome does not establish a general belief; review before adopting.',
        "Decision outcome 'confirmed' records this lesson. Source: Decisions/NovaComplete.md.",
        'proposal_section: heuristics', 'proposal_mode: append', 'proposal_target: People/Self.md', 'status: draft')
    return (row.get('ok') is True and row.get('policy') == 'proposal_only' and row.get('mutated_self') is False and row.get('section') == 'heuristics'
        and isinstance(row.get('proposal_id'), str) and bool(row['proposal_id']) and isinstance(row.get('proposal_path'), str)
        and isinstance(proposal_text, str) and all(fragment in proposal_text for fragment in fragments) and proposal_text.count(LEARNING_LESSON) == 1
        and isinstance(source_text, str) and source_text.encode() == learning_note('Decisions/NovaComplete.md', LEARNING_DECISIONS['Decisions/NovaComplete.md'])
        and isinstance(opened, list) and len(opened) == 1 and isinstance(opened[0], dict)
        and all(opened[0].get(key) == value for key, value in {'path': row['proposal_path'], 'id': row['proposal_id'], 'status': 'draft'}.items()))


def learning_source(path, current):
    if '..' in Path(path).parts:
        raise ValueError('Learning report traverses lexical parent components')
    path = Path(path).absolute()
    relative = path.parent.relative_to(ROOT.absolute())
    if relative.parts[:2] != ('work', 'gc-artifacts') or '.knowledgeos' not in relative.parts[2:]:
        raise ValueError('Learning report leaves contained synthetic evidence')
    data_evidence(path.parent, path.name)
    data = read_json(path)
    support = {name: sha(Path(__file__).with_name(name)) for name in ADAPTER_REQUIREMENTS['learning_producer']['support']}
    if (not isinstance(data, dict) or data.get('producer') != 'verify-twinaatma.learning-source/v1'
            or data.get('producer_sha256') != sha(Path(__file__).with_name('learning.py'))
            or data.get('support_sha256') != support or data.get('support_sha256_after') != support):
        raise ValueError('Learning producer or support bytes are unsupported or stale')
    check_product(data, 'product_hashes', current)
    toolkit = data_toolkit_hashes()
    if (data.get('product_hashes') != toolkit or data.get('product_hashes_after') != toolkit
            or data.get('product_and_producer_unchanged') is not True or data_repository_location(data.get('source_root')) != ''):
        raise ValueError('Learning complete current toolkit is stale or changed')
    if (not data.get('platform') or not data.get('python') or data.get('verdict') not in ('PASS', 'FAIL') or data.get('error') is not None
            or data.get('acceptance_credit_awarded') is not False or data.get('ideal_system_verdict') != 'NOT CHECKED'
            or data.get('case_inventory_complete') is not True or data.get('expected_case_ids') != list(LEARNING_IDS)):
        raise ValueError('Learning execution identity or complete literal case registry differs')
    evidence = data.get('evidence_files')
    if not isinstance(evidence, dict) or not evidence or path.name in evidence:
        raise ValueError('Learning retained evidence is missing')
    for name, digest in evidence.items():
        if sha(retained_observation(path.parent, name)) != digest:
            raise ValueError('Learning retained evidence hash differs: ' + name)
    processes = data.get('processes')
    if data.get('all_started_processes_stopped') is not True or not isinstance(processes, list) or not processes:
        raise ValueError('Learning shutdown is incomplete')
    records, pids = {}, set()
    for process in processes:
        if (not isinstance(process, dict) or type(process.get('pid')) is not int or process['pid'] <= 0 or process['pid'] in pids
                or not isinstance(process.get('role'), str) or not process['role'] or process['role'] in records
                or process.get('stopped') is not True or type(process.get('exit_code')) is not int or process['exit_code'] != 0):
            raise ValueError('Learning requires unique typed owned PIDs, roles and successful stopped exits')
        role = process['role']
        record = proof_json(path.parent, evidence, role + '.command.json')
        if (any(role + suffix not in evidence for suffix in ('.stdout.txt', '.stderr.txt'))
                or type(record.get('pid')) is not int or record['pid'] != process['pid'] or type(record.get('exit_code')) is not int
                or record['exit_code'] != 0 or record.get('stopped') is not True or record.get('shell') is not False
                or not isinstance(record.get('command'), list) or not record['command'] or any(not isinstance(part, str) or not part for part in record['command'])):
            raise ValueError('Learning actual command, outputs or stopped PID differs')
        if not role.endswith('-holder') and (record.get('error', 'missing') is not None or type(record.get('seconds')) not in (int, float) or not 0 <= record['seconds'] < float('inf')):
            raise ValueError('Learning command timing or execution error differs')
        records[role] = record
        pids.add(process['pid'])
    if (set(records) != {'cold-init', 'cold-doctor', 'busy-sqlite-holder', *LEARNING_CALLS}
            or {name for name in evidence if name.endswith('.command.json')} != {role + '.command.json' for role in records}
            or {name for name in evidence if name.endswith('.requests.json')} != {role + '.requests.json' for role in LEARNING_CALLS}):
        raise ValueError('Learning literal complete command/request inventory differs')
    isolation = data.get('isolation', {})
    before, after = isolation.get('before'), isolation.get('after')
    if (not isinstance(before, dict) or not before or before != after or isolation.get('selected_sentinels_unchanged') is not True
            or {data_repository_location(name) for name in before} != {'People/Self.md', 'knowledge_index.db', '.knowledgeos/autopilot.json'}
            or any(value is not None and (not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)) for value in before.values())):
        raise ValueError('Learning isolation sentinels changed or are incomplete')
    trace_hashes = data.get('trace_files', {})
    if not isinstance(trace_hashes, dict):
        raise ValueError('Learning direct/nested trace inventory is missing')
    traces = {proof_json(path.parent, evidence, name)['pid']: proof_json(path.parent, evidence, name) for name in trace_hashes}
    parents = {row.get('parent_pid') for row in traces.values()}
    if (data.get('nested_process_tracking_complete') is not True or data.get('nested_processes') != []
            or data.get('traced_process_ids') != sorted(pids) or set(traces) != pids or len(parents) != 1
            or any(type(pid) is not int or pid <= 0 or pid in pids for pid in parents)
            or set(trace_hashes) != {'child-traces/' + str(pid) + '.json' for pid in pids}
            or {name for name in evidence if name.startswith('child-traces/')} != set(trace_hashes)
            or any(row.get('children') != [] or type(row.get('pid')) is not int for row in traces.values())
            or any(evidence.get(name) != digest for name, digest in trace_hashes.items())
            or data.get('generated_support_sha256') != {'tracer/sitecustomize.py': sha(retained_observation(path.parent, 'tracer/sitecustomize.py'))}
            or retained_observation(path.parent, 'tracer/sitecustomize.py').read_text(encoding='utf-8') != producer_literal('graph.py', 'TRACE_SOURCE')):
        raise ValueError('Learning stopped direct/nested trace or generated tracer differs')
    return path, data, toolkit, evidence, records


def learning_report(path, current):
    path, data, toolkit, evidence, records = learning_source(path, current)
    directory = path.parent
    rows = exact_case_rows(data, LEARNING_IDS)
    if any(row.get('outcome') != ('LEARNING.attributed_lessons' if name in LEARNING_CASES[7:11] else 'LEARNING.decision_views') for name, row in zip(LEARNING_CASES, rows.values())):
        raise ValueError('Learning case was reassigned to another fixed outcome')
    expected_frozen = {'producer': data['producer'], 'case_ids': list(LEARNING_CASES), 'decisions': LEARNING_DECISIONS,
        'external_edit': LEARNING_EDITED, 'new_during_freeze': LEARNING_FRESH, 'nondecision': LEARNING_DISTRACTOR,
        'date': LEARNING_DATE, 'old_excluded_date': '2000-01-01', 'lesson': LEARNING_LESSON, 'timeline_fixture_paths': sorted(LEARNING_PATHS),
        'project_filter_expectation': 'Nova identifies only project Nova, case insensitive; Supernova is a distinct project. Public tool description promises a project filter and does not advertise substring matching.',
        'frozen_before_product_observation': True, 'product_hashes': toolkit}
    if proof_json(directory, evidence, 'frozen-expectations.json') != expected_frozen:
        raise ValueError('Learning frozen literal source expectations differ')
    initialized_fixture(directory, evidence, records, 'cold', toolkit, graph=True)
    results = {}
    for role, calls in LEARNING_CALLS.items():
        proof_operation(records[role], directory, 'cold', 'mcp', graph=True)
        results[role] = proof_rpc(directory, evidence, role, calls, 'verify-twinaatma-identity')
    holder = records['busy-sqlite-holder']
    proof_operation(holder, directory, 'cold', 'holder', graph=True, kind='sqlite')
    ready = holder.get('ready_observation')
    lines = retained_observation(directory, 'busy-sqlite-holder.stdout.txt').read_text(encoding='utf-8').splitlines()
    scope = directory.relative_to(ROOT.absolute()).as_posix() + '/fixtures/cold'
    if (not isinstance(ready, dict) or len(lines) != 1 or json.loads(lines[0]) != ready or ready.get('ready') is not True
            or type(ready.get('pid')) is not int or ready['pid'] != holder['pid'] or ready.get('kind') != 'sqlite'
            or data_repository_location(ready.get('path')) != scope + '/vault/knowledge_index.db'
            or ready.get('stale_threshold_seconds') is not None or ready.get('token') is not None
            or holder.get('ready_was_observed') is not True or holder.get('terminated_exact_owned_child') is not False):
        raise ValueError('Learning live SQLite holder is not bound to actual readiness and released owned process')
    before = proof_inventory(directory, evidence, 'learning.before.json')
    during = proof_inventory(directory, evidence, 'busy-editor.inventory.json')
    after = proof_inventory(directory, evidence, 'learning.after.json')
    fixture = directory / 'fixtures/cold'
    originals = dict(LEARNING_DECISIONS)
    originals['Concepts/LearningNondecision.md'] = LEARNING_DISTRACTOR
    originals['Concepts/LearningOld.md'] = LEARNING_DISTRACTOR
    for relative, values in originals.items():
        body = learning_note(relative, values, 'concept' if relative.startswith('Concepts/') else 'decision', '2000-01-01' if relative.endswith('LearningOld.md') else LEARNING_DATE)
        wanted = {'kind': 'file', 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(), 'links': 1}
        if before.get('vault/' + relative) != wanted:
            raise ValueError('Learning initial literal decision/source bytes differ: ' + relative)
    for relative, values in {'Decisions/NovaPending.md': LEARNING_EDITED, 'Decisions/FreshOrion.md': LEARNING_FRESH}.items():
        body = learning_note(relative, values)
        wanted = {'kind': 'file', 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(), 'links': 1}
        if during.get('vault/' + relative) != wanted or after.get('vault/' + relative) != wanted:
            raise ValueError('Learning literal external edit or newly discovered note differs')
    for relative, row in after.items():
        if relative.startswith('toolkit/') or relative.startswith('vault/') and relative.endswith('.md'):
            if row['kind'] == 'file':
                physical_file(fixture, relative, row)
    actual_names = set()
    def visit(parent):
        for entry in os.scandir(parent):
            member = Path(entry.path)
            info = member.lstat()
            if (stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise ValueError('Learning physical vault contains linked or unknown entries')
            actual_names.add(member.relative_to(fixture).as_posix())
            if stat.S_ISDIR(info.st_mode):
                visit(member)
    visit(fixture / 'vault')
    if actual_names != {name for name in after if name.startswith('vault/')}:
        raise ValueError('Learning complete retained vault census differs')
    fields = ('title', 'type', 'status', 'project', 'outcome_status', 'lesson', 'updated')
    def expected(registry, keys):
        return {relative: {key: values[key] for key in keys} for relative, values in registry.items()}
    registry = {relative: dict(values, type='decision', updated=LEARNING_DATE) for relative, values in LEARNING_DECISIONS.items()}
    all_expected = expected(registry, fields)
    pending_fields = ('title', 'type', 'outcome_status', 'lesson', 'updated', 'overdue', 'awaiting')
    pending = expected({relative: dict(values, overdue=True, awaiting=True) for relative, values in registry.items() if values['outcome_status'] == 'pending'}, pending_fields)
    timeline_fields = ('title', 'type', 'status', 'updated')
    timeline = expected(dict(registry, **{'Concepts/LearningNondecision.md': dict(LEARNING_DISTRACTOR, type='concept', updated=LEARNING_DATE)}), timeline_fields)
    checks = {}
    def case(name, valid):
        checks[name] = verified_case(rows['learning.' + name], bool(valid))
    initial = results['initial']
    case('initial_views', learning_view(initial[0], 'decisions', all_expected) and learning_view(initial[1], 'outcomes', pending)
        and learning_view(initial[2], 'decisions', {p: v for p, v in all_expected.items() if v['outcome_status'] == 'confirmed'})
        and learning_view(initial[3], 'notes', timeline, synthetic_only=True))
    case('exact_project_filter', learning_view(results['filters'][0], 'decisions', {p: v for p, v in all_expected.items() if v['project'] == 'Nova'}))
    case('exact_status_outcome_filter', learning_view(results['filters'][1], 'decisions', {p: v for p, v in all_expected.items() if v['status'] == 'active' and v['outcome_status'] == 'pending'}))
    edited = expected({'Decisions/NovaPending.md': dict(LEARNING_EDITED, type='decision', updated=LEARNING_DATE)}, fields)
    busy_timeline = dict(timeline, **expected({'Decisions/NovaPending.md': dict(LEARNING_EDITED, type='decision', updated=LEARNING_DATE)}, timeline_fields))
    busy_pending = {'Decisions/SupernovaPending.md': pending['Decisions/SupernovaPending.md']}
    for name, index, bucket, wanted, synthetic in (
            ('busy_edited_decision_current', 0, 'decisions', edited, False),
            ('busy_pending_closed', 1, 'outcomes', busy_pending, False),
            ('busy_timeline_current', 2, 'notes', busy_timeline, True)):
        observed = rows['learning.' + name]['observed']
        if observed.get('result') != results['busy'][index] or observed.get('native_holder_alive_during') is not True:
            raise ValueError('Learning busy view lacks its live holder observation or original payload')
        case(name, learning_view(results['busy'][index], bucket, wanted, frozen=True, synthetic_only=synthetic))
    fresh = dict(LEARNING_FRESH, type='decision', updated=LEARNING_DATE)
    retry = results['retry']
    retry_expected = dict(edited, **expected({'Decisions/FreshOrion.md': fresh}, fields))
    retry_pending = dict(busy_pending, **expected({'Decisions/FreshOrion.md': dict(fresh, overdue=True, awaiting=True)}, pending_fields))
    retry_timeline = dict(busy_timeline, **expected({'Decisions/FreshOrion.md': fresh}, timeline_fields))
    case('retry_complete', learning_view(retry[0], 'decisions', retry_expected) and learning_view(retry[1], 'outcomes', retry_pending)
        and learning_view(retry[2], 'notes', retry_timeline, synthetic_only=True) and rows['learning.retry_complete']['observed'].get('holder_stopped') is True)
    lesson = results['lessons']
    proposal_path = lesson[0]['payload'].get('proposal_path')
    if (not isinstance(proposal_path, str) or not re.fullmatch(r'People/Self-Proposals/[^/\\:]+\.md', proposal_path)):
        raise ValueError('Learning lesson lacks a contained plain proposal path')
    proposal = retained_observation(fixture / 'vault', proposal_path)
    proposal_text = proposal.read_text(encoding='utf-8')
    if retained_observation(directory, 'observed-proposal.txt').read_text(encoding='utf-8') != proposal_text:
        raise ValueError('Learning retained observed proposal differs from actual draft bytes')
    source_text = retained_observation(fixture / 'vault', 'Decisions/NovaComplete.md').read_text(encoding='utf-8')
    case('attributed_completed_lesson', learning_proposal(lesson[0], lesson[1], proposal_text, source_text)
        and rows['learning.attributed_completed_lesson']['observed'].get('plain_contained_proposal') is True)
    for index, name, diagnostic, relative in (
            (2, 'pending_lesson_refused', 'decision outcome must be completed before proposing its lesson', 'Decisions/SupernovaPending.md'),
            (3, 'nondecision_lesson_refused', 'lesson source must be a decision', 'Concepts/LearningNondecision.md'),
            (4, 'missing_lesson_refused', 'no lesson found on decision', 'Decisions/NovaNoLesson.md')):
        case(name, lesson[index]['is_error'] is True and lesson[index]['payload'].get('error') == diagnostic and lesson[index]['payload'].get('path') == relative)
    allowed = {'vault/Decisions/NovaPending.md', 'vault/Decisions/FreshOrion.md'}
    protected = {p: row for p, row in before.items() if p.startswith('toolkit/') or p.startswith('vault/') and p.endswith('.md') and not p.startswith('vault/People/Self-Proposals/')}
    changed = sorted(p for p, row in protected.items() if p not in allowed and after.get(p) != row)
    unexpected = sorted(p for p in after if p.startswith('vault/') and p.endswith('.md') and p not in before and p not in allowed and not p.startswith('vault/People/Self-Proposals/'))
    proposals = [p for p, row in after.items() if p.startswith('vault/People/Self-Proposals/') and row.get('kind') == 'file']
    final = results['final-list'][0]
    self_before = before.get('vault/People/Self.md', {}).get('sha256')
    self_after = sha(retained_observation(fixture / 'vault', 'People/Self.md'))
    preservation = rows['learning.identity_and_sources_preserved']['observed']
    if (preservation.get('self_before_sha256') != self_before or preservation.get('self_after_sha256') != self_after
            or preservation.get('unexpected_changed_sources') != changed or preservation.get('unexpected_new_notes') != unexpected
            or preservation.get('observed_approval_calls') != []):
        raise ValueError('Learning claimed source/Self preservation differs from actual retained bytes')
    final_open = final['payload'].get('open')
    trusted = (final['is_error'] is False and isinstance(final_open, list) and len(final_open) == 1 and isinstance(final_open[0], dict)
        and final_open[0].get('path') == proposal_path and final_open[0].get('id') == lesson[0]['payload'].get('proposal_id') and final_open[0].get('status') == 'draft'
        and proposals == ['vault/' + proposal_path])
    case('identity_and_sources_preserved', self_before == self_after and not changed and not unexpected and trusted
        and preservation.get('unchanged_toolkit') is True and preservation.get('one_trusted_draft_after_invalid_sources') is True
        and preservation.get('editor_outputs_match_frozen_bytes') is True)
    aggregates = {}
    for outcome_id, names, aggregate in (
            ('LEARNING.decision_views', LEARNING_CASES[:7], 'learning.decision_views.complete'),
            ('LEARNING.attributed_lessons', LEARNING_CASES[7:11], 'learning.attributed_lessons.complete')):
        verdict = 'PASS' if all(checks[name] for name in (*names, 'identity_and_sources_preserved')) else 'FAIL'
        aggregates[aggregate] = {'id': aggregate, 'verdict': verdict,
            'observed': {name: checks[name] for name in (*names, 'identity_and_sources_preserved')}}
        if data.get('fixed_outcome_candidates', {}).get(outcome_id) != verdict:
            raise ValueError('Learning declared outcome contradicts complete recomputed behavior: ' + outcome_id)
    if (set(data.get('fixed_outcome_candidates', {})) != {'LEARNING.decision_views', 'LEARNING.attributed_lessons'}
            or data['verdict'] != ('PASS' if all(value['verdict'] == 'PASS' for value in aggregates.values()) else 'FAIL')):
        raise ValueError('Learning aggregate contradicts complete recomputed behavior')
    return {'path': str(path), 'report_sha256': sha(path), 'scope': 'source', 'producer': data['producer'],
        'producer_sha256': data['producer_sha256'], 'support_sha256': data['support_sha256'], 'evidence_files': evidence, 'checks': aggregates}


ADAPTER_REQUIREMENTS['version'] = 'verify-twinaatma.adapters/v8'
ADAPTER_REQUIREMENTS['outcomes'].update({
    'PRIVACY.explicit_policy': ['privacy.policy.complete'],
    'PRIVACY.exposure_scope': ['privacy.exposure.complete'],
    'PRIVACY.external_writes': ['privacy.external.complete']})
ADAPTER_REQUIREMENTS['privacy_producer'] = {
    'producer': 'verify-twinaatma.privacy-source/v1', 'file': 'privacy.py',
    'support': ['data_preservation.py'], 'grader': 'privacy_adapter.py',
    'grader_sha256': sha(Path(__file__).with_name('privacy_adapter.py'))}


def privacy_report(path, current):
    from privacy_adapter import privacy_reports
    return privacy_reports(sys.modules[__name__], path, current)


ADAPTER_REQUIREMENTS['outcomes'].update({
    'LEARNING.semantic_drift': ['longitudinal.semantic_drift.complete'],
    'LEARNING.rejection_recurrence': ['longitudinal.rejection_recurrence.complete'],
})
ADAPTER_REQUIREMENTS['longitudinal_producer'] = {
    'producer': 'verify-twinaatma.longitudinal-source/v1', 'file': 'longitudinal.py',
    'support': ['data_preservation.py', 'case-plan.json'],
    'independent_adapter': 'longitudinal_adapter.py', 'scope': 'longitudinal',
    'outcomes': ['LEARNING.semantic_drift', 'LEARNING.rejection_recurrence'],
}
ADAPTER_REQUIREMENTS['version'] = 'verify-twinaatma.adapters/v9'


def longitudinal_report(path, current):
    from longitudinal_adapter import score
    return score(path, current, root=ROOT)



ADAPTER_REQUIREMENTS['version'] = 'verify-twinaatma.adapters/v12'
ADAPTER_REQUIREMENTS['outcomes'].update({
    'QUALITY.correction_lifecycle': ['advanced_host.QUALITY.correction_lifecycle'],
    'LEARNING.host_outcome_loop': ['advanced_host.LEARNING.host_outcome_loop'],
    'PRIVACY.selective_capture': ['advanced_host.PRIVACY.selective_capture'],
    'PRIVACY.untrusted_notes': ['advanced_host.PRIVACY.untrusted_notes'],
})
ADAPTER_REQUIREMENTS['advanced_host_producer'] = {
    'producer': 'verify-twinaatma.advanced-host-staged/v2',
    'independent_adapter': 'advanced_host_acceptance.py',
    'independent_adapter_sha256': sha(Path(__file__).with_name('advanced_host_acceptance.py')),
    'native_bridge_sha256': sha(Path(__file__).with_name('advanced_host_native.py')),
    'native_rendezvous_sha256': sha(Path(__file__).with_name('native_grader_rendezvous.py')),
    'scope': 'real_host', 'complete_chats': 3,
}


def advanced_host_report(path, current, *, rendezvous=None):
    from advanced_host_native import advanced_host_report as verify_host
    return verify_host(path, current, rendezvous=rendezvous)


ADAPTER_REQUIREMENTS['outcomes']['PORT.same_device_move'] = ['port.same_device_move']
ADAPTER_REQUIREMENTS['installed_move_producer'] = {
    'producer': 'verify-twinaatma.native-installed-move/v3', 'file': 'installed_move.py',
    'producer_sha256': sha(Path(__file__).with_name('installed_move.py')),
    'grader': 'grade_installed_move.py',
    'grader_sha256': sha(Path(__file__).with_name('grade_installed_move.py')),
    'support_sha256': {'native_process.py': sha(Path(__file__).with_name('native_process.py'))},
    'native_bridge_sha256': sha(Path(__file__).with_name('advanced_host_native.py')),
    'native_rendezvous_sha256': sha(Path(__file__).with_name('native_grader_rendezvous.py')),
    'scope': 'artifact', 'outcomes': ['PORT.same_device_move'],
    'required_cells': [['Windows', 'wheel'], ['Windows', 'binary']], 'new_model_calls': 0,
}


def installed_move_report(path, current, *, rendezvous=None):
    from advanced_host_native import installed_move_report as verify_move
    return verify_move(path, current, rendezvous=rendezvous)


def installed_move_matrix(reports):
    cells, identities, seen = set(), {}, set()
    expected = 'A same-device vault move preserves note/link content, retrieval and declared host wiring.'
    for report in reports:
        cell = report.get('artifact_cell')
        if (not isinstance(cell, list) or cell not in (['Windows', 'wheel'], ['Windows', 'binary'])
                or report.get('scope') != 'artifact' or report.get('eligible_outcomes') != ['PORT.same_device_move']
                or report.get('producer') != 'verify-twinaatma.native-installed-move-grade/v2'
                or type(report.get('model_calls')) is not int or report['model_calls'] != 0
                or report.get('verdict') not in ('PASS', 'FAIL')):
            raise ValueError('Installed move matrix contains an unknown cell, scope, producer or verdict')
        cell = tuple(cell)
        identity = report.get('artifact_sha256')
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('Installed move matrix lacks the exact artifact identity')
        if cell in identities and identities[cell] != identity:
            raise ValueError('Installed move matrix contains conflicting artifact bytes for one cell')
        identities[cell] = identity
        cells.add(cell)
        check = report.get('checks', {})
        if (set(check) != {'port.same_device_move'} or check['port.same_device_move'].get('id') != 'port.same_device_move'
                or check['port.same_device_move'].get('verdict') != report['verdict']
                or check['port.same_device_move'].get('expected') != expected):
            raise ValueError('Installed move matrix must contain exactly one consistent port check')
        key = (report.get('path'), report.get('report_sha256'))
        if not all(isinstance(value, str) and value for value in key) or key in seen:
            raise ValueError('Installed move matrix repeats or omits an original report identity')
        seen.add(key)
        bridge = report.get('native_bridge', {})
        if bridge.get('operation') != 'installed-move' or bridge.get('binding', {}).get('report_sha256') != key[1]:
            raise ValueError('Installed move matrix needs freshly bound native grading for each report')
    complete = cells == {('Windows', 'wheel'), ('Windows', 'binary')}
    statuses = {report['verdict'] for report in reports}
    verdict = 'FAIL' if 'FAIL' in statuses else 'PASS' if complete and statuses == {'PASS'} else 'NOT CHECKED'
    observed = {'cells': sorted([list(cell) for cell in cells]), 'required_cells': [['Windows', 'wheel'], ['Windows', 'binary']],
                'complete': complete, 'reports': len(reports), 'new_model_calls': 0}
    return {'path': 'installed-native-move-matrix',
            'report_sha256': hashlib.sha256(json.dumps(reports, sort_keys=True).encode()).hexdigest(),
            'scope': 'artifact', 'producer': ADAPTER_REQUIREMENTS['version'],
            'checks': {'port.same_device_move': {'id': 'port.same_device_move', 'verdict': verdict,
                       'expected': expected, 'observed': observed,
                       'evidence': [report['path'] for report in reports]}}}


ADAPTER_REQUIREMENTS['outcomes']['IDENTITY.all_writers_preserve'] = ['identity.writers.complete']
ADAPTER_REQUIREMENTS['identity_writers_producer'] = {
    'producer': 'verify-twinaatma.identity-writers/v1', 'file': 'identity_writers.py',
    'producer_sha256': sha(Path(__file__).with_name('identity_writers.py')),
    'grader': 'identity_writers_grade.py',
    'grader_sha256': sha(Path(__file__).with_name('identity_writers_grade.py')),
    'support_sha256': {name: sha(Path(__file__).with_name(name)) for name in
                       ('writer_census.py', 'writer_contract.py', 'physical_observer.py')},
    'scope': 'source', 'native_platforms': ['nt', 'posix'],
    'outcomes': ['IDENTITY.all_writers_preserve'],
}


# Each extension grades one producer in its own module, so a new proof never edits this file.
# A module exposes grade(api, paths, current) -> [normalized report]; it may award only the
# check IDs declared here, and only in the declared scope.
EXTENSION_ADAPTERS = {
    'integrity': {'module': 'integrity_adapter', 'scope': 'source',
                  'outcomes': {'IDENTITY.integrity_refusal': ['identity.integrity.complete']}},
    'signing-state': {'module': 'signing_state_adapter', 'scope': 'artifact',
                      'outcomes': {'PORT.missing_signing_state': ['port.missing_signing_state']}},
    'resource-budget': {'module': 'resource_budget_adapter', 'scope': 'performance',
                        'outcomes': {'PORT.measured_resource_budget': ['port.resource_budget']}},
    'clean-restore': {'module': 'clean_restore_adapter', 'scope': 'clean_device',
                      'outcomes': {'PORT.clean_device_restore': ['port.clean_device_restore']}},
    'upgrade-divergence': {'module': 'upgrade_divergence_adapter', 'scope': 'artifact',
                           'outcomes': {'PORT.upgrade_divergence': ['port.upgrade_divergence']}},
}
for _spec in EXTENSION_ADAPTERS.values():
    ADAPTER_REQUIREMENTS['outcomes'].update(_spec['outcomes'])
ADAPTER_REQUIREMENTS['extensions'] = {
    name: {'module': spec['module'] + '.py', 'scope': spec['scope'], 'outcomes': spec['outcomes'],
           'module_sha256': sha(Path(__file__).with_name(spec['module'] + '.py'))
           if Path(__file__).with_name(spec['module'] + '.py').is_file() else None}
    for name, spec in EXTENSION_ADAPTERS.items()}
ADAPTER_REQUIREMENTS['version'] = 'verify-twinaatma.adapters/v13'


def extension_reports(name, paths, current):
    spec = EXTENSION_ADAPTERS.get(name)
    if spec is None:
        raise ValueError('Unknown extension adapter: ' + name)
    if ADAPTER_REQUIREMENTS['extensions'][name]['module_sha256'] is None:
        raise ValueError('Extension adapter module is missing: ' + spec['module'])
    import importlib
    reports = importlib.import_module(spec['module']).grade(sys.modules[__name__], list(paths), current)
    allowed = {check for checks in spec['outcomes'].values() for check in checks}
    for report in reports:
        checks = report.get('checks')
        if (report.get('scope') != spec['scope'] or not isinstance(checks, dict) or not set(checks) <= allowed
                or any(not isinstance(row, dict) or row.get('id') != key or row.get('verdict') not in STATUSES
                       for key, row in checks.items())):
            raise ValueError('Extension adapter ' + name + ' returned an out-of-scope or malformed report')
    return reports


def outcome(item, reports):
    requirements = item["checks"] or ADAPTER_REQUIREMENTS["outcomes"].get(item["id"], [])
    scoped = [r for r in reports if r["scope"] == item["required_scope"]]
    matched = [(r, r["checks"][c]) for r in scoped for c in requirements if c in r["checks"]]
    value = dict(expected=item["expected"], required_scope=item["required_scope"],
                 critical=item["critical"], verdict="NOT CHECKED", evidence=[])
    if not requirements:
        value["reason"] = "No executable adapter proves this complete outcome yet"
        return value
    for report, check in matched:
        value["evidence"].append({"report": report["path"], "report_sha256": report["report_sha256"],
                                  "check_id": check["id"], "verdict": check["verdict"]})
    present = {c["id"] for _, c in matched}
    statuses = {c["verdict"] for _, c in matched}
    if "FAIL" in statuses:
        value["verdict"] = "FAIL"
    elif "BLOCKED" in statuses:
        value["verdict"] = "BLOCKED"
    elif set(requirements) <= present and statuses == {"PASS"}:
        value["verdict"] = "PASS"
    else:
        value["reason"] = "Missing complete scoped proof"
    return value


def validate_baseline(baseline, rubric, rubric_hash):
    ids = {i["id"] for i in rubric["outcomes"]}
    if (baseline.get("rubric_sha256") != rubric_hash or baseline.get("rubric_id") != rubric["rubric_id"]
            or baseline.get("denominator") != rubric["denominator"]
            or set(baseline.get("outcomes", {})) != ids):
        raise ValueError("Baseline rubric or denominator changed; comparison refused")
    rows = baseline["outcomes"]
    if any(row.get("verdict") not in STATUSES for row in rows.values()):
        raise ValueError("Invalid baseline statuses")
    counts = {s: sum(row["verdict"] == s for row in rows.values()) for s in STATUSES}
    if baseline.get("counts") != counts:
        raise ValueError("Baseline counts do not match its observed outcomes")
    expected = round(100 * counts["PASS"] / rubric["denominator"], 6)
    if baseline.get("verified_fulfillment_percent") != expected:
        raise ValueError("Baseline percentage does not match its fixed denominator")


def snapshot(source_paths, host_paths, baseline=None, *, artifact_paths=None, runtime_hook_paths=None, data_paths=None,
             identity_paths=None, quality_paths=None, graph_paths=None, recovery_paths=None, learning_paths=None, privacy_paths=None, longitudinal_paths=None, advanced_host_paths=None, native_rendezvous=None, writers_paths=None, installed_move_paths=None, installed_move_rendezvous=None, extension_paths=None):
    rubric = read_json(RUBRIC)
    items = rubric["outcomes"]
    if len(items) != 54 or rubric.get("denominator") != 54 or len({i["id"] for i in items}) != 54:
        raise ValueError("Fixed v1 rubric denominator must remain 54 unique outcomes")
    rubric_hash = sha(RUBRIC)
    current = product_hashes()
    reports = [source_report(p, current) for p in source_paths] + [host_report(p, current) for p in host_paths]
    artifacts = [artifact_report(p, current) for p in (artifact_paths or [])]
    reports += artifacts
    if artifacts:
        reports.append(artifact_matrix(artifacts))
    hooks = [runtime_hook_report(p, current) for p in (runtime_hook_paths or [])]
    reports += hooks
    if hooks:
        reports.append(runtime_hook_matrix(hooks))
    reports += [data_report(path, current) for path in (data_paths or [])]
    reports += [identity_report(path, current) for path in (identity_paths or [])]
    reports += [quality_report(path, current) for path in (quality_paths or [])]
    reports += [graph_report(path, current) for path in (graph_paths or [])]
    reports += [recovery_report(path, current) for path in (recovery_paths or [])]
    reports += [learning_report(path, current) for path in (learning_paths or [])]
    for path in privacy_paths or []:
        reports += privacy_report(path, current)
    reports += [longitudinal_report(path, current) for path in (longitudinal_paths or [])]
    reports += [advanced_host_report(path, current, rendezvous=native_rendezvous) for path in (advanced_host_paths or [])]
    moves = [installed_move_report(path, current, rendezvous=installed_move_rendezvous) for path in (installed_move_paths or [])]
    reports += [{**report, 'checks': {}} for report in moves]
    if moves:
        reports.append(installed_move_matrix(moves))
    if writers_paths:
        from identity_writers_grade import bundle
        reports.append(bundle(writers_paths, data_paths=data_paths or (), source_paths=source_paths or (),
                              recovery_paths=recovery_paths or (), learning_paths=learning_paths or (),
                              base=sys.modules[__name__], current=current))
    for name, paths in (extension_paths or {}).items():
        reports += extension_reports(name, paths, current)
    outcomes = {item["id"]: outcome(item, reports) for item in items}
    counts = {status: sum(row["verdict"] == status for row in outcomes.values()) for status in STATUSES}
    passed = counts["PASS"]
    result = {"schema_version": 1, "rubric_id": rubric["rubric_id"], "rubric_sha256": rubric_hash,
              "adapter_requirements": ADAPTER_REQUIREMENTS,
              "adapter_requirements_sha256": hashlib.sha256(json.dumps(ADAPTER_REQUIREMENTS, sort_keys=True).encode()).hexdigest(),
              "denominator": 54, "counts": counts, "verified_fulfillment_percent": round(100 * passed / 54, 6),
              "unresolved_percent": round(100 * (54 - passed) / 54, 6),
              "readiness_verdict": "PASS" if passed == 54 else "NOT ACCEPTED",
              "mandatory_vetoes": [key for key, row in outcomes.items() if row["verdict"] != "PASS"],
              "critical_vetoes": [key for key, row in outcomes.items() if row["critical"] and row["verdict"] != "PASS"],
              "product_hashes": current, "scorer_sha256": sha(__file__), "outcomes": outcomes,
              "reports": [{k: v for k, v in r.items() if k != "checks"} for r in reports],
              "limits": ["Fulfillment measures verified outcomes, not probability of quality or percentage of code complete.",
                         "Local executable producers and the evidence recorder are trusted; hashes prove binding, not honesty.",
                         "Only explicit supplied reports count; absent mandatory, human and device evidence never earns PASS.",
                         "Optional Notion release acceptance is outside this core-local denominator."]}
    if baseline is not None:
        old = read_json(baseline)
        validate_baseline(old, rubric, rubric_hash)
        newly = [k for k, v in outcomes.items() if v["verdict"] == "PASS" and old["outcomes"][k]["verdict"] != "PASS"]
        regressed = [k for k, v in outcomes.items() if v["verdict"] != "PASS" and old["outcomes"][k]["verdict"] == "PASS"]
        result["comparison"] = {"baseline": str(baseline), "baseline_sha256": sha(baseline),
                                "newly_verified": newly, "regressed": regressed,
                                "fulfillment_percentage_point_change": round(result["verified_fulfillment_percent"] - old["verified_fulfillment_percent"], 6),
                                "unresolved_percentage_point_change": round(result["unresolved_percent"] - old["unresolved_percent"], 6),
                                "product_changed": old.get("product_hashes") != current}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, action="append", default=[])
    parser.add_argument("--host-report", type=Path, action="append", default=[])
    parser.add_argument("--artifact-report", type=Path, action="append", default=[])
    parser.add_argument("--runtime-hook-report", type=Path, action="append", default=[])
    parser.add_argument("--data-report", type=Path, action="append", default=[])
    parser.add_argument("--identity-report", type=Path, action="append", default=[])
    parser.add_argument("--quality-report", type=Path, action="append", default=[])
    parser.add_argument("--graph-report", type=Path, action="append", default=[])
    parser.add_argument("--recovery-report", type=Path, action="append", default=[])
    parser.add_argument("--learning-report", type=Path, action="append", default=[])
    parser.add_argument("--privacy-report", type=Path, action="append", default=[])
    parser.add_argument("--longitudinal-report", type=Path, action="append", default=[])
    parser.add_argument("--advanced-host-report", type=Path, action="append", default=[])
    parser.add_argument("--advanced-native-rendezvous", type=Path)
    parser.add_argument("--identity-writers-report", type=Path, action="append", default=[])
    parser.add_argument("--installed-move-report", type=Path, action="append", default=[])
    parser.add_argument("--installed-move-native-rendezvous", type=Path)
    parser.add_argument("--extension-report", action="append", default=[], metavar="NAME=PATH",
                        help="Report for one extension adapter: " + ", ".join(EXTENSION_ADAPTERS))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output already exists; preserve snapshots and choose a fresh path")
        extension_paths = {}
        for value in args.extension_report:
            name, separator, path = value.partition("=")
            if not separator or not path:
                raise ValueError("Extension report must be NAME=PATH")
            extension_paths.setdefault(name, []).append(Path(path).absolute())
        result = snapshot([p.resolve() for p in args.source_report], [p.resolve() for p in args.host_report], args.baseline, artifact_paths=[p.resolve() for p in args.artifact_report], runtime_hook_paths=[p.resolve() for p in args.runtime_hook_report], data_paths=[p.absolute() for p in args.data_report], identity_paths=[p.absolute() for p in args.identity_report], quality_paths=[p.absolute() for p in args.quality_report], graph_paths=[p.absolute() for p in args.graph_report], recovery_paths=[p.absolute() for p in args.recovery_report], learning_paths=[p.absolute() for p in args.learning_report], privacy_paths=[p.absolute() for p in args.privacy_report], longitudinal_paths=[p.absolute() for p in args.longitudinal_report], advanced_host_paths=[p.absolute() for p in args.advanced_host_report], native_rendezvous=args.advanced_native_rendezvous, writers_paths=[p.absolute() for p in args.identity_writers_report], installed_move_paths=[p.absolute() for p in args.installed_move_report], installed_move_rendezvous=args.installed_move_native_rendezvous, extension_paths=extension_paths)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print(json.dumps({k: result[k] for k in ("denominator", "counts", "verified_fulfillment_percent",
                                                "unresolved_percent", "readiness_verdict")}, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Acceptance evidence rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
