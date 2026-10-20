"""Source decision freshness and attributed lessons in a complete isolated toolkit."""
import argparse
import copy
import json
import os
from pathlib import Path
import platform
import signal
import sys

ROOT = next(path for path in Path(__file__).resolve().parents if (path / "knowledgeos/memory.py").is_file())
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
from data_preservation import inventory, sha, source_files
from identity import IdentityRun
from recovery import RecoveryRun, scope_inventory
from graph import GraphRun, TRACE_SOURCE

PRODUCER = "verify-twinaatma.learning-source/v1"
TODAY = "2026-10-19"
LESSON = "For the synthetic Nova pilot, keep a reversible checkpoint before scaling; this is one local observation."
CASE_IDS = ("initial_views", "exact_project_filter", "exact_status_outcome_filter", "busy_edited_decision_current",
            "busy_pending_closed", "busy_timeline_current", "retry_complete", "attributed_completed_lesson",
            "pending_lesson_refused", "nondecision_lesson_refused", "missing_lesson_refused", "identity_and_sources_preserved")
DECISIONS = {
    "Decisions/NovaPending.md": {"title": "Synthetic Nova pilot", "status": "active", "project": "Nova", "outcome_status": "pending", "review_after": "2000-01-01", "lesson": ""},
    "Decisions/NovaComplete.md": {"title": "Synthetic Nova checkpoint", "status": "archived", "project": "Nova", "outcome_status": "confirmed", "review_after": "", "lesson": LESSON},
    "Decisions/NovaNoLesson.md": {"title": "Synthetic Nova unassessed", "status": "archived", "project": "Nova", "outcome_status": "confirmed", "review_after": "", "lesson": ""},
    "Decisions/SupernovaPending.md": {"title": "Synthetic Supernova pilot", "status": "active", "project": "Supernova", "outcome_status": "pending", "review_after": "2000-01-02", "lesson": "This premature lesson must not become a proposal."},
    "Decisions/NovaInvalidated.md": {"title": "Synthetic Nova rejected route", "status": "archived", "project": "Nova", "outcome_status": "invalidated", "review_after": "", "lesson": "One local route failed; no general identity inference follows."},
}
EDITED = dict(DECISIONS["Decisions/NovaPending.md"], title="Synthetic Nova resolved externally", status="archived", project="Orion", outcome_status="confirmed", lesson="This external local outcome is now closed.")
FRESH = {"title": "Synthetic fresh Orion pilot", "status": "active", "project": "Orion", "outcome_status": "pending", "review_after": "2000-01-03", "lesson": ""}
DISTRACTOR = {"title": "Synthetic nondecision", "status": "active", "project": "Nova", "outcome_status": "confirmed", "review_after": "", "lesson": "A concept is not a decision and cannot justify a lesson proposal."}
FIXTURE_PATHS = {*DECISIONS, "Decisions/FreshOrion.md", "Concepts/LearningNondecision.md", "Concepts/LearningOld.md"}


def note(relative, values, kind="decision", date=TODAY):
    lines = ["---", "type: " + kind, "title: " + values["title"], "description: Frozen synthetic learning acceptance evidence", "schema: knowledgeos-v0.3", "created: " + date, "updated: " + date, "tags: [synthetic, learning731]", "id: kos:" + kind + ":learning731-" + Path(relative).stem.lower()]
    lines += [key + ": " + json.dumps(value) for key, value in values.items() if key != "title"]
    return ("\n".join(lines) + "\n---\n# " + values["title"] + "\nSynthetic source record. No asserted owner identity.\n").encode()


def expected_rows(registry, fields):
    return {path: {key: values[key] for key in fields} for path, values in registry.items()}


