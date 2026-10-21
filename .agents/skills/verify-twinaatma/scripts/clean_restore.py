"""Clean-device restore on two fresh GitHub-hosted Windows runners (producer, grader and bundle writer).

Device A (job ``origin``) installs the exact commit's wheel or executable, initializes a synthetic vault,
writes linked notes, captures one, makes one signed pending identity proposal, then produces the two
backups a person carries: the vault folder (one zip) and the off-vault signing state (a second zip).
Device B (job ``restore``) is another fresh runner. It installs the same commit's artifacts, unpacks the
vault copy and follows the supported procedure (``setup-host --write``, ``doctor``). It proves content,
recall, host reconnection and the explicit signing-state dependency, grades its own evidence with
``evaluate`` and writes one bundle that the workflow attests.

The case list is a literal tuple frozen to ``plan.json`` before the first command of each device. Approval
is never answered: an approval command runs in a hidden console and is observed only up to its refusal.
No model is called and no credential reaches a child process. Every command is a public CLI or MCP call
of the installed product.

Commands: ``origin`` (device A), ``restore`` (device B), ``bundle`` (runner side, after both).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import artifact  # noqa: E402  (installation and binding helpers; unchanged)
import signing_state as ss  # noqa: E402  (refusal and doctor wording rules shared with the signing-state journey)

PRODUCER = "verify-twinaatma.clean-restore/v1"
SCHEMA = "twinaatma.clean-restore/v1"
KINDS = ("wheel", "binary")
SUPPORT = ("artifact.py", "signing_state.py", "ci_graded.py", "build.py")
CHECK = "port.clean_device_restore"
SCOPE = "clean_device"

CASE_NAMES = (
    "clean_devices", "origin_backups", "content_preserved", "recall_and_index_rebuild", "host_reconnected",
    "host_command_serves", "dependency_named", "old_proposal_refused_without_state",
    "old_proposal_valid_after_restore", "identity_never_changed")
CASE_IDS = tuple("restore." + name for name in CASE_NAMES)
EXPECTED = {
    "clean_devices": "Both devices are different fresh GitHub-hosted Windows machines with no earlier vault, install or signing state",
    "origin_backups": "Device A produced a vault with linked notes carrying stable IDs and one signed pending proposal, and two separate backups: the vault folder without signing state, and the signing state",
    "content_preserved": "On device B every note, its ID, its relative links and Self.md are byte-identical to the carried copy after the whole restore, and validation passes",
    "recall_and_index_rebuild": "With no index on device B, ordinary memory calls rebuild it and recall the captured fact and the linked notes without any human command",
    "host_reconnected": "setup-host writes Codex configuration for device B's installed launcher and vault, and no device A path or launcher remains in it",
    "host_command_serves": "The exact configured MCP command answers initialize, lists the memory tools and serves memory_session_start against the restored vault, with no model call and no credential",
    "dependency_named": "Doctor or setup output names the signing state that did not travel and says what to do",
    "old_proposal_refused_without_state": "Without the signing-state backup the old pending proposal is not valid, a hidden-console approval refuses before any prompt with a hint to propose again, and Self is unchanged",
    "old_proposal_valid_after_restore": "After the signing-state backup is restored the old proposal is valid again at describe time, without being applied or rewritten",
    "identity_never_changed": "Self bytes and the proposal file never change on either device, no ledger row is applied, and no approval answer is ever sent",
}
ORIGIN_STEPS = ("init", "capture", "ids-0", "propose", "verify-0", "pending-0", "doctor-0", "validate-0", "setup-host-0")
RESTORE_STEPS = ("setup-host", "doctor-1", "pending-1", "validate-1", "host-mcp-1", "approve-lost", "pending-2",
                 "host-mcp-2", "doctor-2", "validate-2")
TOOLS = ("memory_session_start", "memory_search", "memory_get_note", "memory_related", "memory_capture",
         "memory_propose_self_update", "memory_list_self_proposals", "memory_accept_self_update", "memory_session_end")
TOOLING = {"tool-create-venv", "tool-install", "tool-import-origin"}
DERIVED = ("knowledge_index.db", ".knowledgeos/", ".codex/")
SECRET_NAME = re.compile(r"(?i)token|secret|password|credential|api[_-]?key|_key$|^actions_|^openai|^anthropic")
# The owner's device-local policy (21 October 2026): another device refuses the old proposal with a hint to propose again.
# A bare mention of the signing key is a cause, not an instruction, so these two patterns require an instruction.
PROPOSE_AGAIN = re.compile(r"(?i)\b(?:re-?propos\w*|propose (?:it |this |that |the change )?again|(?:ask for |create |make )(?:a )?new proposal)\b")
ACTION = re.compile(r"(?i)\b(?:restore|back ?up|re-?propos\w*|propose (?:it |this |that |the change )?again|(?:ask for |create |make )(?:a )?new proposal|copy (?:the|your))\b")
OTHER_DEVICE_CAUSE = re.compile(
    r"(?i)(?:signing|gate|approval)[ -]?(?:key|state)[^\n]*\b(?:other|another|different|new) (?:device|machine|computer|install)\b"
    r"|\b(?:other|another|different) (?:device|machine|computer|install)\b[^\n]*(?:signing|gate|approval)[ -]?(?:key|state)")
CONSOLE_DEADLINE = 60
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def lf_sha(path):
    return sha_bytes(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def is_derived(relative):
    return any(relative == prefix or relative.startswith(prefix) for prefix in DERIVED)


def content(files):
    return {name: digest for name, digest in files.items() if not is_derived(name)}


def front_id(text):
    match = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    if not match:
        return None
    found = re.search(r"(?m)^id:\s*(\S+)\s*$", match.group(1))
    return found.group(1) if found else None


def relative_links(text):
    return sorted(set(re.findall(r"\]\((\.\./[^)#]+|[A-Za-z][^):]*\.md)\)", text)))


# --------------------------------------------------------------------------- #
# evidence access
# --------------------------------------------------------------------------- #


class Ev(ss.Evidence):
    """A device's flat evidence directory."""

    def exists(self, name):
        return (self.directory / name).is_file()

    def rpc(self, label):
        record = self.command(label)
        if record.get("exit_code") != 0 or record.get("timed_out") or record.get("stopped") is not True:
            raise ValueError(label + " MCP process did not exit cleanly")
        request = self.json(label + ".requests.json")
        responses = {}
        for line in self.stdout(label).splitlines():
            if line.strip():
                row = json.loads(line)
                responses[row.get("id")] = row
        return request["ids"], responses

    def tool(self, label, key):
        ids, responses = self.rpc(label)
        response = responses[ids[key]]
        result = response["result"]
        content_rows = result["content"]
        if not isinstance(content_rows, list) or len(content_rows) != 1:
            raise ValueError(label + "." + key + " content shape is wrong")
        payload = json.loads(content_rows[0]["text"])
        return {"payload": payload, "is_error": bool(result.get("isError"))}


