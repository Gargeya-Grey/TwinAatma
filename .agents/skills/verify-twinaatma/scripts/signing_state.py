"""Observe lost and restored Self-approval signing state through an installed Windows artifact.

The producer drives the exact installed launcher named by a passing artifact report: the
CLI and the MCP server (NDJSON over stdio) run in a synthetic vault with an isolated
state directory. It records raw evidence only. ``evaluate`` turns that evidence into the
literal cases; the independent grader recomputes the same cases from the retained files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
PRODUCER = "verify-twinaatma.signing-state/v1"
ARTIFACT_PRODUCER = "verify-twinaatma.artifact/v1"
SUPPORT = ("artifact.py",)
KEY_FILE, BINDING_FILE = "gate.key", "vault-bindings.json"
STATE_FILES = (KEY_FILE, BINDING_FILE)
CREATE_NEW_CONSOLE = 0x00000010
CONSOLE_DEADLINE = 90

CASE_NAMES = ("baseline_pending_valid", "present_no_tty_refused", "lost_memory_works", "lost_old_approval_refused",
              "lost_doctor_honest", "lost_identity_and_ledger_intact", "new_proposal_valid_old_refused",
              "restore_old_valid_again", "identity_and_isolation_preserved")
CASE_IDS = tuple("signing." + name for name in CASE_NAMES)
EXPECTED = {
    "baseline_pending_valid": "With signing state present, two MCP proposals are signed, pending, listed and backed up; Self is unchanged",
    "present_no_tty_refused": "The approval command refuses without an interactive terminal and applies nothing",
    "lost_memory_works": "After the key and binding files are removed, session start, capture and search still work",
    "lost_old_approval_refused": "A real hidden console reaches a plain-language refusal with a recovery hint for the old proposal, with no traceback and no prompt",
    "lost_doctor_honest": "Doctor reports the lost signing state, the ignored rows and the unapprovable proposals instead of a healthy ledger",
    "lost_identity_and_ledger_intact": "Self, proposal files and ledger bytes stay unchanged, nothing is listed as valid, and the MCP accept tool refuses",
    "new_proposal_valid_old_refused": "A proposal made after the loss is valid under the new state while the old one stays refused and its ledger line is kept",
    "restore_old_valid_again": "Restoring the retained original state makes the old pending proposals valid again without rewriting the ledger",
    "identity_and_isolation_preserved": "Self bytes never change, no proposal is applied or edited, and no ledger row is ever marked applied",
}
STEPS = ("init", "propose", "list-0", "pending-0", "doctor-0", "approve-notty", "lost-memory", "approve-lost-A",
         "doctor-lost", "pending-lost", "list-lost", "propose-new", "list-new", "pending-new", "approve-new-A",
         "list-restored", "pending-restored", "doctor-restored")
EXPLAINED = re.compile(r"(?i)not registered|cannot be (?:approved|verified)|can't|refus|not valid|invalid|unverif")
RECOVERY = re.compile(r"(?i)\b(?:restore|backup|re-?propos\w*|propose (?:it )?again|new proposal|create a new|signing key|key file|recover\w*)\b")
CAUSE = re.compile(r"(?i)(?:signing|gate|approval)[ -]?(?:key|state)[^\n]*\b(?:missing|lost|absent|not found|regenerated|recreated|replaced|new)\b"
                   r"|\b(?:missing|lost|absent|regenerated|recreated|replaced|new)\b[^\n]*(?:signing|gate|approval)[ -]?(?:key|state)")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def product_hashes():
    paths = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT / "AGENTS.md"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file()}


def support_hashes():
    return {name: sha(Path(__file__).with_name(name)) for name in SUPPORT}


def plain(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Linked paths are not accepted: " + str(path))
    return path.resolve(strict=True)


def link_free_tree(root):
    files = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("Linked distribution member: " + str(path))
        if path.is_file():
            files[path.relative_to(root).as_posix()] = sha(path)
    return files


# --------------------------------------------------------------------------- #
# evaluation: pure functions over retained evidence
# --------------------------------------------------------------------------- #


class Evidence:
    """Read-only view of one run directory's flat evidence files."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def text(self, name):
        return (self.directory / name).read_text(encoding="utf-8", errors="replace")

    def json(self, name):
        return json.loads(self.text(name))

    def command(self, label):
        return self.json(label + ".command.json")

    def stdout(self, label):
        return self.text(label + ".stdout.txt")

    def stderr(self, label):
        return self.text(label + ".stderr.txt")

    def snap(self, number):
        return self.json("snap-%d.json" % number)

    def ledger(self, number):
        name = "snap-%d.ledger.jsonl" % number
        if not (self.directory / name).is_file():
            return []
        lines = [line for line in self.text(name).splitlines() if line.strip()]
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                row = {}
            rows.append({"sha256": sha_text(line), "proposal": row.get("proposal") if isinstance(row, dict) else None,
                         "status": row.get("status") if isinstance(row, dict) else None,
                         "applied": isinstance(row, dict) and ("applied_at" in row or "authorized_by" in row)})
        return rows

    def mcp(self, label, count):
        record = self.command(label)
        if record.get("exit_code") != 0 or record.get("timed_out") or record.get("stopped") is not True:
            raise ValueError(label + " MCP process did not exit cleanly")
        responses = [json.loads(line) for line in self.stdout(label).splitlines() if line.strip()]
        by_id = {response.get("id"): response for response in responses}
        if (len(responses) != count + 1 or set(by_id) != set(range(1, count + 2))
                or by_id[1].get("result", {}).get("serverInfo", {}).get("name") != "knowledgeos-memory"):
            raise ValueError(label + " MCP response inventory or server identity is wrong")
        results = []
        for index in range(2, count + 2):
            result = by_id[index]["result"]
            content = result["content"]
            if not isinstance(content, list) or len(content) != 1 or not isinstance(result.get("isError"), bool):
                raise ValueError(label + " MCP content shape is wrong")
            payload = json.loads(content[0]["text"])
            if not isinstance(payload, dict):
                raise ValueError(label + " MCP payload is not an object")
            results.append({"payload": payload, "is_error": result["isError"]})
        return results


