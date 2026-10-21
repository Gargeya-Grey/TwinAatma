"""Independent grader for the Windows signing-state journey (extension adapter ``signing-state``).

It trusts nothing a report claims. Every case is recomputed from the retained evidence files
with the hashed producer's pure ``evaluate``; stale product, producer or support bytes,
altered or linked evidence, changed artifact bytes, unstopped processes and a duplicated or
incomplete matrix cell are refused. A complete, valid failure stays a FAIL.
"""
import contextlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import signing_state as producer  # noqa: E402  (hash-checked against each report before use)

CHECK = "port.missing_signing_state"
REQUIRED_CELLS = {("Windows", "wheel"), ("Windows", "binary")}
EXPECTED = ("Missing signing state refuses old approvals recoverably without silently approving or corrupting identity.")
CONSOLE_STEPS = {"approve-lost-A", "approve-new-A"}
PROCESS_KEYS = {"pid", "role", "stopped", "console", "exit_code", "timed_out"}


@contextlib.contextmanager
def contained_real_paths(api):
    """Let the scorer's retained-path check accept real absolute paths inside this checkout.

    The scorer rewrites any ``W:/AI-Projects/TwinAatma/`` prefix onto its own root. That is
    right for the shared checkout and wrong for a git worktree below it, so a retained file
    in a worktree looks missing. The fallback keeps every other rule: the path must be
    absolute, exist, and resolve inside the scorer's root.
    """
    original = api.retained_path

    def resolve(value):
        try:
            return original(value)
        except ValueError:
            if not isinstance(value, str) or not value or not Path(value).is_absolute():
                raise
            path = Path(value)
            try:
                path.absolute().relative_to(api.ROOT.absolute())
                path.resolve(strict=True).relative_to(api.ROOT.resolve())
            except (ValueError, OSError) as exc:
                raise ValueError("Artifact path is missing or escapes retained workspace") from exc
            return path

    api.retained_path = resolve
    try:
        yield
    finally:
        api.retained_path = original


def evidence_directory(api, path, data):
    names = data.get("evidence_files")
    if not isinstance(names, dict) or not names:
        raise ValueError("Signing-state report needs hashed evidence")
    directory = path.parent
    for name, digest in names.items():
        if not isinstance(name, str) or "/" in name or "\\" in name or name in ("", ".", "..", "report.json"):
            raise ValueError("Signing-state evidence name is not a plain file name: " + str(name))
        if api.sha(api.file_evidence(directory, name)) != digest:
            raise ValueError("Signing-state evidence hash mismatch: " + name)
    actual = {entry.name for entry in directory.iterdir() if entry.is_file() or entry.is_symlink()} - {"report.json"}
    if actual != set(names):
        raise ValueError("Signing-state evidence inventory differs from the report")
    return directory


def bound_artifact(api, data, current, cell):
    artifact = data.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("kind") != cell[1]:
        raise ValueError("Signing-state artifact identity is missing or names another kind")
    artifact_path = api.retained_file(artifact.get("path"))
    if api.sha(artifact_path) != artifact.get("sha256"):
        raise ValueError("Artifact bytes differ from the signing-state report")
    report_path = api.retained_file(artifact.get("report_path"))
    if api.sha(report_path) != artifact.get("report_sha256"):
        raise ValueError("Artifact report differs from the signing-state report")
    checked = api.artifact_report(report_path, current)
    original = api.read_json(report_path)
    if tuple(checked["cell"]) != cell or original.get("verdict") != "PASS":
        raise ValueError("Artifact report is not a passing report for this cell")
    recorded = original.get("artifact", {})
    installation = original.get("installation", {})
    executable = api.retained_file(artifact.get("executable"))
    if (recorded.get("sha256") != artifact["sha256"] or api.retained_file(recorded.get("path")) != artifact_path
            or api.retained_file(installation.get("executable")) != executable
            or api.sha(executable) != artifact.get("executable_sha256")):
        raise ValueError("Signing-state artifact identity differs from the artifact report")
    if data.get("artifact_unchanged") is not True:
        raise ValueError("Artifact bytes changed during observation")
    return artifact


def checked_processes(directory, data):
    processes = data.get("processes")
    if (data.get("all_started_processes_stopped") is not True or not isinstance(processes, list)
            or [row.get("role") for row in processes] != list(producer.STEPS)):
        raise ValueError("Signing-state process inventory is incomplete")
    for row in processes:
        if (set(row) != PROCESS_KEYS or row["stopped"] is not True or type(row["pid"]) is not int
                or type(row["exit_code"]) is not int or type(row["console"]) is not bool or type(row["timed_out"]) is not bool):
            raise ValueError("Signing-state process was not stopped or is not substantiated: " + str(row.get("role")))
        record = producer.Evidence(directory).command(row["role"])
        if (record.get("pid") != row["pid"] or record.get("exit_code") != row["exit_code"] or record.get("stopped") is not True
                or record.get("console") is not row["console"] or record.get("label") != row["role"]):
            raise ValueError("Process record differs from its retained command: " + row["role"])
        if row["console"] != (row["role"] in CONSOLE_STEPS):
            raise ValueError("Approval commands must use the closed pipe or the hidden console exactly as declared")


