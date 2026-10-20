"""Verify all public generated-report writers in retained synthetic toolkit copies."""
import argparse
import datetime
import json
import os
import platform
import sys
from pathlib import Path

from data_preservation import DataRun, NOTES, ROOT, inventory, operational_metadata_creation, sha

PRODUCER = "verify-twinaatma.generated-writers/v2"
WRITERS = {
    "draft": {"operation": "import runpy; runpy.run_path('scripts/draft_weekly_synthesis.py', run_name='__main__')", "outputs": ["Research/Synthesis/{today}-weekly-draft.md"]},
    "trajectory": {"operation": "from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import learning_trajectory_report; learning_trajectory_report(MemoryAPI('.'))", "outputs": ["Research/Synthesis/{today}-learning-trajectory.md"]},
    "weekly": {"operation": "from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import weekly_intelligence_report; weekly_intelligence_report(MemoryAPI('.'))", "outputs": ["Research/Synthesis/{today}-intelligence-brief.md"]},
    "views": {"operation": "from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import write_intelligence_views; write_intelligence_views(MemoryAPI('.'))", "outputs": ["MOCs/_MOC_Stale_Projects.md", "MOCs/_MOC_Orphans.md", "MOCs/_MOC_Belief_Reviews.md", "MOCs/_MOC_Emerging_Themes.md", "MOCs/_MOC_Tensions.md"]},
    "experiments": {"operation": "import runpy; runpy.run_path('scripts/experiment_dashboard.py', run_name='__main__')", "outputs": ["MOCs/_MOC_Experiments.md"]},
    "outcomes": {"operation": "import runpy; runpy.run_path('scripts/outcomes_dashboard.py', run_name='__main__')", "outputs": ["MOCs/_MOC_Outcomes.md"]},
}
SCENARIOS = ("regenerate", "unowned", "edited", "linked_target", "hardlinked_target", "linked_parent", "receipt_fault", "report_fault")


def excluded(name, prefixes):
    return any(name == prefix or name.startswith(prefix + "/") for prefix in prefixes)


def compare(before, after, allowed=()):
    left = {key: value for key, value in before.items() if not excluded(key, allowed)}
    right = {key: value for key, value in after.items() if not excluded(key, allowed)}
    changed = sorted(key for key in left.keys() | right.keys() if left.get(key) != right.get(key))
    operational = [key for key in operational_metadata_creation(before, after) if key in changed]
    changed = [key for key in changed if key not in operational]
    result = {"unchanged": not changed, "changed": changed}
    if operational:
        result["operational_metadata_created"] = operational
    return result


def report_evidence(vault, outputs):
    rows = {}
    for relative in outputs:
        path = vault / relative
        try:
            raw = path.read_bytes()
            rows[relative] = {"sha256": sha(path), "nonempty": bool(raw), "frontmatter": raw.startswith(b"---\n"),
                              "new_evidence": b"Newly recorded" in raw, "plain": not path.is_symlink() and path.stat().st_nlink == 1}
        except OSError as error:
            rows[relative] = {"error": str(error)}
    return {"outputs": rows, "usable": bool(rows) and all(row.get("nonempty") and row.get("frontmatter") and row.get("plain") for row in rows.values()),
            "source_change_visible": any(row.get("new_evidence") for row in rows.values())}