def finished(record, *, console=False):
    return (record.get("exit_code") is not None and record.get("stopped") is True and not record.get("timed_out")
            and record.get("console") is console)


def proposal_ok(result):
    payload = result["payload"]
    return (not result["is_error"] and payload.get("ok") is True and payload.get("policy") == "proposal_only"
            and payload.get("mutated_self") is False and str(payload.get("proposal_path", "")).startswith("People/Self-Proposals/"))


def listing(result):
    payload = result["payload"]
    opened = payload.get("open")
    untrusted = payload.get("untrusted")
    if result["is_error"] or not isinstance(opened, list) or not isinstance(untrusted, list):
        raise ValueError("Proposal listing has the wrong shape")
    return sorted(item.get("path") for item in opened), sorted(untrusted)


def case_baseline(ev, plan):
    init, doctor, pending = ev.command("init"), ev.command("doctor-0"), ev.command("pending-0")
    initialized = json.loads(ev.stdout("init"))
    post = initialized.get("post_init", {})
    start, first, second = ev.mcp("propose", 3)
    old = [first["payload"].get("proposal_path"), second["payload"].get("proposal_path")]
    opened, untrusted = listing(ev.mcp("list-0", 1)[0])
    s0, s1 = ev.snap(0), ev.snap(1)
    doctor_text, pending_text = ev.stdout("doctor-0"), ev.stdout("pending-0")
    rows = ev.ledger(1)
    observed = {
        "init_ok": finished(init) and init["exit_code"] == 0 and set(post) >= {"rebuild", "validate"} and all(v.get("ok") is True for v in post.values()),
        "doctor_signed_with_key_file": finished(doctor) and doctor["exit_code"] == 0
        and "[OK] Proposal ledger is signed (2 entries" in doctor_text and "per-install key file" in doctor_text,
        "session_started": not start["is_error"] and bool(start["payload"].get("session_id")),
        "two_signed_proposals": proposal_ok(first) and proposal_ok(second) and len(set(old)) == 2,
        "listed_open": opened == sorted(old) and untrusted == [],
        "pending_lists_both": finished(pending) and pending["exit_code"] == 0 and all(path in pending_text for path in old),
        "state_present": bool(s1["gate_key_sha256"]) and bool(s1["bindings_sha256"]),
        "ledger_two_draft_rows": sorted((r["proposal"], r["status"]) for r in rows) == sorted((path, "draft") for path in old),
        "backup_matches_state": s1["gate_key_sha256"] == s1["backup_gate_key_sha256"] and s1["bindings_sha256"] == s1["backup_bindings_sha256"],
        "self_unchanged": s1["self_sha256"] == s0["self_sha256"],
        "old_proposals": old, "doctor_stdout": doctor_text,
    }
    return all(v for k, v in observed.items() if isinstance(v, bool)), observed


def case_no_tty(ev, plan):
    record = ev.command("approve-notty")
    stderr, stdout = ev.stderr("approve-notty"), ev.stdout("approve-notty")
    observed = {"exit_code": record.get("exit_code"), "finished": finished(record), "stderr": stderr, "stdout": stdout,
                "refused_without_terminal": record.get("exit_code") == 2 and "interactive terminal" in stderr,
                "nothing_applied": "Apply this" not in stdout and '"ok": true' not in stdout}
    return observed["finished"] and observed["refused_without_terminal"] and observed["nothing_applied"], observed


