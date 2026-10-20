"""Prove public memory searches exclude toolkit evidence and owned reports."""
import argparse
import json
import platform
import sys
from pathlib import Path

from data_preservation import NOTES, ROOT, inventory, sha
from generated_writers import GeneratedRun, WRITERS

PRODUCER = "verify-twinaatma.memory-census/v2"
EXCLUDED = {
    "instructions": ["AGENTS.md", "CLAUDE.md", ".agents/skills/synthetic/SKILL.md", ".claude/guard.md", ".cursor/guard.md", ".codex/guard.md", ".grok/guard.md", ".commandcode/guard.md"],
    "toolkit": ["README.md", "CONTRIBUTING.md", "docs/guide.md", "knowledgeos/manual.md", "scripts/manual.md", "build/clone.md", "dist/clone.md", "Templates/t-belief.md"],
    "fixtures": ["work/.knowledgeos/probe/People/Self.md", "outputs/proof.md", "tests/fixtures/People/Self.md", "fixtures/fake.md", ".knowledgeos/case/People/Self.md"],
}
PERSONAL = {"MOCs/Personal.md": "CensusPersonalMapMarker", "Research/Synthesis/personal.md": "CensusPersonalSynthesisMarker"}
GENERATED_QUERIES = ("Weekly Synthesis Draft", "Learning Trajectory", "Weekly Intelligence Brief", "Stale Projects", "Orphan Notes", "Belief Reviews", "Emerging Themes", "Tensions", "Experiments Dashboard", "Outcomes Dashboard")


def result_paths(value):
    if not isinstance(value, dict) or not isinstance(value.get("ranked"), list):
        raise ValueError("A successful public search needs ranked results")
    return sorted({row["path"] for rows in value.values() if isinstance(rows, list) for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)})


def query_code(queries):
    return ("from knowledgeos.memory import MemoryAPI\nfrom knowledgeos.indexer import iter_markdown\nfrom pathlib import Path\nimport json\n"
            "api=MemoryAPI('.')\n"
            f"queries={queries!r}\n"
            "print(json.dumps({'probes':{q:api.search(q, limit=50) for q in queries},'census':[p.relative_to(Path.cwd()).as_posix() for p in iter_markdown(Path.cwd())]}))")


