"""Observe fixed synthetic longitudinal learning cases through public processes."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "knowledgeos/memory.py").is_file())
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
from data_preservation import checked_output, inventory, sha, source_files

PRODUCER = "verify-twinaatma.longitudinal-source/v1"
HOME = Path(__file__).resolve().parent
PLAN_PATH = HOME / "case-plan.json"
PLAN = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
BEFORE, AFTER = PLAN["before"], PLAN["after"]
NARRATIVES = PLAN["narratives"]
CASE_IDS = [*PLAN["activity_cases"], *PLAN["negative_cases"], *PLAN["recurrence_cases"], "identity_and_lineage_preserved"]
TRACE_SOURCE = '''import atexit, json, os, subprocess, time
from pathlib import Path
_owned = []
_original = subprocess.Popen
_instance = os.environ["LONGITUDINAL_INSTANCE"]
_role = os.environ["LONGITUDINAL_ROLE"]
_began = time.monotonic_ns()
class ObservedPopen(_original):
    def __init__(self, *args, **kwargs):
        child_id = _instance + "-child-" + str(len(_owned) + 1)
        env = dict(kwargs.get("env") or os.environ)
        env.update(LONGITUDINAL_INSTANCE=child_id, LONGITUDINAL_ROLE=_role + ":child:" + str(len(_owned) + 1), LONGITUDINAL_PARENT_INSTANCE=_instance)
        kwargs["env"] = env
        started = time.monotonic_ns()
        super().__init__(*args, **kwargs)
        argv = args[0] if args else kwargs.get("args", [])
        _owned.append((self, child_id, [str(value) for value in argv] if isinstance(argv, (list, tuple)) else [str(argv)], started))
subprocess.Popen = ObservedPopen
def _finish():
    children = []
    for child, child_id, argv, started in _owned:
        forced = child.poll() is None
        if forced:
            child.kill()
        child.wait()
        children.append({"instance": child_id, "pid": child.pid, "argv": argv, "started_ns": started, "ended_ns": time.monotonic_ns(), "stopped": child.poll() is not None, "exit_code": child.returncode, "cleanup_required": forced})
    row = {"instance": _instance, "parent_instance": os.environ["LONGITUDINAL_PARENT_INSTANCE"], "role": _role, "pid": os.getpid(), "parent_pid": os.getppid(), "started_ns": _began, "ended_ns": time.monotonic_ns(), "children": children}
    target = Path(os.environ["LONGITUDINAL_TRACE_DIR"]) / (_instance + ".json")
    target.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
atexit.register(_finish)
'''


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fields(name, completed=True, **changes):
    row = {"type": "decision", "title": "Synthetic longitudinal " + name, "description": "Synthetic longitudinal source 739",
        "schema": "knowledgeos-v0.3", "status": "active", "created": "2000-01-01", "updated": "2000-01-01",
        "tags": ["synthetic", "long739"], "id": PLAN["decision_ids"][name], "project": "Long739",
        "outcome_status": "confirmed" if completed else "pending", "actual_outcome": NARRATIVES[name] if completed else "",
        "lesson": AFTER if completed else "", "belief_before": BEFORE if completed else "", "belief_after": AFTER if completed else ""}
    row.update(changes)
    return row


def note(row, reformatted=False):
    keys = list(row)
    if reformatted:
        keys.reverse()
    ending = "\r\n" if reformatted else "\n"
    lines = ["---", *[key + ": " + json.dumps(row[key], ensure_ascii=False) for key in keys], "---", "", "# Recorded source 739", "", "Synthetic local report. No asserted owner identity.", ""]
    if reformatted:
        lines.insert(-1, "")
    return ending.join(lines).encode("utf-8")


def negative_registry(name):
    rows = {"Decisions/mail.md": fields("mail"), "Decisions/calendar.md": fields("calendar")}
    if name == "single_completed":
        rows = {"Decisions/mail.md": fields("mail")}
    elif name == "pending_partner":
        rows["Decisions/calendar.md"] = fields("calendar", False)
    elif name == "missing_explicit_pair":
        rows["Decisions/calendar.md"] = fields("calendar", belief_after="")
    elif name == "duplicate_id":
        rows["Decisions/calendar.md"] = fields("calendar", id=PLAN["decision_ids"]["mail"])
    elif name == "copied_narrative":
        rows["Decisions/calendar.md"] = fields("calendar", actual_outcome=NARRATIVES["mail"])
    elif name == "unchanged_belief":
        rows["Decisions/calendar.md"] = fields("calendar", belief_after=BEFORE, lesson=BEFORE)
    elif name == "mismatched_lesson":
        rows["Decisions/calendar.md"] = fields("calendar", lesson="This local lesson does not state a changed preference")
    elif name == "contradictory_sources":
        rows["Decisions/storage.md"] = fields("storage", belief_after=PLAN["contradiction"], lesson=PLAN["contradiction"])
    elif name == "superseded_source":
        rows["Decisions/calendar.md"] = fields("calendar", outcome_status="superseded", supersedes=PLAN["decision_ids"]["mail"])
    else:
        raise ValueError("Unknown frozen negative case " + name)
    return rows


class Run:
    def __init__(self, output):
        self.directory = checked_output(output) / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.inputs = source_files()
        self.product = {p.relative_to(ROOT).as_posix(): sha(p) for p in self.inputs}
        self.support = {"data_preservation.py": sha(SCRIPTS / "data_preservation.py"), "case-plan.json": sha(PLAN_PATH)}
        self.producer_hash = sha(__file__)
        self.adapter_hash = sha(HOME / "longitudinal_adapter.py")
        self.protected = [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json"]
        self.before = self.sentinels()
        self.fixtures, self.processes, self.events = {}, [], []
        self.traces = self.directory / "child-traces"
        self.traces.mkdir()
        self.tracer = self.directory / "tracer/sitecustomize.py"
        self.tracer.parent.mkdir()
        self.tracer.write_text(TRACE_SOURCE, encoding="utf-8")
        self.save("case-plan.json", PLAN)
        self.frozen = {"producer": PRODUCER, "source_root": str(ROOT), "product_hashes": self.product, "producer_sha256": self.producer_hash,
            "support_sha256": self.support, "adapter_sha256": self.adapter_hash, "case_plan_sha256": sha(PLAN_PATH),
            "literal_case_ids": CASE_IDS, "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "frozen_before_first_product_invocation": True, "scope": "longitudinal", "time_basis": "synthetic cadence fixture; no representative elapsed week"}
        self.save("frozen-expectations.json", self.frozen)

    def save(self, name, value):
        write_json(self.directory / name, value)

    def sentinels(self):
        return {str(path): sha(path) if path.is_file() else None for path in self.protected}

    def env(self, fixture, role, instance):
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("KNOWLEDGEOS_") or key.startswith("LONGITUDINAL_") or key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "NOTION_API_KEY", "NOTION_DATABASE_ID", "NOTION_DATA_SOURCE_ID"):
                env.pop(key, None)
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", KNOWLEDGEOS_STATE_DIR=str(fixture["scope"] / "gate-state"),
            KNOWLEDGEOS_VAULT=str(fixture["vault"]), PYTHONPATH=str(self.tracer.parent) + os.pathsep + str(fixture["toolkit"]),
            LONGITUDINAL_INSTANCE=instance, LONGITUDINAL_ROLE=role, LONGITUDINAL_PARENT_INSTANCE="producer-" + str(os.getpid()),
            LONGITUDINAL_TRACE_DIR=str(self.traces))
        return env

    def command(self, role, fixture, tail, wire=None):
        instance = "direct-" + str(len(self.processes) + 1).zfill(3)
        command = [sys.executable, "-B", "-X", "utf8", "-P", "-m", "knowledgeos", *tail]
        env = self.env(fixture, role, instance)
        begun = dt.datetime.now(dt.timezone.utc).isoformat()
        started = time.monotonic_ns()
        child = subprocess.Popen(command, cwd=fixture["scope"], env=env, stdin=subprocess.PIPE if wire is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = {"pid": child.pid, "instance": instance, "role": role, "stopped": False}
        self.processes.append(tracked)
        error, interruption = None, None
        try:
            stdout, stderr = child.communicate(wire, timeout=90)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            error = "Public process exceeded the proof deadline"
        except BaseException as caught:
            child.kill()
            stdout, stderr = child.communicate()
            error, interruption = str(caught), caught
        finally:
            tracked.update(stopped=child.poll() is not None, exit_code=child.returncode)
        ended = time.monotonic_ns()
        for suffix, value in ((".stdout.txt", stdout), (".stderr.txt", stderr)):
            (self.directory / (role + suffix)).write_text(value, encoding="utf-8")
        record = {**tracked, "command": command, "cwd": str(fixture["scope"]), "vault": str(fixture["vault"]), "shell": False,
            "state_dir": env["KNOWLEDGEOS_STATE_DIR"], "import_path": env["PYTHONPATH"], "started_at": begun, "started_ns": started,
            "ended_ns": ended, "parent_pid": os.getpid(), "error": error, "gate_key_override_present": False}
        self.save(role + ".command.json", record)
        if interruption:
            raise interruption
        if error or child.returncode != 0:
            raise RuntimeError(error or role + " exited " + str(child.returncode) + ": " + stderr[-2000:])
        return stdout

    def snapshot(self, fixture, label):
        vault = fixture["vault"]
        texts = {path.relative_to(vault).as_posix(): path.read_bytes().decode("utf-8") for path in sorted(vault.rglob("*.md"))}
        ledger = {path.relative_to(fixture["scope"]).as_posix(): path.read_text(encoding="utf-8") for path in sorted((fixture["scope"] / "gate-state").rglob("*.jsonl"))}
        state = vault / ".knowledgeos/autopilot.json"
        self.save("snapshots/" + label + ".json", {"fixture": fixture["name"], "inventory": inventory(fixture["scope"]),
            "markdown": texts, "ledger": ledger, "autopilot": json.loads(state.read_text(encoding="utf-8")) if state.is_file() else None})

    def prepare(self, name, rows):
        scope = self.directory / "fixtures" / name
        toolkit, vault = scope / "toolkit", scope / "vault"
        toolkit.mkdir(parents=True)
        for path in self.inputs:
            target = toolkit / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        fixture = {"name": name, "scope": scope, "toolkit": toolkit, "vault": vault}
        self.fixtures[name] = fixture
        self.save(name + ".toolkit.json", inventory(toolkit))
        self.command(name + "-init", fixture, ["init", str(vault), "--name", "Synthetic longitudinal 739", "--non-interactive"])
        self.command(name + "-doctor", fixture, ["doctor", "--vault", str(vault)])
        for relative, values in rows.items():
            target = vault / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(note(values))
        self.snapshot(fixture, name + "-seed")
        return fixture

    def rpc(self, role, fixture, calls, case=None):
        self.snapshot(fixture, role + "-before")
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-longitudinal", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        messages.extend({"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": arguments}} for index, (name, arguments) in enumerate(calls, 2))
        wire = "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages)
        (self.directory / (role + ".requests.jsonl")).write_text(wire, encoding="utf-8")
        stdout = self.command(role, fixture, ["mcp", "--vault", str(fixture["vault"]), "--framing", "ndjson"], wire)
        self.snapshot(fixture, role + "-after")
        self.events.append({"role": role, "fixture": fixture["name"], "case": case, "transport": "mcp"})
        responses = {row["id"]: row for row in (json.loads(line) for line in stdout.splitlines())}
        values = [json.loads(responses[index]["result"]["content"][0]["text"]) for index in range(2, len(calls) + 2)]
        print("OBSERVED " + role, flush=True)
        return values

    def review_cli(self, fixture, name):
        role = "review-" + name
        self.snapshot(fixture, role + "-before")
        stdout = self.command(role, fixture, ["memory", "memory_get_note", "--vault", str(fixture["vault"]), "--args", json.dumps({"path_or_id": "Decisions/" + name + ".md"})])
        self.snapshot(fixture, role + "-after")
        self.events.append({"role": role, "fixture": fixture["name"], "case": None, "transport": "cli"})
        return json.loads(stdout)

    def record(self, fixture, name):
        reviewed = self.review_cli(fixture, name)
        args = {"path": reviewed["path"], "expected_sha256": reviewed["sha256"], "outcome_status": "confirmed",
            "actual_outcome": NARRATIVES[name], "lesson": AFTER, "belief_before": BEFORE, "belief_after": AFTER}
        self.rpc("record-" + name, fixture, [("memory_record_outcome", args)])

    def rejection_pair(self, role, fixture, case):
        return self.rpc(role, fixture, [("memory_propose_from_drift", {}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/mail.md"})], case)

    def run(self):
        activity = self.prepare("activity", {"Decisions/mail.md": fields("mail", False), "Decisions/calendar.md": fields("calendar", False)})
        for index, case in enumerate(PLAN["activity_cases"]):
            for name in ("mail", "calendar"):
                row = fields(name, False, updated="2026-10-19" if index == 2 else "2000-01-01")
                (activity["vault"] / ("Decisions/" + name + ".md")).write_bytes(note(row, index == 1))
            write_json(activity["vault"] / ".knowledgeos/autopilot.json", {"real_sessions": 3, "first_session_ts": 1, "last_drift_propose_ts": 0})
            sid = "long739-" + case
            self.rpc(case, activity, [("memory_session_start", {"task_hint": "Remember source activity without inferring a personal belief", "session_id": sid}),
                ("memory_propose_from_drift", {}), ("memory_session_end", {"summary": "Synthetic longitudinal activity only; no owner belief change was supplied.", "session_id": sid})], case)
        for name in PLAN["negative_cases"]:
            fixture = self.prepare(name, negative_registry(name))
            self.rpc(name, fixture, [("memory_propose_from_drift", {})], name)
        fixture = self.prepare("recurrence", {"Decisions/mail.md": fields("mail", False), "Decisions/calendar.md": fields("calendar", False)})
        for name in ("mail", "calendar"):
            self.record(fixture, name)
        self.rpc("recorded_pair", fixture, [("memory_get_note", {"path_or_id": "Decisions/mail.md"}), ("memory_get_note", {"path_or_id": "Decisions/calendar.md"}), ("memory_pending_outcomes", {})], "recorded_pair")
        result = self.rpc("uncertain_attributed", fixture, [("memory_propose_from_drift", {}), ("memory_list_self_proposals", {})], "uncertain_attributed")[0]
        proposal = result["proposal_path"]
        self.rejection_pair("draft_idempotent", fixture, "draft_idempotent")
        self.rpc("public_rejection", fixture, [("memory_reject_self_update", {"proposal_path": proposal, "reason": "Synthetic rejection for retained recurrence evidence"}), ("memory_list_self_proposals", {})], "public_rejection")
        self.rejection_pair("unchanged_rejected", fixture, "unchanged_rejected")
        mail = fixture["vault"] / "Decisions/mail.md"
        original = mail.read_bytes()
        (fixture["scope"] / "mail-original.retained").write_bytes(original)
        reformatted = original.decode().replace("\n", "\r\n").replace("# Recorded source 739", "# Recorded source 739\r\n")
        mail.write_bytes(reformatted.encode())
        self.rejection_pair("reformatted_rejected", fixture, "reformatted_rejected")
        mail.write_bytes(original)
        current = mail.read_text(encoding="utf-8")
        current = current.replace("Synthetic longitudinal mail", "Synthetic retitled mail").replace("2000-01-01", "2026-10-19")
        mail.write_bytes(current.encode())
        self.rejection_pair("retimestamped_rejected", fixture, "retimestamped_rejected")
        mail.write_bytes(original)
        renamed = mail.with_name("mail-renamed.md")
        mail.rename(renamed)
        self.rpc("renamed_rejected", fixture, [("memory_propose_from_drift", {}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/mail-renamed.md"})], "renamed_rejected")
        renamed.rename(mail)
        mail.write_bytes(original.replace(PLAN["decision_ids"]["mail"].encode(), b"kos:decision:long739-rekeyed").replace(NARRATIVES["mail"].encode(), b"A corrected concrete report on the same mail source."))
        self.rejection_pair("rekeyed_rejected", fixture, "rekeyed_rejected")
        mail.write_bytes(original)
        (fixture["vault"] / "Decisions/mail-copy.md").write_bytes(note(fields("mail", id="kos:decision:long739-copy")))
        self.rpc("copied_rejected", fixture, [("memory_propose_from_drift", {}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/mail-copy.md"})], "copied_rejected")
        ledgers = sorted((fixture["scope"] / "gate-state").rglob("*.jsonl"))
        if len(ledgers) != 1:
            raise RuntimeError("Synthetic recurrence fixture must have one signed history")
        ledger = ledgers[0]
        original_ledger = ledger.read_bytes()
        saved = ledger.with_suffix(".history-retained")
        ledger.rename(saved)
        self.rejection_pair("history_unavailable", fixture, "history_unavailable")
        saved.rename(ledger)
        rows = [json.loads(line) for line in original_ledger.decode().splitlines()]
        rows[0]["status"] = "unsigned synthetic mutation"
        ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        ledger.with_suffix(".tampered-retained").write_bytes(ledger.read_bytes())
        self.rejection_pair("history_inconsistent", fixture, "history_inconsistent")
        ledger.write_bytes(original_ledger)
        (fixture["vault"] / "Decisions/storage.md").write_bytes(note(fields("storage", False)))
        self.record(fixture, "storage")
        self.rpc("new_named_source", fixture, [("memory_propose_from_drift", {}), ("memory_list_self_proposals", {})], "new_named_source")
        self.rejection_pair("new_draft_idempotent", fixture, "new_draft_idempotent")

    def finish(self, error=None):
        for name, fixture in self.fixtures.items():
            self.snapshot(fixture, name + "-final")
        product_after = {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}
        support_after = {"data_preservation.py": sha(SCRIPTS / "data_preservation.py"), "case-plan.json": sha(PLAN_PATH)}
        traces = {p.relative_to(self.directory).as_posix(): sha(p) for p in sorted(self.traces.glob("*.json"))}
        trace_rows = [json.loads((self.directory / name).read_text(encoding="utf-8")) for name in traces]
        nested = [child for row in trace_rows for child in row["children"]]
        report = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "producer_sha256_after": sha(__file__), "adapter_sha256": self.adapter_hash,
            "support_sha256": self.support, "support_sha256_after": support_after, "source_root": str(ROOT), "product_hashes": self.product,
            "product_hashes_after": product_after, "product_and_producer_unchanged": product_after == self.product and sha(__file__) == self.producer_hash and self.support == support_after,
            "platform": platform.platform(), "python": sys.version, "interpreter": sys.executable, "frozen": self.frozen, "expected_case_ids": CASE_IDS,
            "events": self.events, "fixtures": list(self.fixtures), "processes": self.processes, "trace_files": traces,
            "nested_processes": nested, "all_started_processes_stopped": all(p["stopped"] for p in self.processes),
            "nested_process_tracking_complete": len([row for row in trace_rows if row["instance"].startswith("direct-") and "-child-" not in row["instance"]]) == len(self.processes) and all(row["stopped"] for row in nested),
            "generated_support_sha256": {"tracer/sitecustomize.py": sha(self.tracer)},
            "isolation": {"before": self.before, "after": self.sentinels()}, "error": error, "scope": "longitudinal", "acceptance_credit_awarded": False,
            "ideal_system_verdict": "NOT CHECKED", "limits": PLAN["excluded_claims"],
            "evidence_files": {p.relative_to(self.directory).as_posix(): sha(p) for p in sorted(self.directory.rglob("*")) if p.is_file() and "fixtures" not in p.relative_to(self.directory).parts}}
        self.save("report.json", report)
        print(str(self.directory / "report.json"), flush=True)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = Run(args.output)
    error = None
    def interrupted(signum, frame):
        raise KeyboardInterrupt("Interrupted longitudinal source proof")
    signal.signal(signal.SIGINT, interrupted)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, interrupted)
    try:
        run.run()
    except BaseException as caught:
        error = type(caught).__name__ + ": " + str(caught)
    report = run.finish(error)
    return 0 if report["error"] is None and report["product_and_producer_unchanged"] and report["all_started_processes_stopped"] and report["nested_process_tracking_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
