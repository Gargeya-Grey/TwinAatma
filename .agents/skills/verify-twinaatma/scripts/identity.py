"""Observe cold-start identity and canonical sections through source CLI and MCP."""
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

from data_preservation import DataRun, ROOT, inventory, sha, source_files

JOURNEYS = {
    "unknown": {"producer": "verify-twinaatma.identity-unknown/v1", "outcome": "IDENTITY.unknown_stays_unknown",
                "cases": ("cold_init", "cold_self_get", "cold_session_start", "restart_self_get", "identity_preserved")},
    "canonical": {"producer": "verify-twinaatma.identity-canonical/v1", "outcome": "IDENTITY.canonical_sections",
                  "cases": ("marked_self_get", "marked_session_start", "marked_proposals", "aliases_self_get",
                            "aliases_session_start", "aliases_proposals", "duplicate_self_get", "duplicate_session_start",
                            "duplicate_proposal", "identity_preserved")},
}
SECTIONS = ("heuristics", "values", "mental_models", "anti_goals", "active_bets", "drift_log")
UNKNOWN = {
    "heuristics": "Unknown. No owner-confirmed heuristics recorded yet.",
    "values": "Unknown. No owner-confirmed values or ranking recorded yet.",
    "mental_models": "Unknown. No owner-confirmed mental models recorded yet.",
    "anti_goals": "Unknown. No owner-confirmed anti-goals recorded yet.",
    "active_bets": "Unknown. No owner-confirmed strategic bets recorded yet.",
}
HEADINGS = {
    "marked": ("🧭 Everyday choices", "🪨 Priorities I confirmed", "🧩 Thinking patterns",
               "🛑 Roads I decline", "🎯 Current commitments", "📈 Changes with evidence"),
    "aliases": ("🧭 Rules of Thumb", "🪨 Core Values", "🧩 Mental Models",
                "🛑 Anti Goals", "🎯 Current Bets", "📈 Semantic Drift Tracking"),
}
CONTENTS = {
    "heuristics": "- Synthetic rule HX41. Compare one reversible option before choosing.\n- Synthetic rule HX42. Record evidence before generalizing.",
    "values": "1. Synthetic priority VX41. Keep explicit evidence above untested confidence.\n2. Synthetic priority VX42. Preserve time for careful review.",
    "mental_models": "- Synthetic model MX41. Separate observations from interpretations.\n- Synthetic model MX42. Consider the cost of reversing a decision.",
    "anti_goals": "- Synthetic limit AX41. Avoid irreversible changes based only on guesses.\n- Synthetic limit AX42. Avoid ranking another person's unstated values.",
    "active_bets": "- Synthetic bet BX41. Test a small local prototype this week.\n- Synthetic bet BX42. Reassess the prototype after measured feedback.",
    "drift_log": "| Topic | Shift Observed | Date Flagged | Evidence |\n|---|---|---|---|\n| Synthetic DX41 | Revised one prototype estimate | 2026-10-19 | fixture evidence DX42 |",
}


def expected_sections(kind):
    return {key: (("<!-- kos:section=" + key + " -->\n") if kind == "marked" else "") + CONTENTS[key]
            for key in SECTIONS}


def fixture_identity(kind):
    body = "---\ntype: person\ntitle: Synthetic Identity C64\nid: kos:person:self\nschema: knowledgeos-v0.3\nstatus: active\n"
    body += "description: Synthetic canonical-section acceptance identity\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [synthetic]\n---\n# Synthetic Identity C64\n\n"
    for key, heading in zip(SECTIONS, HEADINGS["marked" if kind == "duplicate" else kind]):
        body += "## " + heading + "\n"
        if kind != "aliases":
            body += "<!-- kos:section=" + key + " -->\n"
        body += CONTENTS[key] + "\n\n"
    if kind == "duplicate":
        body += "## 🧨 Conflicting second priority\n<!-- kos:section=values -->\n- Synthetic conflicting value QX99. Never guess between duplicate markers.\n"
    return body.encode("utf-8")