def checked_plan(directory, data):
    ev = producer.Evidence(directory)
    plan = ev.json("plan.json")
    if plan.get("case_ids") != list(producer.CASE_IDS) or plan.get("steps") != list(producer.STEPS):
        raise ValueError("Frozen case list or step order differs from the producer")
    if data.get("expected_case_ids") != list(producer.CASE_IDS):
        raise ValueError("Report case list differs from the frozen list")
    frozen = plan.get("frozen_at_ns")
    if type(frozen) is not int or any(type(ev.command(step).get("started_ns")) is not int
                                      or ev.command(step)["started_ns"] <= frozen for step in producer.STEPS):
        raise ValueError("Case list was not frozen before the first product call")


def cell_report(api, path, current):
    report_path = api.retained_file(str(Path(path).absolute()))
    data = api.read_json(report_path)
    if data.get("producer") != producer.PRODUCER or data.get("scope") != "artifact":
        raise ValueError("Unsupported signing-state producer or scope")
    script = Path(producer.__file__)
    if data.get("producer_sha256") != api.sha(script):
        raise ValueError("Signing-state producer hash missing or stale")
    if data.get("support_sha256") != {name: api.sha(script.with_name(name)) for name in producer.SUPPORT}:
        raise ValueError("Signing-state support hash missing or stale")
    api.check_product(data, "product_hashes", current)
    api.check_product(data, "product_hashes_after", current)
    if data.get("product_and_producer_unchanged") is not True:
        raise ValueError("Product or producer changed during observation")
    cell = tuple(data.get("cell") or ())
    if cell not in REQUIRED_CELLS or not str(data.get("platform", "")).startswith("Windows-"):
        raise ValueError("Unsupported signing-state matrix cell or platform")
    if data.get("error") is not None:
        raise ValueError("Signing-state run did not complete: " + str(data["error"]))
    isolation = data.get("isolation", {})
    if (not isinstance(isolation.get("before"), dict) or isolation.get("before") != isolation.get("after")
            or isolation.get("selected_sentinels_unchanged") is not True):
        raise ValueError("Signing-state isolation sentinels are absent or changed")
    directory = evidence_directory(api, report_path, data)
    artifact = bound_artifact(api, data, current, cell)
    checked_plan(directory, data)
    checked_processes(directory, data)
    cases = data.get("cases")
    if not isinstance(cases, list) or [row.get("id") for row in cases if isinstance(row, dict)] != list(producer.CASE_IDS):
        raise ValueError("Signing-state cases are missing, extra, duplicated or reordered")
    recomputed = json.loads(json.dumps(producer.evaluate(directory)))
    if recomputed != cases:
        raise ValueError("Reported cases differ from the retained evidence")
    verdict = "PASS" if all(row["verdict"] == "PASS" for row in recomputed) else "FAIL"
    if data.get("verdict") != verdict:
        raise ValueError("Reported verdict differs from the recomputed cases")
    return {"cell": cell, "path": report_path, "report_sha256": api.sha(report_path), "verdict": verdict,
            "cases": {row["id"]: row["verdict"] for row in recomputed}, "evidence": sorted(data["evidence_files"]),
            "artifact": {key: artifact[key] for key in ("kind", "sha256", "report_sha256", "executable_sha256")}}


def grade(api, paths, current):
    with contained_real_paths(api):
        cells = {}
        for path in paths:
            row = cell_report(api, path, current)
            if row["cell"] in cells:
                raise ValueError("Duplicate signing-state matrix cell: " + "/".join(row["cell"]))
            cells[row["cell"]] = row
    complete = set(cells) == REQUIRED_CELLS
    reports = []
    for cell, row in sorted(cells.items()):
        verdict = row["verdict"] if complete or row["verdict"] != "PASS" else "NOT CHECKED"
        observed = {"cell": list(cell), "cell_verdict": row["verdict"], "matrix_complete": complete, "cases": row["cases"],
                    "failed_cases": sorted(case for case, value in row["cases"].items() if value != "PASS"), "artifact": row["artifact"]}
        if verdict != row["verdict"]:
            observed["reason"] = "Both Windows cells are required; one passing cell earns no credit"
        reports.append({"path": str(row["path"]), "report_sha256": row["report_sha256"], "scope": "artifact",
                        "producer": producer.PRODUCER, "cell": list(cell),
                        "checks": {CHECK: {"id": CHECK, "verdict": verdict, "expected": EXPECTED, "observed": observed,
                                           "evidence": ["report.json", *row["evidence"]]}}})
    return reports
