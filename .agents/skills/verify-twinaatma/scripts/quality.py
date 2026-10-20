"""Measure frozen source retrieval labels through actual startup MCP contexts."""
import argparse
from collections import Counter
import datetime
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import subprocess
import sys
import time

from data_preservation import DataRun, ROOT, inventory, sha

PRODUCER = "verify-twinaatma.quality/v1"
CORPUS = ROOT / "tests/fixtures/quality-v1.json"
CORPUS_SHA256 = "787de4674bb0a51fceee87acb7ee7e9b8872068e1fab8af24de3e729bcbac379"
SPLITS = ("development", "held_out")
REQUIRED_CATEGORIES = {"natural_hint", "paraphrase", "contextual_preference", "changed_fact",
                       "multilingual", "ambiguous_names", "irrelevant_chatter", "unknown",
                       "unsupported_personal_question"}
SELF = ("# Self\n\nSynthetic fixture only. Personal identity is unknown.\n\n"
        "## Operating Heuristics & Rules of Thumb\n<!-- kos:section=heuristics -->\nUnknown.\n\n"
        "## Values Hierarchy\n<!-- kos:section=values -->\nUnknown.\n\n"
        "## Mental Models\n<!-- kos:section=mental_models -->\nUnknown.\n\n"
        "## Anti-Goals\n<!-- kos:section=anti_goals -->\nUnknown.\n\n"
        "## Active Bets\n<!-- kos:section=active_bets -->\nUnknown.\n\n"
        "## Drift Log\n<!-- kos:section=drift_log -->\nNo history.\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def note_path(value):
    require(text(value) and "\\" not in value and ":" not in value
            and not any(ord(char) < 32 for char in value), "Unsafe corpus path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix() == value and path.suffix == ".md"
            and all(part not in (".", "..") and not part.startswith(".") for part in path.parts),
            "Corpus paths must be plain vault-relative Markdown paths")
    require(value != "People/Self.md" and not value.startswith("People/Self-Proposals/")
            and path.parts[0] not in {"knowledgeos", "scripts", "Templates", "work", "outputs", "tests"}
            and value not in {"AGENTS.md", "README.md"}, "Corpus path overlaps protected inputs")
    return value


def validate_corpus(corpus):
    require(isinstance(corpus, dict) and corpus.get("schema_version") == "twinaatma.quality-corpus/v1",
            "Unknown corpus schema")
    require(text(corpus.get("corpus_id")) and corpus.get("frozen_before_product_observation") is True
            and corpus.get("labels_observed_from_product") is False and text(corpus.get("label_provenance")),
            "Corpus must have pre-observation label provenance")
    subject = corpus.get("synthetic_subject", {})
    require(subject.get("all_people_and_projects_are_fictional") is True
            and subject.get("real_person_data") is False, "Only wholly synthetic labels are allowed")
    contract = corpus.get("evaluation_contract", {})
    require(contract.get("fixed_rubric_id") == "twinaatma-ideal-v1"
            and contract.get("fixed_outcome_count") == 54 and contract.get("source_top_k") == 8
            and contract.get("critical_expected_source_target") == 1
            and contract.get("noncritical_expected_source_target") == 0.9, "Acceptance thresholds changed")
    require(contract.get("capture_policy", {}).get("status") == "UNAPPROVED"
            and contract["capture_policy"].get("release_acceptance") == "BLOCKED",
            "An assumed capture policy cannot become release acceptance")
    notes, cases, splits = corpus.get("notes"), corpus.get("cases"), corpus.get("splits")
    require(isinstance(notes, list) and notes and isinstance(cases, list) and len(cases) >= 30,
            "Corpus needs notes and at least 30 cases")
    by_path = {}
    for note in notes:
        require(isinstance(note, dict), "Invalid note")
        path = note_path(note.get("path"))
        require(path.casefold() not in {name.casefold() for name in by_path}, "Duplicate note path")
        content = note.get("content")
        require(text(note.get("title")) and note.get("role") in ("relevant", "distractor")
                and text(content) and "\r" not in content and "\x00" not in content
                and content.endswith("\n"), "Notes require exact nonempty LF text and a known role")
        content.encode("utf-8", errors="strict")
        by_path[path] = note
    require(any(n["role"] == "distractor" for n in notes), "Distractors are mandatory")
    require(isinstance(splits, dict) and set(splits) == set(SPLITS), "Two named splits are required")
    for split in SPLITS:
        require(isinstance(splits[split], list) and splits[split]
                and all(text(item) for item in splits[split])
                and len(set(splits[split])) == len(splits[split]), "Invalid split IDs")
    require(not set(splits[SPLITS[0]]) & set(splits[SPLITS[1]]), "Splits must be disjoint")
    identifiers, categories = set(), set()
    totals = {split: Counter() for split in SPLITS}
    for case in cases:
        require(isinstance(case, dict), "Invalid case")
        identifier, split = case.get("id"), case.get("split")
        require(text(identifier) and re.fullmatch(r"[A-Za-z0-9_-]+", identifier)
                and identifier not in identifiers, "Duplicate or unsafe case ID")
        require(split in SPLITS and identifier in splits[split], "Case and split registry disagree")
        identifiers.add(identifier)
        require(isinstance(case.get("categories"), list) and case["categories"]
                and all(text(item) for item in case["categories"]), "Case categories are required")
        categories.update(case["categories"])
        require(all(text(case.get(key)) for key in ("task_hint", "question", "conversation_input"))
                and type(case.get("critical")) is bool, "Case prompts and critical flag are required")
        require(isinstance(case.get("expected_answer"), dict)
                and text(case["expected_answer"].get("mode"))
                and isinstance(case.get("disallowed_claims"), list) and case["disallowed_claims"]
                and all(text(item) for item in case["disallowed_claims"])
                and isinstance(case.get("expected_capture"), dict)
                and text(case["expected_capture"].get("decision"))
                and text(case["expected_capture"].get("policy_status"))
                and all(isinstance(case["expected_capture"].get(key), list) for key in ("required", "forbidden")),
                "Answer, forbidden-claim and capture labels must be authored first")
        sources = case.get("expected_sources")
        require(isinstance(sources, list), "Expected sources must be a list")
        seen = set()
        totals[split]["cases"] += 1
        totals[split]["empty_source_cases"] += int(not sources)
        for source in sources:
            require(isinstance(source, dict), "Invalid expected source")
            path = source.get("path")
            require(path in by_path and path not in seen and type(source.get("critical")) is bool,
                    "Expected source must name a unique corpus note")
            seen.add(path)
            claims = source.get("claims")
            require(isinstance(claims, list) and claims, "Expected sources need literal claims")
            claim_ids = set()
            for claim in claims:
                require(isinstance(claim, dict) and text(claim.get("id"))
                        and claim["id"] not in claim_ids and text(claim.get("text"))
                        and text(claim.get("quote")) and claim["quote"] in by_path[path]["content"]
                        and text(claim.get("temporal_status")), "Claim must quote its exact source content")
                claim_ids.add(claim["id"])
            kind = "critical" if source["critical"] else "noncritical"
            totals[split][kind + "_sources"] += 1
            if source["critical"]:
                totals[split]["critical_claims"] += len(claims)
    require(identifiers == set(splits[SPLITS[0]]) | set(splits[SPLITS[1]]), "Split IDs must cover every case")
    require(REQUIRED_CATEGORIES <= categories, "Required corpus diversity is missing")
    require(any(not case["expected_sources"] and case["expected_answer"]["mode"] == "honest_unknown"
                for case in cases), "An unsupported personal question must have no expected sources")
    return {"cases": len(cases), "notes": len(notes), "roles": dict(Counter(note["role"] for note in notes)),
            "categories": sorted(categories), "splits": {key: dict(value) for key, value in totals.items()}}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for member in value:
            yield from strings(member)
    elif isinstance(value, dict):
        for member in value.values():
            yield from strings(member)


def source_rows(value, path):
    if isinstance(value, dict):
        if value.get("path") == path:
            yield value
        for member in value.values():
            yield from source_rows(member, path)
    elif isinstance(value, list):
        for member in value:
            yield from source_rows(member, path)


def grade_case(case, payload):
    require(isinstance(payload, dict) and not payload.get("error"), "Startup call did not succeed")
    context = payload.get("context")
    require(isinstance(context, dict) and context.get("task_hint") == case["task_hint"]
            and isinstance(payload.get("session_id"), str) and payload["session_id"],
            "Startup context must retain the literal natural hint and session ID")
    relevant = context.get("relevant")
    require(isinstance(relevant, dict) and isinstance(relevant.get("ranked"), list), "No ranked startup context")
    ranked = relevant["ranked"][:8]
    require(all(isinstance(row, dict) and text(row.get("path")) for row in ranked), "Malformed ranked note")
    paths = [row["path"] for row in ranked]
    require(len(set(paths)) == len(paths), "Ranked startup notes must be unique")
    sources = []
    for source in case["expected_sources"]:
        row = next((item for item in ranked if item["path"] == source["path"]), None)
        quoted_strings = [value for member in source_rows(context, source["path"]) for value in strings(member)] if row is not None else []
        claims = [{"id": claim["id"], "quote": claim["quote"],
                   "available_in_source_context": any(claim["quote"] in value for value in quoted_strings)}
                  for claim in source["claims"]]
        sources.append({"path": source["path"], "critical": source["critical"],
                        "rank": paths.index(source["path"]) + 1 if row is not None else None,
                        "in_first_eight": row is not None, "claims": claims})
    has_sources = bool(sources)
    complete = all(source["in_first_eight"] and (not source["critical"]
                   or all(claim["available_in_source_context"] for claim in source["claims"])) for source in sources)
    return {"id": case["id"], "split": case["split"], "categories": case["categories"],
            "task_hint": case["task_hint"], "verdict": ("PASS" if complete else "FAIL") if has_sources else "NOT APPLICABLE",
            "expected": "All labeled sources occur in the first eight; every critical quote is available in its source row",
            "ranked_paths": paths, "returned_notes": len(paths), "sources": sources,
            "empty_source_case": not has_sources, "expected_answer_mode": case["expected_answer"]["mode"],
            "host_answer_verdict": "NOT CHECKED", "capture_verdict": "NOT CHECKED",
            "labeled_source_precision": {"numerator": sum(row["in_first_eight"] for row in sources),
                                         "denominator": len(paths),
                                         "ratio": sum(row["in_first_eight"] for row in sources) / len(paths) if paths else None}}


def aggregate(rows):
    result = {}
    for split in (*SPLITS, "combined"):
        selected = [row for row in rows if split == "combined" or row["split"] == split]
        sources = [source for row in selected for source in row["sources"]]
        count = {"cases": len(selected), "source_cases": sum(not row["empty_source_case"] for row in selected),
                 "empty_source_cases": sum(row["empty_source_case"] for row in selected),
                 "case_verdicts": dict(Counter(row["verdict"] for row in selected))}
        for critical, name in ((True, "critical_sources"), (False, "noncritical_sources")):
            members = [source for source in sources if source["critical"] is critical]
            numerator = sum(source["in_first_eight"] for source in members)
            count[name] = {"numerator": numerator, "denominator": len(members),
                           "ratio": numerator / len(members) if members else None}
        claims = [claim for source in sources if source["critical"] for claim in source["claims"]]
        count["critical_claims"] = {"numerator": sum(claim["available_in_source_context"] for claim in claims),
                                    "denominator": len(claims)}
        numerator = sum(row["labeled_source_precision"]["numerator"] for row in selected if not row["empty_source_case"])
        denominator = sum(row["returned_notes"] for row in selected if not row["empty_source_case"])
        count["labeled_source_precision"] = {"numerator": numerator, "denominator": denominator,
                                            "ratio": numerator / denominator if denominator else None,
                                            "limitation": "Expected-source labels are not exhaustive semantic relevance labels"}
        critical, noncritical = count["critical_sources"], count["noncritical_sources"]
        count["retrieval_target_met"] = (bool(selected) and critical["denominator"] > 0
            and critical["numerator"] == critical["denominator"]
            and count["critical_claims"]["numerator"] == count["critical_claims"]["denominator"]
            and noncritical["denominator"] > 0 and noncritical["numerator"] * 10 >= noncritical["denominator"] * 9)
        result[split] = count
    return result


class QualityRun(DataRun):
    def __init__(self, output):
        super().__init__(output)
        self.producer_hash = sha(__file__)
        self.support = {"data_preservation.py": sha(Path(__file__).with_name("data_preservation.py"))}
        self.corpus_hash = sha(CORPUS)
        require(self.corpus_hash == CORPUS_SHA256, "Frozen corpus bytes changed; use a newly authored version")
        self.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.corpus_summary = validate_corpus(self.corpus)
        self.expected_notes = {note["path"]: {"sha256": __import__("hashlib").sha256(note["content"].encode("utf-8")).hexdigest(),
                                               "size": len(note["content"].encode("utf-8")), "role": note["role"]}
                               for note in self.corpus["notes"]}
        self.fixtures = {}
        self.prepared = False
        self.binding_checks = []

    def note_inventory(self, vault):
        found = inventory(vault)
        require(all(row.get("kind") == "file" and row.get("links") == 1
                    for name, row in found.items() if name in self.expected_notes), "Frozen corpus notes must be plain unlinked files")
        return {name: {"sha256": row.get("sha256"), "size": row.get("size"),
                       "role": self.expected_notes[name]["role"]} for name, row in found.items() if name in self.expected_notes}

    def verify_notes(self, vault):
        observed = self.note_inventory(vault)
        require(observed == self.expected_notes, "The complete frozen note inventory, including all distractors, must remain present")
        require((vault / "People/Self.md").read_bytes() == SELF.encode("utf-8"), "Synthetic Self bytes changed")
        return observed

    def prepare_fixtures(self):
        for case in self.corpus["cases"]:
            label = case["id"]
            scope = self.directory / "fixtures" / label
            vault = scope / "vault"
            vault.mkdir(parents=True)
            for source in self.inputs:
                destination = vault / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for note in self.corpus["notes"]:
                target = vault / note["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(note["content"].encode("utf-8"))
            (vault / "People/Self.md").write_bytes(SELF.encode("utf-8"))
            before = inventory(vault)
            copied = {name: before.get(name, {}).get("sha256") for name in self.sources}
            require(copied == self.sources, "Copied toolkit differs from frozen product")
            self.save(label + ".before.json", before)
            notes = self.verify_notes(vault)
            self.save(label + ".notes.before.json", notes)
            self.fixtures[label] = vault
        self.save("run-manifest.json", {"frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "frozen_before_first_product_invocation": True, "producer": PRODUCER, "producer_sha256": self.producer_hash,
            "support_sha256": self.support, "corpus_path": CORPUS.relative_to(ROOT).as_posix(),
            "corpus_sha256": self.corpus_hash, "corpus_summary": self.corpus_summary, "product_hashes": self.sources,
            "complete_note_inventory": self.expected_notes, "case_registry": [case["id"] for case in self.corpus["cases"]],
            "fixtures": {label: str(vault) for label, vault in self.fixtures.items()},
            "held_out_status": "Process held out; labels inspectable; output must not tune queries, prompts, ranking or labels",
            "capture_policy_status": "UNAPPROVED", "acceptance_credit_awarded": False})
        self.prepared = True

    def rpc_start(self, label, vault, hint):
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "memory_session_start", "arguments": {"task_hint": hint}}}]
        self.save(label + ".requests.json", requests)
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", str(vault), "--framing", "ndjson"]
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=self.directory, env=self.env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        error = None
        try:
            stdout, stderr = process.communicate("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests), timeout=90)
        except BaseException as caught:
            process.kill()
            stdout, stderr = process.communicate()
            error = str(caught)
            raise
        finally:
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode)
            (self.directory / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8")
            (self.directory / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8")
            self.save(label + ".command.json", {"command": command, "cwd": str(self.directory), "shell": False,
                "vault": str(vault), "state_dir": self.env["KNOWLEDGEOS_STATE_DIR"], "pythonpath": self.env["PYTHONPATH"],
                "pid": process.pid, "exit_code": process.returncode, "stopped": tracked["stopped"],
                "seconds": time.monotonic() - started, "error": error})
        require(process.returncode == 0, "MCP process failed")
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {row["id"]: row for row in responses}
        require(len(responses) == 2 and len(by_id) == 2 and set(by_id) == {1, 2}
                and by_id[1].get("result", {}).get("serverInfo", {}).get("name") == "knowledgeos-memory",
                "MCP response identity or sequence differs")
        result = by_id[2].get("result", {})
        require(not result.get("isError") and len(result.get("content", [])) == 1
                and result["content"][0].get("type") == "text", "Startup RPC failed")
        return json.loads(result["content"][0]["text"])

    def run_case(self, case):
        require(self.prepared, "Freeze manifest and all fixtures before invoking the product")
        label, vault = case["id"], self.fixtures[case["id"]]
        before_notes = self.verify_notes(vault)
        self.env.update(PYTHONPATH=str(vault), KNOWLEDGEOS_VAULT=str(vault),
                        KNOWLEDGEOS_STATE_DIR=str(vault.parent / "gate-state"))
        doctor, _, _ = self.command(label + "-doctor", [sys.executable, "-B", "-P", "-m", "knowledgeos", "doctor", "--vault", str(vault)],
                                     cwd=self.directory, vault=vault)
        require(doctor["exit_code"] == 0 and doctor["error"] is None, "Fresh fixture doctor failed")
        payload = self.rpc_start(label + "-startup", vault, case["task_hint"])
        self.save(label + ".context.json", payload)
        after_notes = self.verify_notes(vault)
        after = inventory(vault)
        self.save(label + ".after.json", after)
        self.save(label + ".notes.after.json", after_notes)
        copied = {name: after.get(name, {}).get("sha256") for name in self.sources}
        unchanged = copied == self.sources and before_notes == after_notes
        self.binding_checks.append({"id": label, "copied_product_unchanged": copied == self.sources,
                                    "all_frozen_notes_unchanged": before_notes == after_notes,
                                    "synthetic_self_unchanged": after.get("People/Self.md", {}).get("sha256")
                                       == __import__("hashlib").sha256(SELF.encode("utf-8")).hexdigest()})
        require(unchanged, "Copied product or corpus changed during observation")
        row = grade_case(case, payload)
        row["evidence"] = [label + suffix for suffix in (".before.json", ".after.json", ".notes.before.json", ".notes.after.json",
            "-doctor.command.json", "-doctor.stdout.txt", "-doctor.stderr.txt", "-startup.requests.json", "-startup.command.json",
            "-startup.stdout.txt", "-startup.stderr.txt", ".context.json")]
        row["observed"] = {"complete_inventory_preserved": unchanged, "literal_hint_used": True,
                           "session_id": payload["session_id"], "fresh_process_and_vault": True}
        self.cases.append(row)
        print(json.dumps({"id": label, "verdict": row["verdict"], "split": row["split"]}), flush=True)

    def finish(self, error=None):
        current = {path.relative_to(ROOT).as_posix(): sha(path) for path in self.inputs}
        after = self.sentinels()
        stable = (current == self.sources and sha(__file__) == self.producer_hash and sha(CORPUS) == self.corpus_hash
                  and self.support == {name: sha(Path(__file__).with_name(name)) for name in self.support})
        stopped = bool(self.processes) and all(row["stopped"] for row in self.processes)
        complete = len(self.cases) == len(self.corpus["cases"])
        metrics = aggregate(self.cases)
        valid_run = error is None and self.prepared and stable and stopped and complete and self.before == after
        retrieval = valid_run and all(metrics[split]["retrieval_target_met"] for split in (*SPLITS, "combined"))
        checks = [{"id": "quality.fixed_corpus", "verdict": "PASS" if valid_run else "FAIL",
                   "expected": "A versioned pre-labeled diverse corpus with at least 30 cases and a held-out split",
                   "observed": self.corpus_summary, "evidence": ["run-manifest.json"]},
                  {"id": "quality.retrieval_target", "verdict": "PASS" if retrieval else "FAIL",
                   "expected": "Every critical source and literal critical claim; at least 90 percent noncritical sources in first eight",
                   "observed": metrics, "evidence": [row["id"] + ".context.json" for row in self.cases]}]
        report = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": self.support,
            "source_root": str(ROOT), "revision": getattr(self, "revision", None), "platform": platform.platform(), "python": sys.version,
            "scope": "evaluation source-only startup MCP retrieval with a frozen synthetic corpus; no host answer judgment",
            "corpus_path": CORPUS.relative_to(ROOT).as_posix(), "corpus_sha256": self.corpus_hash, "corpus_summary": self.corpus_summary,
            "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
            "checks": checks, "cases": self.cases, "metrics": metrics, "binding_checks": self.binding_checks,
            "verdict": "PASS" if valid_run and retrieval else "FAIL", "execution_complete": valid_run,
            "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidates": ["QUALITY.fixed_corpus", "QUALITY.retrieval_target"],
            "acceptance_credit_awarded": False, "processes": self.processes, "all_started_processes_stopped": stopped,
            "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after},
            "capture_policy_status": "UNAPPROVED", "error": str(error) if error is not None else None,
            "limits": ["One deterministic source run per case; no host, package, human approval, correction or representative-week claim",
                       "Empty-source cases are excluded from positive recall denominators; honest-unknown answers remain NOT CHECKED",
                       "Labeled-source precision is not full semantic precision; labels are not exhaustive relevance judgments",
                       "Held-out labels are inspectable by maintainers; held-out outputs must not tune queries, prompts, ranking or labels",
                       "Capture policy is UNAPPROVED; no privacy acceptance", "Selected real-vault sentinels only; no exhaustive filesystem audit"]}
        if error is not None:
            self.save("execution-error.json", {"error": str(error)})
        report["evidence_files"] = {path.name: sha(path) for path in self.directory.iterdir() if path.is_file() and path.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"],
                          "completed": len(self.cases), "total": len(self.corpus["cases"]), "metrics": metrics["combined"]}), flush=True)
        return 0 if report["verdict"] == "PASS" else 1

    def run(self):
        error = None
        try:
            self.prepare_fixtures()
            _, revision, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            self.revision = revision.strip()
            for case in self.corpus["cases"]:
                self.run_case(case)
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Quality proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return QualityRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
