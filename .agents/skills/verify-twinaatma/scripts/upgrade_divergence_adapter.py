"""Independently grade retained upgrade and device-divergence observations.

The producer (``upgrade_divergence.py``) drives the previous product revision, the
current wheel and the current executable. This module owns the case predicates. It
recomputes every case from the retained command transcripts and snapshots, so an edited
report, transcript or artifact cannot raise a verdict.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

PRODUCER = "verify-twinaatma.upgrade-divergence/v1"
CHECK = "port.upgrade_divergence"
SCOPE = "artifact"
SCOPE_DESCRIPTION = "Exact installed artifact upgrade and two-device divergence on native Windows; no host conversation and no human approval"
OLD_REVISION = "e831fdc1a2070acb15eafe3b6e331d3ec07d071a"
PRODUCER_FILE = "upgrade_divergence.py"
SUPPORT_NAME = "upgrade_divergence_adapter.py"
OBSERVER_NAME = "console-observer.py"
FINAL_TREES = ("upgrade/vault", "upgrade/state", "device-a/vault", "device-a/state", "device-b/vault", "device-b/state")

UPGRADE_CASES = (
    "upgrade.old_baseline",
    "upgrade.installed_current",
    "upgrade.notes_ids_links_preserved",
    "upgrade.self_unchanged",
    "upgrade.recall_works",
    "upgrade.index_rebuilds_automatically",
    "upgrade.pending_proposal_valid_same_device",
    "upgrade.doctor_passes",
    "upgrade.version_schema_reported",
    "upgrade.validate_clean",
    "upgrade.executable_opens_upgraded_vault",
)
DIVERGENCE_CASES = (
    "divergence.devices_prepared",
    "divergence.sync_keeps_both_copies",
    "divergence.no_rewrite",
    "divergence.conflict_copies_searchable",
    "divergence.doctor_flags_conflict_copy",
    "divergence.foreign_proposal_refused",
    "divergence.refusal_hints_propose_again",
    "divergence.proposal_valid_on_origin",
    "divergence.foreign_ledger_fails_closed",
    "divergence.doctor_explains_foreign_ledger",
    "divergence.own_proposal_valid_on_b",
    "divergence.self_unchanged_everywhere",
)
CASE_IDS = UPGRADE_CASES + DIVERGENCE_CASES

EXPECTED = {
    "upgrade.old_baseline": "The previous revision is installed from its own wheel and creates a vault, notes with IDs and links, a capture and a pending proposal",
    "upgrade.installed_current": "Upgrading the same environment in place installs exactly the current product bytes and version",
    "upgrade.notes_ids_links_preserved": "Every note keeps its bytes, ID and relative links through the upgrade and through ordinary current commands",
    "upgrade.self_unchanged": "People/Self.md keeps its exact bytes through the upgrade",
    "upgrade.recall_works": "The current product recalls the old authored note and the old capture by their literal tokens",
    "upgrade.index_rebuilds_automatically": "Ordinary memory calls rebuild the index with no human command and doctor then reports it healthy",
    "upgrade.pending_proposal_valid_same_device": "The pending identity proposal made before the upgrade is still valid on the same device (approval reaches its prompt)",
    "upgrade.doctor_passes": "Doctor on the upgraded vault exits zero, reports PASSED and prints no error line",
    "upgrade.version_schema_reported": "The product reports the installed version and the vault's declared schema so compatibility is visible",
    "upgrade.validate_clean": "Validation of the vault the previous revision created reports no error and supports its declared schema",
    "upgrade.executable_opens_upgraded_vault": "The current executable opens the same upgraded vault, reports the same version, recalls its notes and leaves bytes unchanged",
    "divergence.devices_prepared": "Two vault copies with the same vault ID and separate state directories are driven by the current installed wheel",
    "divergence.sync_keeps_both_copies": "A sync tool that copies both ways keeps both versions of a note both devices edited, the loser as a conflict copy",
    "divergence.no_rewrite": "TwinAatma never rewrites the bytes of either copy or of any other note on either device",
    "divergence.conflict_copies_searchable": "Each version is a separate searchable source on both devices",
    "divergence.doctor_flags_conflict_copy": "Doctor names the conflict copy on both devices",
    "divergence.foreign_proposal_refused": "A proposal made on A and synced to B is refused on B at describe time and B's Self is unchanged",
    "divergence.refusal_hints_propose_again": "The refusal on B tells the person to propose again on that device",
    "divergence.proposal_valid_on_origin": "The same proposal stays valid on A, where it was made, and is listed as pending only there",
    "divergence.foreign_ledger_fails_closed": "A ledger that came from A fails closed on B: the proposal stays refused, rows are rejected and Self is unchanged",
    "divergence.doctor_explains_foreign_ledger": "Doctor on B says the ledger came from another device or install",
    "divergence.own_proposal_valid_on_b": "A new proposal made on B is valid on B even with the foreign ledger rows present",
    "divergence.self_unchanged_everywhere": "Self.md bytes never change on either device and no input is ever sent to an approval prompt",
}

SHARED_NOTE = "Projects/Shared-Plan.md"
CONFLICT_PATTERN = re.compile(r"^Projects/Shared-Plan\.sync-conflict-\d{8}-\d{6}-[A-Z0-9]{7}\.md$")
WINNER_TOKEN = "alphaharbour"
LOSER_TOKEN = "bravoharbour"
ORCHARD_TOKEN = "orchardquince"
CAPTURE_TOKEN = "captureplum"
ORCHARD_NOTE = "Concepts/Orchard-Plan.md"
PROMPT = "[y/N]"
VERSION_PROBE = ("import sys; from pathlib import Path; from knowledgeos.vault_resolve import vault_version_check; "
                 "print(vault_version_check(Path(sys.argv[1])))")

OBSERVER_SOURCE = r'''import json, os, subprocess, sys, time
spec = json.load(open(sys.argv[1], encoding="utf-8"))
record = {"observer_pid": os.getpid(), "stdin_isatty": sys.stdin.isatty(), "input_written": False}
out = open(spec["stdout"], "wb")
err = open(spec["stderr"], "wb")
child = subprocess.Popen(spec["command"], cwd=spec["cwd"], stdout=out, stderr=err)
record["child_pid"] = child.pid
deadline = time.monotonic() + spec["timeout"]
reason = "exited"
while child.poll() is None:
    if time.monotonic() > deadline:
        reason = "timeout"
        break
    try:
        data = open(spec["stdout"], "rb").read()
    except OSError:
        data = b""
    if spec["marker"].encode() in data:
        reason = "prompt_reached"
        break
    time.sleep(0.2)
if child.poll() is None:
    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=30)
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass
record.update(reason=reason, exit_code=child.returncode, stopped=child.poll() is not None)
out.close()
err.close()
json.dump(record, open(spec["record"], "w", encoding="utf-8"))
'''
OBSERVER_SHA256 = hashlib.sha256(OBSERVER_SOURCE.encode("utf-8")).hexdigest()


class MissingEvidence(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def need(condition, message):
    if not condition:
        raise ValueError(message)


def _reparse(info):
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def tree_hashes(root):
    """Hash every regular file below a retained directory; refuse links."""
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not _reparse(info), "Retained tree contains a link: " + str(path))
        if stat.S_ISREG(info.st_mode):
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def _frontmatter_id(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:60]:
        if line.strip() == "---":
            return None
        match = re.match(r"^id:\s*(\S.*?)\s*$", line)
        if match:
            return match.group(1)
    return None


def _links(text):
    found = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        target = target.split("#", 1)[0]
        if target and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            found.append(target)
    return sorted(set(found))


def snapshot(vault):
    """Facts about a vault at one moment: file hashes, note IDs, relative links, Self, marker."""
    vault = Path(vault)
    files = tree_hashes(vault)
    ids, links, resolved = {}, {}, {}
    for rel in files:
        if not rel.endswith(".md") or rel.startswith(".knowledgeos/"):
            continue
        text = (vault / rel).read_text(encoding="utf-8", errors="replace")
        note_id = _frontmatter_id(text)
        if note_id:
            ids[rel] = note_id
        targets = _links(text)
        if targets:
            links[rel] = targets
            resolved[rel] = {}
            for target in targets:
                joined = PurePosixPath(rel).parent.joinpath(target)
                parts = []
                for part in joined.parts:
                    if part == "..":
                        if parts:
                            parts.pop()
                    elif part != ".":
                        parts.append(part)
                resolved[rel][target] = "/".join(parts) in files
    marker = {}
    marker_path = vault / ".knowledgeos-vault.json"
    if marker_path.is_file():
        try:
            loaded = json.loads(marker_path.read_text(encoding="utf-8"))
            marker = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            marker = {}
    return {"files": files, "ids": ids, "links": links, "links_resolved": resolved,
            "self": files.get("People/Self.md"), "marker": marker}


def version_tuple(value):
    return tuple(int(part) for part in re.findall(r"\d+", str(value))[:3])


def wheel_facts(path):
    """Version, member list and module hashes of a wheel, read from its bytes."""
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        metadata = next(n for n in names if n.endswith(".dist-info/METADATA"))
        text = wheel.read(metadata).decode("utf-8", errors="replace")
        version = re.search(r"^Version:\s*(\S+)", text, re.M).group(1)
        modules = {n: digest(wheel.read(n)) for n in names if n.startswith("knowledgeos/") and n.count("/") == 1 and n.endswith(".py")}
    return {"version": version, "members": sorted(names), "modules": modules}


class Evidence:
    """Retained transcripts and snapshots for one report, read by name."""

    def __init__(self, directory, data):
        self.directory = Path(directory)
        self.data = data
        self.calls = {row["label"]: row for row in data.get("calls", [])}
        self.used = set()

    def text(self, name):
        self.used.add(name)
        return (self.directory / name).read_text(encoding="utf-8", errors="replace")

    def snap(self, name):
        try:
            return json.loads(self.text(name + ".json"))
        except OSError as error:
            raise MissingEvidence("missing snapshot " + name) from error

    def call(self, label):
        row = self.calls.get(label)
        if row is None:
            raise MissingEvidence("missing call " + label)
        record = {}
        if row.get("kind") == "console":
            record = json.loads(self.text(row["record"]))
        return SimpleNamespace(label=label, row=row, exit_code=row.get("exit_code"), command=row.get("command", []),
                               stdout=self.text(row["stdout"]), stderr=self.text(row["stderr"]),
                               reason=record.get("reason"), stdin_isatty=record.get("stdin_isatty"),
                               input_written=record.get("input_written"))

    def out(self, label):
        call = self.call(label)
        try:
            value = json.loads(call.stdout)
        except ValueError:
            value = None
        return call, value


def last_object(text):
    """The final top-level JSON object printed by a command (the previous revision prints two)."""
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r"^\{", text, re.M))):
        try:
            value, end = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if not text[match.start() + end:].strip():
            return value
    raise ValueError("No trailing JSON object in command output")


def ranked_paths(value):
    ranked = value.get("ranked") if isinstance(value, dict) else None
    return [row.get("path") for row in ranked or [] if isinstance(row, dict)]


def reached_prompt(call, name):
    return (call.stdin_isatty is True and call.reason == "prompt_reached" and ("Proposal: " + name) in call.stdout
            and PROMPT in call.stdout)


def refused_before_prompt(call):
    return (call.stdin_isatty is True and call.reason == "exited" and call.exit_code == 1 and call.stderr.strip() != ""
            and PROMPT not in call.stdout and "Refusing to approve without an interactive terminal" not in call.stderr)


def notes_only(files):
    return {rel: h for rel, h in files.items() if rel.endswith(".md") and not rel.startswith(".knowledgeos/")}


def p_old_baseline(ev):
    steps = {label: ev.call(label) for label in ("up-old-install", "up-old-version", "up-old-init", "up-old-capture", "up-old-propose")}
    pre = ev.snap("up-pre")
    init = last_object(steps["up-old-init"].stdout)
    capture = last_object(steps["up-old-capture"].stdout)
    proposal = last_object(steps["up-old-propose"].stdout)
    members = ev.data["old_wheel"]["members"]
    observed = {
        "install_exit": steps["up-old-install"].exit_code,
        "old_version": steps["up-old-version"].stdout.strip(),
        "init_ok": steps["up-old-init"].exit_code == 0 and init.get("post_init", {}).get("rebuild", {}).get("ok") is True,
        "capture_path": capture.get("path"),
        "proposal_path": proposal.get("proposal_path"),
        "proposal_mutated_self": proposal.get("mutated_self"),
        "authored_ids": sorted(pre["ids"].get(n, "") for n in (ORCHARD_NOTE, "Projects/Harvest.md")),
        "old_wheel_has_gate": "knowledgeos/gate.py" in members,
        "installed_old_wheel": steps["up-old-install"].command[-1] == ev.data["old_wheel"]["path"],
    }
    passed = (observed["install_exit"] == 0 and observed["old_version"] == "0.4.0-dev" and observed["init_ok"]
              and str(observed["capture_path"]).startswith("Inbox/") and str(observed["proposal_path"]).startswith("People/Self-Proposals/")
              and observed["proposal_mutated_self"] is False
              and observed["authored_ids"] == ["kos:concept:orchard-plan", "kos:project:harvest"]
              and observed["proposal_path"] in pre["files"] and not observed["old_wheel_has_gate"] and observed["installed_old_wheel"])
    return passed, observed


def p_installed_current(ev):
    install = ev.call("up-new-install")
    version = ev.call("up-new-version")
    installed = ev.snap("up-installed")
    current = {Path(p).name: h for p, h in ev.data["product_hashes"].items() if p.startswith("knowledgeos/")}
    wheel_version = ev.data["artifacts"]["wheel"]["version"]
    observed = {"install_exit": install.exit_code, "replaced_old": ("Uninstalling twinaatma-" + ev.data["old_wheel"]["version"]) in install.stdout,
                "installed_version": version.stdout.strip(), "wheel_version": wheel_version,
                "modules_match_current": installed.get("modules") == current,
                "installed_current_wheel": install.command[-1] == ev.data["artifacts"]["wheel"]["artifact_path"],
                "same_environment": bool(version.command) and version.command[0] == ev.call("up-old-version").command[0]}
    passed = (install.exit_code == 0 and observed["replaced_old"] and observed["installed_current_wheel"] and observed["same_environment"] and version.exit_code == 0
              and observed["installed_version"] == wheel_version and observed["modules_match_current"])
    return passed, observed


def p_notes_preserved(ev):
    pre, post, after_exe = ev.snap("up-pre"), ev.snap("up-post"), ev.snap("up-post-exe")
    before = notes_only(pre["files"])
    changed = {}
    for label, later in (("post_upgrade", post), ("post_executable", after_exe)):
        now = notes_only(later["files"])
        changed[label] = sorted(rel for rel, h in before.items() if now.get(rel) != h)
    ids_same = all(post["ids"].get(rel) == value and after_exe["ids"].get(rel) == value for rel, value in pre["ids"].items())
    links_same = all(post["links"].get(rel) == value and after_exe["links"].get(rel) == value for rel, value in pre["links"].items())
    authored = (ORCHARD_NOTE, "Projects/Harvest.md")
    relative_ok = all(rel in pre["links_resolved"] and rel in post["links_resolved"] and all(pre["links_resolved"][rel].values())
                      and all(post["links_resolved"][rel].values()) for rel in authored)
    observed = {"notes_before": len(before), "changed": changed, "ids_same": ids_same, "links_same": links_same,
                "relative_links_resolve": relative_ok, "authored_links": sorted(rel for rel in pre["links"] if rel in authored)}
    passed = (len(before) > 0 and not changed["post_upgrade"] and not changed["post_executable"] and ids_same and links_same
              and relative_ok and len(observed["authored_links"]) == 2)
    return passed, observed


def p_self_unchanged(ev):
    pre, post, after_exe = ev.snap("up-pre"), ev.snap("up-post"), ev.snap("up-post-exe")
    observed = {"before": pre["self"], "after_upgrade": post["self"], "after_executable": after_exe["self"]}
    return pre["self"] is not None and pre["self"] == post["self"] == after_exe["self"], observed


def p_recall(ev):
    _, orchard = ev.out("up-search-orchard")
    _, capture = ev.out("up-search-capture")
    orchard_paths, capture_paths = ranked_paths(orchard), ranked_paths(capture)
    captured = json.loads(ev.call("up-old-capture").stdout).get("path")
    observed = {"orchard_paths": orchard_paths, "capture_paths": capture_paths, "captured": captured}
    return ORCHARD_NOTE in orchard_paths and captured in capture_paths, observed


ORDINARY_PREFIXES = ("up-new-", "up-search", "up-doctor", "up-validate", "up-pending", "up-list", "up-approve", "exe-")


def p_index_rebuilds(ev):
    ordinary = [row for row in ev.data["calls"] if row["label"].startswith(ORDINARY_PREFIXES)]
    manual = [row["label"] for row in ordinary if any(word in " ".join(map(str, row["command"])).lower() for word in ("rebuild", "reindex"))]
    after = ev.call("up-doctor-after")
    post = ev.snap("up-post")
    observed = {"human_index_commands": manual, "ordinary_calls": len(ordinary), "doctor_after_healthy": "[OK] Index healthy" in after.stdout,
                "index_file_present": "knowledge_index.db" in post["files"],
                "doctor_before_index_lines": [line.strip() for line in ev.call("up-doctor-before").stdout.splitlines() if "ndex" in line]}
    passed = bool(ordinary) and not manual and observed["doctor_after_healthy"] and observed["index_file_present"]
    return passed, observed


def p_pending_valid(ev):
    old = json.loads(ev.call("up-old-propose").stdout).get("proposal_path", "")
    approve = ev.call("up-approve")
    pending = ev.call("up-pending")
    listed = ev.out("up-list-proposals")[1] or {}
    name = Path(old).name
    observed = {"proposal": old, "stdin_isatty": approve.stdin_isatty, "reason": approve.reason, "exit_code": approve.exit_code,
                "refusal": approve.stderr.strip().splitlines()[:2], "pending_output": pending.stdout.strip().splitlines()[:2],
                "open": listed.get("open"), "untrusted": listed.get("untrusted")}
    return reached_prompt(approve, name), observed


def p_doctor_passes(ev):
    doctor = ev.call("up-doctor-after")
    errors = [line.strip() for line in doctor.stdout.splitlines() if "[ERROR]" in line]
    observed = {"exit_code": doctor.exit_code, "passed_line": "Environment check PASSED" in doctor.stdout, "error_lines": errors,
                "warning_lines": len([line for line in doctor.stdout.splitlines() if "[WARNING]" in line])}
    return doctor.exit_code == 0 and observed["passed_line"] and not errors, observed


def p_version_schema(ev):
    doctor = ev.call("up-doctor-after")
    pre = ev.snap("up-pre")
    version = ev.data["artifacts"]["wheel"]["version"]
    schema = str(pre["marker"].get("schema", ""))
    lines = [line for line in doctor.stdout.splitlines()
             if not line.startswith("Vault Root:") and "site-packages" not in line and "gate.key" not in line]
    text = "\n".join(lines)
    probe = ev.call("up-version-check")
    observed = {"installed_version": version, "vault_schema": schema, "vault_declared_minimum": pre["marker"].get("toolkit_min_version"),
                "doctor_mentions_version": version in text, "doctor_mentions_schema": bool(schema) and schema in text,
                "library_compatibility_check": probe.stdout.strip(), "probe_is_reviewed_code": probe.command[-2:-1] == [VERSION_PROBE]}
    passed = (bool(schema) and observed["doctor_mentions_version"] and observed["doctor_mentions_schema"]
              and probe.exit_code == 0 and observed["library_compatibility_check"] == "None" and observed["probe_is_reviewed_code"])
    return passed, observed


def p_validate_clean(ev):
    call, report = ev.out("up-validate")
    pre = ev.snap("up-pre")
    schema = pre["marker"].get("schema")
    report = report if isinstance(report, dict) else {}
    observed = {"exit_code": call.exit_code, "errors": report.get("errors"), "supports_vault_schema": schema in (report.get("supported_schemas") or []),
                "vault_schema": schema}
    return call.exit_code == 0 and report.get("errors") == [] and observed["supports_vault_schema"], observed


def p_executable(ev):
    version = ev.call("exe-version")
    doctor = ev.call("exe-doctor")
    _, search = ev.out("exe-search")
    pending = ev.call("exe-pending")
    pre, after_exe = ev.snap("up-pre"), ev.snap("up-post-exe")
    binary = ev.data["artifacts"]["binary"]
    same_vault = all(row["command"] and str(row["command"][0]) == binary["executable"] for row in (version.row, doctor.row, pending.row, ev.calls["exe-search"]))
    unchanged = all(after_exe["files"].get(rel) == h for rel, h in notes_only(pre["files"]).items()) and pre["self"] == after_exe["self"]
    observed = {"same_executable": same_vault, "version": version.stdout.strip(), "wheel_version": ev.data["artifacts"]["wheel"]["version"],
                "doctor_exit": doctor.exit_code, "search_paths": ranked_paths(search), "pending_exit": pending.exit_code, "bytes_unchanged": unchanged}
    passed = (same_vault and version.exit_code == 0 and observed["version"] == observed["wheel_version"] and doctor.exit_code == 0
              and ORCHARD_NOTE in observed["search_paths"] and pending.exit_code == 0 and unchanged)
    return passed, observed


def p_devices(ev):
    prepared = ev.snap("dv-prepared")
    init = ev.call("dv-a-init")
    a, b = prepared["device_a"], prepared["device_b"]
    observed = {"init_exit": init.exit_code, "vault_ids_equal": bool(a["vault_id"]) and a["vault_id"] == b["vault_id"],
                "vault_dirs_distinct": a["vault"] != b["vault"], "state_dirs_distinct": a["state"] != b["state"],
                "signing_keys_distinct": bool(a["key_sha256"]) and bool(b["key_sha256"]) and a["key_sha256"] != b["key_sha256"],
                "copy_identical_at_start": prepared["copy_tree_equal"], "executable": prepared["executable"],
                "executable_is_wheel": prepared["executable"] == ev.data["artifacts"]["wheel"]["executable"],
                "all_calls_use_wheel": all(str(row["command"][0]) == ev.data["artifacts"]["wheel"]["executable"]
                                           for row in ev.data["calls"] if row["label"].startswith("dv-"))}
    passed = (init.exit_code == 0 and observed["vault_ids_equal"] and observed["vault_dirs_distinct"] and observed["state_dirs_distinct"]
              and observed["signing_keys_distinct"] and observed["copy_identical_at_start"] and observed["executable_is_wheel"]
              and observed["all_calls_use_wheel"])
    return passed, observed


def p_sync(ev):
    pre_a, pre_b = ev.snap("dv-pre-sync-a"), ev.snap("dv-pre-sync-b")
    done_a, done_b = ev.snap("dv-synced-a"), ev.snap("dv-synced-b")
    ev.snap("dv-sync")
    a_capture = json.loads(ev.call("dv-a-capture").stdout).get("path")
    b_capture = json.loads(ev.call("dv-b-capture").stdout).get("path")
    conflicts = sorted(rel for rel in done_a["files"] if CONFLICT_PATTERN.match(rel))
    same_names = conflicts == sorted(rel for rel in done_b["files"] if CONFLICT_PATTERN.match(rel))
    winner, loser = pre_a["files"].get(SHARED_NOTE), pre_b["files"].get(SHARED_NOTE)
    observed = {"conflict_copies": conflicts, "same_on_both": same_names, "edited_versions_differ": bool(winner) and winner != loser,
                "winner_on_a": done_a["files"].get(SHARED_NOTE) == winner, "winner_on_b": done_b["files"].get(SHARED_NOTE) == winner,
                "loser_copy_on_a": bool(conflicts) and done_a["files"].get(conflicts[0]) == loser,
                "loser_copy_on_b": bool(conflicts) and done_b["files"].get(conflicts[0]) == loser,
                "a_capture_on_b": bool(a_capture) and done_b["files"].get(a_capture) == pre_a["files"].get(a_capture),
                "b_capture_on_a": bool(b_capture) and done_a["files"].get(b_capture) == pre_b["files"].get(b_capture)}
    passed = (len(conflicts) == 1 and same_names and observed["edited_versions_differ"] and observed["winner_on_a"] and observed["winner_on_b"]
              and observed["loser_copy_on_a"] and observed["loser_copy_on_b"] and observed["a_capture_on_b"] and observed["b_capture_on_a"])
    return passed, observed


def p_no_rewrite(ev):
    result = {}
    for device in ("a", "b"):
        synced, ops, final = ev.snap("dv-synced-" + device), ev.snap("dv-ops-" + device), ev.snap("dv-final-" + device)
        before = notes_only(synced["files"])
        result[device] = {
            "changed_after_reads": sorted(rel for rel, h in before.items() if notes_only(ops["files"]).get(rel) != h),
            "changed_by_end": sorted(rel for rel, h in before.items() if notes_only(final["files"]).get(rel) != h),
            "conflict_copies_kept": sorted(rel for rel in final["files"] if CONFLICT_PATTERN.match(rel)),
            "notes_checked": len(before)}
    passed = all(not row["changed_after_reads"] and not row["changed_by_end"] and len(row["conflict_copies_kept"]) == 1
                 and row["notes_checked"] > 0 for row in result.values())
    return passed, result


def p_searchable(ev):
    synced = ev.snap("dv-synced-a")
    conflicts = sorted(rel for rel in synced["files"] if CONFLICT_PATTERN.match(rel))
    result = {"conflict_copies": conflicts}
    passed = len(conflicts) == 1
    for device in ("a", "b"):
        _, winner = ev.out("dv-%s-search-winner" % device)
        _, loser = ev.out("dv-%s-search-loser" % device)
        winner_paths, loser_paths = ranked_paths(winner), ranked_paths(loser)
        row = {"winner_token_paths": winner_paths, "loser_token_paths": loser_paths}
        passed = passed and bool(conflicts) and SHARED_NOTE in winner_paths and conflicts[0] not in winner_paths \
            and conflicts[0] in loser_paths and SHARED_NOTE not in loser_paths
        result[device] = row
    return passed, result


def p_doctor_conflict(ev):
    synced = ev.snap("dv-synced-a")
    conflicts = sorted(rel for rel in synced["files"] if CONFLICT_PATTERN.match(rel))
    result = {"conflict_copies": conflicts}
    passed = len(conflicts) == 1
    for device in ("a", "b"):
        doctor = ev.call("dv-%s-doctor" % device)
        text = doctor.stdout
        row = {"exit_code": doctor.exit_code, "names_conflict_copy": bool(conflicts) and (conflicts[0] in text or Path(conflicts[0]).name in text),
               "says_conflict": "conflict" in text.lower()}
        passed = passed and row["names_conflict_copy"] and row["says_conflict"]
        result[device] = row
    return passed, result


def proposal_name(ev, label):
    return Path(json.loads(ev.call(label).stdout).get("proposal_path", "")).name


def p_foreign_refused(ev):
    refused = ev.call("dv-b-approve-pa")
    first, last = ev.snap("dv-prepared"), ev.snap("dv-final-b")
    observed = {"stdin_isatty": refused.stdin_isatty, "reason": refused.reason, "exit_code": refused.exit_code,
                "refusal": refused.stderr.strip().splitlines(), "prompt_reached": PROMPT in refused.stdout,
                "self_unchanged": first["device_b"]["self"] == last["self"]}
    return refused_before_prompt(refused) and observed["self_unchanged"], observed


def p_hint(ev):
    refused = ev.call("dv-b-approve-pa")
    text = refused.stderr
    pattern = re.compile(r"propos\w*[^.\n]{0,40}\bagain\b|\bagain\b[^.\n]{0,40}propos|new proposal", re.I)
    observed = {"stderr": text.strip().splitlines(), "hint_to_propose_again": bool(pattern.search(text))}
    return refused_before_prompt(refused) and observed["hint_to_propose_again"], observed


def p_origin_valid(ev):
    name = proposal_name(ev, "dv-a-propose")
    approve = ev.call("dv-a-approve-pa")
    a_pending, b_pending = ev.call("dv-a-pending"), ev.call("dv-b-pending")
    observed = {"proposal": name, "reason": approve.reason, "stdin_isatty": approve.stdin_isatty,
                "listed_on_a": name in a_pending.stdout, "listed_on_b": name in b_pending.stdout}
    return reached_prompt(approve, name) and observed["listed_on_a"] and not observed["listed_on_b"], observed


def p_ledger_closed(ev):
    approve = ev.call("dv-b-approve-ledger")
    pending = ev.call("dv-b-pending-ledger")
    _, listed = ev.out("dv-b-list-ledger")
    copy = ev.snap("dv-ledger-copy")
    listed = listed if isinstance(listed, dict) else {}
    name = proposal_name(ev, "dv-a-propose")
    first, last = ev.snap("dv-prepared"), ev.snap("dv-final-b")
    observed = {"ledger_copied": copy.get("copied") is True, "approve_reason": approve.reason, "approve_exit": approve.exit_code,
                "approve_refusal": approve.stderr.strip().splitlines(), "pending_stdout": pending.stdout.strip().splitlines(),
                "rejected_rows_warning": "failed signature" in pending.stderr, "open": listed.get("open"),
                "untrusted": listed.get("untrusted"), "self_unchanged": first["device_b"]["self"] == last["self"]}
    passed = (observed["ledger_copied"] and refused_before_prompt(approve) and observed["rejected_rows_warning"]
              and listed.get("open") == [] and any(name in str(item) for item in listed.get("untrusted") or []) and observed["self_unchanged"])
    return passed, observed


def p_doctor_ledger(ev):
    doctor = ev.call("dv-b-doctor-ledger")
    lines = [line.strip() for line in doctor.stdout.splitlines() if "ledger" in line.lower() or "signature" in line.lower()]
    pattern = re.compile(r"\b(another|different|other)\b[^.\n]{0,24}\b(device|install|machine|computer)\b", re.I)
    observed = {"exit_code": doctor.exit_code, "ledger_lines": lines, "explains_other_device": bool(pattern.search(doctor.stdout))}
    return observed["explains_other_device"], observed


def p_own_valid(ev):
    name = proposal_name(ev, "dv-b-propose")
    approve = ev.call("dv-b-approve-own")
    pending = ev.call("dv-b-pending-own")
    observed = {"proposal": name, "reason": approve.reason, "stdin_isatty": approve.stdin_isatty,
                "listed_on_b": name in pending.stdout, "pa_listed_on_b": proposal_name(ev, "dv-a-propose") in pending.stdout}
    return reached_prompt(approve, name) and observed["listed_on_b"] and not observed["pa_listed_on_b"], observed


def p_self_everywhere(ev):
    result = {}
    passed = True
    for device in ("a", "b"):
        values = [ev.snap(name)["self"] for name in ("dv-init-" + device, "dv-synced-" + device, "dv-ops-" + device, "dv-final-" + device)]
        result[device] = values
        passed = passed and values[0] is not None and len(set(values)) == 1
    consoles = [row for row in ev.data["calls"] if row.get("kind") == "console"]
    writes = [row["label"] for row in consoles if ev.call(row["label"]).input_written is not False]
    result["console_calls"] = len(consoles)
    result["calls_with_input"] = writes
    return passed and len(consoles) >= 5 and not writes, result


PREDICATES = {
    "upgrade.old_baseline": p_old_baseline,
    "upgrade.installed_current": p_installed_current,
    "upgrade.notes_ids_links_preserved": p_notes_preserved,
    "upgrade.self_unchanged": p_self_unchanged,
    "upgrade.recall_works": p_recall,
    "upgrade.index_rebuilds_automatically": p_index_rebuilds,
    "upgrade.pending_proposal_valid_same_device": p_pending_valid,
    "upgrade.doctor_passes": p_doctor_passes,
    "upgrade.version_schema_reported": p_version_schema,
    "upgrade.validate_clean": p_validate_clean,
    "upgrade.executable_opens_upgraded_vault": p_executable,
    "divergence.devices_prepared": p_devices,
    "divergence.sync_keeps_both_copies": p_sync,
    "divergence.no_rewrite": p_no_rewrite,
    "divergence.conflict_copies_searchable": p_searchable,
    "divergence.doctor_flags_conflict_copy": p_doctor_conflict,
    "divergence.foreign_proposal_refused": p_foreign_refused,
    "divergence.refusal_hints_propose_again": p_hint,
    "divergence.proposal_valid_on_origin": p_origin_valid,
    "divergence.foreign_ledger_fails_closed": p_ledger_closed,
    "divergence.doctor_explains_foreign_ledger": p_doctor_ledger,
    "divergence.own_proposal_valid_on_b": p_own_valid,
    "divergence.self_unchanged_everywhere": p_self_everywhere,
}
assert tuple(PREDICATES) == CASE_IDS and set(EXPECTED) == set(CASE_IDS)


def evaluate(ev, case_id):
    """Return (passed, observed). Missing or malformed evidence is a FAIL, never a PASS."""
    ev.used = set()
    try:
        passed, observed = PREDICATES[case_id](ev)
    except MissingEvidence as error:
        return False, {"error": str(error)}
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, StopIteration) as error:
        return False, {"error": type(error).__name__ + ": " + str(error)}
    return bool(passed), json.loads(json.dumps(observed, sort_keys=True))


def case_row(ev, case_id):
    passed, observed = evaluate(ev, case_id)
    return {"id": case_id, "verdict": "PASS" if passed else "FAIL", "expected": EXPECTED[case_id], "observed": observed,
            "evidence": sorted(ev.used)}


def literal_cases(producer):
    tree = ast.parse(Path(producer).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CASE_IDS" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise ValueError("Producer has no literal CASE_IDS")


def stable(value):
    return json.dumps(value, sort_keys=True)


def grade(api, paths, current):
    return [grade_report(api, Path(path), current) for path in paths]


def grade_report(api, path, current, data=None):
    """Grade one report. ``data`` lets a test grade an altered in-memory copy of the report at ``path``."""
    path = api.retained_file(str(path))
    data = api.read_json(path) if data is None else data
    directory = path.parent
    need(isinstance(data, dict) and data.get("producer") == PRODUCER, "Unsupported upgrade-divergence producer")
    producer = Path(__file__).with_name(PRODUCER_FILE)
    need(producer.is_file() and data.get("producer_sha256") == api.sha(producer), "Upgrade-divergence producer hash missing or stale")
    need(data.get("support") == {SUPPORT_NAME: api.sha(__file__)}, "Upgrade-divergence support hash missing or stale")
    api.check_product(data, "product_hashes", current)
    need(data.get("scope") == SCOPE and data.get("scope_description") == SCOPE_DESCRIPTION, "Report scope was changed")
    for field in ("artifacts_unchanged", "product_unchanged", "all_started_processes_stopped"):
        need(data.get(field) is True, "Stability is not substantiated: " + field)
    isolation = data.get("isolation", {})
    need(isolation.get("before") and isolation.get("before") == isolation.get("after") and isolation.get("unchanged") is True,
         "Isolation sentinels changed or are absent")
    need(isinstance(data.get("artifacts"), dict) and set(data["artifacts"]) == {"wheel", "binary"}, "Wheel and executable artifact references are required")
    wheel_version = None
    for kind, ref in data["artifacts"].items():
        report_path = api.retained_file(ref["report"])
        need(api.sha(report_path) == ref["report_sha256"], "Artifact report changed: " + kind)
        raw = api.read_json(report_path)
        scored = api.artifact_report(report_path, current)
        need(scored["cell"][1] == kind and raw["artifact"]["kind"] == kind and raw.get("verdict") == "PASS", "Artifact report is not a passing " + kind + " install")
        artifact_file = api.retained_file(raw["artifact"]["path"])
        need(api.sha(artifact_file) == raw["artifact"]["sha256"] == ref["artifact_sha256"], "Artifact bytes differ from their report: " + kind)
        executable = api.retained_file(raw["installation"]["executable"])
        need(str(executable) == ref["executable"] or str(raw["installation"]["executable"]) == ref["executable"], "Executable differs from its report: " + kind)
        need(api.sha(executable) == ref["executable_sha256"], "Executable bytes differ from their report: " + kind)
        if kind == "wheel":
            facts = wheel_facts(artifact_file)
            need(facts["version"] == ref["version"], "Wheel version differs from its report")
            wheel_version = facts["version"]
    old = data.get("old_wheel", {})
    old_file = api.retained_file(old.get("path"))
    need(api.sha(old_file) == old.get("sha256"), "Previous-revision wheel bytes changed")
    old_facts = wheel_facts(old_file)
    need(old_facts["version"] == old.get("version") and old_facts["members"] == old.get("members"), "Previous-revision wheel contents differ from the report")
    need(version_tuple(old_facts["version"]) <= version_tuple(wheel_version) and old_facts["version"] != wheel_version, "Previous wheel is not older than the current wheel")
    need(old_facts["modules"].get("knowledgeos/memory.py") != current.get("knowledgeos/memory.py"), "Previous wheel carries current product bytes")
    need(old.get("revision") == OLD_REVISION, "Previous revision identity changed")

    transcripts = data.get("transcript_files")
    need(isinstance(transcripts, dict) and transcripts, "Hashed transcripts are required")
    for name, expected in transcripts.items():
        need(Path(name).name == name, "Evidence name is not flat: " + name)
        need(api.sha(api.file_evidence(directory, name)) == expected, "Evidence changed: " + name)
    need(OBSERVER_NAME in transcripts and transcripts[OBSERVER_NAME] == OBSERVER_SHA256, "Console observer is not the reviewed observer")
    need(data.get("expected_case_ids") == list(CASE_IDS) == list(literal_cases(producer)), "Case plan differs from the frozen literal list")
    need("case-plan.json" in transcripts and json.loads((directory / "case-plan.json").read_text(encoding="utf-8")) == list(CASE_IDS),
         "Frozen case plan is missing or altered")

    calls = data.get("calls")
    need(isinstance(calls, list) and calls, "Retained command records are required")
    labels = [row.get("label") for row in calls]
    need(len(labels) == len(set(labels)), "Duplicate command label")
    processes = data.get("processes")
    need(isinstance(processes, list) and processes and all(isinstance(p, dict) and p.get("stopped") is True for p in processes),
         "Process shutdown is not substantiated")
    pids = {(p.get("role"), p.get("pid")) for p in processes}
    for row in calls:
        for field in ("stdout", "stderr", "record"):
            need(row.get(field) in transcripts, "Unhashed command evidence: " + str(row.get("label")))
        need(row.get("stopped") is True and isinstance(row.get("pid"), int) and row["pid"] > 0, "Command process is not stopped: " + str(row.get("label")))
        need((row["label"], row["pid"]) in pids, "Command process is not recorded: " + row["label"])
        retained = json.loads((directory / row["record"]).read_text(encoding="utf-8"))
        if row.get("kind") == "console":
            need(retained.get("child_pid") == row.get("child_pid") and retained.get("stopped") is True
                 and retained.get("exit_code") == row.get("exit_code") and retained.get("observer_pid") == row["pid"],
                 "Console record differs from its retained observation: " + row["label"])
            need((row["label"] + "-child", retained["child_pid"]) in pids, "Console child is not recorded: " + row["label"])
        else:
            need(retained.get("command") == row.get("command") and retained.get("exit_code") == row.get("exit_code")
                 and retained.get("pid") == row.get("pid"), "Command record differs from its retained record: " + row["label"])
    need(set(data.get("final_trees") or {}) == set(FINAL_TREES), "Retained vault trees are incomplete")
    for name, hashes in data["final_trees"].items():
        target = directory / name
        need(target.is_dir() or not hashes, "Retained tree is missing: " + name)
        need((tree_hashes(target) if target.is_dir() else {}) == hashes, "Retained state changed after the run: " + name)

    evidence = Evidence(directory, data)
    rows = data.get("cases")
    need(isinstance(rows, list) and [row.get("id") for row in rows] == list(CASE_IDS), "Missing, extra or reordered cases")
    results = {}
    for row in rows:
        recomputed = case_row(evidence, row["id"])
        need(all(name in transcripts for name in recomputed["evidence"]), "Case cites unhashed evidence: " + row["id"])
        need(stable(row) == stable(recomputed), "Report case contradicts its retained evidence: " + row["id"])
        results[row["id"]] = recomputed["verdict"]
    failed = sorted(case for case, verdict in results.items() if verdict != "PASS")
    verdict = "PASS" if not failed and not data.get("execution_errors") else "FAIL"
    need(data.get("verdict") == verdict, "Report verdict contradicts its recomputed cases")
    check = {"id": CHECK, "verdict": verdict,
             "expected": "Upgrades preserve data and compatibility, and divergent devices follow the approved device-local conflict and approval policy",
             "observed": {"cases": len(results), "passed": len(results) - len(failed), "failed": failed},
             "evidence": [str(path)]}
    return {"path": str(path), "report_sha256": api.sha(path), "scope": SCOPE, "producer": PRODUCER,
            "producer_sha256": api.sha(producer), "case_results": results, "checks": {CHECK: check}}
