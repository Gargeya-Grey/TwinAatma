"""Independently recompute the single complete writer-preservation outcome."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath

from writer_census import read_census
from physical_observer import physical, alias_relative
from writer_contract import (PRODUCER, OUTCOME, SCOPE, CAPTURE_NAME, FIXTURE_NOTES, HISTORY,
                             OUTCOME_ARGS, normal_calls, capture_call, proposal_call, forget_call,
                             alias_specs, directory_specs, expected_case_ids, cli_arguments, legacy_specs,
                             native_join, public_operation, fault_operation, SHELL_RUNNER, RUNTIME_OBSERVER)

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "knowledgeos/memory.py").is_file())
VERIFY = ROOT / ".agents/skills/verify-twinaatma/scripts"
HEX = re.compile(r"[0-9a-f]{64}\Z")
REUSED = {
    "verify-twinaatma.data-preservation/v1": "export",
    "verify-twinaatma.generated-writers/v2": "generated",
    "verify-twinaatma.memory-census/v2": "census",
    "verify-twinaatma.maintenance/v1": "maintenance",
    "verify-twinaatma.hooks-preservation/v1": "hooks",
    "verify-twinaatma.validation/v1": "validation",
}


def checked_freeze_revision(value):
    require(isinstance(value, dict), "Frozen source manifest is not an object")
    schema = value.get("schema")
    require("schema" not in value or type(schema) is str, "Frozen source schema must be explicit text")
    key = {None: "revision", "twinaatma.C-product-freeze/v1": "source_revision"}.get(schema)
    require(key is not None, "Unsupported frozen source manifest schema")
    revision = value.get(key)
    require(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision), "Frozen source revision is missing or malformed")
    require(all(name not in value or value[name] == revision for name in ("revision", "source_revision")),
            "Frozen source revision fields conflict")
    return revision


def checked_init_refresh(record, refresh, before, after, toolkit):
    require(type(record.get("exit_code")) is int and record["exit_code"] == 0
            and refresh.get("ok") is True, "Public init refresh did not complete successfully")
    post = refresh.get("post_init")
    require(isinstance(post, dict) and all(isinstance(post.get(name), dict) and post[name].get("ok") is True
            for name in ("rebuild", "validate")), "Public init refresh lacks successful rebuild and validation")
    summary = post["validate"].get("summary")
    require(isinstance(summary, dict) and type(summary.get("errors")) is int and summary["errors"] == 0,
            "Public init refresh has validation errors or an invalid summary")
    require(refresh.get("conflicts") == ["People/Self.md", "README.md"], "Public init refresh lost its exact protected conflicts")
    preserved_identity(before, after)
    for relative in refresh["conflicts"]:
        original = before.get("vault/" + relative)
        require(isinstance(original, dict) and original.get("kind") == "file" and after.get("vault/" + relative) == original,
                "Public init refresh changed a protected conflict")
    require(isinstance(toolkit, dict) and toolkit, "Public init refresh lacks the current complete source inventory")
    for relative, digest in toolkit.items():
        original = before.get("toolkit/" + relative)
        require(isinstance(original, dict) and original.get("kind") == "file" and original.get("sha256") == digest
                and after.get("toolkit/" + relative) == original, "Public init refresh changed its complete source inventory")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plain_file(directory, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "Evidence name must be a contained lexical file")
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and all(p not in {"", ".", ".."} for p in relative.split("/")), "Evidence path escapes its directory")
    path = Path(directory).joinpath(*parts.parts)
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)), "Evidence traverses a link or reparse point")
        if item == Path(directory):
            break
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Evidence is not a plain single-link file")
    return path


def local(value, base):
    return ROOT / base.data_repository_location(value)


def evidence_json(directory, evidence, name):
    require(name in evidence and sha(plain_file(directory, name)) == evidence[name], "Missing or altered independently hashed observation: " + name)
    return read(plain_file(directory, name))


def valid_inventory(value):
    require(isinstance(value, dict) and bool(value), "Full source inventory is absent")
    for name, row in value.items():
        require(isinstance(name, str) and name and not name.startswith("/") and all(p not in {"", ".", ".."} for p in name.split("/")), "Source inventory path is unsafe")
        require(isinstance(row, dict) and row.get("kind") in {"file", "directory", "link", "other"}, "Source inventory row is invalid")
        if row["kind"] == "file":
            require(type(row.get("size")) is int and row["size"] >= 0 and type(row.get("links")) is int and row["links"] > 0
                    and isinstance(row.get("sha256"), str) and HEX.fullmatch(row["sha256"]), "Source inventory file metadata is invalid")
    return value


def preserved_identity(before, after, allowed=(), *, expected_self_links=None):
    before, after = valid_inventory(before), valid_inventory(after)
    key = "vault/People/Self.md"
    expected = dict(before.get(key, {}))
    if expected_self_links is not None:
        require(type(expected_self_links) is int and expected_self_links > 0, "Invalid narrowly expected Self link count")
        expected["links"] = expected_self_links
    require(expected.get("kind") == "file" and expected == after.get(key), "Protected Self changed or disappeared in full before/after inventories")
    for path, row in before.items():
        if path.startswith("vault/People/") and row.get("kind") == "file" and path not in allowed:
            require(after.get(path) == (expected if path == key else row), "Existing protected identity or proposal history changed: " + path)
    return True


def same_physical_self(before, after, expected_links=None):
    require(isinstance(before, dict) and before.get("kind") == "file" and isinstance(after, dict), "Physical original Self observation is absent")
    require(all(type(before.get(key)) is int and before[key] >= 0 for key in ("device", "inode", "size", "links")) and before["inode"] > 0, "Original Self physical identity is malformed")
    expected = dict(before)
    if expected_links is not None:
        expected["links"] = expected_links
    require(after == expected, "Original Self inode, device, bytes, size or exact expected link count changed")


def protected_io(stderr, record, fixture, before_self, *, detach=None):
    starts = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_PROTECTED_AUDIT_START=")]
    runtimes = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_RUNTIME_START=")]
    require(starts and {s.get("pid") for s in starts} == {r.get("pid") for r in runtimes}
            and len(starts) == len(runtimes), "Python protected-I/O audit lacks an actual runtime PID")
    expected = {key: before_self[key] for key in ("device", "inode", "size", "links", "sha256")}
    for start in starts:
        require(start.get("self_path") == native_join(fixture["vault"], "People/Self.md") and start.get("self") == expected, "Protected-I/O audit observed a different original Self")
    events = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_PROTECTED_IO=")]
    if detach is None:
        require(not events, "A public writer attempted a hidden write, truncate, rename or metadata change on protected Self or its alias")
        return
    require(len(events) == 1 and events[0].get("pid") == record["pid"] and events[0].get("event") == "os.rename", "Safe manifest detachment lacks one actual atomic replacement and no identity write/truncate")
    paths = events[0].get("paths", [])
    require(len(paths) == 2 and paths[0].get("protected") is False and paths[1].get("protected") is True
            and paths[1].get("path") == native_join(fixture["scope"], "vault/.knowledgeos/index-manifest.json")
            and paths[1].get("identity") == expected, "Atomic replacement did not target only the inspected manifest alias")
    source = paths[0].get("path", "").replace("\\", "/")
    fresh = paths[0].get("identity", {})
    require(source.rsplit("/", 1)[0] == native_join(fixture["scope"], "vault/.knowledgeos").replace("\\", "/")
            and source.rsplit("/", 1)[1].startswith(".gate-write-") and source.endswith(".tmp")
            and fresh.get("device") == expected["device"] and type(fresh.get("inode")) is int and fresh["inode"] > 0
            and fresh["inode"] != expected["inode"] and fresh.get("links") == 1
            and type(fresh.get("size")) is int and fresh["size"] >= 0
            and isinstance(fresh.get("sha256"), str) and HEX.fullmatch(fresh["sha256"]),
            "Safe manifest replacement did not publish one independently fingerprinted distinct file")


def manifest_detach(name, before, after, physical_before, physical_after):
    if name not in {"hard-index-manifest", "symlink-index-manifest"}:
        return None
    target = "vault/.knowledgeos/index-manifest.json"
    if before.get(target) == after.get(target):
        return None
    left, right = physical_before.get("alias"), physical_after.get("alias")
    original = physical_before.get("self")
    require(isinstance(original, dict) and original.get("links") == (2 if name.startswith("hard-") else 1),
            "Manifest detachment began with an unexpected original Self link count")
    require(physical_before.get("alias_relative") == physical_after.get("alias_relative") == target
            and isinstance(left, dict) and isinstance(right, dict) and right.get("kind") == "file" and right.get("links") == 1,
            "Manifest alias detachment did not produce one plain independent file")
    linked = left.get("effective") if name.startswith("symlink-") else left
    require(linked and all(linked.get(key) == original.get(key) for key in ("device", "inode", "size", "links", "sha256"))
            and (right["device"], right["inode"]) != (original["device"], original["inode"])
            and after.get(target) == {key: right[key] for key in ("kind", "size", "sha256", "links")}, "Manifest alias was not the actual original Self before safe detachment")
    expected_links = original["links"] - (1 if name.startswith("hard-") else 0)
    same_physical_self(original, physical_after.get("self"), expected_links)
    preserved_identity(before, after, expected_self_links=expected_links)
    return right


def physical_regular(path, row):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)), "Retained protected bytes became a redirected path")
    require(info.st_size == row["size"] and sha(path) == row["sha256"] and info.st_nlink == row["links"], "Retained physical bytes disagree with their full final inventory")


def checked_processes(data, directory, evidence, base):
    processes = data.get("processes")
    require(isinstance(processes, list) and processes and data.get("all_started_processes_stopped") is True, "Real owned process shutdown is absent")
    require(type(data.get("producer_pid")) is int and data["producer_pid"] > 0, "Actual producer PID is missing")
    records = {}
    for process in processes:
        role = process.get("role")
        require(isinstance(role, str) and role and role not in records and type(process.get("pid")) is int and process["pid"] > 0,
                "Owned PIDs need unique launch roles")
        record = evidence_json(directory, evidence, role + ".command.json")
        require(process.get("stopped") is True and type(process.get("exit_code")) is int
                and record.get("pid") == process["pid"] and record.get("exit_code") == process["exit_code"]
                and record.get("stopped") is True and record.get("shell") is False and record.get("error") is None
                and type(record.get("seconds")) in {int, float} and 0 <= record["seconds"] < 300,
                "Fabricated or incomplete process receipt disagrees with retained command")
        require(isinstance(record.get("command"), list) and record["command"] and all(isinstance(s, str) and s for s in record["command"]), "Process argv is absent")
        for suffix in (".stdout.txt", ".stderr.txt"):
            require(role + suffix in evidence, "Process output is not retained")
        if role != "revision" and not role.endswith("-junction") and not role.startswith("shell-"):
            stderr = plain_file(directory, role + ".stderr.txt").read_text(encoding="utf-8")
            starts = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_RUNTIME_START=")]
            own = [start for start in starts if start.get("pid") == process["pid"]]
            require(len(own) == 1 and own[0].get("argv") == record["command"]
                    and own[0].get("observer") == native_join(record.get("import_path", ""), "sitecustomize.py")
                    and own[0].get("parent_pid") == data["producer_pid"],
                    "Process receipt is not bound to its real Python startup PID and argv")
        require(local(record["state_dir"], base).is_relative_to(directory), "Process state leaves its owned fixture evidence")
        records[role] = record
    require({name for name in evidence if name.endswith(".command.json")} == {role + ".command.json" for role in records}, "An actual command is untracked or fabricated")
    return records


def parse_rpc(directory, evidence, role, calls):
    requests = evidence_json(directory, evidence, role + ".requests.json")
    expected = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-identity", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    expected += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": args}}
                 for index, (name, args) in enumerate(calls, 2)]
    require(requests == expected, "Actual public MCP request inventory differs from the literal writer contract")
    rows = [json.loads(line) for line in plain_file(directory, role + ".stdout.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(rows) == len(calls) + 1 and [row.get("id") for row in rows] == list(range(1, len(calls) + 2))
            and rows[0].get("result", {}).get("serverInfo", {}).get("name") == "knowledgeos-memory", "Actual MCP response sequence or server identity is wrong")
    results = []
    for row in rows[1:]:
        result = row.get("result", {})
        contents = result.get("content")
        require(isinstance(contents, list) and len(contents) == 1 and contents[0].get("type") == "text" and type(result.get("isError")) is bool, "MCP status is not a truthful typed protocol result")
        payload = json.loads(contents[0]["text"])
        require(isinstance(payload, dict), "MCP public result must be an object")
        failed = "error" in payload or payload.get("ok") is False or bool(payload.get("missing")) or bool(payload.get("failed"))
        require(result["isError"] == failed, "MCP isError contradicts actual public refusal fields")
        results.append({"payload": payload, "is_error": failed})
    require(evidence_json(directory, evidence, role + ".results.json") == results, "Parsed result claims differ from original wire bytes")
    return results


def nested_trace(directory, role, record, expected_child=None, shell=False):
    stderr = plain_file(directory, role + ".stderr.txt").read_text(encoding="utf-8")
    if shell:
        starts = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_SHELL_CHILD_START=")]
        ends = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_SHELL_CHILD_EXIT=")]
        require(len(starts) == len(ends) == 1 and type(starts[0].get("pid")) is int and starts[0]["pid"] != record["pid"]
                and starts[0]["pid"] == ends[0].get("pid") and type(ends[0].get("exit_code")) is int,
                "Native shell wrapper lacks its actual synchronous Python child and exit")
        require(starts[0].get("operation_argv") == expected_child
                and starts[0].get("argv", [])[1:] == ["-B", "-P", "-c", SHELL_RUNNER, *expected_child]
                and ends[0]["exit_code"] == record["exit_code"], "Shell child argv/exit is fabricated or calls the wrong public source")
        native = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_NATIVE_SHELL_START=")]
        exited = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("IDENTITY_NATIVE_SHELL_EXIT=")]
        require(native and len(native) == len(exited) and {r["pid"] for r in native} == {r["pid"] for r in exited}
                and record["pid"] in {r["pid"] for r in native} and starts[0]["parent_pid"] in {r["pid"] for r in native}, "Native shell wrapper or its intermediate shell lacks actual PID/exit binding")
        scripts = {record["command"][1]}
        if record["command"][1].endswith("/capture.sh"):
            scripts.add(record["command"][1][:-len("capture.sh")] + "rebuild_index.sh")
        require({r.get("script") for r in native} == scripts and len(native) == len(scripts)
                and all(r.get("exit_code") == record["exit_code"] for r in exited), "Native shell trace omits or invents a public wrapper")
        require(all(r["pid"] == record["pid"] or r["parent_pid"] == record["pid"] for r in native), "Native intermediate shell has an invented parent")
        return [*native, *starts]
    traces = [json.loads(line.partition("=")[2]) for line in stderr.splitlines() if line.startswith("MAINTENANCE_CHILDREN=")]
    require(len(traces) == 1 and traces[0].get("parent_pid") == record["pid"], "Traced writer lacks a real parent process binding")
    children = traces[0].get("children")
    require(isinstance(children, list), "Nested child receipt is missing")
    for child in children:
        require(type(child.get("pid")) is int and child["pid"] > 0 and child["pid"] != record["pid"]
                and child.get("stopped") is True and type(child.get("exit_code")) is int
                and isinstance(child.get("argv"), list) and child["argv"], "Nested child was invented or not waited after shutdown")
    if expected_child == "hook":
        require(bool(children) and all("knowledgeos" in child["argv"] or "import knowledgeos" in " ".join(child["argv"]) for child in children), "Hook did not actually invoke its copied public runtime")
    return children


def support_module(filename):
    module_name = "_writer_checked_" + filename.replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, VERIFY / filename)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(VERIFY))
    spec.loader.exec_module(module)
    return module


def expected_calls(name, fixtures, parsed):
    if name == "normal-tools":
        return normal_calls()
    if name == "normal-reject":
        proposal = parsed["normal-tools"][15]["payload"]["proposal_path"]
        return [("memory_reject_self_update", {"proposal_path": proposal, "reason": "Synthetic writer proof declines this draft."})]
    if name in {"capture-first", "capture-collision"}:
        tool, args = capture_call()
        return [(tool, dict(args, content="Different synthetic content for the same reviewed request."))] if name.endswith("collision") else [(tool, args)]
    if name == "outcome-protected-self":
        return [("memory_record_outcome", dict(OUTCOME_ARGS, path="People/Self.md", expected_sha256=fixtures["normal"]["initial_self"]["sha256"]))]
    if name in {"memory_forget-self", "memory_supersede-self"}:
        tool = name[:-5]
        args = {"path_or_id": "People/Self.md", "expected_sha256": fixtures["normal"]["initial_self"]["sha256"]}
        if tool.endswith("supersede"):
            args.update(replacement_path_or_id="Concepts/New.md", replacement_sha256=hashlib.sha256(FIXTURE_NOTES["Concepts/New.md"].encode()).hexdigest())
        return [(tool, args)]
    for spec in alias_specs():
        if name in {"hard-" + spec["id"], "symlink-" + spec["id"]}:
            return [spec["call"]]
    for spec in directory_specs():
        if name == "directory-" + spec["id"]:
            return spec["calls"]
    if name.startswith("symlink-database"):
        return [("memory_search", {"query": "prototype", "limit": 8})]
    return None


def normal_behavior(results, directory, fixture, after):
    require(len(results) == len(normal_calls()) and all(not row["is_error"] for row in results), "A normal supported public writer refused or failed instead of exercising its write")
    require(results[0]["payload"].get("path") == "People/Self.md", "Normal reader did not load the protected identity")
    for index in (13, 14, 15, 16, 17, 19, 20):
        require(results[index]["payload"].get("ok") is True, "Normal public mutation did not return success")
    require(results[13]["payload"].get("path") == CAPTURE_NAME and after.get("vault/" + CAPTURE_NAME, {}).get("kind") == "file", "Normal capture is not durable at its actual public path")
    require(results[15]["payload"].get("policy") == "proposal_only" and results[15]["payload"].get("mutated_self") is False
            and results[16]["payload"].get("mutated_self") is False, "Proposal/outcome falsely claims an applied identity change")
    require(results[18]["payload"].get("proposed") is True and results[18]["payload"].get("mutated_self") is False
            and results[18]["payload"].get("semantic_change_assessed") is True, "Corroborated source drift did not actually exercise its proposal writer")
    require(results[21]["payload"].get("captured", {}).get("ok") is True, "Session writer did not durably capture its required summary")
    vault = fixture["local_scope"] / "vault"
    review = vault / "Decisions/Review.md"
    require(sha(review) == results[16]["payload"].get("sha256") == after.get("vault/Decisions/Review.md", {}).get("sha256"), "Reviewed outcome is not bound to durable physical source bytes")
    raw = review.read_text(encoding="utf-8")
    require(raw.split("\n---\n", 1)[1] == FIXTURE_NOTES["Decisions/Review.md"].split("\n---\n", 1)[1]
            and "outcome_status: 'confirmed'" in raw and "actual_outcome: '" + OUTCOME_ARGS["actual_outcome"] + "'" in raw
            and "lesson: '" + OUTCOME_ARGS["lesson"] + "'" in raw, "Reviewed writer changed unrelated decision body bytes or omitted the literal reviewed outcome")
    for relative, text in FIXTURE_NOTES.items():
        if relative != "Decisions/Review.md":
            require((vault / relative).read_bytes() == text.encode(), "An ordinary source changed during policy or proposal writes")
    policy = read(vault / ".knowledgeos/remembering-policy.json")["state"]
    require(set(policy["forgotten"]) == {"Concepts/Forget.md"} and set(policy["superseded"]) == {"Concepts/Old.md"}, "The public forget and correction writers did not durably store their exact reviewed targets")


def alias_refused(result):
    payload = result["payload"]
    context = payload.get("context", {})
    freshness = payload.get("freshness", {})
    context = context if isinstance(context, dict) else {}
    freshness = freshness if isinstance(freshness, dict) else {}
    blocked = (context.get("index_frozen") is True
               and isinstance(context.get("index_blocked"), str) and bool(context["index_blocked"])
               and freshness.get("blocked") is True
               and isinstance(freshness.get("error"), str) and bool(freshness["error"]))
    return (result["is_error"] or payload.get("index_frozen") is True or bool(payload.get("index_blocked"))
            or payload.get("indexed") is False or bool(context.get("self", {}).get("error")) or blocked)


def focus_report(path, base, *, data_override=None):
    path = Path(path).absolute()
    directory = path.parent
    base.data_repository_location(str(directory))
    require(".knowledgeos" in directory.parts and directory.is_relative_to(ROOT / "work/gc-artifacts"), "Writer evidence leaves contained synthetic task storage")
    plain_file(directory, path.name)
    data = read(path) if data_override is None else data_override
    require(data.get("producer") == PRODUCER and data.get("scope") == SCOPE and data.get("outcome") == OUTCOME, "Wrong writer producer, scope or outcome")
    require(data.get("producer_sha256") == sha(HERE / "identity_writers.py")
            and data.get("support_sha256") == {name: sha(HERE / name) for name in ("writer_census.py", "writer_contract.py", "physical_observer.py")}
            and data.get("root_support_sha256") == {name: sha(VERIFY / name) for name in ("data_preservation.py", "identity.py", "maintenance.py")}, "Writer producer or helper bytes are stale")
    toolkit = base.data_toolkit_hashes()
    require(data.get("product_hashes") == toolkit and data.get("product_hashes_after") == toolkit
            and data.get("product_and_producer_unchanged") is True and data.get("error") is None, "Complete current source binding is stale, incomplete or failed")
    require(data.get("os_name") in {"nt", "posix"} and isinstance(data.get("platform"), str) and data.get("python") and data.get("interpreter"), "Writer source runtime identity is missing")
    evidence = data.get("evidence_files")
    require(isinstance(evidence, dict) and evidence and path.name not in evidence, "Writer evidence hash inventory is missing")
    for name, digest in evidence.items():
        require(isinstance(digest, str) and HEX.fullmatch(digest) and sha(plain_file(directory, name)) == digest, "Tampered or missing writer evidence: " + str(name))
    require(evidence_json(directory, evidence, "writer-census.json") == read_census(ROOT), "Census omits a current supported source, caller or mutation site")
    freeze = local(data.get("freeze_path"), base)
    require(freeze.is_file() and sha(freeze) == data.get("freeze_sha256") and read(freeze).get("product") == toolkit, "Writer proof was captured against a wrong or changed source freeze")
    contract = evidence_json(directory, evidence, "case-contract.json")
    require(contract.get("frozen_before_any_product_invocation") is True and contract.get("toolkit_hashes") == toolkit
            and contract.get("freeze_sha256") == data.get("freeze_sha256")
            and contract.get("hardlink_cases") == [s["id"] for s in alias_specs()]
            and contract.get("directory_cases") == [s["id"] for s in directory_specs()]
            and contract.get("tools") == read_census(ROOT)["memory_tools"], "Literal writer case contract was not frozen against the current complete source")
    isolation = data.get("isolation", {})
    require(isolation.get("before") and isolation.get("before") == isolation.get("after") and isolation.get("selected_sentinels_unchanged") is True
            and {base.data_repository_location(p) for p in isolation["before"]} == {"People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json"}, "Real-vault isolation sentinels are missing or changed")
    records = checked_processes(data, directory, evidence, base)
    fixtures = {}
    for fixture in data.get("fixtures", []):
        label = fixture.get("label")
        require(isinstance(label, str) and label and label not in fixtures, "Writer fixture identity is duplicated or missing")
        scope = local(fixture["scope"], base)
        require(scope == directory / "fixtures" / label and local(fixture["vault"], base) == scope / "vault"
                and local(fixture["toolkit"], base) == scope / ("vault" if fixture["kind"] == "legacy" else "toolkit"), "Fixture targets the wrong source or scope")
        copied = valid_inventory(evidence_json(directory, evidence, label + ".toolkit-initial.json"))
        require(all(copied.get(p, {}).get("sha256") == digest and copied[p].get("links") == 1 for p, digest in toolkit.items()), "Complete copied toolkit input bytes are missing or wrong")
        initial = valid_inventory(evidence_json(directory, evidence, label + ".fixture-initial.json"))
        final = valid_inventory(evidence_json(directory, evidence, label + ".fixture-final.json"))
        physical_initial = evidence_json(directory, evidence, label + ".physical-initial.json")
        physical_final = evidence_json(directory, evidence, label + ".physical-final.json")
        require(initial.get("vault/People/Self.md", {}).get("links") == physical_initial.get("self", {}).get("links") == 1,
                "Fixture initialization did not begin with one original plain Self file")
        expected_links = physical_initial["self"]["links"]
        alias = alias_relative(label, alias_specs())
        if alias is not None:
            case_before = evidence_json(directory, evidence, label + ".before.json")
            case_after = evidence_json(directory, evidence, label + ".after.json")
            physical_before = evidence_json(directory, evidence, label + ".physical-before.json")
            physical_after = evidence_json(directory, evidence, label + ".physical-after.json")
            expected_links += int(label.startswith("hard-"))
            same_physical_self(physical_initial["self"], physical_before["self"], expected_links)
            linked = physical_before["alias"].get("effective") if label.startswith("symlink-") else physical_before["alias"]
            require(all(linked.get(key) == physical_before["self"].get(key) for key in ("device", "inode", "size", "links", "sha256")), "Fixture alias seed did not target the same original Self")
            detach = manifest_detach(label, case_before, case_after, physical_before, physical_after)
            if detach is not None:
                expected_links -= int(label.startswith("hard-"))
        same_physical_self(physical_initial["self"], physical_final["self"], expected_links)
        preserved_identity(initial, final, expected_self_links=expected_links)
        physical_regular(scope / "vault/People/Self.md", final["vault/People/Self.md"])
        for name, row in final.items():
            if name.startswith("vault/People/") and row.get("kind") == "file":
                physical_regular(scope / name, row)
        prefix = "vault/" if fixture["kind"] == "legacy" else "toolkit/"
        for relative, digest in toolkit.items():
            require(final.get(prefix + relative, {}).get("sha256") == digest, "Source changed while the writer was observed")
            physical_regular(local(fixture["toolkit"], base) / relative, final[prefix + relative])
        observer = local(fixture["toolkit"], base) / "sitecustomize.py"
        require(observer.read_text(encoding="utf-8") == RUNTIME_OBSERVER
                and copied.get("sitecustomize.py", {}).get("sha256") == sha(observer), "Actual child identity observer is missing or altered")
        executable_suffixes = {".py", ".sh", ".pyc", ".pyo", ".pth", ".so", ".pyd", ".dll"}
        recorded_code = {name[len(prefix):] for name, row in final.items()
                         if name.startswith(prefix) and row.get("kind") == "file" and Path(name).suffix in executable_suffixes}
        require(recorded_code == {p for p in toolkit if Path(p).suffix in executable_suffixes} | {"sitecustomize.py"}, "Copied runtime contains unreviewed executable source or caches")
        fixture = dict(fixture, local_scope=scope, initial_self=initial["vault/People/Self.md"])
        fixtures[label] = fixture
    rows = data.get("cases")
    require(isinstance(rows, list) and len({row.get("id") for row in rows}) == len(rows)
            and {row.get("id") for row in rows} == expected_case_ids(data["os_name"]), "Missing, duplicated or arbitrary writer coverage")
    expected_roles = {row["id"][len("writers."):] for row in rows} | {"revision", "normal-history-create", "normal-history-reject"}
    expected_roles |= {label + "-init" for label, fixture in fixtures.items() if fixture["kind"] != "legacy"}
    if data["os_name"] == "nt":
        expected_roles |= {"directory-" + spec["id"] + "-junction" for spec in directory_specs()}
    require(set(records) == expected_roles, "Untracked or arbitrary producer process role entered the proof")
    revision = records["revision"]
    require(revision["command"] == ["git", "rev-parse", "HEAD"] and revision["exit_code"] == 0
            and plain_file(directory, "revision.stdout.txt").read_text(encoding="utf-8").strip() == checked_freeze_revision(read(freeze)), "Revision receipt is not the actual frozen-source command")
    for label, fixture in fixtures.items():
        if fixture["kind"] == "legacy":
            continue
        record = records[label + "-init"]
        require(record["command"] == [data["interpreter"], "-B", "-P", "-m", "knowledgeos", "init", fixture["vault"], "--name", "Synthetic writer IW41", "--non-interactive"]
                and record["vault"] == fixture["vault"] and record["import_path"] == fixture["toolkit"] and record["exit_code"] == 0, "Fixture initialization did not use its exact public source CLI")
        initialized = json.loads(plain_file(directory, label + "-init.stdout.txt").read_text(encoding="utf-8"))
        post = initialized.get("post_init", {})
        require(set(post) >= {"rebuild", "validate"} and all(p.get("ok") is True for p in post.values()), "Fixture's actual required post-init checks failed")
    history = parse_rpc(directory, evidence, "normal-history-create", [("memory_propose_self_update", args) for args in HISTORY.values()])
    for role in ("normal-history-create", "normal-history-reject"):
        fixture = fixtures["normal"]
        require(records[role]["command"] == [data["interpreter"], "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", fixture["vault"], "--framing", "ndjson"]
                and records[role]["vault"] == fixture["vault"] and records[role]["import_path"] == fixture["toolkit"] and records[role]["exit_code"] == 0,
                "Synthetic existing history used the wrong public source process")
    require(all(not row["is_error"] and row["payload"].get("ok") is True and row["payload"].get("mutated_self") is False for row in history), "Existing no-approval synthetic proposal history was not actually created")
    declined = parse_rpc(directory, evidence, "normal-history-reject", [("memory_reject_self_update", {"proposal_path": history[1]["payload"]["proposal_path"], "reason": "Retain this synthetic rejected history."})])
    require(not declined[0]["is_error"] and declined[0]["payload"].get("policy") == "explicit_reject", "Existing synthetic declined history was not recorded by the public gate")
    for result, status in zip(history, ("draft", "rejected")):
        source = fixtures["normal"]["local_scope"] / "vault" / result["payload"]["proposal_path"]
        require(("status: " + status + "\n") in source.read_text(encoding="utf-8"), "Prior no-approval synthetic history lost its actual disposition")
    parsed, actual_tools, actual_scripts, nested = {}, set(), set(), []
    safe_detachments, successful_refreshes = [], []
    maintenance = support_module("maintenance.py")
    for row in rows:
        name = row["id"][len("writers."):]
        fixture = fixtures.get(row.get("fixture"))
        require(fixture is not None and row.get("roles") == [name], "Writer case targets an unknown fixture or invented launch role")
        before = evidence_json(directory, evidence, name + ".before.json")
        after = evidence_json(directory, evidence, name + ".after.json")
        calls = expected_calls(name, fixtures, parsed)
        allowed = {"vault/" + calls[0][1]["proposal_path"]} if name == "normal-reject" else set()
        if name == "script-propose_self_update-3":
            previous = json.loads(plain_file(directory, "script-propose_self_update-0.stdout.txt").read_text(encoding="utf-8"))
            allowed = {"vault/" + previous["proposal_path"]}
        physical_before = evidence_json(directory, evidence, name + ".physical-before.json")
        physical_after = evidence_json(directory, evidence, name + ".physical-after.json")
        require(before.get("vault/People/Self.md") == {key: physical_before["self"][key] for key in ("kind", "size", "sha256", "links")}
                and after.get("vault/People/Self.md") == {key: physical_after["self"][key] for key in ("kind", "size", "sha256", "links")}, "Case inventory and physical original Self observations disagree")
        detach = manifest_detach(name, before, after, physical_before, physical_after)
        if detach is not None:
            safe_detachments.append({"case": name, "original_self_before": physical_before["self"],
                                     "original_self_after": physical_after["self"], "detached_manifest": detach})
        expected_links = physical_before["self"]["links"] - int(detach is not None and name.startswith("hard-"))
        same_physical_self(physical_before["self"], physical_after["self"], expected_links)
        preserved_identity(before, after, allowed, expected_self_links=expected_links)
        prefix = "vault/" if fixture["kind"] == "legacy" else "toolkit/"
        require(all(before.get(prefix + relative, {}).get("sha256") == digest == after.get(prefix + relative, {}).get("sha256")
                    for relative, digest in toolkit.items()), "Complete public-operation source inventories differ from current copied input bytes")
        record = records.get(name)
        require(record is not None and record.get("vault") == fixture["vault"]
                and record.get("import_path") == fixture["toolkit"]
                and local(record["state_dir"], base) == fixture["local_scope"] / "gate-state", "Writer process is not bound to its actual fixture and copied imports")
        command = record["command"]
        protected_io(plain_file(directory, name + ".stderr.txt").read_text(encoding="utf-8"), record, fixture, physical_before["self"], detach=detach)
        if calls is not None:
            require(command == [data["interpreter"], "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", fixture["vault"], "--framing", "ndjson"]
                    and record["exit_code"] == 0, "Writer MCP command does not invoke the copied public server")
            results = parse_rpc(directory, evidence, name, calls)
            parsed[name] = results
            actual_tools.update(tool for tool, _ in calls)
            if name == "normal-tools":
                normal_behavior(results, directory, fixture, after)
            if name in {"capture-collision", "outcome-protected-self", "memory_forget-self", "memory_supersede-self", "normal-reject"}:
                if name == "normal-reject":
                    require(not results[0]["is_error"] and results[0]["payload"].get("policy") == "explicit_reject", "Public rejection did not record a decline")
                else:
                    require(results[0]["is_error"], "Unsafe mutation or collision did not honestly refuse")
            if row.get("kind") in {"file-alias", "directory-alias"} and detach is None:
                require(all(alias_refused(result) for result in results), "Unsafe writer alias was silently reported as ordinary success: " + name)
        elif row.get("kind") == "script":
            specs = {n: (s, a) for n, s, a in legacy_specs(fixture)}
            specs.update({"shell-" + Path(s).stem: (s, a) for s, a in (("scripts/rebuild_index.sh", []), ("scripts/capture.sh", ["Concepts/Source.md"]), ("scripts/weekly_data.sh", []), ("scripts/search.sh", ["prototype"]))})
            if name == "script-propose_self_update-3":
                specs[name] = ("scripts/propose_self_update.py", ["--vault", fixture["vault"], "reject", previous["proposal_path"], "--reason", "Synthetic source wrapper rejection."])
            relative, args = specs[name]
            actual_scripts.add(relative)
            shell = relative.endswith(".sh")
            if shell:
                require(command == ["bash", native_join(fixture["toolkit"], relative), *args], "Wrong public shell source caller")
                nested += nested_trace(directory, name, record, [native_join(fixture["toolkit"], "scripts/" + ("rebuild_index.py" if relative.endswith("capture.sh") else Path(relative).stem + ".py")), *([] if relative.endswith("capture.sh") else args)], shell=True)
            else:
                operation = "import runpy, sys\nsys.argv = " + repr([relative, *args]) + "\nrunpy.run_path(" + repr(native_join(fixture["toolkit"], relative)) + ", run_name='__main__')"
                require(command == [data["interpreter"], "-B", "-P", "-c", maintenance.traced(operation)], "Wrong public source-script command")
                nested += nested_trace(directory, name, record, "hook" if name.startswith("hook-") else None)
            if name == "script-onboarding-0":
                require(record["exit_code"] == 1 and "Legacy onboarding cannot change People/Self.md." in plain_file(directory, name + ".stderr.txt").read_text(encoding="utf-8"), "Retired onboarding did not truthfully refuse")
            else:
                require(record["exit_code"] == 0, "Supported source writer did not complete its ordinary public exercise")
        else:
            arguments = cli_arguments(name, fixture)
            if row.get("kind") == "fault":
                target = {"capture-fault": CAPTURE_NAME, "outcome-fault": "Decisions/Review.md", "policy-fault": ".knowledgeos/remembering-policy.json", "setup-fault": ".cursor/mcp.json"}[name]
                expected_command = [data["interpreter"], "-B", "-P", "-c", fault_operation(public_operation(arguments), target)]
                fault_log = plain_file(directory, name + ".stderr.txt").read_text(encoding="utf-8")
                require(record["exit_code"] != 0 and "IDENTITY_WRITER_FAULT=" + native_join(fixture["vault"], target) in fault_log, "Interrupted write fault was not actually reached")
            elif name == "cli-hook-start":
                expected_command = [data["interpreter"], "-B", "-P", "-c", maintenance.traced(public_operation(arguments))]
                nested += nested_trace(directory, name, record, "hook")
                require(record["exit_code"] == 0, "Public CLI hook did not complete")
            else:
                expected_command = [data["interpreter"], "-B", "-P", "-m", "knowledgeos", *arguments]
                if name == "init-refresh":
                    refresh = json.loads(plain_file(directory, name + ".stdout.txt").read_text(encoding="utf-8"))
                    checked_init_refresh(record, refresh, before, after, toolkit)
                    successful_refreshes.append({"case": name, "pid": record["pid"], "exit_code": record["exit_code"],
                                                 "post_init": refresh["post_init"], "conflicts": refresh["conflicts"],
                                                 "evidence_scope": "Identity preservation during successful source init refresh only."})
                else:
                    require(record["exit_code"] != 0 if row.get("kind") in {"file-alias-cli", "refuse-cli"} else record["exit_code"] == 0, "Public CLI success/refusal status differs from the literal writer case")
            require(command == expected_command, "Wrong or arbitrary public CLI writer command")
        if name.startswith("hard-") and row.get("kind") in {"file-alias", "file-alias-cli"} and detach is None:
            target = row.get("detail", {}).get("path")
            require(before.get(target, {}).get("kind") == "file" and before[target]["links"] >= 2 and before[target]["sha256"] == before["vault/People/Self.md"]["sha256"]
                    and after.get(target) == before[target], "Hardlink refusal was not an actual unchanged identity alias")
        if name.startswith("symlink-") and row.get("kind") in {"file-alias", "file-alias-cli"} and detach is None:
            target = row.get("detail", {}).get("path")
            require(before.get(target, {}).get("kind") == "link" and before[target].get("target") == native_join(fixture["vault"], "People/Self.md")
                    and after.get(target) == before[target], "Symlink refusal was not an actual unchanged identity alias")
        if row.get("kind") == "directory-alias":
            spec = next(s for s in directory_specs() if name == "directory-" + s["id"])
            require(before.get(spec["path"], {}).get("kind") == "link" and after.get(spec["path"]) == before[spec["path"]], "Native directory alias was not retained unchanged")
            outside_before = {p: r for p, r in before.items() if p.startswith("outside/")}
            outside_after = {p: r for p, r in after.items() if p.startswith("outside/")}
            require(outside_before and outside_before == outside_after, "Directory alias allowed an external identity-target write")
    require(actual_tools == set(read_census(ROOT)["memory_tools"]) - {"memory_accept_self_update"}, "A supported memory writer tool lacks actual public observations")
    require(data.get("verdict") == "PASS" and all(row.get("verdict") == "PASS" for row in rows), "Producer verdict contradicts the independently recomputed passing preservation observations")
    return {"path": str(path), "report_sha256": sha(path), "os_name": data["os_name"], "cases": len(rows),
            "actual_tools": sorted(actual_tools), "actual_scripts": sorted(actual_scripts), "nested_processes": nested,
            "safe_manifest_detachments": safe_detachments, "known_product_refusals": [], "successful_refreshes": successful_refreshes,
            "verdict": "PASS", "producer_reported_verdict": data.get("verdict"), "product_hashes": toolkit}


def reused_data(path, base, current):
    checked = base.data_report(path, current)
    data = read(path)
    producer = data["producer"]
    require(producer in REUSED, "Unsupported writer reuse input")
    spec = base.ALL_DATA_PRODUCERS[producer]
    directory, evidence = Path(path).parent, data["evidence_files"]
    require(set(row["id"] for row in data["cases"]) == set(spec["cases"]), "Reused writer report has incomplete literal coverage")
    complete = checked["checks"][spec["aggregate"]]["verdict"] == "PASS"
    require(complete, "Reused writer report is not complete passing public evidence")
    records = {row["role"]: evidence_json(directory, evidence, row["role"] + ".command.json") for row in data["processes"]}
    stages = 0
    for row in data["cases"]:
        if producer == "verify-twinaatma.memory-census/v2":
            before_name, after_name = "census.before.json", "census.after.json"
        else:
            prefix, file_prefix = base.DATA_COPY_PREFIXES[spec.get("journey", spec["file"])]
            stem = file_prefix + row["id"][len(prefix):]
            before_name, after_name = stem + ".before.json", stem + ".after.json"
        before = evidence_json(directory, evidence, before_name)
        after = evidence_json(directory, evidence, after_name)
        preserved_identity(before, after)
        stages += 1
        for name in row["evidence"]:
            if name.endswith((".retry.json", ".repeat.json", ".ran.json")):
                preserved_identity(before, evidence_json(directory, evidence, name))
                stages += 1
        command_names = [name for name in row["evidence"] if name.endswith(".command.json")]
        require(command_names, "Reused writer case has no actual public process")
        for name in command_names:
            record = evidence_json(directory, evidence, name)
            vault = local(record["vault"], base)
            physical_regular(vault / "People/Self.md", before["vault/People/Self.md"])
            for relative, protected in before.items():
                if relative.startswith("vault/People/Self-Proposals/") and protected.get("kind") == "file":
                    physical_regular(vault.parent / relative, protected)
        if producer == "verify-twinaatma.generated-writers/v2":
            generated = support_module("generated_writers.py")
            writer, scenario = row["id"][len("data.generated."):].split("-", 1)
            operation = generated.WRITERS[writer]["operation"]
            record = records[writer + "-" + scenario]
            require(record["command"][-1].endswith(operation), "Reused generated case invoked a different writer")
        elif producer == "verify-twinaatma.data-preservation/v1":
            exports = support_module("data_preservation.py")
            identifier = row["id"][len("data.export."):]
            selected, output = next((s, o) for i, s, o, _ in exports.CASES if i == identifier)
            record = records[identifier]
            require(record["command"][1:] == ["-B", native_join(record["vault"], "scripts/export_bundle.py"), "--paths", *selected, "--out", output], "Reused export case invoked an arbitrary source command")
    return {"path": str(path), "report_sha256": sha(path), "producer": producer, "family": REUSED[producer], "cases": len(data["cases"]), "recomputed_identity_inventory_stages": stages, "verdict": "PASS"}


def core_refusal(path, base, current):
    checked = base.source_report(path, current)
    data = read(path)
    require(data.get("journey") == "core", "Writer refusal reuse needs the current complete source core journey")
    directory = Path(path).parent
    transcript = plain_file(directory, "transcript.jsonl")
    entries = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepts = []
    for entry in entries:
        command = entry.get("command", [])
        require(not any(command[i:i+2] == ["self", "approve"] for i in range(len(command))), "This unit cannot import owner approval as alternative-writer evidence")
        if entry.get("kind") != "mcp":
            continue
        responses = {r.get("id"): r for r in (json.loads(line) for line in entry["stdout"].splitlines() if line.strip())}
        for request in entry.get("requests", []):
            if request.get("method") == "tools/call" and request.get("params", {}).get("name") == "memory_accept_self_update":
                result = responses[request["id"]]["result"]
                payload = json.loads(result["content"][0]["text"])
                require(result.get("isError") is True and payload.get("policy") == "human_only" and payload.get("mutated_self") is False and payload.get("error"), "Actual alternative tool acceptance did not refuse with unchanged identity")
                accepts.append((entry["pid"], request, payload))
    require(len(accepts) == 1, "Actual MCP refusal coverage is missing or duplicated")
    row = next((r for r in data["checks"] if r["id"] == "identity.bytes_unchanged"), {})
    require(row.get("observed", {}).get("before") == row.get("observed", {}).get("after") == sha(directory / "vault/People/Self.md"), "Core refusal identity bytes are missing or changed")
    return {"path": str(path), "report_sha256": sha(path), "transcript_sha256": sha(transcript), "tool": "memory_accept_self_update", "verdict": "PASS"}


def bundle(writer_paths, *, data_paths=(), source_paths=(), recovery_paths=(), learning_paths=(), base=None, current=None):
    base = base or support_module("acceptance.py")
    current = current or base.product_hashes()
    focused = [focus_report(Path(p).absolute(), base) for p in writer_paths]
    require({row["os_name"] for row in focused} == {"nt", "posix"}, "Native Windows hardlinks/junctions and native Linux symlinks/shell wrappers are both required")
    reused = [reused_data(Path(p).absolute(), base, current) for p in data_paths]
    require({r["family"] for r in reused} == set(REUSED.values()), "A supported export/generated/census/maintenance/hook/validation caller lacks complete current public writer evidence")
    core = [core_refusal(Path(p).absolute(), base, current) for p in source_paths if read(p).get("journey") == "core"]
    require(core, "Missing actual tool-refusal writer coverage")
    recovery = [base.recovery_report(Path(p).absolute(), current) for p in recovery_paths]
    require({r["producer"] for r in recovery} >= {"verify-twinaatma.recovery-index/v1", "verify-twinaatma.recovery-locks/v1", "verify-twinaatma.recovery-write-faults/v1"}
            and all(any(c.get("verdict") == "PASS" and name.endswith(".complete") for name, c in r["checks"].items()) for r in recovery), "Index, native lock and partial-marker recovery coverage is incomplete")
    learning = [base.learning_report(Path(p).absolute(), current) for p in learning_paths]
    require(learning and all(r["checks"].get("learning.attributed_lessons.complete", {}).get("verdict") == "PASS" for r in learning), "The possible drift and attributed-lesson proposal writers lack complete current public coverage")
    census = read_census(ROOT)
    writer_roles = {"proposal", "index", "generated", "links", "export", "git-hooks", "retired", "database-reader", "sessions"}
    expected_scripts = {name for name, info in census["files"].items()
                        if name.startswith(("scripts/", ".cursor/hooks/")) and info["classification"] in writer_roles}
    observed_scripts = {script for report in focused for script in report["actual_scripts"]}
    reused_scripts = {"export": {"scripts/export_bundle.py"}, "generated": {"scripts/draft_weekly_synthesis.py", "scripts/experiment_dashboard.py", "scripts/outcomes_dashboard.py"},
                      "maintenance": {"scripts/refactor_links.py", "scripts/update_mocs.py"}, "hooks": {"scripts/setup_git_hooks.py"}, "validation": {"scripts/validate_schema.py"}, "census": set()}
    for report in reused:
        observed_scripts.update(reused_scripts[report["family"]])
    unexercised = sorted(expected_scripts - observed_scripts)
    require(not unexercised, "Supported public writer script callers remain unexercised: " + repr(unexercised))
    observation = {"outcome": OUTCOME, "scope": SCOPE, "focused": focused, "reused": reused, "core_refusals": core,
                   "recovery_reports": [{"path": r["path"], "report_sha256": r["report_sha256"]} for r in recovery],
                   "learning_reports": [{"path": r["path"], "report_sha256": r["report_sha256"]} for r in learning],
                   "census": {"files": len(census["files"]), "mutation_sites": len(census["mutation_sites"]), "memory_tools": len(census["memory_tools"])},
                   "public_writer_scripts_expected": sorted(expected_scripts), "public_writer_scripts_observed": sorted(observed_scripts),
                   "unexercised_writer_families": unexercised, "owner_approval": "NOT CHECKED", "fixed54_credit": [OUTCOME]}
    return {"path": str(Path(writer_paths[0]).absolute()), "report_sha256": sha(writer_paths[0]), "scope": "source",
            "producer": "verify-twinaatma.identity-writers-bundle/v1", "producer_sha256": sha(HERE / "identity_writers.py"),
            "grader_sha256": sha(__file__), "checks": {"identity.writers.complete": {"id": "identity.writers.complete", "verdict": "PASS",
            "expected": "Every supported alternative public writer and maintenance path preserves protected Self with complete current source evidence.",
            "observed": observation, "evidence": [*map(str, writer_paths), *map(str, data_paths), *map(str, source_paths), *map(str, recovery_paths), *map(str, learning_paths)]}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "data-report", "source-report", "recovery-report", "learning-report"):
        parser.add_argument("--" + name, type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Preserve the prior writer grading output")
    try:
        result = bundle(args.report, data_paths=args.data_report, source_paths=args.source_report, recovery_paths=args.recovery_report, learning_paths=args.learning_report)
    except (ValueError, KeyError, OSError, TypeError) as error:
        result = {"producer": "verify-twinaatma.identity-writers-grading/v1", "outcome": OUTCOME, "verdict": "NOT CHECKED", "error": str(error), "fixed54_credit": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "verdict": result.get("verdict", "PASS"), "outcome": OUTCOME}))
    return 0 if result.get("checks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