def unknown_observation(result):
    payload = result.get("payload") if isinstance(result, dict) else None
    sections = payload.get("sections") if isinstance(payload, dict) else None
    present = isinstance(sections, dict) and set(sections) == set(SECTIONS)
    expected = {key: "<!-- kos:section=" + key + " -->\n" + content for key, content in UNKNOWN.items()}
    attributes = {key: present and sections.get(key) == content for key, content in expected.items()}
    drift = sections.get("drift_log", "") if isinstance(sections, dict) else ""
    drift_pattern = (r"<!-- kos:section=drift_log -->\n\| Topic \| Shift Observed \| Date Flagged \| Evidence \|\n"
                     r"\|---\|---\|---\|---\|\n\| — \| Vault initialized \| \d{4}-\d{2}-\d{2} \| init \|")
    return {"valid": result.get("is_error") is False and isinstance(payload, dict) and payload.get("path") == "People/Self.md"
                     and present and all(attributes.values()) and re.fullmatch(drift_pattern, drift) is not None,
            "all_six_sections_present": present, "unknown_attributes": attributes, "drift_only_records_initialization": re.fullmatch(drift_pattern, drift) is not None,
            "payload": payload, "is_error": result.get("is_error")}


def section_observation(result, kind):
    payload = result.get("payload") if isinstance(result, dict) else None
    sections = payload.get("sections") if isinstance(payload, dict) else None
    expected = expected_sections(kind)
    return {"valid": result.get("is_error") is False and isinstance(payload, dict) and payload.get("path") == "People/Self.md" and sections == expected,
            "literal_sections_match": sections == expected, "expected_sections": expected, "payload": payload, "is_error": result.get("is_error")}


def context_self(result):
    payload = result.get("payload") if isinstance(result, dict) else None
    context = payload.get("context") if isinstance(payload, dict) else None
    value = context.get("self") if isinstance(context, dict) else None
    return {"payload": value, "is_error": result.get("is_error")}


def duplicate_observation(result):
    payload = result.get("payload") if isinstance(result, dict) else None
    message = payload.get("error") if isinstance(payload, dict) else None
    valid = result.get("is_error") is True and isinstance(message, str) and "duplicate" in message.lower() and "kos:section=values" in message
    return {"valid": valid, "is_error": result.get("is_error"), "payload": payload}