def finished(record, *, console=False):
    return (record.get("exit_code") is not None and record.get("stopped") is True and not record.get("timed_out")
            and record.get("console") is console)


def command_ok(ev, label):
    record = ev.command(label)
    return finished(record) and record.get("exit_code") == 0


def ran_to_completion(ev, label):
    """Doctor exits 1 when it reports an error, such as a stale Cursor hook path. It still ran and printed its findings."""
    record = ev.command(label)
    return finished(record) and record.get("exit_code") in (0, 1)


# --------------------------------------------------------------------------- #
# evaluation: pure functions over the two devices' retained evidence
# --------------------------------------------------------------------------- #


def case_clean_devices(a, b, facts):
    start_a, start_b = a.json("clean-start.json"), b.json("clean-start.json")
    info_a, info_b = a.json("device.json"), b.json("device.json")
    observed = {
        "a_fresh": start_a.get("default_state_exists") is False and start_a.get("vault_exists") is False and start_a.get("install_exists") is False,
        "b_fresh": start_b.get("default_state_exists") is False and start_b.get("vault_exists") is False and start_b.get("install_exists") is False,
        "both_github_hosted": all(i.get("github_actions") == "true" and i.get("runner_environment") == "github-hosted" for i in (info_a, info_b)),
        "both_windows": all(str(i.get("platform", "")).startswith("Windows-") for i in (info_a, info_b)),
        "different_machines": bool(info_a.get("hostname")) and info_a.get("hostname") != info_b.get("hostname")
        and bool(info_a.get("runner_name")) and info_a.get("runner_name") != info_b.get("runner_name"),
        "a_machine": {k: info_a.get(k) for k in ("hostname", "runner_name", "image_version", "github_job")},
        "b_machine": {k: info_b.get(k) for k in ("hostname", "runner_name", "image_version", "github_job")},
    }
    return all(v for k, v in observed.items() if isinstance(v, bool)), observed


def case_origin(a, b, facts):
    plan_ok = a.json("plan.json").get("steps") == list(ORIGIN_STEPS)
    init = a.command("init")
    post = json.loads(a.stdout("init")).get("post_init", {})
    opened, untrusted = ss.listing(a.tool("verify-0", "list"))
    search = a.tool("verify-0", "search")["payload"]
    s1 = a.snap(1)
    rows = a.ledger(1)
    carried = a.json("carried.json")
    vault_members, state_members = carried["vault_members"], carried["state_members"]
    notes = facts["notes"]
    doctor = a.stdout("doctor-0")
    observed = {
        "plan_steps": plan_ok,
        "install_bound": a.json("install.json").get("product_bound") is True,
        "init_ok": finished(init) and init["exit_code"] == 0 and set(post) >= {"rebuild", "validate"} and all(v.get("ok") is True for v in post.values()),
        "notes_have_ids": len(notes) == 3 and all(n.get("id") and n["id"].startswith("kos:") for n in notes.values()),
        "notes_link_each_other": all(n["links"] for n in notes.values()),
        "links_resolve": facts.get("links_resolve") is True,
        "capture_ok": command_ok(a, "capture") and facts["capture_path"] in notes,
        "ids_assigned_publicly": command_ok(a, "ids-0"),
        "self_untouched_by_setup": a.snap(0)["self_sha256"] == s1["self_sha256"] == facts["self_sha256"],
        "one_pending_signed": a.tool("propose", "propose")["payload"].get("proposal_path") == facts["proposal_path"]
        and [row["proposal"] for row in rows] == [facts["proposal_path"]] and [row["status"] for row in rows] == ["draft"],
        "listed_open": opened == [facts["proposal_path"]] and untrusted == [],
        "recalled_before_backup": any(hit.get("path") == facts["capture_path"] for hit in search.get("ranked", [])),
        "doctor_signed": command_ok(a, "doctor-0") and "[OK] Proposal ledger is signed (1 entries" in doctor,
        "pending_lists_it": command_ok(a, "pending-0") and facts["proposal_path"] in a.stdout("pending-0"),
        "validate_ok": command_ok(a, "validate-0") and json.loads(a.stdout("validate-0"))["summary"]["errors"] == 0,
        "state_present": bool(s1["gate_key_sha256"]) and bool(s1["bindings_sha256"]) and s1["ledger_count"] == 1,
        "vault_backup_has_no_signing_state": not any(m.endswith(("gate.key", "vault-bindings.json", "self-proposals.jsonl")) for m in vault_members)
        and facts["proposal_path"] in vault_members and "People/Self.md" in vault_members,
        "state_backup_has_key_bindings_ledger": any(m == "gate.key" for m in state_members) and any(m == "vault-bindings.json" for m in state_members)
        and any(m.startswith("vaults/") and m.endswith("/self-proposals.jsonl") for m in state_members),
        "two_distinct_backups": carried["vault_zip_sha256"] != carried["state_zip_sha256"] and HEX64.fullmatch(carried["vault_zip_sha256"]) is not None,
        "inventory_matches_backup": sorted(a.json("inventory-a.json")) == sorted(vault_members),
    }
    return all(v for v in observed.values()), observed


def case_content(a, b, facts):
    inv_a, inv_0, inv_final = a.json("inventory-a.json"), b.json("inventory-b0.json"), b.json("inventory-b-final.json")
    ca, cf = content(inv_a), content(inv_final)
    unpack = b.json("unpack.json")
    final_notes = b.json("note-files.json")
    observed = {
        "carried_copy_intact": unpack.get("vault_zip_sha256") == a.json("carried.json")["vault_zip_sha256"] and inv_0 == inv_a,
        "content_files_identical": ca == cf,
        "no_extra_content_files": set(cf) == set(ca),
        "notes_identical": all(final_notes.get(rel, {}).get("sha256") == info["sha256"] for rel, info in facts["notes"].items()),
        "ids_identical": all(final_notes.get(rel, {}).get("id") == info["id"] for rel, info in facts["notes"].items()),
        "links_identical": all(final_notes.get(rel, {}).get("links") == info["links"] for rel, info in facts["notes"].items()),
        "self_identical": inv_final.get("People/Self.md") == inv_a.get("People/Self.md") and bool(inv_a.get("People/Self.md")),
        "validate_ok": all(command_ok(b, label) and json.loads(b.stdout(label))["summary"]["errors"] == 0 for label in ("validate-1", "validate-2")),
        "changed": sorted(name for name in set(ca) | set(cf) if ca.get(name) != cf.get(name)),
    }
    return all(v for k, v in observed.items() if isinstance(v, bool)), observed