def case_memory(ev, plan):
    s1, s2, s3 = ev.snap(1), ev.snap(2), ev.snap(3)
    start, capture, search = ev.mcp("lost-memory", 3)
    path = capture["payload"].get("path")
    note = ev.text("captured-note.md")
    ranked = search["payload"].get("ranked", [])
    observed = {
        "key_file_removed": s2["gate_key_sha256"] is None and s2["backup_gate_key_sha256"] == s1["gate_key_sha256"],
        "binding_file_removed": s2["bindings_sha256"] is None and s2["backup_bindings_sha256"] == s1["bindings_sha256"],
        "ledger_untouched_by_removal": s2["ledger_sha256"] == s1["ledger_sha256"] and s1["ledger_sha256"] is not None,
        "session_started": not start["is_error"] and bool(start["payload"].get("session_id")),
        "capture_ok": not capture["is_error"] and capture["payload"].get("ok") is True and isinstance(path, str) and plan["marker"] in note,
        "search_finds_capture": not search["is_error"] and any(hit.get("path") == path for hit in ranked),
        "self_unchanged": s3["self_sha256"] == s1["self_sha256"],
        "capture_path": path,
    }
    return all(v for k, v in observed.items() if isinstance(v, bool)), observed


def refusal(ev, label):
    record = ev.command(label)
    stderr = ev.stderr(label)
    return {"finished_by_itself": finished(record, console=True) and record.get("exit_code") == 1,
            "exit_code": record.get("exit_code"), "timed_out": bool(record.get("timed_out")), "stderr": stderr,
            "no_traceback": bool(stderr.strip()) and "Traceback" not in stderr,
            "explained": bool(EXPLAINED.search(stderr)), "recovery_hint": bool(RECOVERY.search(stderr))}


def case_old_refused(ev, plan):
    s1, s4 = ev.snap(1), ev.snap(4)
    old = ev.mcp("propose", 3)[1]["payload"]["proposal_path"]
    observed = refusal(ev, "approve-lost-A")
    name = Path(old).name
    observed.update(proposal_file_unchanged=s1["proposals"].get(name) is not None and s4["proposals"].get(name) == s1["proposals"][name],
                    self_unchanged=s4["self_sha256"] == s1["self_sha256"])
    return all(v for k, v in observed.items() if isinstance(v, bool) and k != "timed_out") and not observed["timed_out"], observed


def case_doctor(ev, plan):
    record, text = ev.command("doctor-lost"), ev.stdout("doctor-lost")
    count = len(plan["old_proposals"])
    searchable = "\n".join(re.sub(r"\([^)]*\)", "", line) for line in text.splitlines() if not line.strip().startswith("Key:"))
    observed = {"finished": finished(record), "exit_code": record.get("exit_code"),
                "rows_failed_warned": re.search(r"%d ledger row\(s\) failed signature" % count, text) is not None,
                "unapprovable_files_warned": re.search(r"%d Self proposal file\(s\) are not in the ledger" % count, text) is not None,
                "cause_named": CAUSE.search(searchable) is not None,
                "claims_signed_ok": "[OK] Proposal ledger is signed" in text, "stdout": text}
    return observed["finished"] and observed["rows_failed_warned"] and observed["unapprovable_files_warned"] and observed["cause_named"], observed


def case_lost_intact(ev, plan):
    s1, s4 = ev.snap(1), ev.snap(4)
    old = plan["old_proposals"]
    opened, untrusted = listing(ev.mcp("list-lost", 2)[0])
    accept = ev.mcp("list-lost", 2)[1]
    pending, pending_text, pending_err = ev.command("pending-lost"), ev.stdout("pending-lost"), ev.stderr("pending-lost")
    rows = ev.ledger(4)
    observed = {
        "self_unchanged": s4["self_sha256"] == s1["self_sha256"],
        "ledger_bytes_unchanged": s4["ledger_sha256"] == s1["ledger_sha256"] and s1["ledger_sha256"] is not None,
        "proposal_files_unchanged": s4["proposals"] == s1["proposals"] and bool(s1["proposals"]),
        "nothing_listed_valid": opened == [] and set(old) <= set(untrusted),
        "pending_reports_none_and_warns": finished(pending) and "No Self proposals waiting" in pending_text and "failed signature" in pending_err,
        "mcp_accept_refuses": accept["is_error"] and accept["payload"].get("policy") == "human_only" and accept["payload"].get("mutated_self") is False,
        "still_draft_not_applied": [(r["proposal"], r["status"], r["applied"]) for r in rows] == [(path, "draft", False) for path in old],
    }
    return all(observed.values()), observed