class IdentityRun(DataRun):
    def __init__(self, output, journey):
        super().__init__(output)
        self.journey = journey
        self.producer_hash = sha(__file__)
        self.support = {"data_preservation.py": sha(Path(__file__).with_name("data_preservation.py"))}
        self.fixtures = []

    def add_case(self, name, expected, observed, passed, evidence):
        self.cases.append({"id": "identity." + self.journey + "." + name, "verdict": "PASS" if passed else "FAIL",
                           "expected": expected, "observed": observed, "evidence": evidence})
        print(self.cases[-1]["verdict"] + " " + self.cases[-1]["id"], flush=True)

    def activate(self, fixture):
        self.env["PYTHONPATH"] = str(fixture["toolkit"])
        self.env["KNOWLEDGEOS_STATE_DIR"] = str(fixture["scope"] / "gate-state")

    def cli(self, label, fixture, arguments):
        self.activate(fixture)
        record, stdout, stderr = self.command(label, [sys.executable, "-B", "-P", "-m", "knowledgeos", *arguments],
                                             cwd=fixture["scope"], vault=fixture["vault"], timeout=90)
        record["import_path"] = self.env["PYTHONPATH"]
        self.save(label + ".command.json", record)
        return record, stdout, stderr

    def rpc(self, label, fixture, calls):
        self.activate(fixture)
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-identity", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        messages += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                     for index, (name, arguments) in enumerate(calls, 2)]
        self.save(label + ".requests.json", messages)
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", str(fixture["vault"]), "--framing", "ndjson"]
        env = dict(self.env, KNOWLEDGEOS_VAULT=str(fixture["vault"]))
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=fixture["scope"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        error, interruption = None, None
        try:
            stdout, stderr = process.communicate("".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages), timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            error = "Identity MCP exceeded the proof deadline"
        except BaseException as caught:
            process.kill()
            stdout, stderr = process.communicate()
            error, interruption = str(caught), caught
        finally:
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode)
        (self.directory / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (self.directory / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        record = {"command": command, "cwd": str(fixture["scope"]), "shell": False, "vault": str(fixture["vault"]),
                  "state_dir": env["KNOWLEDGEOS_STATE_DIR"], "import_path": env["PYTHONPATH"], "pid": process.pid,
                  "exit_code": process.returncode, "seconds": time.monotonic() - started, "stopped": tracked["stopped"], "error": error}
        self.save(label + ".command.json", record)
        if interruption is not None:
            raise interruption
        if error or process.returncode:
            raise RuntimeError(error or "Identity MCP exited " + str(process.returncode))
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {response.get("id"): response for response in responses}
        if len(responses) != len(calls) + 1 or set(by_id) != set(range(1, len(calls) + 2)) or by_id[1].get("result", {}).get("serverInfo", {}).get("name") != "knowledgeos-memory":
            raise ValueError("Wrong identity MCP response inventory or server identity")
        results = []
        for index in range(2, len(calls) + 2):
            result = by_id[index]["result"]
            content = result["content"]
            if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text" or not isinstance(result.get("isError"), bool):
                raise ValueError("Wrong identity MCP content or protocol error shape")
            payload = json.loads(content[0]["text"])
            if not isinstance(payload, dict):
                raise ValueError("Identity MCP payload must be an object")
            results.append({"payload": payload, "is_error": result["isError"]})
        self.save(label + ".results.json", results)
        return results

    def prepare(self, kind):
        scope = self.directory / "fixtures" / kind
        toolkit, vault = scope / "toolkit", scope / "vault"
        toolkit.mkdir(parents=True)
        for source in self.inputs:
            target = toolkit / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        fixture = {"kind": kind, "scope": scope, "toolkit": toolkit, "vault": vault}
        self.fixtures.append(fixture)
        self.save(kind + ".toolkit-before.json", inventory(toolkit))
        label = kind + "-init"
        command, stdout, _ = self.cli(label, fixture, ["init", str(vault), "--name", "Synthetic Unknown A47", "--non-interactive"])
        initialized = json.loads(stdout) if command["exit_code"] == 0 else {}
        post = initialized.get("post_init", {})
        doctor, doctor_stdout, doctor_stderr = self.cli(kind + "-doctor", fixture, ["doctor", "--vault", str(vault)])
        ready = command["exit_code"] == 0 and not command["error"] and command["stopped"] and (vault / "People/Self.md").is_file()
        ready = ready and set(post) >= {"rebuild", "validate"} and all(row.get("ok") is True for row in post.values())
        fixture["ready"] = ready and doctor["exit_code"] == 0 and not doctor["error"] and doctor["stopped"]
        fixture["initialization"] = {"cli_exit_code": command["exit_code"], "initialized": initialized,
                                     "doctor_exit_code": doctor["exit_code"], "doctor_stdout": doctor_stdout, "doctor_stderr": doctor_stderr,
                                     "only_supplied_identity_attribute": "name", "ready": fixture["ready"]}
        if not fixture["ready"]:
            raise RuntimeError("Fresh identity fixture failed init or doctor")
        if kind != "cold":
            (vault / "People/Self.md").write_bytes(fixture_identity(kind))
        fixture["identity_before"] = sha(vault / "People/Self.md")
        fixture["proposals_before"] = inventory(vault / "People/Self-Proposals")
        fixture["source_before"] = inventory(scope)
        self.save(kind + ".before.json", fixture["source_before"])
        return fixture

    def evidence(self, label):
        return [label + suffix for suffix in (".command.json", ".requests.json", ".stdout.txt", ".stderr.txt", ".results.json")]

    def read_case(self, fixture, name, session=False, unknown=False, duplicate=False):
        label = self.journey + "-" + name
        tool = "memory_session_start" if session else "memory_self_get"
        arguments = {"task_hint": "What owner-confirmed preferences, ranked values, mental models, anti-goals and live bets do you know?",
                     "session_id": self.journey + "-" + fixture["kind"] + "-section-proof"} if session else {}
        result = self.rpc(label, fixture, [(tool, arguments)])[0]
        if duplicate:
            observed = duplicate_observation(result)
            expected = "Protocol error identifies duplicate canonical values markers; no section is guessed"
        else:
            candidate = context_self(result) if session else result
            observed = unknown_observation(candidate) if unknown else section_observation(candidate, fixture["kind"])
            observed["public_result"] = result
            if session:
                observed["returned_requested_session_id"] = result["payload"].get("session_id") == arguments["session_id"]
                observed["valid"] = observed["valid"] and observed["returned_requested_session_id"]
            expected = "Every cold-start personal attribute is explicitly unknown and drift records only initialization" if unknown else "All six literal canonical section bodies reach the public reader unchanged"
        preserved = sha(fixture["vault"] / "People/Self.md") == fixture["identity_before"]
        observed["self_bytes_unchanged"] = preserved
        self.add_case(name, expected, observed, fixture["ready"] and observed["valid"] and preserved,
                      [fixture["kind"] + ".before.json", *self.evidence(label)])

    def proposals_case(self, fixture, name, duplicate=False):
        label = self.journey + "-" + name
        keys = ("values",) if duplicate else SECTIONS
        patches = {key: "- Synthetic addition PX41 for " + key + ". Compare retained evidence before revising this test preference." for key in keys}
        calls = [("memory_propose_self_update", {"summary": "Synthetic canonical target " + key, "section": key,
                  "proposed_markdown": patches[key], "rationale": "Synthetic source identity acceptance only.", "mode": "append"}) for key in keys]
        before = inventory(fixture["scope"])
        self.save(label + ".before.json", before)
        results = self.rpc(label, fixture, calls)
        rows = []
        if duplicate:
            rows.append(duplicate_observation(results[0]))
            same = fixture["proposals_before"] == inventory(fixture["vault"] / "People/Self-Proposals")
            rows[0]["proposal_evidence_unchanged"] = same
            rows[0]["valid"] = rows[0]["valid"] and same
        else:
            expected = expected_sections(fixture["kind"])
            for key, result in zip(keys, results):
                payload = result["payload"]
                relative = payload.get("proposal_path")
                target = fixture["vault"] / relative if isinstance(relative, str) else None
                contained = target is not None and target.parent == fixture["vault"] / "People/Self-Proposals" and target.name.endswith(".md")
                plain = contained and target.is_file() and not target.is_symlink() and target.stat().st_nlink == 1
                if plain:
                    components = (target, target.parent, target.parent.parent, fixture["vault"])
                    plain = all(not stat.S_ISLNK(part.lstat().st_mode) and not bool(getattr(part.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)) for part in components)
                raw = target.read_text(encoding="utf-8") if plain else ""
                expected_base = hashlib.sha256("\n".join(line.rstrip() for line in expected[key].splitlines() if line.strip()).encode("utf-8")).hexdigest()[:16]
                required = ("proposal_section: " + key, "proposal_target: People/Self.md", "proposal_mode: append",
                            "proposal_origin: memory_propose_self_update", "proposal_base_hash: " + expected_base, "status: draft")
                frontmatter = raw.split("---\n", 2)[1] if raw.startswith("---\n") and raw.count("---\n") >= 2 else ""
                metadata = all(frontmatter.splitlines().count(line) == 1 for line in required)
                exact_patch = "```markdown\n" + patches[key] + "\n```" in raw
                valid = (not result["is_error"] and payload.get("ok") is True and payload.get("policy") == "proposal_only"
                         and payload.get("section") == key and payload.get("base_digest") == expected_base and payload.get("mutated_self") is False
                         and plain and metadata and exact_patch)
                rows.append({"section": key, "valid": valid, "result": result, "expected_base_digest": expected_base,
                             "plain_contained_proposal": plain, "canonical_metadata_matches": metadata, "literal_patch_present": exact_patch,
                             "proposal_sha256": sha(target) if plain else None, "proposal_text": raw})
        after = inventory(fixture["scope"])
        self.save(label + ".after.json", after)
        self.save(label + ".proposal-observations.json", rows)
        preserved = sha(fixture["vault"] / "People/Self.md") == fixture["identity_before"]
        proposal_after = inventory(fixture["vault"] / "People/Self-Proposals")
        observed = {"targets": rows, "self_bytes_unchanged": preserved, "proposal_inventory": proposal_after,
                    "prior_proposals_unchanged": all(proposal_after.get(key) == value for key, value in fixture["proposals_before"].items())}
        if not duplicate:
            observed["exact_six_draft_files"] = len([value for value in proposal_after.values() if value["kind"] == "file"]) == 6
        passed = fixture["ready"] and preserved and all(row["valid"] for row in rows) and observed["prior_proposals_unchanged"] and observed.get("exact_six_draft_files", True)
        self.add_case(name, "Duplicate markers refuse without proposal writes" if duplicate else "Six persisted append proposals identify the literal canonical target and expected source section digest; Self remains unchanged",
                      observed, passed, [fixture["kind"] + ".before.json", label + ".before.json", label + ".after.json", label + ".proposal-observations.json", *self.evidence(label)])

    def preservation_case(self):
        rows = []
        evidence = []
        for fixture in self.fixtures:
            kind, vault = fixture["kind"], fixture["vault"]
            after, toolkit = inventory(fixture["scope"]), inventory(fixture["toolkit"])
            self.save(kind + ".after.json", after)
            self.save(kind + ".toolkit-after.json", toolkit)
            current = {relative: toolkit.get(relative, {}).get("sha256") for relative in self.sources}
            proposal_after = inventory(vault / "People/Self-Proposals")
            original_notes = {path: row for path, row in fixture["source_before"].items() if path.endswith(".md") and not path.startswith("vault/People/Self-Proposals/")}
            current_notes = {path: row for path, row in after.items() if path.endswith(".md") and not path.startswith("vault/People/Self-Proposals/")}
            rows.append({"kind": kind, "self_before_sha256": fixture["identity_before"], "self_after_sha256": sha(vault / "People/Self.md"),
                         "toolkit_matches_product": current == self.sources, "toolkit_unchanged": toolkit == json.loads((self.directory / (kind + ".toolkit-before.json")).read_text(encoding="utf-8")),
                         "all_other_note_bytes_unchanged": original_notes == current_notes,
                         "prior_proposals_unchanged": all(proposal_after.get(key) == value for key, value in fixture["proposals_before"].items()),
                         "proposal_inventory": proposal_after})
            evidence.extend([kind + ".before.json", kind + ".after.json", kind + ".toolkit-before.json", kind + ".toolkit-after.json"])
        passed = bool(rows) and all(row["self_before_sha256"] == row["self_after_sha256"] and row["toolkit_matches_product"] and row["toolkit_unchanged"] and row["all_other_note_bytes_unchanged"] and row["prior_proposals_unchanged"]
                                    and (row["kind"] not in ("cold", "duplicate") or not row["proposal_inventory"]) for row in rows)
        self.add_case("identity_preserved", "Every synthetic Self and preexisting proposal remains byte-identical; complete toolkit copies match current product; cold and duplicate cases create no proposal",
                      {"fixtures": rows}, passed, evidence)

    def run_journey(self):
        if self.journey == "unknown":
            fixture = self.prepare("cold")
            self.add_case("cold_init", "Name-only CLI initialization and doctor succeed without supplied preferences", fixture["initialization"], fixture["ready"],
                          ["cold-init.command.json", "cold-init.stdout.txt", "cold-init.stderr.txt", "cold-doctor.command.json", "cold-doctor.stdout.txt", "cold-doctor.stderr.txt", "cold.before.json"])
            self.read_case(fixture, "cold_self_get", unknown=True)
            self.read_case(fixture, "cold_session_start", session=True, unknown=True)
            self.read_case(fixture, "restart_self_get", unknown=True)
        else:
            for kind in ("marked", "aliases"):
                fixture = self.prepare(kind)
                self.read_case(fixture, kind + "_self_get")
                self.read_case(fixture, kind + "_session_start", session=True)
                self.proposals_case(fixture, kind + "_proposals")
            fixture = self.prepare("duplicate")
            self.read_case(fixture, "duplicate_self_get", duplicate=True)
            self.read_case(fixture, "duplicate_session_start", session=True, duplicate=True)
            self.proposals_case(fixture, "duplicate_proposal", duplicate=True)
        self.preservation_case()

    def finish(self, error=None):
        current = {path.relative_to(ROOT).as_posix(): sha(path) for path in source_files()}
        support = {name: sha(Path(__file__).with_name(name)) for name in self.support}
        stable = current == self.sources and sha(__file__) == self.producer_hash and support == self.support
        after = self.sentinels()
        stopped = bool(self.processes) and all(row["stopped"] and isinstance(row.get("exit_code"), int) for row in self.processes)
        spec = JOURNEYS[self.journey]
        expected_ids = ["identity." + self.journey + "." + case for case in spec["cases"]]
        complete = [row["id"] for row in self.cases] == expected_ids and all(row["verdict"] == "PASS" for row in self.cases)
        passed = error is None and stable and self.before == after and stopped and complete
        if error is not None:
            self.save("execution-error.json", {"error": str(error)})
        report = {"producer": spec["producer"], "producer_sha256": self.producer_hash, "support_sha256": self.support,
                  "source_root": str(ROOT), "revision": getattr(self, "revision", None), "platform": platform.platform(), "python": sys.version,
                  "scope": "source-only CLI initialization and public MCP identity in complete synthetic toolkit copies",
                  "verdict": "PASS" if passed else "FAIL", "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidate": spec["outcome"],
                  "acceptance_credit_awarded": False, "product_hashes": self.sources, "product_hashes_after": current,
                  "product_and_producer_unchanged": stable, "expected_case_ids": expected_ids, "cases": self.cases,
                  "processes": self.processes, "all_started_processes_stopped": stopped,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after,
                                "limitation": "Selected real-vault sentinels only; not an exhaustive filesystem audit"},
                  "limits": ["No installed package, genuine host, or independent owner approval claim", "Proposals are never accepted or applied",
                             "Name-only unknowns and two section layouts are synthetic source cases; no longitudinal or all-writer claim",
                             "Stopped records cover directly launched commands; not an exhaustive descendant audit"],
                  "error": str(error) if error is not None else None}
        report["evidence_files"] = {path.name: sha(path) for path in sorted(self.directory.iterdir()) if path.is_file() and path.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"], "passed": sum(row["verdict"] == "PASS" for row in self.cases), "total": len(expected_ids)}), flush=True)
        return 0 if passed else 1

    def run(self):
        error = None
        try:
            record, stdout, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            if record["exit_code"] != 0:
                raise RuntimeError("Cannot bind source revision")
            self.revision = stdout.strip()
            self.run_journey()
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journey", choices=tuple(JOURNEYS), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Identity source proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return IdentityRun(args.output, args.journey).run()


if __name__ == "__main__":
    raise SystemExit(main())