class GeneratedRun(DataRun):
    def invoke(self, label, vault, operation):
        return self.command(label, [sys.executable, "-B", "-c", operation], cwd=vault, vault=vault)

    def index(self, label, vault):
        record, _, error = self.invoke(label + "-index", vault, "from knowledgeos.indexer import rebuild_index; rebuild_index('.')")
        if record["exit_code"] != 0 or record["error"]:
            raise RuntimeError("Fixture index initialization failed: " + error)

    def changed_sources(self, vault):
        today = datetime.date.today().isoformat()
        for folder, kind in (("Decisions", "decision"), ("Experiments", "experiment"), ("Projects", "project")):
            path = vault / folder / "Changed.md"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes((f"---\ntype: {kind}\ntitle: Newly recorded {kind}\nstatus: active\ncreated: {today}\nupdated: 2020-01-01\ntags: [synthetic]\n---\n# Changed\n").encode())

    def case(self, writer, scenario):
        label = writer + "-" + scenario
        scope, vault, outside = self.fixture("g" + str(len(self.cases)))
        operation = WRITERS[writer]["operation"]
        outputs = [value.format(today=datetime.date.today().isoformat()) for value in WRITERS[writer]["outputs"]]
        first = vault / outputs[0]
        self.index(label, vault)
        needs_prior = scenario in ("regenerate", "edited", "receipt_fault", "report_fault")
        if needs_prior:
            initial, _, error = self.invoke(label + "-initial", vault, operation)
            if initial["exit_code"] != 0 or not report_evidence(vault, outputs)["usable"]:
                raise RuntimeError("Initial public report generation failed: " + error)
        self.changed_sources(vault)
        self.index(label + "-changed", vault)
        try:
            if scenario in ("unowned", "edited"):
                first.parent.mkdir(parents=True, exist_ok=True)
                first.write_bytes(b"USER OWNED REPORT\r\nKeep these bytes.\n")
            elif scenario in ("linked_target", "hardlinked_target"):
                first.parent.mkdir(parents=True, exist_ok=True)
                if scenario == "linked_target":
                    first.symlink_to(outside / "private.md")
                else:
                    os.link(outside / "private.md", first)
            elif scenario == "linked_parent":
                first.parent.parent.mkdir(parents=True, exist_ok=True)
                first.parent.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.cases.append({"id": "data.generated." + label, "verdict": "NOT CHECKED", "expected": "Actual native link/hardlink refusal", "observed": {"error": str(error)}, "evidence": []})
            return
        before = inventory(scope)
        self.save(label + ".before.json", before)
        injected = operation
        if scenario in ("receipt_fault", "report_fault"):
            condition = "'.knowledgeos/generated' in str(destination).replace(chr(92), '/')" if scenario == "receipt_fault" else "str(destination).endswith('.md')"
            injected = ("import os\nfrom unittest.mock import patch\noriginal_replace = os.replace\ndef fail_selected(source, destination):\n"
                        f"    if {condition}:\n        raise OSError('injected {scenario} replacement failure')\n"
                        "    return original_replace(source, destination)\npatch.object(os, 'replace', fail_selected).start()\n" + operation)
        record, stdout, stderr = self.invoke(label, vault, injected)
        after = inventory(scope)
        self.save(label + ".after.json", after)
        permitted = ["vault/" + relative for relative in outputs] + ["vault/.knowledgeos/generated"] if scenario == "regenerate" else []
        if scenario == "report_fault":
            permitted = ["vault/.knowledgeos/generated"]
        derived = ["vault/knowledge_index.db", "vault/.knowledgeos/index-manifest.json"]
        observation = compare(before, after, permitted + derived)
        observation["derived_state_changes"] = [name for name in derived if before.get(name) != after.get(name)]
        observation.update(exit_code=record["exit_code"], fault_injected=scenario not in ("receipt_fault", "report_fault") or "injected " + scenario in stderr,
                           protected_bytes_unchanged=all((vault / relative).read_bytes() == raw for relative, raw in NOTES.items()))
        expected_success = scenario == "regenerate"
        if expected_success:
            observation["reports"] = report_evidence(vault, outputs)
        passed = (not record["error"] and ((record["exit_code"] == 0) if expected_success else (record["exit_code"] != 0 and bool(stderr.strip())))
                  and observation["unchanged"] and observation["protected_bytes_unchanged"] and observation["fault_injected"])
        if expected_success:
            passed = passed and observation["reports"]["usable"] and observation["reports"]["source_change_visible"]
        evidence = [label + suffix for suffix in (".before.json", ".after.json", ".command.json", ".stdout.txt", ".stderr.txt")]
        if scenario in ("receipt_fault", "report_fault", "regenerate"):
            retry, _, _ = self.invoke(label + "-retry", vault, operation)
            reports = report_evidence(vault, outputs)
            retry_after = inventory(scope)
            self.save(label + ".retry.json", retry_after)
            allowed = ["vault/" + relative for relative in outputs] + ["vault/.knowledgeos/generated"]
            observation["retry"] = {"exit_code": retry["exit_code"], "reports": reports, "preservation": compare(before, retry_after, allowed + derived)}
            repeated, _, _ = self.invoke(label + "-repeat", vault, operation)
            repeat_after = inventory(scope)
            self.save(label + ".repeat.json", repeat_after)
            observation["repeat"] = {"exit_code": repeated["exit_code"], "unchanged": compare(retry_after, repeat_after, derived)["unchanged"]}
            passed = passed and retry["exit_code"] == 0 and reports["usable"] and reports["source_change_visible"] and observation["retry"]["preservation"]["unchanged"] and repeated["exit_code"] == 0 and observation["repeat"]["unchanged"]
            evidence += [label + suffix for suffix in (".retry.json", ".repeat.json", "-retry.command.json", "-retry.stdout.txt", "-retry.stderr.txt", "-repeat.command.json", "-repeat.stdout.txt", "-repeat.stderr.txt")]
        self.cases.append({"id": "data.generated." + label, "verdict": "PASS" if passed else "FAIL",
                           "expected": "Public writer preserves complete source/identity and unrelated data; owned reports regenerate; unsafe paths and edits refuse; atomic commit faults preserve prior report and retry converges",
                           "observed": observation, "evidence": evidence})

    def run(self):
        self.producer_hash = sha(__file__)
        support = Path(__file__).with_name("data_preservation.py")
        support_hash = sha(support)
        error = None
        revision = ""
        try:
            _, revision, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            for writer in WRITERS:
                for scenario in SCENARIOS:
                    self.case(writer, scenario)
        except Exception as caught:
            error = str(caught)
        current = {path.relative_to(ROOT).as_posix(): sha(path) for path in self.inputs}
        after = self.sentinels()
        stable = current == self.sources and sha(__file__) == self.producer_hash and sha(support) == support_hash
        stopped = bool(self.processes) and all(row["stopped"] for row in self.processes)
        complete = len(self.cases) == len(WRITERS) * len(SCENARIOS) and all(row["verdict"] == "PASS" for row in self.cases)
        result = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": {support.name: support_hash},
                  "scope": "source-only public generated writers in complete synthetic toolkit copies", "platform": platform.platform(), "python": sys.version,
                  "revision": revision.strip(), "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
                  "verdict": "PASS" if complete and stable and stopped and self.before == after and error is None else "FAIL", "cases": self.cases,
                  "processes": self.processes, "all_started_processes_stopped": stopped,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after}, "error": error,
                  "limits": ["Per-output atomicity; no all-report transaction claim", "Derived index/database may refresh; report/source/identity bytes are independently checked", "No installed, host, independent owner or privacy policy acceptance"],
                  "evidence_files": {path.name: sha(path) for path in self.directory.iterdir() if path.is_file()}}
        self.save("report.json", result)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": result["verdict"], "passed": sum(row["verdict"] == "PASS" for row in self.cases), "total": len(WRITERS) * len(SCENARIOS)}))
        return 0 if result["verdict"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return GeneratedRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