def case_recall(a, b, facts):
    drop = b.json("drop-index.json")
    s0, s1 = b.snap(0), b.snap(1)
    ids, responses = b.rpc("host-mcp-1")
    search = b.tool("host-mcp-1", "search")["payload"]
    note = b.tool("host-mcp-1", "get_note")
    related = b.tool("host-mcp-1", "related")["payload"]
    project = facts["project_path"]
    source = facts["source_path"]
    hits = [hit.get("path") for hit in search.get("ranked", [])]
    related_text = json.dumps(related)
    observed = {
        "index_was_carried": drop.get("existed_before") is True,
        "index_absent_before_first_memory_call": drop.get("absent_after") is True and s0["index_exists"] is False,
        "index_rebuilt_by_ordinary_calls": s1["index_exists"] is True,
        "recalls_captured_fact": facts["capture_path"] in hits and facts["project_path"] in hits,
        "note_text_served": not note["is_error"] and facts["token"] in json.dumps(note["payload"]),
        "linked_note_found": source in related_text and not b.tool("host-mcp-1", "related")["is_error"],
        "only_ordinary_commands": {row.get("role") for row in b.json("processes.json")} <= set(RESTORE_STEPS) | TOOLING,
    }
    return all(observed.values()), observed


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []


def same_path(left, right):
    return Path(left).as_posix().casefold() == Path(right).as_posix().casefold()


def case_reconnected(a, b, facts):
    install = b.json("install.json")
    before = tomllib.loads(b.text("config-b-before.toml"))["mcp_servers"]["knowledgeos"]
    config = tomllib.loads(b.text("config-b.toml"))["mcp_servers"]["knowledgeos"]
    vault = b.json("paths.json")["vault"]
    exe = install["executable"]
    old = a.json("paths.json")
    old_values = [old["vault"], a.json("install.json")["executable"]]
    stale_present = all(any(same_path(value, text) for text in strings(before)) for value in old_values)
    observed = {
        "setup_ok": command_ok(b, "setup-host") and "Wrote codex config" in b.stdout("setup-host"),
        "carried_config_was_stale": stale_present,
        "launcher_is_device_b_install": Path(config.get("command", "")).as_posix().casefold() == Path(exe).as_posix().casefold(),
        "binds_vault_id_and_path": config.get("args") == ["mcp", "--host-vault-id", facts["vault_id"], "--vault", vault],
        "env_points_at_device_b": config.get("env", {}).get("KNOWLEDGEOS_VAULT") == vault and "PYTHONPATH" not in config.get("env", {}),
        "marked_required": config.get("required") is True,
        "bound_to_installed_launcher": artifact.installed_server_binding(config, exe, vault),
        "no_device_a_path_left": not any(same_path(value, text) for value in old_values for text in strings(config)),
        "device_a_paths_differ": all(Path(x).as_posix().casefold() != Path(y).as_posix().casefold()
                                     for x, y in ((old["vault"], vault), (a.json("install.json")["executable"], exe))),
    }
    return all(observed.values()), observed


def case_serves(a, b, facts):
    record = b.command("host-mcp-1")
    config = tomllib.loads(b.text("config-b.toml"))["mcp_servers"]["knowledgeos"]
    ids, responses = b.rpc("host-mcp-1")
    init = responses[ids["initialize"]]["result"]
    listed = {tool["name"] for tool in responses[ids["tools_list"]]["result"]["tools"]}
    start = b.tool("host-mcp-1", "session_start")
    environment = b.json("host-mcp-1.environment.json")
    observed = {
        "ran_exact_configured_command": record.get("command") == [config["command"], *config["args"]],
        "configured_environment_applied": environment.get("KNOWLEDGEOS_VAULT") == config["env"]["KNOWLEDGEOS_VAULT"],
        "initialize_answered": init.get("serverInfo", {}).get("name") == "knowledgeos-memory",
        "memory_tools_listed": set(TOOLS) <= listed,
        "session_start_served": not start["is_error"] and bool(start["payload"].get("session_id")),
        "process_stopped_cleanly": finished(record) and record.get("exit_code") == 0,
        "no_credentials_in_children": not [name for name in b.json("child-environment.json")["names"] if SECRET_NAME.search(name)],
        "no_model_call": b.json("child-environment.json")["model_calls"] == 0,
    }
    return all(observed.values()), observed


def wording(text):
    """The product's words only: a file path in an evidence folder named clean-restore must not count as a hint."""
    return re.sub(r"[A-Za-z]:[\\/][^\s]*", "", text)


def case_dependency(a, b, facts):
    parts = {"doctor-1.stdout": b.stdout("doctor-1"), "setup-host.stdout": b.stdout("setup-host"), "setup-host.stderr": b.stderr("setup-host")}
    text = "\n".join(parts.values())
    searchable = "\n".join(re.sub(r"\([^)]*\)", "", wording(line)) for line in text.splitlines() if not line.strip().startswith("Key:"))
    observed = {
        "doctor_finished": ran_to_completion(b, "doctor-1"),
        "cause_named": ss.CAUSE.search(searchable) is not None or OTHER_DEVICE_CAUSE.search(searchable) is not None,
        "action_named": ACTION.search(searchable) is not None,
        "doctor_stdout": parts["doctor-1.stdout"],
    }
    return observed["doctor_finished"] and observed["cause_named"] and observed["action_named"], observed


def case_refused(a, b, facts):
    old = facts["proposal_path"]
    listing = b.tool("host-mcp-1", "list_proposals")
    opened, untrusted = ss.listing(listing)
    record, stderr = b.command("approve-lost"), b.stderr("approve-lost")
    refusal = {"finished_by_itself": finished(record, console=True) and record.get("exit_code") == 1, "exit_code": record.get("exit_code"),
               "timed_out": bool(record.get("timed_out")), "stderr": stderr, "no_traceback": bool(stderr.strip()) and "Traceback" not in stderr,
               "explained": bool(ss.EXPLAINED.search(wording(stderr))), "recovery_hint": bool(PROPOSE_AGAIN.search(wording(stderr))),
               "no_prompt_shown": "[y/N]" not in stderr and "Apply this" not in stderr}
    s0, s2 = b.snap(0), b.snap(2)
    pending = b.stdout("pending-1")
    observed = {
        "not_listed_valid": opened == [] and old in untrusted,
        "pending_lists_none": command_ok(b, "pending-1") and "No Self proposals waiting" in pending and old not in pending,
        **refusal,
        "self_unchanged": s2["self_sha256"] == b.snap(0)["self_sha256"] == a.snap(1)["self_sha256"],
        "proposal_file_unchanged": s2["proposals"] == s0["proposals"] == a.snap(1)["proposals"] and bool(s0["proposals"]),
        "no_row_for_it": [row for row in b.ledger(2) if row["proposal"] == old] == [],
    }
    keep = {k: v for k, v in observed.items() if isinstance(v, bool) and k != "timed_out"}
    return all(keep.values()) and not observed["timed_out"], observed