def case_new(ev, plan):
    s1, s5 = ev.snap(1), ev.snap(5)
    old = plan["old_proposals"]
    new = ev.mcp("propose-new", 1)[0]
    opened, untrusted = listing(ev.mcp("list-new", 1)[0])
    pending, pending_text = ev.command("pending-new"), ev.stdout("pending-new")
    rows, base = ev.ledger(5), ev.ledger(1)
    path = new["payload"].get("proposal_path")
    refused = refusal(ev, "approve-new-A")
    observed = {
        "new_proposal_ok": proposal_ok(new),
        "only_new_is_open": opened == [path] and not set(old) & set(opened),
        "pending_lists_only_new": finished(pending) and path in pending_text and not any(p in pending_text for p in old),
        "old_ledger_lines_kept": {r["sha256"] for r in base} <= {r["sha256"] for r in rows} and len(rows) == len(base) + 1,
        "new_row_draft": [r["status"] for r in rows if r["proposal"] == path] == ["draft"],
        "old_still_refused": refused["finished_by_itself"] and refused["no_traceback"] and refused["explained"],
        "old_refusal": {key: refused[key] for key in ("exit_code", "timed_out", "stderr")},
        "self_unchanged": s5["self_sha256"] == s1["self_sha256"],
        "new_proposal": path,
    }
    return all(v for k, v in observed.items() if isinstance(v, bool)), observed


def case_restore(ev, plan):
    s1, s5, s6, s7 = ev.snap(1), ev.snap(5), ev.snap(6), ev.snap(7)
    old = plan["old_proposals"]
    opened, untrusted = listing(ev.mcp("list-restored", 1)[0])
    pending, pending_text = ev.command("pending-restored"), ev.stdout("pending-restored")
    doctor, doctor_text = ev.command("doctor-restored"), ev.stdout("doctor-restored")
    base, rows = ev.ledger(1), ev.ledger(7)
    waiting = doctor_text.split("waiting for you", 1)[1] if "waiting for you" in doctor_text else ""
    observed = {
        "original_key_restored": s6["gate_key_sha256"] == s1["gate_key_sha256"] and s6["bindings_sha256"] == s1["bindings_sha256"],
        "replacement_state_differed": s5["gate_key_sha256"] is not None and s5["gate_key_sha256"] != s1["gate_key_sha256"],
        "old_open_again": set(old) <= set(opened),
        "pending_lists_old": finished(pending) and pending["exit_code"] == 0 and all(p in pending_text for p in old),
        "doctor_lists_old_as_waiting": finished(doctor) and "[OK] Proposal ledger is signed" in doctor_text and all(p in waiting for p in old),
        "old_ledger_lines_kept": {r["sha256"] for r in base} <= {r["sha256"] for r in rows},
        "old_rows_still_draft": sorted((r["proposal"], r["status"]) for r in rows if r["proposal"] in old) == sorted((p, "draft") for p in old),
        "self_unchanged": s7["self_sha256"] == s1["self_sha256"],
        "new_proposal_still_open_after_restore": plan.get("new_proposal") in opened if plan.get("new_proposal") else None,
    }
    return all(v for k, v in observed.items() if isinstance(v, bool) and k != "new_proposal_still_open_after_restore"), observed


def case_preserved(ev, plan):
    snaps = [ev.snap(n) for n in range(8)]
    old = plan["old_proposals"]
    names = [Path(p).name for p in old]
    observed = {
        "self_identical_everywhere": len({s["self_sha256"] for s in snaps}) == 1,
        "old_proposal_files_identical": all(len({s["proposals"].get(name) for s in snaps[1:]}) == 1 and snaps[1]["proposals"].get(name) for name in names),
        "no_row_applied_ever": not any(row["applied"] or row["status"] not in ("draft",) for n in range(1, 8) for row in ev.ledger(n)),
        "snapshots": len(snaps) == 8,
    }
    return all(observed.values()), observed


EVALUATORS = {
    "baseline_pending_valid": case_baseline, "present_no_tty_refused": case_no_tty, "lost_memory_works": case_memory,
    "lost_old_approval_refused": case_old_refused, "lost_doctor_honest": case_doctor,
    "lost_identity_and_ledger_intact": case_lost_intact, "new_proposal_valid_old_refused": case_new,
    "restore_old_valid_again": case_restore, "identity_and_isolation_preserved": case_preserved,
}