class CensusRun(GeneratedRun):
    def run(self):
        self.producer_hash = sha(__file__)
        support = {name: sha(Path(__file__).with_name(name)) for name in ("data_preservation.py", "generated_writers.py")}
        error = None
        revision = ""
        try:
            _, revision, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            scope, vault, outside = self.fixture("c")
            self.save("toolkit-copy.before.json", inventory(scope))
            markers = {}
            for group, relatives in EXCLUDED.items():
                markers[group] = {}
                for index, relative in enumerate(relatives):
                    marker = "CensusExcluded" + group.title() + str(index) + "Marker"
                    path = vault / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("ab") as stream:
                        stream.write(("\n# " + marker + "\n").encode())
                    markers[group][relative] = marker
            for relative, marker in PERSONAL.items():
                path = vault / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("---\ntype: moc\ntags: [generated]\n---\n# " + marker + "\nPersonal authored evidence.\n").encode())
            before = inventory(scope)
            self.save("census.before.json", before)
            self.index("census", vault)
            generated = []
            import datetime
            for writer, definition in WRITERS.items():
                record, _, stderr = self.invoke("census-write-" + writer, vault, definition["operation"])
                if record["exit_code"] != 0:
                    raise RuntimeError("Public writer failed during census proof: " + stderr)
                generated.extend(value.format(today=datetime.date.today().isoformat()) for value in definition["outputs"])
            queries = [marker for values in markers.values() for marker in values.values()] + list(PERSONAL.values()) + list(GENERATED_QUERIES)
            record, output, _ = self.invoke("census-search", vault, query_code(queries))
            if record["exit_code"] != 0 or record["error"]:
                raise RuntimeError("Public census searches failed")
            observed = json.loads(output)
            paths = {query: result_paths(value) for query, value in observed["probes"].items()}
            census = set(observed["census"])
            evidence = ["census-search.command.json", "census-search.stdout.txt", "census-search.stderr.txt", "census.before.json"]
            for group, entries in markers.items():
                details = {relative: {"query": marker, "results": paths[marker], "in_census": relative in census} for relative, marker in entries.items()}
                self.cases.append({"id": "data.census." + group + "_excluded", "verdict": "PASS" if all(not row["results"] and not row["in_census"] for row in details.values()) else "FAIL",
                                   "expected": "Every literal synthetic marker in this excluded source class is absent from public search and the shared note census", "observed": details, "evidence": evidence})
            excluded_generated = not (set(generated) & census) and all(not (set(rows) & set(generated)) for rows in paths.values())
            self.cases.append({"id": "data.census.generated_excluded", "verdict": "PASS" if excluded_generated else "FAIL",
                               "expected": "All ten owned outputs of the six public writers are absent from every public query and shared census", "observed": {"expected_generated": generated, "census": sorted(census), "queries": paths},
                               "evidence": evidence + ["census-write-" + writer + ".command.json" for writer in WRITERS]})
            personal = {relative: {"query": marker, "results": paths[marker], "in_census": relative in census} for relative, marker in PERSONAL.items()}
            self.cases.append({"id": "data.census.personal_preserved", "verdict": "PASS" if all(relative in row["results"] and row["in_census"] for relative, row in personal.items()) else "FAIL",
                               "expected": "User-authored MOC and synthesis notes, including generated tags, remain searchable", "observed": personal, "evidence": evidence})
            edited = generated[0]
            path = vault / edited
            raw = path.read_bytes() + b"\nCensusEditedPersonalMarker\n"
            path.write_bytes(raw)
            record, output, _ = self.invoke("census-edited-search", vault, query_code(["CensusEditedPersonalMarker"]))
            edited_result = json.loads(output) if record["exit_code"] == 0 else {}
            edited_paths = result_paths(edited_result.get("probes", {}).get("CensusEditedPersonalMarker"))
            edited_ok = edited in edited_paths and edited in edited_result.get("census", []) and path.read_bytes() == raw
            self.cases.append({"id": "data.census.edited_generated_preserved", "verdict": "PASS" if edited_ok else "FAIL",
                               "expected": "A user-edited generated report becomes personal evidence and remains byte-identical through search", "observed": {"path": edited, "results": edited_paths, "bytes_unchanged": path.read_bytes() == raw},
                               "evidence": ["census-edited-search.command.json", "census-edited-search.stdout.txt", "census-edited-search.stderr.txt"]})
            identity = {relative: {"expected_sha256": __import__('hashlib').sha256(content).hexdigest(), "actual_sha256": sha(vault / relative)} for relative, content in NOTES.items() if relative.startswith("People/")}
            self.save("census.after.json", inventory(scope))
            self.cases.append({"id": "data.census.identity_unchanged", "verdict": "PASS" if all(row["expected_sha256"] == row["actual_sha256"] for row in identity.values()) else "FAIL",
                               "expected": "Self and pending/rejected proposal bytes remain unchanged throughout indexing and generation", "observed": identity,
                               "evidence": ["census.before.json", "census.after.json", "census-search.command.json", "census-edited-search.command.json"]})
        except Exception as caught:
            error = str(caught)
        current = {path.relative_to(ROOT).as_posix(): sha(path) for path in self.inputs}
        after = self.sentinels()
        stable = current == self.sources and self.producer_hash == sha(__file__) and support == {name: sha(Path(__file__).with_name(name)) for name in support}
        stopped = bool(self.processes) and all(row["stopped"] for row in self.processes)
        passed = len(self.cases) == 7 and all(row["verdict"] == "PASS" for row in self.cases) and stable and stopped and self.before == after and error is None
        result = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": support, "platform": platform.platform(), "python": sys.version,
                  "toolkit_copy_evidence": "toolkit-copy.before.json", "scope": "source-only public searches and shared census in a complete synthetic toolkit copy", "revision": revision.strip(),
                  "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
                  "cases": self.cases, "verdict": "PASS" if passed else "FAIL", "processes": self.processes, "all_started_processes_stopped": stopped,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after}, "error": error,
                  "evidence_files": {path.name: sha(path) for path in self.directory.iterdir() if path.is_file()},
                  "limits": ["Source-only public API evidence; no installed host or human approval claim", "Ownership receipts identify unchanged generated content; edited/unowned personal notes stay searchable", "Selected real-vault sentinels only"]}
        self.save("report.json", result)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": result["verdict"], "passed": sum(row["verdict"] == "PASS" for row in self.cases), "total": 7}))
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return CensusRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