def case_valid_again(a, b, facts):
    old = facts["proposal_path"]
    restored = b.json("restore-state.json")
    s3 = b.snap(3)
    pending, pending_text = b.command("pending-2"), b.stdout("pending-2")
    opened, untrusted = ss.listing(b.tool("host-mcp-2", "list_proposals"))
    doctor, doctor_text = b.command("doctor-2"), b.stdout("doctor-2")
    waiting = doctor_text.split("waiting for you", 1)[1] if "waiting for you" in doctor_text else ""
    base, rows = a.ledger(1), b.ledger(4)
    carried_state = a.json("carried.json")["state_members"]
    observed = {
        "state_restored_from_backup": restored.get("members") == carried_state and restored.get("gate_key_sha256") == a.snap(1)["gate_key_sha256"],
        "replacement_state_differed": b.snap(2)["gate_key_sha256"] is not None and b.snap(2)["gate_key_sha256"] != a.snap(1)["gate_key_sha256"],
        "ledger_is_devices_a_ledger": s3["ledger_sha256"] == a.snap(1)["ledger_sha256"] and s3["ledger_sha256"] is not None,
        "listed_open_again": opened == [old] and untrusted == [],
        "pending_lists_it": finished(pending) and pending["exit_code"] == 0 and old in pending_text,
        "doctor_lists_it_as_waiting": finished(doctor) and "[OK] Proposal ledger is signed (1 entries" in doctor_text and old in waiting,
        "ledger_rows_kept": {r["sha256"] for r in base} <= {r["sha256"] for r in rows},
        "still_draft_not_applied": [(r["proposal"], r["status"], r["applied"]) for r in rows] == [(old, "draft", False)],
        "self_unchanged": b.snap(4)["self_sha256"] == a.snap(1)["self_sha256"],
    }
    return all(observed.values()), observed


def case_identity(a, b, facts):
    old = Path(facts["proposal_path"]).name
    snaps = [("a", a.snap(n)) for n in (0, 1)] + [("b", b.snap(n)) for n in range(5)]
    approvals = [row for row in b.json("processes.json") if row.get("role") == "approve-lost"]
    ledgers = [row for n in (1,) for row in a.ledger(n)] + [row for n in (3, 4) for row in b.ledger(n)]
    observed = {
        "self_identical_everywhere": len({s["self_sha256"] for _, s in snaps}) == 1,
        "proposal_file_identical": len({s["proposals"].get(old) for _, s in snaps[1:]}) == 1 and bool(snaps[1][1]["proposals"].get(old)),
        "no_row_applied": bool(ledgers) and not any(r["applied"] or r["status"] != "draft" for r in ledgers),
        "approval_refused_not_accepted": len(approvals) == 1 and approvals[0].get("exit_code") == 1 and approvals[0].get("console") is True,
        "no_answer_channel": b.command("approve-lost").get("answers_sent") == 0,
        "snapshots": len(snaps) == 7,
    }
    return all(observed.values()), observed


EVALUATORS = {
    "clean_devices": case_clean_devices, "origin_backups": case_origin, "content_preserved": case_content,
    "recall_and_index_rebuild": case_recall, "host_reconnected": case_reconnected, "host_command_serves": case_serves,
    "dependency_named": case_dependency, "old_proposal_refused_without_state": case_refused,
    "old_proposal_valid_after_restore": case_valid_again, "identity_never_changed": case_identity,
}


def evaluate(origin_dir, restore_dir):
    """The literal cases, recomputed from the two devices' retained evidence files alone."""
    a, b = Ev(origin_dir), Ev(restore_dir)
    try:
        facts = a.json("facts.json")
    except (OSError, ValueError, KeyError) as error:
        facts = None
        failure = type(error).__name__ + ": " + str(error)
    rows = []
    for name in CASE_NAMES:
        try:
            if facts is None:
                raise ValueError("Origin facts are unreadable: " + failure)
            passed, observed = EVALUATORS[name](a, b, facts)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            passed, observed = False, {"error": type(error).__name__ + ": " + str(error)}
        rows.append({"id": "restore." + name, "verdict": "PASS" if passed else "FAIL", "expected": EXPECTED[name],
                     "observed": observed, "evidence": ["report.json"]})
    return rows


# --------------------------------------------------------------------------- #
# running a device
# --------------------------------------------------------------------------- #