def view_observation(result, bucket, expected, frozen=False, synthetic_only=False):
    payload = result.get("payload") if isinstance(result, dict) else None
    rows = payload.get(bucket) if isinstance(payload, dict) else None
    values = {}
    duplicates = False
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                continue
            if synthetic_only and row["path"] not in FIXTURE_PATHS:
                continue
            duplicates = duplicates or row["path"] in values
            values[row["path"]] = row
    matching = isinstance(rows, list) and set(values) == set(expected) and not duplicates
    for path, fields in expected.items():
        matching = matching and all(values.get(path, {}).get(key) == value for key, value in fields.items())
    complete = isinstance(payload, dict) and not payload.get("index_frozen")
    disclosed = isinstance(payload, dict) and payload.get("index_frozen") is True and isinstance(payload.get("index_frozen_note"), str) and "may be missing" in payload["index_frozen_note"]
    count = isinstance(rows, list) and payload.get("count") == len(rows)
    valid = result.get("is_error") is False and matching and count and (disclosed if frozen else complete)
    return {"valid": valid, "literal_rows_match": matching, "reported_count_matches_rows": count,
            "completeness_disclosed": disclosed, "expected_rows": expected, "observed_rows": values, "result": result}


def refusal_observation(result, diagnostic, path):
    payload = result.get("payload") if isinstance(result, dict) else None
    valid = result.get("is_error") is True and isinstance(payload, dict) and payload.get("error") == diagnostic and payload.get("path") == path
    return {"valid": valid, "result": result, "expected_error": diagnostic, "expected_path": path}


def lesson_observation(result, proposal_text, source_text, open_result):
    payload = result.get("payload") if isinstance(result, dict) else None
    opened = open_result.get("payload") if isinstance(open_result, dict) else None
    row = payload if isinstance(payload, dict) else {}
    link = "[Synthetic Nova checkpoint](Decisions/NovaComplete.md)"
    uncertainty = "This single recorded outcome does not establish a general belief; review before adopting."
    source = "Decision outcome 'confirmed' records this lesson. Source: Decisions/NovaComplete.md."
    literal = isinstance(proposal_text, str) and link in proposal_text and LESSON in proposal_text and uncertainty in proposal_text and source in proposal_text
    no_overreach = literal and proposal_text.count(LESSON) == 1 and "proposal_section: heuristics" in proposal_text and "proposal_mode: append" in proposal_text and "proposal_target: People/Self.md" in proposal_text and "status: draft" in proposal_text
    evidence = isinstance(source_text, str) and LESSON in source_text and "outcome_status: \"confirmed\"" in source_text and "type: decision" in source_text
    open_rows = opened.get("open") if isinstance(opened, dict) else None
    ledger_backed = isinstance(open_rows, list) and len(open_rows) == 1 and open_rows[0].get("path") == row.get("proposal_path") and open_rows[0].get("id") == row.get("proposal_id") and open_rows[0].get("status") == "draft"
    valid = result.get("is_error") is False and row.get("ok") is True and row.get("policy") == "proposal_only" and row.get("mutated_self") is False and row.get("section") == "heuristics" and no_overreach and evidence and open_result.get("is_error") is False and ledger_backed
    return {"valid": valid, "literal_source_link_and_uncertainty": literal, "local_scope_preserved": no_overreach,
            "actual_completed_source_matches": evidence, "listed_as_one_trusted_draft": ledger_backed,
            "result": result, "open_result": open_result}


