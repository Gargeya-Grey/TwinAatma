"""Independently score retained synthetic longitudinal source observations."""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys

PRODUCER = "verify-twinaatma.longitudinal-source/v1"
BEFORE = "Choose annual subscriptions before trying the service"
AFTER = "Prefer short cancellable trials before annual commitments"
CONTRADICTION = "Prefer annual commitments instead of short trials"
NARRATIVES = {"mail": "The mail trial revealed missing exports before its renewal deadline.",
    "calendar": "The calendar pilot failed offline during two scheduled meetings.",
    "storage": "The storage pilot could not restore the archived project on another device."}
IDS = {name: "kos:decision:long739-" + name for name in NARRATIVES}
ACTIVITY = ("activity_initial", "activity_reformatted", "activity_retimestamped")
NEGATIVE = ("single_completed", "pending_partner", "missing_explicit_pair", "duplicate_id", "copied_narrative",
    "unchanged_belief", "mismatched_lesson", "contradictory_sources", "superseded_source")
RECURRENCE = ("recorded_pair", "uncertain_attributed", "draft_idempotent", "public_rejection", "unchanged_rejected",
    "reformatted_rejected", "retimestamped_rejected", "renamed_rejected", "rekeyed_rejected", "copied_rejected",
    "history_unavailable", "history_inconsistent", "new_named_source", "new_draft_idempotent")
CASE_IDS = (*ACTIVITY, *NEGATIVE, *RECURRENCE, "identity_and_lineage_preserved")
PLAN = {"version": 1, "scope": "longitudinal", "allowed_evidence": "Synthetic longitudinal public CLI/MCP records only",
    "excluded_claims": ["representative week", "real-host usefulness", "independent human consent", "owner approval"],
    "before": BEFORE, "after": AFTER, "contradiction": CONTRADICTION, "narratives": NARRATIVES,
    "activity_cases": list(ACTIVITY), "negative_cases": list(NEGATIVE), "recurrence_cases": list(RECURRENCE), "decision_ids": IDS,
    "policy": "A new completed source must have a new stable ID, new path and distinct concrete narrative; old-source edits and copied narratives do not reopen a rejected claim.",
    "identity": "Every proposal remains an unapproved uncertain draft. Never call approval or mutate Self."}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError("Unreadable retained JSON: " + str(path)) from error


def need(condition, message):
    if not condition:
        raise ValueError(message)


def plain(path, base=None):
    path = Path(path).absolute()
    need(".." not in path.parts, "Evidence traverses a lexical parent")
    if base is not None:
        need(path.is_relative_to(Path(base).absolute()), "Evidence leaves its retained root")
    for member in (path, *path.parents):
        info = member.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not bool(getattr(info, "st_file_attributes", 0) & 0x400), "Evidence traverses a link or reparse point")
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Evidence is not a single-link regular file")
    return path