class Device:
    def __init__(self, role, kind, out):
        self.role, self.kind = role, kind
        self.out = Path(out).absolute()
        self.directory = self.out / kind
        self.data = self.out / (kind + "-data")
        self.carry = self.out / "carry" / kind
        for folder in (self.directory, self.data):
            folder.mkdir(parents=True, exist_ok=True)
        self.vault, self.neutral = self.data / "vault", self.data / "neutral"
        self.appdata = self.data / "appdata"
        self.state = self.appdata / "TwinAatma"
        for folder in (self.neutral, self.appdata):
            folder.mkdir(exist_ok=True)
        self.real_default = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")) / "TwinAatma"
        self.env, self.removed = self.child_environment()
        self.processes = []
        self.exe = None
        self.sources = artifact.product_hashes()
        self.snapshots = 0
        self.token = "cleanrestore" + uuid.uuid4().hex[:10]
        self.producer_hash = sha(__file__)

    def child_environment(self):
        env = {k: v for k, v in os.environ.items() if not SECRET_NAME.search(k)}
        removed = sorted(k for k in os.environ if SECRET_NAME.search(k))
        env.update(LOCALAPPDATA=str(self.appdata), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSAFEPATH", "VIRTUAL_ENV", "KNOWLEDGEOS_VAULT", "KNOWLEDGEOS_STATE_DIR", "KNOWLEDGEOS_GATE_KEY"):
            env.pop(key, None)
        return env, removed

    def save(self, name, value):
        text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
        (self.directory / name).write_text(text, encoding="utf-8", newline="\n")

    def freeze_plan(self, steps):
        self.save("plan.json", {"producer": PRODUCER, "role": self.role, "kind": self.kind, "case_ids": list(CASE_IDS),
                                "steps": list(steps), "frozen_at_ns": time.time_ns(),
                                "limits": "Case list and step order are frozen before the first command of this device"})

    def clean_start(self):
        self.save("clean-start.json", {"default_state_dir": str(self.real_default), "default_state_exists": self.real_default.exists(),
                                       "vault_exists": self.vault.exists(), "install_exists": (self.data / "venv").exists()})
        self.save("device.json", {
            "hostname": socket.gethostname(), "node": platform.node(), "computername": os.environ.get("COMPUTERNAME"),
            "runner_name": os.environ.get("RUNNER_NAME"), "runner_environment": os.environ.get("RUNNER_ENVIRONMENT"),
            "github_actions": os.environ.get("GITHUB_ACTIONS"), "github_job": os.environ.get("GITHUB_JOB"),
            "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "image_os": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"),
            "platform": platform.platform(), "python": sys.version, "role": self.role, "kind": self.kind})
        self.save("paths.json", {"vault": str(self.vault), "state_dir": str(self.state), "neutral": str(self.neutral)})
        self.save("child-environment.json", {"names": sorted(self.env), "removed_names": self.removed, "model_calls": 0,
                                             "note": "Credential-like names are removed from every child; no model is ever called"})

    def record(self, label, process, console=False):
        row = {"pid": process.pid, "role": label, "stopped": False, "console": console}
        self.processes.append(row)
        return row

    def finish(self, label, command, process, started_ns, started, timed_out, stdout, stderr, console, **extra):
        if stdout is not None:
            self.save(label + ".stdout.txt", stdout)
            self.save(label + ".stderr.txt", stderr)
        self.save(label + ".command.json", {
            "label": label, "command": command, "cwd": str(self.neutral), "shell": False, "console": console,
            "pid": process.pid, "exit_code": process.returncode, "stopped": process.poll() is not None,
            "timed_out": timed_out, "started_ns": started_ns, "seconds": time.monotonic() - started,
            "localappdata": str(self.appdata), "answers_sent": 0, **extra})

    def run(self, label, command, *, text_input="", env=None, timeout=240, **extra):
        command = [str(part) for part in command]
        started_ns, started = time.time_ns(), time.monotonic()
        process = subprocess.Popen(command, cwd=self.neutral, env=env or self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        row = self.record(label, process)
        timed_out = False
        try:
            stdout, stderr = process.communicate(text_input, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30)
            stdout, stderr = process.communicate(timeout=30)
        finally:
            row.update(stopped=process.poll() is not None, exit_code=process.returncode, timed_out=timed_out)
        self.finish(label, command, process, started_ns, started, timed_out, stdout, stderr, False, **extra)
        return row, stdout, stderr

    def cli(self, label, *arguments, timeout=240):
        return self.run(label, [self.exe, *arguments], timeout=timeout)

    def mcp(self, label, command, calls, env=None, **extra):
        """Send initialize, optional tools/list and tools/call messages over NDJSON on stdin."""
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-clean-restore", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        ids = {"initialize": 1}
        number = 1
        for key, name, arguments in calls:
            number += 1
            ids[key] = number
            if name == "tools/list":
                messages.append({"jsonrpc": "2.0", "id": number, "method": "tools/list"})
            else:
                messages.append({"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        self.save(label + ".requests.json", {"messages": messages, "ids": ids})
        return self.run(label, command, text_input="".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages), env=env, **extra)

    def console_approve(self, label, relative):
        """Reach the approval refusal from a hidden real console. No answer is ever sent."""
        stderr_path = self.directory / (label + ".stderr.txt")
        inner = subprocess.list2cmdline([str(self.exe), "self", "approve", relative, "--vault", str(self.vault)])
        line = '"%s" /d /s /c "%s 2>"%s""' % (os.environ.get("ComSpec", "cmd.exe"), inner, stderr_path)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        started_ns, started = time.time_ns(), time.monotonic()
        process = subprocess.Popen(line, cwd=self.neutral, env=self.env, creationflags=ss.CREATE_NEW_CONSOLE, startupinfo=startup)
        row = self.record(label, process, console=True)
        timed_out = False
        try:
            process.wait(timeout=CONSOLE_DEADLINE)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30)
                process.wait(timeout=30)
            row.update(stopped=process.poll() is not None, exit_code=process.returncode, timed_out=timed_out)
        if not stderr_path.exists():
            stderr_path.write_text("", encoding="utf-8")
        self.save(label + ".stdout.txt", "")
        self.finish(label, line, process, started_ns, started, timed_out, None, None, True,
                    stdout_note="stdout stays on the hidden console and is not captured; stderr was redirected to the retained file",
                    deadline_seconds=CONSOLE_DEADLINE)

    def install(self, manifest_path):
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
        record = {"kind": self.kind, "product_hashes": self.sources, "build_manifest_sha256": sha(manifest_path)}
        if self.kind == "wheel":
            wheel = artifact.plain(manifest["wheel"])
            artifact.wheel_binding(wheel, self.sources)
            venv = self.data / "venv"
            for label, command in (("tool-create-venv", [sys.executable, "-I", "-m", "venv", "--without-pip", venv]),
                                   ("tool-install", [sys.executable, "-I", "-m", "pip", "--python", venv / "Scripts/python.exe",
                                                     "install", "--no-index", "--no-deps", wheel])):
                row, _, stderr = self.run(label, command, timeout=400)
                if row["exit_code"] != 0:
                    raise RuntimeError(label + " failed: " + stderr[-1500:])
            python = venv / "Scripts/python.exe"
            row, stdout, stderr = self.run("tool-import-origin", [python, "-I", "-c", "import knowledgeos;print(knowledgeos.__file__)"])
            origin = artifact.installed_origin(stdout.strip(), venv, self.sources)
            self.exe = python.with_name("twinaatma.exe")
            record.update(artifact=str(wheel), artifact_sha256=sha(wheel), import_origin=str(origin))
        else:
            self.exe = artifact.plain(manifest["executable"])
            root, files = artifact.binary_binding(self.exe, manifest_path, self.sources)
            record.update(artifact=str(self.exe), artifact_sha256=sha(self.exe), distribution_root=str(root), distribution_file_count=len(files))
        if not self.exe.is_file():
            raise RuntimeError("Installed launcher is missing: " + str(self.exe))
        record.update(executable=str(self.exe), executable_sha256=sha(self.exe), product_bound=True)
        self.save("install.json", record)

    def snapshot(self):
        number = self.snapshots
        self.snapshots += 1
        ledgers = sorted((self.state / "vaults").glob("*/self-proposals.jsonl")) if (self.state / "vaults").is_dir() else []
        ledger = ledgers[0] if len(ledgers) == 1 else None
        if ledger is not None:
            shutil.copyfile(ledger, self.directory / ("snap-%d.ledger.jsonl" % number))
        proposals = self.vault / "People/Self-Proposals"
        key, bindings = self.state / "gate.key", self.state / "vault-bindings.json"
        self.save("snap-%d.json" % number, {
            "name": number, "taken_ns": time.time_ns(), "self_sha256": sha(self.vault / "People/Self.md"),
            "gate_key_sha256": sha(key) if key.is_file() else None, "bindings_sha256": sha(bindings) if bindings.is_file() else None,
            "ledger_count": len(ledgers), "ledger_sha256": sha(ledger) if ledger else None,
            "index_exists": (self.vault / "knowledge_index.db").is_file(),
            "state_files": {p.relative_to(self.state).as_posix(): sha(p) for p in sorted(self.state.rglob("*")) if p.is_file()} if self.state.is_dir() else {},
            "proposals": {p.name: sha(p) for p in sorted(proposals.glob("*.md"))} if proposals.is_dir() else {}})

    def note_files(self, relatives):
        found = {}
        for relative in relatives:
            path = self.vault / relative
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                found[relative] = {"sha256": sha(path), "id": front_id(text), "links": relative_links(text)}
        self.save("note-files.json", found)
        return found

    def stop_summary(self):
        self.save("processes.json", self.processes)
        return bool(self.processes) and all(p["stopped"] is True and isinstance(p.get("exit_code"), int) for p in self.processes)


def zip_tree(root, target):
    root, target = Path(root), Path(target)
    members = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                archive.write(path, relative)
                members.append(relative)
    return sorted(members)


def unzip_tree(source, root):
    root = Path(root).absolute()
    members = []
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            target = (root / name).absolute()
            if ".." in Path(name).parts or Path(name).is_absolute() or root not in target.parents:
                raise ValueError("Unsafe backup member: " + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            members.append(name)
    return sorted(members)


# --------------------------------------------------------------------------- #
# device A
# --------------------------------------------------------------------------- #


def run_origin(kind, manifest, out):
    device = Device("origin", kind, out)
    device.freeze_plan(ORIGIN_STEPS)
    error = None
    try:
        device.clean_start()
        device.install(manifest)
        exe, vault, token = device.exe, device.vault, device.token
        row, stdout, _ = device.cli("init", "init", vault, "--name", "Clean restore fixture", "--non-interactive")
        if row["exit_code"] != 0:
            raise RuntimeError("init failed")
        device.snapshot()
        project_rel, source_rel = "Projects/clean-restore-orbit.md", "Research/clean-restore-source.md"
        project = ("---\nid: kos:project:clean-restore-orbit\ntitle: Clean Restore Orbit\ntype: project\ndescription: Synthetic project for the clean-device restore journey\nschema: knowledgeos-v0.2\nstatus: active\ncreated: 2026-10-21\nupdated: 2026-10-21\ntags: [synthetic]\n---\n\n"
                   "# Clean Restore Orbit\n\nThe synthetic Meridian crate has a 17 kg limit. Token " + token + ".\n\n"
                   "## Links\n- [Source](../Research/clean-restore-source.md)\n")
        source = ("---\nid: kos:research:clean-restore-source\ntitle: Clean Restore Source\ntype: research\ndescription: Synthetic source for the clean-device restore journey\nschema: knowledgeos-v0.2\nstatus: draft\ncreated: 2026-10-21\nupdated: 2026-10-21\ntags: [synthetic]\n---\n\n"
                  "# Clean Restore Source\n\nSynthetic cargo evidence.\n\n## Links\n- [Project](../Projects/clean-restore-orbit.md)\n")
        for relative, text in ((project_rel, project), (source_rel, source)):
            (vault / relative).write_text(text, encoding="utf-8", newline="\n")
        row, stdout, _ = device.cli("capture", "memory", "memory_capture", "--vault", vault, "--title", "Clean restore Meridian fact",
                                    "--content", "The synthetic Meridian crate has a 17 kg limit. Token " + token + ". [Project](../Projects/clean-restore-orbit.md)")
        capture_path = json.loads(stdout).get("path")
        if row["exit_code"] != 0 or not capture_path:
            raise RuntimeError("capture failed")
        device.cli("ids-0", "ids", "assign", "--write", "--vault", vault)
        base = [str(exe), "mcp", "--vault", str(vault), "--framing", "ndjson"]
        row, stdout, _ = device.mcp("propose", base, [
            ("start", "memory_session_start", {"task_hint": "clean device restore"}),
            ("propose", "memory_propose_self_update", {"summary": "Synthetic clean restore proposal", "section": "heuristics",
                                                       "proposed_markdown": "* Prefer retained evidence after a restore.",
                                                       "rationale": "Synthetic clean-device acceptance only.", "mode": "append"})])
        proposal = Ev(device.directory).tool("propose", "propose")["payload"].get("proposal_path")
        if not proposal:
            raise RuntimeError("proposal was not made")
        device.mcp("verify-0", base, [("list", "memory_list_self_proposals", {}), ("search", "memory_search", {"query": token})])
        device.cli("pending-0", "self", "pending", "--vault", vault)
        device.cli("doctor-0", "doctor", "--vault", vault)
        device.cli("validate-0", "validate", "--vault", vault)
        device.cli("setup-host-0", "setup-host", "--host", "codex", "--vault", vault, "--write")
        device.snapshot()
        relatives = [project_rel, source_rel, capture_path]
        notes = device.note_files(relatives)
        marker = json.loads((vault / ".knowledgeos-vault.json").read_text(encoding="utf-8"))
        links_resolve = all((vault / Path(rel).parent / link).resolve().is_file() for rel, info in notes.items() for link in info["links"])
        self_hash = sha(vault / "People/Self.md")
        device.save("facts.json", {"token": token, "vault_id": marker["vault_id"], "notes": notes, "project_path": project_rel,
                                   "source_path": source_rel, "capture_path": capture_path, "proposal_path": proposal,
                                   "self_sha256": self_hash, "links_resolve": links_resolve})
        files = inventory(vault)
        device.save("inventory-a.json", files)
        carry = device.carry
        carry.mkdir(parents=True, exist_ok=True)
        vault_members = zip_tree(vault, carry / "vault.zip")
        state_members = zip_tree(device.state, carry / "signing-state.zip")
        device.save("carried.json", {"vault_zip_sha256": sha(carry / "vault.zip"), "state_zip_sha256": sha(carry / "signing-state.zip"),
                                     "vault_members": vault_members, "state_members": state_members})
    except BaseException as caught:  # the report must still say what happened
        error = caught
        device.save("execution-error.json", {"error": type(caught).__name__ + ": " + str(caught)})
    stopped = device.stop_summary()
    device.save("origin-result.json", {"error": None if error is None else type(error).__name__ + ": " + str(error),
                                       "all_started_processes_stopped": stopped, "producer": PRODUCER,
                                       "producer_sha256": device.producer_hash})
    print(("FAIL " if error else "ok   ") + "origin " + kind + (": " + str(error) if error else ""), flush=True)
    return 0 if error is None else 1


# --------------------------------------------------------------------------- #
# device B
# --------------------------------------------------------------------------- #


def run_restore(kind, manifest, out, origin_root, vault_zip, state_zip):
    device = Device("restore", kind, out)
    device.freeze_plan(RESTORE_STEPS)
    origin_dir = Path(origin_root) / kind
    error = None
    try:
        device.clean_start()
        facts = Ev(origin_dir).json("facts.json")
        members = unzip_tree(vault_zip, device.vault)
        inv0 = inventory(device.vault)
        device.save("inventory-b0.json", inv0)
        device.save("unpack.json", {"vault_zip_sha256": sha(vault_zip), "state_zip_sha256": sha(state_zip), "members": members})
        device.install(manifest)
        exe, vault = device.exe, device.vault
        index = [p for p in vault.glob("knowledge_index.db*")]
        existed = (vault / "knowledge_index.db").is_file()
        for path in index:
            path.unlink()
        device.save("drop-index.json", {"existed_before": existed, "removed": [p.name for p in index],
                                        "absent_after": not (vault / "knowledge_index.db").exists(),
                                        "reason": "knowledge_index.db is ignored by the vault's own .gitignore, so a synced copy lacks it"})
        device.snapshot()
        config_path = vault / ".codex/config.toml"
        (device.directory / "config-b-before.toml").write_bytes(config_path.read_bytes())
        device.cli("setup-host", "setup-host", "--host", "codex", "--vault", vault, "--write")
        (device.directory / "config-b.toml").write_bytes(config_path.read_bytes())
        device.cli("doctor-1", "doctor", "--vault", vault)
        device.cli("pending-1", "self", "pending", "--vault", vault)
        device.cli("validate-1", "validate", "--vault", vault)
        server = tomllib.loads(config_path.read_text(encoding="utf-8"))["mcp_servers"]["knowledgeos"]
        host_env = dict(device.env, **server.get("env", {}))
        device.save("host-mcp-1.environment.json", {k: v for k, v in server.get("env", {}).items()})
        device.mcp("host-mcp-1", [server["command"], *server["args"]], [
            ("tools_list", "tools/list", None),
            ("session_start", "memory_session_start", {"task_hint": "after a clean-device restore"}),
            ("search", "memory_search", {"query": facts["token"]}),
            ("get_note", "memory_get_note", {"path_or_id": facts["project_path"]}),
            ("related", "memory_related", {"path_or_id": facts["project_path"], "hops": 1}),
            ("list_proposals", "memory_list_self_proposals", {})], env=host_env)
        device.snapshot()
        device.console_approve("approve-lost", facts["proposal_path"])
        device.snapshot()
        restored = unzip_tree(state_zip, device.state)
        key = device.state / "gate.key"
        device.save("restore-state.json", {"members": restored, "gate_key_sha256": sha(key) if key.is_file() else None,
                                           "state_zip_sha256": sha(state_zip)})
        device.snapshot()
        device.cli("pending-2", "self", "pending", "--vault", vault)
        device.mcp("host-mcp-2", [server["command"], *server["args"]], [("list_proposals", "memory_list_self_proposals", {})], env=host_env)
        device.cli("doctor-2", "doctor", "--vault", vault)
        device.cli("validate-2", "validate", "--vault", vault)
        device.snapshot()
        device.save("inventory-b-final.json", inventory(vault))
        device.note_files(list(facts["notes"]))
    except BaseException as caught:
        error = caught
        device.save("execution-error.json", {"error": type(caught).__name__ + ": " + str(caught)})
    stopped = device.stop_summary()
    try:
        cases = evaluate(origin_dir, device.directory)
    except (OSError, ValueError, KeyError) as caught:
        error = error or caught
        cases = []
    origin_result = {}
    try:
        origin_result = json.loads((origin_dir / "origin-result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        origin_result = {"error": "origin result is missing"}
    plan_ok = frozen_before_calls(origin_dir) and frozen_before_calls(device.directory)
    try:
        findings = observe_restore(origin_dir, device.directory, device.vault)
    except (OSError, ValueError, KeyError) as caught:
        findings = {"error": type(caught).__name__ + ": " + str(caught)}
    complete = [row["id"] for row in cases] == list(CASE_IDS)
    passed = (error is None and complete and all(row["verdict"] == "PASS" for row in cases) and stopped
              and origin_result.get("error") is None and origin_result.get("all_started_processes_stopped") is True and plan_ok)
    for row in cases:
        print(row["verdict"] + " " + row["id"], flush=True)
    report = {
        "producer": PRODUCER, "producer_sha256": device.producer_hash, "kind": kind, "cell": ["Windows", kind],
        "platform": platform.platform(), "scope": SCOPE, "expected_case_ids": list(CASE_IDS), "cases": cases,
        "verdict": "PASS" if passed else "FAIL", "origin_error": origin_result.get("error"),
        "origin_processes_stopped": origin_result.get("all_started_processes_stopped"),
        "restore_processes_stopped": stopped, "frozen_before_first_command": plan_ok, "product_hashes": device.sources,
        "observations": findings,
        "error": None if error is None else type(error).__name__ + ": " + str(error),
        "limits": ["Windows runners only; the approval prompt is never answered; no Codex application, model chat or credential is used",
                   "Validity is observed at describe time through listings, pending and doctor, never by applying a proposal"]}
    device.save("report.json", report)
    print(json.dumps({"report": str(device.directory / "report.json"), "verdict": report["verdict"],
                      "passed": sum(row["verdict"] == "PASS" for row in cases), "total": len(CASE_IDS)}), flush=True)
    return 0  # the verdict is data in report.json; a failed case does not make the run itself fail


def observe_restore(origin_dir, directory, vault):
    """Findings that are not part of any frozen case: they are reported, never graded."""
    a, b = Ev(origin_dir), Ev(directory)
    old_vault, old_exe = a.json("paths.json")["vault"], a.json("install.json")["executable"]
    needles = {old_vault, old_vault.replace("\\", "\\\\"), old_exe, old_exe.replace("\\", "\\\\")}
    stale = []
    for relative in sorted(content(inventory(vault))):
        path = Path(vault) / relative
        try:
            text = path.read_text(encoding="utf-8") if path.stat().st_size < 200000 else ""
        except (OSError, UnicodeError):
            continue
        if any(needle in text for needle in needles):
            stale.append(relative)
    errors = {label: [line.strip() for line in b.stdout(label).splitlines() if "[ERROR]" in line] for label in ("doctor-1", "doctor-2")}
    return {"doctor_exit_codes": {label: b.command(label).get("exit_code") for label in ("doctor-1", "doctor-2")},
            "doctor_error_lines": errors, "vault_files_still_naming_device_a_paths": stale,
            "note": "Reported, not graded: init writes Cursor files with absolute device paths, and they stay stale after a restore"}


def frozen_before_calls(directory):
    directory = Path(directory)
    try:
        frozen = json.loads((directory / "plan.json").read_text(encoding="utf-8"))["frozen_at_ns"]
        starts = [json.loads(p.read_text(encoding="utf-8"))["started_ns"] for p in directory.glob("*.command.json")]
    except (OSError, ValueError, KeyError):
        return False
    return type(frozen) is int and bool(starts) and all(type(s) is int and s > frozen for s in starts)


# --------------------------------------------------------------------------- #
# the bundle (runner side)
# --------------------------------------------------------------------------- #


def build_bundle(restore_root, origin_root, output):
    import acceptance as base
    import ci_graded as ci

    local = ci.local_binding(base)
    environment = os.environ
    commit = environment.get("GITHUB_SHA")
    ci.require(commit == local["commit"], "Runner HEAD differs from GITHUB_SHA")
    cells, raw = {}, {}
    root = Path(base.ROOT).absolute()
    for kind in KINDS:
        directory = Path(restore_root).absolute() / kind
        origin = Path(origin_root).absolute() / kind
        try:
            report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            report = None
            cells[kind] = {"cell": ["Windows", kind], "verdict": "FAIL", "cases": [], "error": "report.json unreadable: " + str(error)}
        for folder in (directory, origin):
            if folder.is_dir():
                for path in sorted(folder.iterdir()):
                    if path.is_file():
                        raw[path.relative_to(root).as_posix() if root in path.parents else path.as_posix()] = sha(path)
        if report is None:
            continue
        info = {role: json.loads((folder / "device.json").read_text(encoding="utf-8")) for role, folder in (("origin", origin), ("restore", directory))
                if (folder / "device.json").is_file()}
        cells[kind] = {"cell": ["Windows", kind], "verdict": report["verdict"], "cases": report["cases"],
                       "frozen_before_first_command": report.get("frozen_before_first_command") is True,
                       "origin_processes_stopped": report.get("origin_processes_stopped") is True,
                       "restore_processes_stopped": report.get("restore_processes_stopped") is True,
                       "origin_error": report.get("origin_error"), "error": report.get("error"),
                       "observations": report.get("observations"),
                       "report_sha256": sha(directory / "report.json"), "devices": info,
                       "install": {role: json.loads((folder / "install.json").read_text(encoding="utf-8")) for role, folder in (("origin", origin), ("restore", directory))
                                   if (folder / "install.json").is_file()}}
    graded = {"cells": cells}
    adapter = HERE / "clean_restore_adapter.py"
    binding = {
        "repository": environment.get("GITHUB_REPOSITORY", ci.REPOSITORY), "commit": commit, "ref": environment.get("GITHUB_REF"),
        "event": environment.get("GITHUB_EVENT_NAME"), "workflow_ref": environment.get("GITHUB_WORKFLOW_REF"),
        "run_id": environment.get("GITHUB_RUN_ID"), "run_attempt": environment.get("GITHUB_RUN_ATTEMPT"),
        "runner_environment": environment.get("RUNNER_ENVIRONMENT"),
        "platform": {"system": platform.system(), "machine": platform.machine(), "platform": platform.platform(), "python": sys.version,
                     "image": environment.get("ImageOS"), "image_version": environment.get("ImageVersion"), "runner_name": environment.get("RUNNER_NAME")},
        **{key: local[key] for key in ("product_hashes", "product_hashes_lf", "toolkit_hashes_lf", "scorer_sha256", "scorer_sha256_lf",
                                       "rubric_sha256", "adapter_requirements_sha256", "adapter_requirements_sha256_lf")},
        "producer_sha256_lf": lf_sha(__file__),
        "adapter_sha256_lf": lf_sha(adapter) if adapter.is_file() else None,
        "support_sha256_lf": {name: lf_sha(HERE / name) for name in SUPPORT},
    }
    bundle = {"schema": SCHEMA, "binding": binding, "raw_reports": raw, "graded": graded,
              "graded_sha256": sha_bytes(ci.canonical(graded).encode())}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    complete = all(cell.get("verdict") == "PASS" for cell in cells.values()) and set(cells) == set(KINDS)
    for kind, cell in cells.items():
        for row in cell.get("cases", []):
            print("{:<11} {} ({})".format(row["verdict"], row["id"], kind))
    # The verdicts are data: a failed case is a finding the scorer reports, so the bundle is still attested.
    print("bundle:", output, "all-pass" if complete else "NOT ALL PASS")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    origin = commands.add_parser("origin", help="Device A")
    origin.add_argument("--build-manifest", type=Path, required=True)
    origin.add_argument("--output", type=Path, required=True)
    origin.add_argument("--kind", choices=KINDS, action="append")
    restore = commands.add_parser("restore", help="Device B")
    restore.add_argument("--build-manifest", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    restore.add_argument("--origin-evidence", type=Path, required=True)
    restore.add_argument("--vault-zip-dir", type=Path, required=True, help="Folder holding <kind>/vault.zip files")
    restore.add_argument("--state-zip-dir", type=Path, required=True, help="Folder holding <kind>/signing-state.zip files")
    restore.add_argument("--kind", choices=KINDS, action="append")
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--restore-root", type=Path, required=True)
    bundle.add_argument("--origin-root", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("The clean-device restore journey runs on native Windows only", file=sys.stderr)
        return 2
    try:
        if args.command == "bundle":
            return build_bundle(args.restore_root, args.origin_root, args.output)
        status = 0
        for kind in args.kind or KINDS:
            if args.command == "origin":
                status |= run_origin(kind, args.build_manifest, args.output)
            else:
                status |= run_restore(kind, args.build_manifest, args.output, args.origin_evidence,
                                      args.vault_zip_dir / kind / "vault.zip", args.state_zip_dir / kind / "signing-state.zip")
        return status
    except (ValueError, OSError, KeyError) as error:
        print("clean-restore rejected: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