class LearningRun(IdentityRun):
    def __init__(self, output):
        super().__init__(output, "unknown")
        self.producer_hash = sha(__file__)
        self.support = {name: sha(SCRIPTS / name) for name in ("data_preservation.py", "identity.py", "recovery.py", "graph.py")}
        self.holders = []
        self.trace_directory = self.directory / "child-traces"
        self.trace_directory.mkdir()
        self.tracer = self.directory / "tracer/sitecustomize.py"
        self.tracer.parent.mkdir()
        self.tracer.write_text(TRACE_SOURCE, encoding="utf-8")
        self.trace_hash = sha(self.tracer)
        self.fixture = None
        self.save("frozen-expectations.json", {"producer": PRODUCER, "case_ids": CASE_IDS, "decisions": DECISIONS,
                  "external_edit": EDITED, "new_during_freeze": FRESH, "nondecision": DISTRACTOR,
                  "date": TODAY, "old_excluded_date": "2000-01-01", "lesson": LESSON, "timeline_fixture_paths": sorted(FIXTURE_PATHS),
                  "project_filter_expectation": "Nova identifies only project Nova, case insensitive; Supernova is a distinct project. Public tool description promises a project filter and does not advertise substring matching.",
                  "frozen_before_product_observation": True, "product_hashes": self.sources})

    def activate(self, fixture):
        super().activate(fixture)
        self.env["KNOWLEDGEOS_VAULT"] = str(fixture["vault"])
        self.env["PYTHONPATH"] = str(self.tracer.parent) + os.pathsep + self.env["PYTHONPATH"]
        self.env["TWIN_GRAPH_TRACE_DIR"] = str(self.trace_directory)

    rebuild = RecoveryRun.rebuild
    hold = RecoveryRun.hold
    stop_holder = RecoveryRun.stop_holder
    evidence = RecoveryRun.evidence
    process_observation = GraphRun.process_observation

    def add(self, name, expected, observed, passed, labels):
        self.cases.append({"id": "learning." + name, "outcome": "LEARNING.attributed_lessons" if name in CASE_IDS[7:11] else "LEARNING.decision_views",
                           "expected": expected, "observed": observed, "verdict": "PASS" if passed else "FAIL", "evidence": ["frozen-expectations.json", *self.evidence(*labels)]})
        print(self.cases[-1]["verdict"] + " learning." + name, flush=True)

    def run_journey(self):
        fixture = self.prepare("cold")
        self.fixture = fixture
        vault = fixture["vault"]
        for relative, values in DECISIONS.items():
            target = vault / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(note(relative, values))
        (vault / "Concepts/LearningNondecision.md").write_bytes(note("Concepts/LearningNondecision.md", DISTRACTOR, "concept"))
        (vault / "Concepts/LearningOld.md").write_bytes(note("Concepts/LearningOld.md", DISTRACTOR, "concept", "2000-01-01"))
        self.scope_before = scope_inventory(fixture["scope"])
        self.save("learning.before.json", self.scope_before)
        all_calls = [("memory_decisions", {}), ("memory_pending_outcomes", {}), ("memory_decisions", {"outcome_status": "confirmed"}), ("memory_timeline", {"days": 365, "limit": 100})]
        initial = self.rpc("initial", fixture, all_calls)
        fields = ("title", "type", "status", "project", "outcome_status", "lesson", "updated")
        all_expected = expected_rows({p: dict(v, type="decision", updated=TODAY) for p, v in DECISIONS.items()}, fields)
        pending_expected = expected_rows({p: dict(v, type="decision", updated=TODAY, overdue=True, awaiting=True) for p, v in DECISIONS.items() if v["outcome_status"] == "pending"}, ("title", "type", "outcome_status", "lesson", "updated", "overdue", "awaiting"))
        confirmed = {p: v for p, v in all_expected.items() if v["outcome_status"] == "confirmed"}
        timeline_values = dict(DECISIONS, **{"Concepts/LearningNondecision.md": DISTRACTOR})
        timeline_expected = expected_rows({p: dict(v, type="decision" if p.startswith("Decisions/") else "concept", updated=TODAY) for p, v in timeline_values.items()}, ("title", "type", "status", "updated"))
        initial_observed = {"all": view_observation(initial[0], "decisions", all_expected), "pending": view_observation(initial[1], "outcomes", pending_expected), "closed": view_observation(initial[2], "decisions", confirmed), "timeline": view_observation(initial[3], "notes", timeline_expected, synthetic_only=True)}
        self.add("initial_views", "Five attributed decisions, two pending and two confirmed outcomes; the timeline contains all six current synthetic sources and excludes the old synthetic source. Other legitimate initialized notes are retained in the full payload", initial_observed, all(v["valid"] for v in initial_observed.values()), ["initial", "learning.before", "cold-init", "cold-doctor"])
        filters = self.rpc("filters", fixture, [("memory_decisions", {"project": "nOvA"}), ("memory_decisions", {"status": "active", "outcome_status": "pending"})])
        observed = view_observation(filters[0], "decisions", {p: v for p, v in all_expected.items() if v["project"] == "Nova"})
        self.add("exact_project_filter", "The project filter nOvA includes four Nova decisions and excludes the separate Supernova project", observed, observed["valid"], ["filters"])
        observed = view_observation(filters[1], "decisions", {p: v for p, v in all_expected.items() if v["status"] == "active" and v["outcome_status"] == "pending"})
        self.add("exact_status_outcome_filter", "Combined active/pending filters include both pending decisions and exclude every archived or closed decision", observed, observed["valid"], ["filters"])
        holder = self.hold("busy-sqlite-holder", fixture, "sqlite")
        try:
            (vault / "Decisions/NovaPending.md").write_bytes(note("Decisions/NovaPending.md", EDITED))
            (vault / "Decisions/FreshOrion.md").write_bytes(note("Decisions/FreshOrion.md", FRESH))
            self.save("busy-editor.inventory.json", scope_inventory(fixture["scope"]))
            busy = self.rpc("busy", fixture, [("memory_decisions", {"project": "Orion", "status": "archived", "outcome_status": "confirmed"}), ("memory_pending_outcomes", {}), ("memory_timeline", {"days": 365, "limit": 100})])
            alive = holder["process"].poll() is None
            edited_expected = expected_rows({"Decisions/NovaPending.md": dict(EDITED, type="decision", updated=TODAY)}, fields)
            observed = view_observation(busy[0], "decisions", edited_expected, frozen=True)
            observed["native_holder_alive_during"] = alive
            self.add("busy_edited_decision_current", "Under a live SQLite BEGIN IMMEDIATE holder, the moved/closed decision is attributed to Orion with current metadata and explicit incompleteness", observed, observed["valid"] and alive, ["busy", "busy-sqlite-holder", "busy-editor"])
            observed = view_observation(busy[1], "outcomes", {"Decisions/SupernovaPending.md": pending_expected["Decisions/SupernovaPending.md"]}, frozen=True)
            observed["native_holder_alive_during"] = alive
            self.add("busy_pending_closed", "The externally completed decision is absent from pending, the existing Supernova pending source remains, and incompleteness is disclosed for the new unindexed note", observed, observed["valid"] and alive, ["busy", "busy-sqlite-holder"])
            busy_timeline_expected = copy.deepcopy(timeline_expected)
            busy_timeline_expected["Decisions/NovaPending.md"] = {"title": EDITED["title"], "type": "decision", "status": "archived", "updated": TODAY}
            observed = view_observation(busy[2], "notes", busy_timeline_expected, frozen=True, synthetic_only=True)
            observed["native_holder_alive_during"] = alive
            self.add("busy_timeline_current", "The current timeline attributes the edited title/status to the original source, preserves other current sources and admits possible omissions", observed, observed["valid"] and alive, ["busy", "busy-sqlite-holder"])
        finally:
            self.stop_holder(holder)
        retried = self.rpc("retry", fixture, [("memory_decisions", {"project": "Orion"}), ("memory_pending_outcomes", {}), ("memory_timeline", {"days": 365, "limit": 100})])
        orion_expected = dict(edited_expected, **expected_rows({"Decisions/FreshOrion.md": dict(FRESH, type="decision", updated=TODAY)}, fields))
        pending_retry = dict({"Decisions/SupernovaPending.md": pending_expected["Decisions/SupernovaPending.md"]}, **expected_rows({"Decisions/FreshOrion.md": dict(FRESH, type="decision", updated=TODAY, overdue=True, awaiting=True)}, ("title", "type", "outcome_status", "lesson", "updated", "overdue", "awaiting")))
        retry_timeline = dict(busy_timeline_expected, **{"Decisions/FreshOrion.md": {"title": FRESH["title"], "type": "decision", "status": "active", "updated": TODAY}})
        observed = {"decisions": view_observation(retried[0], "decisions", orion_expected), "pending": view_observation(retried[1], "outcomes", pending_retry), "timeline": view_observation(retried[2], "notes", retry_timeline, synthetic_only=True), "holder_stopped": holder["tracked"]["stopped"]}
        self.add("retry_complete", "Unchanged public reads after holder release discover the newly added Orion source in all three views without a human rebuild or frozen flag", observed, observed["holder_stopped"] and all(observed[k]["valid"] for k in ("decisions", "pending", "timeline")), ["retry", "busy-sqlite-holder"])
        lessons = self.rpc("lessons", fixture, [("memory_propose_from_lesson", {"path_or_id": "Decisions/NovaComplete.md"}), ("memory_list_self_proposals", {}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/SupernovaPending.md"}), ("memory_propose_from_lesson", {"path_or_id": "Concepts/LearningNondecision.md"}), ("memory_propose_from_lesson", {"path_or_id": "Decisions/NovaNoLesson.md"})])
        relative = lessons[0].get("payload", {}).get("proposal_path", "")
        path = vault / relative
        contained = bool(relative) and path.is_file() and path.resolve().is_relative_to(vault.resolve()) and not path.is_symlink() and path.stat().st_nlink == 1
        proposal_text = path.read_text(encoding="utf-8") if contained else ""
        (self.directory / "observed-proposal.txt").write_text(proposal_text, encoding="utf-8")
        observed = lesson_observation(lessons[0], proposal_text, (vault / "Decisions/NovaComplete.md").read_text(encoding="utf-8"), lessons[1])
        observed["plain_contained_proposal"] = contained
        self.add("attributed_completed_lesson", "One ledger-backed draft quotes the completed Nova decision lesson, links its exact source, limits the claim to one recorded outcome, and requires human terminal approval", observed, observed["valid"] and contained and sha(vault / "People/Self.md") == fixture["identity_before"], ["lessons", "observed-proposal"])
        for index, name, diagnostic, relative in ((2, "pending_lesson_refused", "decision outcome must be completed before proposing its lesson", "Decisions/SupernovaPending.md"), (3, "nondecision_lesson_refused", "lesson source must be a decision", "Concepts/LearningNondecision.md"), (4, "missing_lesson_refused", "no lesson found on decision", "Decisions/NovaNoLesson.md")):
            observed = refusal_observation(lessons[index], diagnostic, relative)
            self.add(name, "Protocol refusal names the exact invalid source and creates no identity proposal from it", observed, observed["valid"], ["lessons"])
        final_list = self.rpc("final-list", fixture, [("memory_list_self_proposals", {})])[0]
        after = scope_inventory(fixture["scope"])
        self.save("learning.after.json", after)
        allowed_edits = {"vault/Decisions/NovaPending.md", "vault/Decisions/FreshOrion.md"}
        protected = {p: row for p, row in self.scope_before.items() if p.startswith("toolkit/") or p.startswith("vault/") and p.endswith(".md") and not p.startswith("vault/People/Self-Proposals/")}
        changed = sorted(p for p, row in protected.items() if p not in allowed_edits and after.get(p) != row)
        expected_draft = final_list.get("payload", {}).get("open", [])
        approvals = [message for requests in self.directory.glob("*.requests.json") for message in json.loads(requests.read_text()) if message.get("params", {}).get("name") == "memory_accept_self_update"]
        unexpected_new = sorted(p for p in after if p.startswith("vault/") and p.endswith(".md") and p not in self.scope_before and p not in allowed_edits and not p.startswith("vault/People/Self-Proposals/"))
        proposals = [p for p, row in after.items() if p.startswith("vault/People/Self-Proposals/") and row.get("kind") == "file"]
        observed = {"self_before_sha256": fixture["identity_before"], "self_after_sha256": sha(vault / "People/Self.md"), "unchanged_toolkit": inventory(fixture["toolkit"]) == json.loads((self.directory / "cold.toolkit-before.json").read_text()), "unexpected_changed_sources": changed, "unexpected_new_notes": unexpected_new, "one_trusted_draft_after_invalid_sources": final_list.get("is_error") is False and len(expected_draft) == 1 and expected_draft[0].get("path") == lessons[0].get("payload", {}).get("proposal_path") and proposals == ["vault/" + lessons[0].get("payload", {}).get("proposal_path", "")], "observed_approval_calls": approvals, "editor_outputs_match_frozen_bytes": (vault / "Decisions/NovaPending.md").read_bytes() == note("Decisions/NovaPending.md", EDITED) and (vault / "Decisions/FreshOrion.md").read_bytes() == note("Decisions/FreshOrion.md", FRESH)}
        self.add("identity_and_sources_preserved", "Every source except the two frozen external-editor changes remains byte-identical, the complete toolkit is unchanged, Self is unchanged and no approval endpoint is invoked", observed, observed["self_before_sha256"] == observed["self_after_sha256"] and observed["unchanged_toolkit"] and not changed and not unexpected_new and not approvals and observed["one_trusted_draft_after_invalid_sources"] and observed["editor_outputs_match_frozen_bytes"], ["final-list", "learning.before", "learning.after", "cold.toolkit-before"])

    def finish(self, error=None):
        for holder in self.holders:
            if not holder["tracked"]["stopped"]:
                self.stop_holder(holder)
        current = {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}
        support = {name: sha(SCRIPTS / name) for name in self.support}
        stable = current == self.sources and sha(__file__) == self.producer_hash and support == self.support and sha(self.tracer) == self.trace_hash
        process = self.process_observation()
        stopped = bool(self.processes) and all(row["stopped"] and isinstance(row.get("exit_code"), int) for row in self.processes) and process["nested_process_tracking_complete"]
        after = self.sentinels()
        complete = [case["id"] for case in self.cases] == ["learning." + name for name in CASE_IDS]
        preserved = self.cases[-1]["verdict"] == "PASS" if complete else False
        outcomes = {}
        for identifier, names in (("LEARNING.decision_views", CASE_IDS[:7]), ("LEARNING.attributed_lessons", CASE_IDS[7:11])):
            selected = [c for c in self.cases if c["id"] in {"learning." + n for n in (*names, CASE_IDS[-1])}]
            outcomes[identifier] = "PASS" if complete and preserved and stable and stopped and self.before == after and error is None and all(c["verdict"] == "PASS" for c in selected) else "FAIL"
        if error is not None:
            self.save("execution-error.json", {"error": str(error), "type": type(error).__name__})
        report = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": self.support, "support_sha256_after": support,
                  "generated_support_sha256": {"tracer/sitecustomize.py": self.trace_hash}, "source_root": str(ROOT), "platform": platform.platform(), "python": sys.version,
                  "verdict": "PASS" if set(outcomes.values()) == {"PASS"} else "FAIL", "fixed_outcome_candidates": outcomes, "acceptance_credit_awarded": False,
                  "ideal_system_verdict": "NOT CHECKED", "case_inventory_complete": complete, "expected_case_ids": ["learning." + n for n in CASE_IDS], "cases": self.cases,
                  "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
                  "processes": self.processes, "all_started_processes_stopped": stopped, **process,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after, "limitation": "Selected real-vault sentinels only; not an exhaustive filesystem audit"},
                  "error": str(error) if error else None,
                  "limits": ["Source CLI/MCP only, complete synthetic toolkit copy; no installed artifact, host chat, human approval, privacy or cumulative54 credit", "Project precision case explicitly expects exact case-insensitive project membership; public API currently advertises an unspecified project filter", "Only a single recorded outcome supports the lesson; it establishes no general belief", "Tracer covers subprocess.Popen descendants only; no native process-spawn audit", "All proposals remain drafts; no approve or accept command is invoked"]}
        report["evidence_files"] = {p.relative_to(self.directory).as_posix(): sha(p) for p in self.directory.rglob("*") if p.is_file() and not p.is_relative_to(self.directory / "fixtures") and p.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "outcomes": outcomes, "passed": sum(c["verdict"] == "PASS" for c in self.cases), "total": len(CASE_IDS)}), flush=True)
        return 0 if report["verdict"] == "PASS" else 1

    def run(self):
        error = None
        try:
            self.run_journey()
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Learning source proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return LearningRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