def toolkit(root):
    result = {}
    for relative in ("knowledgeos", "scripts", "Templates", ".cursor/hooks"):
        for path in sorted((root / relative).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                result[path.relative_to(root).as_posix()] = sha(plain(path, root))
    for name in ("AGENTS.md", "README.md", "pyproject.toml", "setup.py", "MANIFEST.in", "LICENSE", "knowledgeos.config.example.json", "mcp.cursor.example.json"):
        result[name] = sha(plain(root / name, root))
    return dict(sorted(result.items()))


def fields(name, completed=True, **changes):
    row = {"type": "decision", "title": "Synthetic longitudinal " + name, "description": "Synthetic longitudinal source 739",
        "schema": "knowledgeos-v0.3", "status": "active", "created": "2000-01-01", "updated": "2000-01-01",
        "tags": ["synthetic", "long739"], "id": IDS[name], "project": "Long739", "outcome_status": "confirmed" if completed else "pending",
        "actual_outcome": NARRATIVES[name] if completed else "", "lesson": AFTER if completed else "",
        "belief_before": BEFORE if completed else "", "belief_after": AFTER if completed else ""}
    row.update(changes)
    return row


def note(row, reformatted=False):
    keys = list(row)
    if reformatted:
        keys.reverse()
    lines = ["---", *[key + ": " + json.dumps(row[key], ensure_ascii=False) for key in keys], "---", "", "# Recorded source 739", "", "Synthetic local report. No asserted owner identity.", ""]
    if reformatted:
        lines.insert(-1, "")
    return ("\r\n" if reformatted else "\n").join(lines)


def negative_rows(case):
    rows = {"Decisions/mail.md": fields("mail"), "Decisions/calendar.md": fields("calendar")}
    if case == "single_completed":
        return {"Decisions/mail.md": fields("mail")}
    changes = {
        "pending_partner": fields("calendar", False),
        "missing_explicit_pair": fields("calendar", belief_after=""),
        "duplicate_id": fields("calendar", id=IDS["mail"]),
        "copied_narrative": fields("calendar", actual_outcome=NARRATIVES["mail"]),
        "unchanged_belief": fields("calendar", belief_after=BEFORE, lesson=BEFORE),
        "mismatched_lesson": fields("calendar", lesson="This local lesson does not state a changed preference"),
        "superseded_source": fields("calendar", outcome_status="superseded", supersedes=IDS["mail"]),
    }
    if case in changes:
        rows["Decisions/calendar.md"] = changes[case]
    elif case == "contradictory_sources":
        rows["Decisions/storage.md"] = fields("storage", belief_after=CONTRADICTION, lesson=CONTRADICTION)
    else:
        raise ValueError("Unknown independent negative criterion")
    return rows


def frontmatter(text):
    lines = text.splitlines()
    need(lines and lines[0] == "---", "Source lacks its frontmatter")
    result = {}
    for line in lines[1:]:
        if line == "---":
            return result
        key, colon, value = line.partition(":")
        need(bool(colon) and key not in result, "Source has malformed or duplicate frontmatter")
        value = value.strip()
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            try:
                value = json.loads(value)
            except ValueError:
                pass
        result[key] = value
    raise ValueError("Source frontmatter is incomplete")


def decision_texts(snapshot):
    return {name: text for name, text in snapshot["markdown"].items() if name.startswith("Decisions/") and not name.endswith("_Index.md")}


def public_metadata(text):
    result = frontmatter(text)
    if "outcome_recording" in result:
        result["outcome_recording"] = next(line.partition(":")[2].strip() for line in text.splitlines() if line.startswith("outcome_recording:"))
    return result


def evidence_for(texts):
    rows = []
    for path, text in sorted(texts.items()):
        row = frontmatter(text)
        rows.append({"source_id": row["id"], "path": path, "title": row["title"], "outcome": row["outcome_status"],
            "lesson": row["lesson"], "actual_outcome": row["actual_outcome"], "before": row["belief_before"], "after": row["belief_after"]})
    return rows


def no_change(payload):
    return (isinstance(payload, dict) and payload.get("ok") is True and payload.get("proposed") is False
        and payload.get("mutated_self") is False and payload.get("semantic_change_assessed") is False and "proposal_path" not in payload
        and "error" not in payload and isinstance(payload.get("reason"), str) and "No corroborated" in payload["reason"])


def suppressed(payload, disposition, prior):
    return (isinstance(payload, dict) and payload.get("ok") is True and payload.get("proposed") is False
        and payload.get("mutated_self") is False and payload.get("suppression") == disposition
        and payload.get("existing_proposal") == prior and "proposal_path" not in payload and "error" not in payload)


def proposal_valid(payload, listed, text, source_texts):
    if not isinstance(payload, dict) or not isinstance(listed, dict) or not isinstance(text, str):
        return False
    sources = evidence_for(source_texts)
    corroborated = (len(sources) >= 2 and len({source["source_id"] for source in sources}) == len(sources)
        and len({source["actual_outcome"] for source in sources}) >= 2 and all(
            re.fullmatch(r"kos:decision:[a-z0-9][a-z0-9_-]*", source["source_id"]) and source["outcome"] == "confirmed"
            and source["before"] == BEFORE and source["after"] == AFTER and source["lesson"] == AFTER and bool(source["actual_outcome"].strip())
            for source in sources))
    row = payload
    patch = ("* **Possible change, uncertain**: recorded before: " + BEFORE + "; recorded after: " + AFTER + ". Sources: "
        + "; ".join("[" + source["title"] + "](" + source["path"] + ") (confirmed)" for source in sources) + ".")
    expected_rationale = ["not independent verification of the outcomes or your current belief", "this suggestion is uncertain and needs your review."]
    expected_rationale.extend("Source: " + source["path"] + "; outcome (confirmed): " + source["actual_outcome"] + "; lesson: " + source["lesson"] for source in sources)
    rationale = ("At least two completed decisions with unique stable IDs record this explicit before/after change, "
        "the matching lesson, and distinct outcome narratives. This is recorded corroboration, "
        "not independent verification of the outcomes or your current belief. Matching wording groups "
        "claims only; this suggestion is uncertain and needs your review.\n" + "\n".join(expected_rationale[2:]))
    metadata = frontmatter(text)
    date = metadata.get("created")
    tail = ("\n# Self proposal — drift_log\n\n## Summary\nReview a recorded possible preference change\n\n## Rationale\n" + rationale
        + "\n\n## Proposed markdown for section `drift_log`\n\n```markdown\n" + patch + "\n```\n\n## Accept\n\nA human must approve this in a terminal:\n\n    twinaatma self approve \""
        + Path(str(row.get("proposal_path", ""))).name + "\"\n\nThe agent cannot approve its own proposal; that is the point.\n")
    metadata_expected = {"type": "research", "title": "Review a recorded possible preference change", "description": "Proposed Self.md update for section 'drift_log'.",
        "schema": "knowledgeos-v0.3", "status": "draft", "created": date, "updated": date, "timestamp": str(date) + "T00:00:00Z", "tags": "[self-proposal, ego-node]",
        "project": "KnowledgeOS", "proposal_id": row.get("proposal_id"), "proposal_section": "drift_log", "proposal_target": "People/Self.md", "proposal_mode": "append",
        "proposal_origin": "memory_propose_self_update", "proposal_base_hash": row.get("base_digest")}
    open_rows = listed.get("open")
    return (corroborated and row.get("ok") is True and row.get("proposed") is True and row.get("semantic_change_assessed") is True
        and row.get("mutated_self") is False and row.get("policy") == "proposal_only" and row.get("section") == "drift_log"
        and isinstance(row.get("proposal_id"), str) and bool(row["proposal_id"]) and isinstance(row.get("proposal_path"), str)
        and row.get("evidence") == sources and metadata == metadata_expected and isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
        and re.fullmatch(r"[0-9a-f]{16}", str(row.get("base_digest"))) is not None and text.partition("\n---\n")[2] == tail
        and "status: draft\n" in text and "proposal_target: People/Self.md\n" in text
        and "proposal_section: drift_log\n" in text and "proposal_mode: append\n" in text
        and ("## Proposed markdown for section `drift_log`\n\n```markdown\n" + patch + "\n```") in text
        and all(fragment in text for fragment in expected_rationale)
        and all(text.count("Source: " + source["path"] + "; outcome (confirmed):") == 1 for source in sources)
        and isinstance(open_rows, list) and len(open_rows) == 1 and listed.get("untrusted") == []
        and all(open_rows[0].get(key) == value for key, value in {"path": row.get("proposal_path"), "id": row.get("proposal_id"), "status": "draft", "section": "drift_log", "mode": "append"}.items()))


def recorded_valid(before_text, after_text, request, payload, started_at):
    old, new = frontmatter(before_text), frontmatter(after_text)
    name = Path(request["path"]).stem
    expected = fields(name, False)
    if old != expected or request != {"path": "Decisions/" + name + ".md", "expected_sha256": digest(before_text.encode()),
            "outcome_status": "confirmed", "actual_outcome": NARRATIVES[name], "lesson": AFTER, "belief_before": BEFORE, "belief_after": AFTER}:
        return False
    wanted = dict(old, outcome_status="confirmed", actual_outcome=NARRATIVES[name], lesson=AFTER, belief_before=BEFORE, belief_after=AFTER)
    try:
        timestamp = dt.datetime.fromisoformat(new["outcome_recorded_at"])
        marker = new["outcome_recording"]
        content = "".join(line for line in after_text.splitlines(keepends=True) if not line.startswith("outcome_recording:"))
        request_digest = digest(json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
        wanted.update(updated=dt.datetime.fromisoformat(started_at).astimezone().date().isoformat(), outcome_recorded_at=new["outcome_recorded_at"], outcome_recording=marker)
        editable = {"outcome_status", "actual_outcome", "lesson", "belief_before", "belief_after", "updated", "outcome_recorded_at", "outcome_recording"}
        stable = lambda text: "".join(line for line in text.splitlines(keepends=True) if line.partition(":")[0] not in editable)
        return (new == wanted and timestamp.tzinfo is not None and marker == {"version": 1, "before_sha256": digest(before_text.encode()), "request_sha256": request_digest, "content_sha256": digest(content.encode())}
            and stable(before_text) == stable(after_text) and payload.get("ok") is True and payload.get("recorded") is True
            and payload.get("path") == request["path"] and payload.get("outcome_status") == "confirmed" and payload.get("reviewed_sha256") == request["expected_sha256"]
            and payload.get("sha256") == digest(after_text.encode()) and payload.get("mutated_self") is False and payload.get("index_refresh") == {"status": "current", "retryable": False}
            and not payload.get("index_frozen"))
    except (KeyError, TypeError, ValueError):
        return False


def ledger_evidence(texts):
    key = lambda text: " ".join(re.findall(r"\w+|[<>=+/#]", text.casefold()))
    return {"version": 1, "claim": key(AFTER), "sources": [{"id": source["source_id"], "path": source["path"], "outcome": source["outcome"],
        "lesson": key(source["lesson"]), "actual_outcome": key(source["actual_outcome"]), "before": key(source["before"]), "after": key(source["after"])} for source in evidence_for(texts)]}


def expected_events():
    rows = [{"role": name, "fixture": "activity", "case": name, "transport": "mcp"} for name in ACTIVITY]
    rows += [{"role": name, "fixture": name, "case": name, "transport": "mcp"} for name in NEGATIVE]
    for name in ("mail", "calendar"):
        rows += [{"role": "review-" + name, "fixture": "recurrence", "case": None, "transport": "cli"}, {"role": "record-" + name, "fixture": "recurrence", "case": None, "transport": "mcp"}]
    rows += [{"role": name, "fixture": "recurrence", "case": name, "transport": "mcp"} for name in RECURRENCE if name not in ("new_named_source", "new_draft_idempotent")]
    rows += [{"role": "review-storage", "fixture": "recurrence", "case": None, "transport": "cli"}, {"role": "record-storage", "fixture": "recurrence", "case": None, "transport": "mcp"}]
    rows += [{"role": name, "fixture": "recurrence", "case": name, "transport": "mcp"} for name in ("new_named_source", "new_draft_idempotent")]
    return rows


def process_roles():
    result = ["activity-init", "activity-doctor", *ACTIVITY]
    for name in NEGATIVE:
        result.extend((name + "-init", name + "-doctor", name))
    result.extend(("recurrence-init", "recurrence-doctor"))
    result.extend(row["role"] for row in expected_events() if row["fixture"] == "recurrence")
    return result


def validate_lifetimes(records, traces, processes):
    roles = process_roles()
    need([row.get("role") for row in processes] == roles and set(records) == set(roles), "Incomplete or reassigned process role inventory")
    need(set(traces) == {"direct-" + str(i).zfill(3) for i in range(1, len(roles) + 1)}, "Unknown, missing or reused process instance")
    parent_pids, previous_end = set(), 0
    for ordinal, role in enumerate(roles, 1):
        record, tracked = records[role], processes[ordinal - 1]
        instance = "direct-" + str(ordinal).zfill(3)
        trace = traces[instance]
        need(type(record.get("pid")) is int and record["pid"] > 0 and type(record.get("parent_pid")) is int and record["parent_pid"] > 0, "Process PID ownership is untyped")
        need(tracked == {"pid": record["pid"], "instance": instance, "role": role, "stopped": True, "exit_code": 0}, "Process report disagrees with its recorded exact instance")
        need(record.get("instance") == instance and record.get("role") == role and record.get("stopped") is True and type(record.get("exit_code")) is int and record["exit_code"] == 0
            and record.get("error", "absent") is None and record.get("shell") is False and record.get("gate_key_override_present") is False, "Process did not stop successfully through the literal isolated command")
        times = (record.get("started_ns"), trace.get("started_ns"), trace.get("ended_ns"), record.get("ended_ns"))
        need(all(type(value) is int and value > 0 for value in times) and previous_end < times[0] <= times[1] <= times[2] <= times[3], "Process binding overlaps, reuses a lifetime or reverses trace time")
        need(trace.get("instance") == instance and trace.get("role") == role and trace.get("pid") == record["pid"] and type(trace.get("pid")) is int
            and trace.get("parent_pid") == record["parent_pid"] and trace.get("parent_instance") == "producer-" + str(record["parent_pid"])
            and trace.get("children") == [], "Direct or nested process ownership differs from its original exit trace")
        parent_pids.add(record["parent_pid"])
        previous_end = times[-1]
    need(len(parent_pids) == 1 and not any(record["pid"] in parent_pids for record in records.values()), "Public processes do not belong to one distinct producer")


class RecordedPaths:
    """Accept only the current root or its exact Windows/WSL drive spelling."""
    def __init__(self, root, declared):
        self.root = Path(root).absolute()
        need(isinstance(declared, str) and declared, "Missing original source root")
        self.windows = bool(re.match(r"^[A-Za-z]:[\\/]", declared))
        self.origin = (PureWindowsPath if self.windows else PurePosixPath)(declared)
        need(self.origin.is_absolute() and ".." not in self.origin.parts and declared == str(self.origin), "Noncanonical original source root")
        allowed = {str(self.root)}
        current = str(self.root)
        if re.match(r"^[A-Za-z]:[\\/]", current):
            native = PureWindowsPath(current)
            allowed.add(str(PurePosixPath('/mnt', native.drive[0].lower(), *native.parts[1:])))
        elif len(self.root.parts) > 3 and self.root.parts[1] == 'mnt' and re.fullmatch('[a-z]', self.root.parts[2]):
            allowed.add(str(PureWindowsPath(self.root.parts[2].upper() + ':\\', *self.root.parts[3:])))
        need(declared in allowed, "Original source root is not this exact checkout")

    def text(self, path):
        relative = Path(path).absolute().relative_to(self.root)
        need('..' not in relative.parts, "Original command traverses a parent")
        return str(self.origin.joinpath(*relative.parts))

    def local(self, recorded):
        cls = PureWindowsPath if self.windows else PurePosixPath
        path = cls(recorded)
        need(isinstance(recorded, str) and path.is_absolute() and '..' not in path.parts and str(path) == recorded, "Noncanonical original sentinel path")
        relative = path.relative_to(self.origin)
        local = self.root.joinpath(*relative.parts)
        need(self.text(local) == recorded, "Original sentinel path spelling differs")
        return local


class Observations:
    def __init__(self, path, current=None, root=None):
        self.root = Path(root) if root is not None else next(p for p in Path(__file__).resolve().parents if (p / "knowledgeos/memory.py").is_file())
        self.directory = Path(path).absolute().parent
        relative = self.directory.relative_to(self.root.absolute())
        need(relative.parts[:2] == ("work", "gc-artifacts") and ".knowledgeos" in relative.parts[2:], "Longitudinal report is outside contained synthetic evidence")
        self.path = plain(path, self.directory)
        self.data = load(self.path)
        self.evidence = self.data.get("evidence_files")
        need(isinstance(self.evidence, dict) and self.evidence and self.path.name not in self.evidence, "Missing executable retained evidence")
        for name, value in self.evidence.items():
            need(isinstance(name, str) and not Path(name).is_absolute() and ".." not in Path(name).parts and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Malformed retained file binding")
            need(sha(plain(self.directory / name, self.directory)) == value, "Retained evidence hash mismatch: " + name)
        home = Path(__file__).resolve().parent
        support = {"data_preservation.py": sha(self.root / ".agents/skills/verify-twinaatma/scripts/data_preservation.py"), "case-plan.json": sha(home / "case-plan.json")}
        need(load(home / "case-plan.json") == PLAN and self.json("case-plan.json") == PLAN, "Frozen independent literal criteria changed")
        product = toolkit(self.root)
        self.product = product
        data = self.data
        self.paths = RecordedPaths(self.root, data.get("source_root"))
        self.recorded = self.paths.text
        need(data.get("producer") == PRODUCER and data.get("producer_sha256") == sha(home / "longitudinal.py") == data.get("producer_sha256_after")
            and isinstance(data.get("adapter_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", data["adapter_sha256"])
            and data.get("support_sha256") == support == data.get("support_sha256_after"), "Unsupported or stale producer or support")
        need(data.get("product_hashes") == product == data.get("product_hashes_after") and data.get("product_and_producer_unchanged") is True
            and data.get("source_root") == self.recorded(self.root), "Current complete source product changed or was replaced")
        if current is not None:
            need({key: value for key, value in product.items() if key in current or Path(key).suffix == ".py" and Path(key).parent.as_posix() in ("knowledgeos", ".cursor/hooks")} == current, "Current scorer product namespace differs")
        need(data.get("error", "absent") is None and data.get("expected_case_ids") == list(CASE_IDS) and data.get("events") == expected_events()
            and data.get("fixtures") == ["activity", *NEGATIVE, "recurrence"] and data.get("scope") == "longitudinal"
            and data.get("acceptance_credit_awarded") is False and data.get("ideal_system_verdict") == "NOT CHECKED"
            and data.get("limits") == PLAN["excluded_claims"] and str(data.get("platform", "")).startswith("Windows-" if self.paths.windows else "Linux-")
            and isinstance(data.get("python"), str) and re.match(r"3\.\d+\.", data["python"])
            and isinstance(data.get("interpreter"), str) and (PureWindowsPath if self.paths.windows else PurePosixPath)(data["interpreter"]).is_absolute(), "Longitudinal execution registry, scope or attribution differs")
        self.frozen = self.json("frozen-expectations.json")
        frozen = dict(data["frozen"])
        expected = {"producer": PRODUCER, "source_root": self.recorded(self.root), "product_hashes": product, "producer_sha256": data["producer_sha256"],
            "support_sha256": support, "adapter_sha256": data["adapter_sha256"], "case_plan_sha256": support["case-plan.json"], "literal_case_ids": list(CASE_IDS),
            "frozen_at": frozen.get("frozen_at"), "frozen_before_first_product_invocation": True, "scope": "longitudinal", "time_basis": "synthetic cadence fixture; no representative elapsed week"}
        need(frozen == expected == self.frozen, "Literal pre-invocation freeze is incomplete or reassigned")
        frozen_at = dt.datetime.fromisoformat(frozen["frozen_at"])
        need(frozen_at.tzinfo is not None, "Freeze timestamp has no timezone")
        roles = process_roles()
        need({name for name in self.evidence if name.endswith(".command.json")} == {role + ".command.json" for role in roles}, "Unexpected public process inventory")
        self.records = {role: self.json(role + ".command.json") for role in roles}
        trace_hashes = data.get("trace_files")
        need(isinstance(trace_hashes, dict) and set(trace_hashes) == {"child-traces/direct-" + str(i).zfill(3) + ".json" for i in range(1, len(roles) + 1)}
            and all(self.evidence.get(name) == value for name, value in trace_hashes.items()), "Incomplete direct/nested trace binding")
        traces = {self.json(name)["instance"]: self.json(name) for name in trace_hashes}
        validate_lifetimes(self.records, traces, data.get("processes", []))
        need(data.get("all_started_processes_stopped") is True and data.get("nested_process_tracking_complete") is True and data.get("nested_processes") == [], "Unstopped or untracked public process")
        need(data.get("generated_support_sha256") == {"tracer/sitecustomize.py": self.evidence.get("tracer/sitecustomize.py")}, "Tracer bytes are not bound")
        producer_tree = ast.parse((home / "longitudinal.py").read_text(encoding="utf-8"))
        tracer_literals = [ast.literal_eval(node.value) for node in producer_tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "TRACE_SOURCE" for target in node.targets)]
        need(len(tracer_literals) == 1 and self.text("tracer/sitecustomize.py").replace("\r\n", "\n") == tracer_literals[0], "Executed tracer differs from the current literal producer recorder")
        prefix = [data["interpreter"], "-B", "-X", "utf8", "-P", "-m", "knowledgeos"]
        for role, record in self.records.items():
            fixture = self.fixture_of(role)
            scope = self.directory / "fixtures" / fixture
            need(record.get("cwd") == self.recorded(scope) and record.get("vault") == self.recorded(scope / "vault") and record.get("state_dir") == self.recorded(scope / "gate-state")
                and record.get("import_path") == self.recorded(self.directory / "tracer") + (";" if self.paths.windows else ":") + self.recorded(scope / "toolkit") and record.get("command", [])[:7] == prefix
                and frozen_at <= dt.datetime.fromisoformat(record["started_at"]), "Command escaped its source fixture or preceded literal freeze")
            need(role + ".stdout.txt" in self.evidence and role + ".stderr.txt" in self.evidence, "Original public output is missing")
            if role.endswith("-init"):
                need(record["command"][7:] == ["init", self.recorded(scope / "vault"), "--name", "Synthetic longitudinal 739", "--non-interactive"], "Init command differs")
                initialized = json.loads(self.text(role + ".stdout.txt"))
                need(initialized.get("ok") is True and all(v.get("ok") is True for v in initialized.get("post_init", {}).values()) and set(initialized.get("post_init", {})) >= {"rebuild", "validate"}, "Fresh source fixture init did not establish its postconditions")
            elif role.endswith("-doctor"):
                need(record["command"][7:] == ["doctor", "--vault", self.recorded(scope / "vault")], "Doctor command differs")
        rpc_roles = {row["role"] for row in expected_events() if row["transport"] == "mcp"}
        need({name for name in self.evidence if name.endswith(".requests.jsonl")} == {role + ".requests.jsonl" for role in rpc_roles}, "Incomplete or unexpected public wire inventory")
        isolation = data.get("isolation", {})
        need(isinstance(isolation.get("before"), dict) and isolation["before"] == isolation.get("after")
            and set(isolation["before"]) == {self.recorded(self.root / name) for name in ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}, "Real-vault isolation sentinel set differs")
        for name, value in isolation["before"].items():
            need(value == (sha(self.paths.local(name)) if self.paths.local(name).is_file() else None), "Real-vault sentinel changed after shutdown")
        self.snapshot_cache = {}
        for fixture in data["fixtures"]:
            self.seed(fixture)
            final = self.snapshot(fixture + "-final")
            need(self.physical(self.directory / "fixtures" / fixture) == final["inventory"], "Retained physical source inventory differs from final observations")

    def json(self, name):
        need(name in self.evidence, "Unbound observation: " + name)
        return load(self.directory / name)

    def text(self, name):
        need(name in self.evidence, "Unbound text observation: " + name)
        return (self.directory / name).read_bytes().decode("utf-8")

    def fixture_of(self, role):
        if role.startswith("activity"):
            return "activity"
        for case in NEGATIVE:
            if role == case or role.startswith(case + "-"):
                return case
        return "recurrence"

    def physical(self, directory):
        result = {}
        for parent, dirs, files in os.walk(directory, followlinks=False):
            for name in sorted([*dirs, *files]):
                path = Path(parent) / name
                info = path.lstat()
                need(not stat.S_ISLNK(info.st_mode) and not bool(getattr(info, "st_file_attributes", 0) & 0x400), "Retained fixture contains linked content")
                relative = path.relative_to(directory).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    result[relative] = {"kind": "directory"}
                else:
                    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Retained fixture contains nonplain or hardlinked content")
                    result[relative] = {"kind": "file", "size": info.st_size, "sha256": sha(path), "links": 1}
        return result

    def snapshot(self, label):
        if label in self.snapshot_cache:
            return self.snapshot_cache[label]
        snap = self.json("snapshots/" + label + ".json")
        need(isinstance(snap, dict) and snap.get("fixture") in self.data["fixtures"] and isinstance(snap.get("inventory"), dict)
            and isinstance(snap.get("markdown"), dict) and isinstance(snap.get("ledger"), dict), "Snapshot source inventory is incomplete")
        inv = snap["inventory"]
        for name, row in inv.items():
            need(not Path(name).is_absolute() and ".." not in Path(name).parts and isinstance(row, dict) and row.get("kind") in ("file", "directory")
                and (row["kind"] == "directory" or row.get("links") == 1), "Snapshot contains unknown or linked source ownership")
        need(set(snap["markdown"]) == {name[6:] for name, row in inv.items() if name.startswith("vault/") and name.endswith(".md") and row["kind"] == "file"}, "Source text census is incomplete")
        for name, text in snap["markdown"].items():
            need(isinstance(text, str) and inv.get("vault/" + name) == {"kind": "file", "size": len(text.encode()), "sha256": digest(text.encode()), "links": 1}, "Source text differs from its complete inventory")
        for name, text in snap["ledger"].items():
            raw_options = {text.encode(), text.replace("\r\n", "\n").replace("\n", "\r\n").encode()}
            need(name.startswith("gate-state/vaults/") and name.endswith("/self-proposals.jsonl")
                and any(inv.get(name) == {"kind": "file", "size": len(raw), "sha256": digest(raw), "links": 1} for raw in raw_options), "Original signed history is not inventory bound")
        need(set(snap["ledger"]) == {name for name in inv if name.startswith("gate-state/") and name.endswith(".jsonl")}, "Signed history census is incomplete")
        seed_name = "snapshots/" + snap["fixture"] + "-seed.json"
        initial = snap if label.endswith("-seed") else self.json(seed_name)
        need(snap["markdown"]["People/Self.md"] == initial["markdown"]["People/Self.md"], "Identity bytes changed during the source journey")
        toolkit_inv = {name[8:]: row for name, row in inv.items() if name.startswith("toolkit/")}
        need(toolkit_inv == self.json(snap["fixture"] + ".toolkit.json"), "Isolated product bytes changed during the journey")
        self.snapshot_cache[label] = snap
        return snap

    def seed(self, fixture):
        snap = self.snapshot(fixture + "-seed")
        expected = negative_rows(fixture) if fixture in NEGATIVE else {"Decisions/mail.md": fields("mail", False), "Decisions/calendar.md": fields("calendar", False)}
        need(decision_texts(snap) == {name: note(values) for name, values in expected.items()}, "Frozen seeded source bytes differ: " + fixture)
        need(not any(name.startswith("People/Self-Proposals/") for name in snap["markdown"]) and snap["ledger"] == {}, "Source fixture began with hidden proposal history")
        inv = self.json(fixture + ".toolkit.json")
        need({name: row["sha256"] for name, row in inv.items() if row.get("kind") == "file"} == self.product, "Copied complete product does not match current source")

    def rpc(self, role, calls):
        fixture = self.fixture_of(role)
        scope = self.directory / "fixtures" / fixture
        need(self.records[role]["command"][7:] == ["mcp", "--vault", self.recorded(scope / "vault"), "--framing", "ndjson"], "Public MCP command differs from isolated source")
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-longitudinal", "version": "1"}}}, {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        messages += [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments}} for i, (name, arguments) in enumerate(calls, 2)]
        need([json.loads(line) for line in self.text(role + ".requests.jsonl").splitlines()] == messages, "Wrong-source, extra, missing or changed public request: " + role)
        responses = [json.loads(line) for line in self.text(role + ".stdout.txt").splitlines()]
        need(len(responses) == len(calls) + 1 and [row.get("id") for row in responses] == list(range(1, len(calls) + 2)) and all(row.get("jsonrpc") == "2.0" and "error" not in row for row in responses), "Original MCP response sequence differs")
        initialized = responses[0].get("result", {})
        need(initialized.get("serverInfo", {}).get("name") == "knowledgeos-memory" and initialized.get("protocolVersion") == "2024-11-05", "Public server identity differs")
        result = []
        for response in responses[1:]:
            row = response.get("result", {})
            content = row.get("content")
            need(type(row.get("isError")) is bool and isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text" and isinstance(content[0].get("text"), str), "MCP result lacks typed original content")
            payload = json.loads(content[0]["text"])
            need(isinstance(payload, dict) and row["isError"] == bool(payload.get("error")), "Public MCP error observation disagrees")
            result.append(payload)
        self.snapshot(role + "-before")
        self.snapshot(role + "-after")
        return result

    def cli_review(self, name):
        role = "review-" + name
        scope = self.directory / "fixtures/recurrence"
        need(self.records[role]["command"][7:] == ["memory", "memory_get_note", "--vault", self.recorded(scope / "vault"), "--args", json.dumps({"path_or_id": "Decisions/" + name + ".md"})], "Public reviewed outcome source differs")
        payload = json.loads(self.text(role + ".stdout.txt"))
        before, after = self.snapshot(role + "-before"), self.snapshot(role + "-after")
        text = before["markdown"]["Decisions/" + name + ".md"]
        need(before["markdown"] == after["markdown"] and payload.get("path") == "Decisions/" + name + ".md" and payload.get("sha256") == digest(text.encode()) and payload.get("frontmatter") == frontmatter(text), "CLI review failed to bind the exact current source")
        return payload

    def signed_rows(self, snapshot, *, invalid=False):
        ledgers = snapshot["ledger"]
        need(len(ledgers) == 1, "Expected one complete signed proposal history")
        path, text = next(iter(ledgers.items()))
        key_path = plain(self.directory / "fixtures/recurrence/gate-state/gate.key", self.directory)
        key = bytes.fromhex(key_path.read_text(encoding="ascii").strip())
        rows = [json.loads(line) for line in text.splitlines()]
        need(rows and all(isinstance(row, dict) for row in rows), "Signed history lacks rows")
        authentic = [hmac.compare_digest(str(row.get("mac", "")), hmac.new(key, json.dumps({k: v for k, v in row.items() if k != "mac"}, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()) for row in rows]
        need(not all(authentic) if invalid else all(authentic), "Signed history integrity does not match the exercised condition")
        return rows


def score(path, current=None, *, root=None):
    obs = Observations(path, current, root)
    checks = {}
    def case(name, passed):
        checks[name] = bool(passed)
    for ordinal, name in enumerate(ACTIVITY):
        sid = "long739-" + name
        result = obs.rpc(name, [("memory_session_start", {"task_hint": "Remember source activity without inferring a personal belief", "session_id": sid}), ("memory_propose_from_drift", {}), ("memory_session_end", {"summary": "Synthetic longitudinal activity only; no owner belief change was supplied.", "session_id": sid})])
        before, after = obs.snapshot(name + "-before"), obs.snapshot(name + "-after")
        expected = {"Decisions/" + key + ".md": note(fields(key, False, updated="2026-10-19" if ordinal == 2 else "2000-01-01"), ordinal == 1) for key in ("mail", "calendar")}
        need(decision_texts(before) == expected == decision_texts(after) and before["autopilot"] == {"real_sessions": 3, "first_session_ts": 1, "last_drift_propose_ts": 0}, "Mechanical churn or synthetic cadence fixture differs")
        tick = result[0].get("drift_tick", {})
        no_proposals = not any(key.startswith("People/Self-Proposals/") for key in after["markdown"])
        activity_paths = {row.get("path") for row in result[1].get("activity", {}).get("recent_notes", [])}
        case(name, result[0].get("session_id") == sid and no_change(tick) and no_change(result[1]) and no_proposals and result[2].get("ritual") == "session_end"
            and result[2].get("session_id") == sid and result[2].get("captured", {}).get("ok") is True and after["autopilot"].get("sessions", {}).get(sid, {}).get("status") == "ended"
            and (ordinal != 2 or {"Decisions/mail.md", "Decisions/calendar.md"} <= activity_paths))
    for name in NEGATIVE:
        result = obs.rpc(name, [("memory_propose_from_drift", {})])[0]
        before, after = obs.snapshot(name + "-before"), obs.snapshot(name + "-after")
        need(decision_texts(before) == decision_texts(after) == {key: note(row) for key, row in negative_rows(name).items()}, "Insufficient or contradictory evidence corpus changed")
        case(name, no_change(result) and not any(key.startswith("People/Self-Proposals/") for key in after["markdown"]) and after["ledger"] == {})
    recorded = {}
    for name in ("mail", "calendar", "storage"):
        reviewed = obs.cli_review(name)
        args = {"path": reviewed["path"], "expected_sha256": reviewed["sha256"], "outcome_status": "confirmed", "actual_outcome": NARRATIVES[name], "lesson": AFTER, "belief_before": BEFORE, "belief_after": AFTER}
        result = obs.rpc("record-" + name, [("memory_record_outcome", args)])[0]
        before, after = obs.snapshot("record-" + name + "-before"), obs.snapshot("record-" + name + "-after")
        relative = "Decisions/" + name + ".md"
        need(all(text == after["markdown"].get(key) for key, text in before["markdown"].items() if key != relative), "Reviewed recording changed unrelated notes or identity")
        recorded[name] = recorded_valid(before["markdown"][relative], after["markdown"][relative], args, result, obs.records["record-" + name]["started_at"])
    pair = obs.rpc("recorded_pair", [("memory_get_note", {"path_or_id": "Decisions/mail.md"}), ("memory_get_note", {"path_or_id": "Decisions/calendar.md"}), ("memory_pending_outcomes", {})])
    pair_texts = decision_texts(obs.snapshot("recorded_pair-after"))
    case("recorded_pair", all(recorded[name] for name in ("mail", "calendar")) and all(pair[i].get("frontmatter") == public_metadata(pair_texts["Decisions/" + name + ".md"]) and pair[i].get("sha256") == digest(pair_texts["Decisions/" + name + ".md"].encode()) for i, name in enumerate(("mail", "calendar"))) and pair[2].get("outcomes") == [] and pair[2].get("count") == 0)
    created = obs.rpc("uncertain_attributed", [("memory_propose_from_drift", {}), ("memory_list_self_proposals", {})])
    first = created[0].get("proposal_path")
    need(isinstance(first, str) and first.startswith("People/Self-Proposals/") and first in obs.snapshot("uncertain_attributed-after")["markdown"], "Missing attributed proposal source")
    proposal_text = obs.snapshot("uncertain_attributed-after")["markdown"][first]
    need(decision_texts(obs.snapshot("uncertain_attributed-before")) == pair_texts == decision_texts(obs.snapshot("uncertain_attributed-after")), "Attributed change was not derived from the exact reviewed source pair")
    case("uncertain_attributed", proposal_valid(created[0], created[1], proposal_text, pair_texts))
    first_ledger = obs.signed_rows(obs.snapshot("uncertain_attributed-after"))
    need(len(first_ledger) == 1 and first_ledger[0].get("proposal") == first and first_ledger[0].get("status") == "draft" and first_ledger[0].get("file_sha256") == digest(proposal_text.encode())
        and first_ledger[0].get("learning_evidence") == ledger_evidence(pair_texts), "Created proposal is not the exact source-attributed signed draft")
    repeated = obs.rpc("draft_idempotent", [("memory_propose_from_drift", {}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/mail.md"})])
    need(obs.snapshot("draft_idempotent-before")["markdown"] == obs.snapshot("draft_idempotent-after")["markdown"] == obs.snapshot("uncertain_attributed-after")["markdown"], "Draft repeat changed source or proposal bytes")
    case("draft_idempotent", all(suppressed(value, "already_suggested", first) for value in repeated))
    rejected = obs.rpc("public_rejection", [("memory_reject_self_update", {"proposal_path": first, "reason": "Synthetic rejection for retained recurrence evidence"}), ("memory_list_self_proposals", {})])
    rejected_snapshot = obs.snapshot("public_rejection-after")
    rejected_rows = obs.signed_rows(rejected_snapshot)
    case("public_rejection", rejected[0].get("ok") is True and rejected[0].get("mutated_self") is False and rejected[1].get("open") == [] and rejected[1].get("untrusted") == [] and len(rejected_rows) == 1 and rejected_rows[0].get("status") == "rejected" and "## Rejected" in rejected_snapshot["markdown"][first])
    original = pair_texts["Decisions/mail.md"]
    for name in ("unchanged_rejected", "reformatted_rejected", "retimestamped_rejected", "renamed_rejected", "rekeyed_rejected", "copied_rejected", "history_unavailable", "history_inconsistent"):
        path = "Decisions/mail-renamed.md" if name == "renamed_rejected" else "Decisions/mail-copy.md" if name == "copied_rejected" else "Decisions/mail.md"
        results = obs.rpc(name, [("memory_propose_from_drift", {}), ("memory_propose_from_lesson", {"path_or_id": path})])
        before, after = obs.snapshot(name + "-before"), obs.snapshot(name + "-after")
        wanted = dict(pair_texts)
        if name == "reformatted_rejected":
            wanted["Decisions/mail.md"] = original.replace("\n", "\r\n").replace("# Recorded source 739", "# Recorded source 739\r\n")
        elif name == "retimestamped_rejected":
            wanted["Decisions/mail.md"] = original.replace("Synthetic longitudinal mail", "Synthetic retitled mail").replace("2000-01-01", "2026-10-19")
        elif name == "renamed_rejected":
            wanted["Decisions/mail-renamed.md"] = wanted.pop("Decisions/mail.md")
        elif name == "rekeyed_rejected":
            wanted["Decisions/mail.md"] = original.replace(IDS["mail"], "kos:decision:long739-rekeyed").replace(NARRATIVES["mail"], "A corrected concrete report on the same mail source.")
        if name in ("copied_rejected", "history_unavailable", "history_inconsistent"):
            wanted["Decisions/mail-copy.md"] = note(fields("mail", id="kos:decision:long739-copy"))
        need(decision_texts(before) == wanted == decision_texts(after) and before["markdown"] == after["markdown"], "Rejected recurrence changed source lineage or created a new suggestion: " + name)
        if name == "history_unavailable":
            need(before["ledger"] == after["ledger"] == {}, "Unavailable history condition was not exercised")
            valid = all(value.get("error") == "proposal history is incomplete; refusing to repeat a learning suggestion" and "proposal_path" not in value for value in results)
        elif name == "history_inconsistent":
            rows = obs.signed_rows(before, invalid=True)
            need(len(rows) == 1 and rows[0].get("status") == "unsigned synthetic mutation", "Inconsistent signed history condition differs")
            valid = all(value.get("error") == "proposal history could not be verified; refusing to repeat a learning suggestion" and "proposal_path" not in value for value in results)
        else:
            rows = obs.signed_rows(before)
            need(rows == rejected_rows and after["ledger"] == before["ledger"], "Signed rejection changed during an old-evidence retry")
            valid = all(suppressed(value, "rejected_without_new_source", first) for value in results)
        case(name, valid)
    new = obs.rpc("new_named_source", [("memory_propose_from_drift", {}), ("memory_list_self_proposals", {})])
    latest = new[0].get("proposal_path")
    new_snapshot = obs.snapshot("new_named_source-after")
    need(isinstance(latest, str) and latest != first and latest in new_snapshot["markdown"], "Genuinely new evidence did not create its separate proposal")
    source_texts = decision_texts(new_snapshot)
    expected_new_sources = dict(pair_texts, **{"Decisions/mail-copy.md": note(fields("mail", id="kos:decision:long739-copy")),
        "Decisions/storage.md": obs.snapshot("record-storage-after")["markdown"]["Decisions/storage.md"]})
    need(decision_texts(obs.snapshot("new_named_source-before")) == source_texts == expected_new_sources, "New evidence is not the exact reviewed named source with preserved prior lineage")
    previous_sources = evidence_for(pair_texts)
    next_sources = evidence_for(source_texts)
    fresh = [source for source in next_sources if source["source_id"] not in {s["source_id"] for s in previous_sources} and source["path"] not in {s["path"] for s in previous_sources} and source["actual_outcome"] not in {s["actual_outcome"] for s in previous_sources}]
    case("new_named_source", recorded["storage"] and len(fresh) == 1 and fresh[0]["path"] == "Decisions/storage.md" and proposal_valid(new[0], new[1], new_snapshot["markdown"][latest], source_texts))
    rows = obs.signed_rows(new_snapshot)
    need(len(rows) == 2 and rows[0] == rejected_rows[0] and rows[1].get("status") == "draft" and rows[1].get("proposal") == latest and rows[1].get("file_sha256") == digest(new_snapshot["markdown"][latest].encode())
        and rows[1].get("learning_evidence") == ledger_evidence(source_texts), "New named source did not preserve the source-attributed signed rejection lineage")
    repeated = obs.rpc("new_draft_idempotent", [("memory_propose_from_drift", {}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/mail.md"})])
    need(obs.snapshot("new_draft_idempotent-before")["markdown"] == obs.snapshot("new_draft_idempotent-after")["markdown"] == new_snapshot["markdown"], "The new draft replay changed preserved evidence")
    final = obs.snapshot("recurrence-final")
    need(final["markdown"] == new_snapshot["markdown"] and obs.signed_rows(final) == rows
        and {name for name in final["markdown"] if name.startswith("People/Self-Proposals/")} == {first, latest}, "Final stopped fixture lost or invented proposal lineage")
    case("new_draft_idempotent", suppressed(repeated[0], "already_suggested", latest) and suppressed(repeated[1], "rejected_without_new_source", first))
    for event in expected_events():
        before, after = obs.snapshot(event["role"] + "-before"), obs.snapshot(event["role"] + "-after")
        if event["fixture"] != "activity":
            seed = obs.snapshot(event["fixture"] + "-seed")
            baseline = {k: v for k, v in seed["markdown"].items() if not k.startswith(("Decisions/", "People/Self-Proposals/"))}
            need(all(after["markdown"].get(k) == v for k, v in baseline.items()), "Public source operation changed unrelated existing markdown")
        need(before["markdown"]["People/Self.md"] == after["markdown"]["People/Self.md"], "Public source operation mutated identity")
    case("identity_and_lineage_preserved", True)
    need(set(checks) == set(CASE_IDS), "Independent scoring omitted a frozen case")
    aggregates = {}
    for outcome, names, identifier in (("LEARNING.semantic_drift", (*ACTIVITY, *NEGATIVE, "recorded_pair", "uncertain_attributed", "identity_and_lineage_preserved"), "longitudinal.semantic_drift.complete"),
            ("LEARNING.rejection_recurrence", (*RECURRENCE, "identity_and_lineage_preserved"), "longitudinal.rejection_recurrence.complete")):
        aggregates[identifier] = {"id": identifier, "verdict": "PASS" if all(checks[name] for name in names) else "FAIL", "outcome": outcome, "observed": {name: checks[name] for name in names}}
    return {"path": str(obs.path), "report_sha256": sha(obs.path), "scope": "longitudinal", "producer": PRODUCER,
        "producer_sha256": obs.data["producer_sha256"], "support_sha256": obs.data["support_sha256"], "adapter_sha256": sha(__file__),
        "adapter_sha256_at_observation": obs.data["adapter_sha256"], "assessment_kind": "independent regrade of retained public-process observations",
        "evidence_files": obs.evidence, "checks": aggregates, "case_results": checks, "limits": PLAN["excluded_claims"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        need(not args.output.exists(), "Preserve the existing score and choose a fresh output")
        result = score(args.report)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({key: row["verdict"] for key, row in result["checks"].items()}))
        return 0 if all(row["verdict"] == "PASS" for row in result["checks"].values()) else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("Longitudinal evidence rejected: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