def evaluate(directory):
    """The literal cases, recomputed from the retained evidence files alone."""
    ev = Evidence(directory)
    try:
        plan = ev.json("plan.json")
        plan = dict(plan, old_proposals=ev.json("proposals.json")["old"], new_proposal=ev.json("proposals.json").get("new"))
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError("Plan or proposal inventory is unreadable: " + str(exc)) from exc
    rows = []
    for name in CASE_NAMES:
        try:
            passed, observed = EVALUATORS[name](ev, plan)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            passed, observed = False, {"error": type(exc).__name__ + ": " + str(exc)}
        evidence = sorted(path.name for path in Path(directory).iterdir() if path.is_file()
                          and name_matches(name, path.name))
        rows.append({"id": "signing." + name, "verdict": "PASS" if passed else "FAIL", "expected": EXPECTED[name],
                     "observed": observed, "evidence": evidence})
    return rows


EVIDENCE_LABELS = {
    "baseline_pending_valid": ("init", "doctor-0", "propose", "list-0", "pending-0", "snap-0", "snap-1", "backup."),
    "present_no_tty_refused": ("approve-notty",),
    "lost_memory_works": ("lost-memory", "captured-note", "snap-2", "snap-3"),
    "lost_old_approval_refused": ("approve-lost-A", "snap-4"),
    "lost_doctor_honest": ("doctor-lost",),
    "lost_identity_and_ledger_intact": ("list-lost", "pending-lost", "snap-4"),
    "new_proposal_valid_old_refused": ("propose-new", "list-new", "pending-new", "approve-new-A", "snap-5"),
    "restore_old_valid_again": ("replacement.", "list-restored", "pending-restored", "doctor-restored", "snap-6", "snap-7"),
    "identity_and_isolation_preserved": ("snap-",),
}


def name_matches(name, filename):
    return any(filename.startswith(prefix) for prefix in EVIDENCE_LABELS[name]) or filename == "plan.json" or filename == "proposals.json"


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #


class SigningRun:
    def __init__(self, output, report_path):
        base = Path(output).absolute()
        generated = (ROOT / "work/gc-artifacts").resolve()
        probe = base
        while not probe.exists():
            probe = probe.parent
        if any(p.is_symlink() for p in (probe, *probe.parents)):
            raise ValueError("Output may not traverse a link")
        base = base.resolve()
        if not base.is_relative_to(generated) or ".knowledgeos" not in base.relative_to(generated).parts:
            raise ValueError("Output must be below work/gc-artifacts and contain .knowledgeos")
        self.directory = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True)
        self.neutral, self.vault, self.state = self.directory / "neutral", self.directory / "vault", self.directory / "gate-state"
        self.neutral.mkdir()
        self.report_path = Path(report_path).absolute()
        self.env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(self.state), PYTHONIOENCODING="utf-8",
                        PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
        self.cleared = ("PYTHONPATH", "PYTHONHOME", "PYTHONSAFEPATH", "VIRTUAL_ENV", "KNOWLEDGEOS_VAULT", "KNOWLEDGEOS_GATE_KEY")
        for key in self.cleared:
            self.env.pop(key, None)
        self.producer_hash, self.support = sha(__file__), support_hashes()
        self.sources = product_hashes()
        self.protected = [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json"]
        self.before = self.sentinels()
        self.processes = []
        self.artifact = None
        self.exe = None
        self.snapshots = 0
        self.proposals = {"old": [], "new": None}
        self.marker = "signingquartz" + uuid.uuid4().hex[:10]

    def sentinels(self):
        return {str(p): sha(p) if p.is_file() else None for p in self.protected}

    def save(self, name, value):
        text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
        (self.directory / name).write_text(text, encoding="utf-8")

    def bind_artifact(self):
        report = plain(self.report_path)
        data = json.loads(report.read_text(encoding="utf-8-sig"))
        artifact, installation = data.get("artifact", {}), data.get("installation", {})
        helper = Path(__file__).with_name("artifact.py")
        problems = []
        if data.get("producer") != ARTIFACT_PRODUCER or data.get("producer_sha256") != sha(helper):
            problems.append("artifact producer or its hash")
        if data.get("product_hashes") != self.sources:
            problems.append("artifact product hashes")
        if data.get("verdict") != "PASS" or any(row.get("verdict") != "PASS" for row in data.get("cases", [])):
            problems.append("artifact verdict")
        if any(data.get(key) is not True for key in ("source_bound", "product_unchanged", "artifact_unchanged", "all_started_processes_stopped")):
            problems.append("artifact binding or shutdown")
        if not str(installation.get("platform", "")).startswith("Windows-") or os.name != "nt":
            problems.append("Windows platform")
        kind = artifact.get("kind")
        if kind not in ("wheel", "binary"):
            problems.append("artifact kind")
        if problems:
            raise ValueError("Artifact report is not usable: " + ", ".join(problems))
        path, exe = plain(artifact["path"]), plain(installation["executable"])
        if sha(path) != artifact.get("sha256"):
            raise ValueError("Artifact bytes differ from the artifact report")
        if kind == "binary":
            root = plain(artifact["distribution_root"])
            if exe != path or not exe.is_relative_to(root) or link_free_tree(root) != artifact.get("distribution_files"):
                raise ValueError("Frozen distribution differs from the artifact report")
            exe_hash, origin = sha(exe), None
        else:
            exe_hash = installation.get("file_hashes", {}).get(str(exe))
            if exe_hash is None or sha(exe) != exe_hash:
                raise ValueError("Installed launcher differs from the artifact report")
            python = plain(installation["python"])
            probe = subprocess.run([str(python), "-I", "-c", "import knowledgeos;print(knowledgeos.__file__)"], cwd=self.neutral,
                                   env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            origin = probe.stdout.strip()
            self.save("import-origin.stdout.txt", probe.stdout)
            self.save("import-origin.stderr.txt", probe.stderr)
            if probe.returncode or Path(origin).resolve() != plain(installation["import_origin"]):
                raise ValueError("Isolated interpreter does not import the recorded installed package")
        self.exe = exe
        self.artifact = {"kind": kind, "path": str(path), "sha256": artifact["sha256"], "report_path": str(report),
                         "report_sha256": sha(report), "executable": str(exe), "executable_sha256": exe_hash,
                         "distribution_root": str(plain(artifact["distribution_root"])), "import_origin": origin}

    def record_process(self, label, process, **extra):
        record = {"pid": process.pid, "role": label, "stopped": False, **extra}
        self.processes.append(record)
        return record

    def command(self, label, arguments, timeout=180):
        command = [str(self.exe), *map(str, arguments)]
        started_ns, started = time.time_ns(), time.monotonic()
        process = subprocess.Popen(command, cwd=self.neutral, env=self.env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        record = self.record_process(label, process, console=False)
        timed_out = False
        try:
            stdout, stderr = process.communicate("", timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30)
            stdout, stderr = process.communicate(timeout=30)
        finally:
            record.update(stopped=process.poll() is not None, exit_code=process.returncode, timed_out=timed_out)
        self.finish_command(label, command, process, started_ns, started, timed_out, stdout, stderr, console=False,
                            stdin="closed pipe with no input; a NUL device would count as a terminal on Windows")

    def finish_command(self, label, command, process, started_ns, started, timed_out, stdout, stderr, console, **extra):
        if stdout is not None:
            self.save(label + ".stdout.txt", stdout)
            self.save(label + ".stderr.txt", stderr)
        self.save(label + ".command.json", {
            "label": label, "command": command, "cwd": str(self.neutral), "shell": False, "console": console,
            "state_dir": str(self.state), "cleared_environment": list(self.cleared), "pid": process.pid,
            "exit_code": process.returncode, "stopped": process.poll() is not None, "timed_out": timed_out,
            "started_ns": started_ns, "seconds": time.monotonic() - started, **extra})

    def rpc(self, label, calls, timeout=180):
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-signing", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        messages += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                     for index, (name, arguments) in enumerate(calls, 2)]
        self.save(label + ".requests.json", messages)
        command = [str(self.exe), "mcp", "--vault", str(self.vault), "--framing", "ndjson"]
        started_ns, started = time.time_ns(), time.monotonic()
        process = subprocess.Popen(command, cwd=self.neutral, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        record = self.record_process(label, process, console=False)
        timed_out = False
        try:
            stdout, stderr = process.communicate("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30)
            stdout, stderr = process.communicate(timeout=30)
        finally:
            record.update(stopped=process.poll() is not None, exit_code=process.returncode, timed_out=timed_out)
        self.finish_command(label, command, process, started_ns, started, timed_out, stdout, stderr, console=False)
        try:
            return Evidence(self.directory).mcp(label, len(calls))
        except (ValueError, KeyError, OSError):
            return None

    def console_approve(self, label, relative):
        """Reach the approval refusal from a hidden real console. No answer is ever sent."""
        stderr_path = self.directory / (label + ".stderr.txt")
        inner = subprocess.list2cmdline([str(self.exe), "self", "approve", relative, "--vault", str(self.vault)])
        line = '"%s" /d /s /c "%s 2>"%s""' % (os.environ.get("ComSpec", "cmd.exe"), inner, stderr_path)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        started_ns, started = time.time_ns(), time.monotonic()
        process = subprocess.Popen(line, cwd=self.neutral, env=self.env, creationflags=CREATE_NEW_CONSOLE, startupinfo=startup)
        record = self.record_process(label, process, console=True)
        timed_out = False
        try:
            process.wait(timeout=CONSOLE_DEADLINE)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30)
                process.wait(timeout=30)
            record.update(stopped=process.poll() is not None, exit_code=process.returncode, timed_out=timed_out)
        if not stderr_path.exists():
            stderr_path.write_text("", encoding="utf-8")
        self.save(label + ".stdout.txt", "")
        self.finish_command(label, line, process, started_ns, started, timed_out, None, None, console=True,
                            stdout_note="stdout stays on the hidden console and is not captured; stderr was redirected to the retained file",
                            deadline_seconds=CONSOLE_DEADLINE)

    def snapshot(self):
        number = self.snapshots
        self.snapshots += 1
        ledgers = sorted((self.state / "vaults").glob("*/self-proposals.jsonl")) if (self.state / "vaults").is_dir() else []
        ledger = ledgers[0] if len(ledgers) == 1 else None
        if ledger is not None:
            shutil.copyfile(ledger, self.directory / ("snap-%d.ledger.jsonl" % number))
        proposals = self.vault / "People/Self-Proposals"
        files = {p.relative_to(self.state).as_posix(): sha(p) for p in sorted(self.state.rglob("*")) if p.is_file()} if self.state.is_dir() else {}
        backups = {name: self.directory / ("backup." + name) for name in STATE_FILES}
        data = {"name": number, "taken_ns": time.time_ns(), "self_sha256": sha(self.vault / "People/Self.md"),
                "gate_key_sha256": sha(self.state / KEY_FILE) if (self.state / KEY_FILE).is_file() else None,
                "bindings_sha256": sha(self.state / BINDING_FILE) if (self.state / BINDING_FILE).is_file() else None,
                "backup_gate_key_sha256": sha(backups[KEY_FILE]) if backups[KEY_FILE].is_file() else None,
                "backup_bindings_sha256": sha(backups[BINDING_FILE]) if backups[BINDING_FILE].is_file() else None,
                "ledger_count": len(ledgers), "ledger_sha256": sha(ledger) if ledger else None, "state_files": files,
                "proposals": {p.name: sha(p) for p in sorted(proposals.glob("*.md"))} if proposals.is_dir() else {}}
        self.save("snap-%d.json" % number, data)

    def propose(self, summary, section, text):
        return ("memory_propose_self_update", {"summary": summary, "section": section, "proposed_markdown": text,
                                               "rationale": "Synthetic signing-state acceptance only.", "mode": "append"})

    def run(self):
        d = self.directory
        self.save("plan.json", {"producer": PRODUCER, "case_ids": list(CASE_IDS), "marker": self.marker, "frozen_at_ns": time.time_ns(),
                                "removed_state": list(STATE_FILES), "console_deadline_seconds": CONSOLE_DEADLINE,
                                "steps": list(STEPS),
                                "limits": "Case list, step order and removed files are frozen before the first product call"})
        self.bind_artifact()
        self.command("init", ["init", self.vault, "--name", "Signing state fixture", "--non-interactive"])
        self.snapshot()
        made = self.rpc("propose", [("memory_session_start", {"task_hint": "signing state acceptance"}),
                                    self.propose("Synthetic signing proposal one", "heuristics", "* Prefer retained evidence one."),
                                    self.propose("Synthetic signing proposal two", "anti_goals", "* Avoid unretained evidence two.")])
        old = [made[1]["payload"].get("proposal_path"), made[2]["payload"].get("proposal_path")] if made else []
        self.proposals["old"] = old
        self.save("proposals.json", self.proposals)
        self.rpc("list-0", [("memory_list_self_proposals", {})])
        self.command("pending-0", ["self", "pending", "--vault", self.vault])
        self.command("doctor-0", ["doctor", "--vault", self.vault])
        for name in STATE_FILES:
            shutil.copyfile(self.state / name, d / ("backup." + name))
        self.snapshot()
        if not old or not all(old):
            raise RuntimeError("Could not create the pending-proposal precondition")
        self.command("approve-notty", ["self", "approve", old[0], "--vault", self.vault])
        for name in STATE_FILES:
            (self.state / name).unlink()
        self.snapshot()
        lost = self.rpc("lost-memory", [("memory_session_start", {"task_hint": "after signing state loss"}),
                                        ("memory_capture", {"title": "Signing loss fact", "content": "The signing loss marker is " + self.marker + "."}),
                                        ("memory_search", {"query": self.marker})])
        if lost and isinstance(lost[1]["payload"].get("path"), str):
            note = self.vault / lost[1]["payload"]["path"]
            shutil.copyfile(note, d / "captured-note.md") if note.is_file() else self.save("captured-note.md", "")
        else:
            self.save("captured-note.md", "")
        self.snapshot()
        self.console_approve("approve-lost-A", old[0])
        self.command("doctor-lost", ["doctor", "--vault", self.vault])
        self.command("pending-lost", ["self", "pending", "--vault", self.vault])
        self.rpc("list-lost", [("memory_list_self_proposals", {}), ("memory_accept_self_update", {"proposal_path": old[0]})])
        self.snapshot()
        made = self.rpc("propose-new", [self.propose("Synthetic signing proposal after loss", "values", "* Keep evidence after state loss.")])
        self.proposals["new"] = made[0]["payload"].get("proposal_path") if made else None
        self.save("proposals.json", self.proposals)
        self.rpc("list-new", [("memory_list_self_proposals", {})])
        self.command("pending-new", ["self", "pending", "--vault", self.vault])
        self.console_approve("approve-new-A", old[0])
        for name in STATE_FILES:
            if (self.state / name).is_file():
                shutil.copyfile(self.state / name, d / ("replacement." + name))
        self.snapshot()
        for name in STATE_FILES:
            shutil.copyfile(d / ("backup." + name), self.state / name)
        self.snapshot()
        self.rpc("list-restored", [("memory_list_self_proposals", {})])
        self.command("pending-restored", ["self", "pending", "--vault", self.vault])
        self.command("doctor-restored", ["doctor", "--vault", self.vault])
        self.snapshot()

    def finish(self, error=None):
        after = self.sentinels()
        current = product_hashes()
        stable = current == self.sources and sha(__file__) == self.producer_hash and support_hashes() == self.support
        unchanged = False
        try:
            if self.artifact:
                unchanged = sha(self.artifact["path"]) == self.artifact["sha256"] and sha(self.artifact["executable"]) == self.artifact["executable_sha256"]
                if self.artifact["kind"] == "binary":
                    unchanged = unchanged and link_free_tree(self.artifact["distribution_root"]) == json.loads(
                        Path(self.artifact["report_path"]).read_text(encoding="utf-8-sig"))["artifact"]["distribution_files"]
        except (OSError, ValueError, KeyError):
            unchanged = False
        if error is not None:
            self.save("execution-error.json", {"error": type(error).__name__ + ": " + str(error)})
        cases = []
        if error is None:
            try:
                cases = evaluate(self.directory)
            except ValueError as exc:
                error = exc
        stopped = bool(self.processes) and all(p["stopped"] is True and isinstance(p.get("exit_code"), int) for p in self.processes)
        complete = [row["id"] for row in cases] == list(CASE_IDS)
        passed = (error is None and complete and all(row["verdict"] == "PASS" for row in cases) and stable and unchanged
                  and stopped and self.before == after)
        for row in cases:
            print(row["verdict"] + " " + row["id"], flush=True)
        report = {
            "producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": self.support,
            "platform": platform.platform(), "python": sys.version,
            "scope": "artifact", "cell": ["Windows", self.artifact["kind"]] if self.artifact else None,
            "claim": "Installed Windows launcher, CLI and MCP in a synthetic vault; no model chat, host application, human consent or other platform",
            "verdict": "PASS" if passed else "FAIL", "fixed_outcome_candidate": "PORT.missing_signing_state",
            "acceptance_credit_awarded": False, "product_hashes": self.sources, "product_hashes_after": current,
            "product_and_producer_unchanged": stable, "artifact": self.artifact, "artifact_unchanged": unchanged,
            "expected_case_ids": list(CASE_IDS), "cases": cases, "directory": str(self.directory),
            "processes": self.processes, "all_started_processes_stopped": stopped,
            "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after,
                          "limitation": "Selected real-vault sentinels only; not an exhaustive filesystem audit"},
            "limits": ["Windows only; a Linux cell needs its own native run",
                       "The approval prompt is never answered; a valid proposal is judged by the ledger, listings, pending and doctor, not by applying it",
                       "Console stdout is not captured; the refusal text is read from the redirected stderr",
                       "Stopped records cover directly launched commands and the hidden-console shell; not an exhaustive descendant audit"],
            "error": (type(error).__name__ + ": " + str(error)) if error is not None else None}
        report["evidence_files"] = {p.name: sha(p) for p in sorted(self.directory.iterdir()) if p.is_file() and p.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"],
                          "passed": sum(row["verdict"] == "PASS" for row in cases), "total": len(CASE_IDS)}), flush=True)
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise InterruptedError("Signing-state proof interrupted by signal " + str(signum))

    signal.signal(signal.SIGTERM, interrupted)
    run = SigningRun(args.output, args.artifact_report)
    error = None
    try:
        run.run()
    except BaseException as caught:
        error = caught
    return run.finish(error)


if __name__ == "__main__":
    raise SystemExit(main())
