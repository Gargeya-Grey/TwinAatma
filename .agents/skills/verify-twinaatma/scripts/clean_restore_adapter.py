"""Independent grader for the clean-device restore journey (extension adapter ``clean-restore``).

The evidence comes from two GitHub-hosted Windows runners and arrives as one bundle that the workflow
attested. This grader trusts none of it until all of these hold: ``gh attestation verify`` accepts the
file for this repository and the clean-device-restore workflow and its signed claims name the bundle's
commit and run; the commit equals the local ``git rev-parse HEAD``; the product, toolkit, scorer, adapter,
producer and support hashes equal the local ones (CRLF folded to LF); the runners were GitHub-hosted
Windows machines; the digest of the graded rows still matches; and every cell carries the frozen case
list with the frozen wording and a verdict that follows from its own observed values. A complete valid
failure returns FAIL. PASS needs every case in both the wheel and the executable cell.

It never awards another scope: the one check it returns is ``port.clean_device_restore`` with the scope
``clean_device``. It does not regrade the raw evidence, which lives on the runner (the producer's pure
``evaluate`` graded it there); the raw reports stay retained as run artifacts and by hash in the bundle.
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ci_graded as ci  # noqa: E402  (helpers reused unchanged: hashing, binding, gh boundary)
import clean_restore as producer  # noqa: E402  (frozen case list and wording)

CHECK = "port.clean_device_restore"
SCOPE = "clean_device"
REPOSITORY = ci.REPOSITORY
WORKFLOW = ".github/workflows/clean-device-restore.yml"
EXPECTED = "A clean-device restore preserves content and reconnects the supported host with explicit operational dependencies."
FALSE_IS_GOOD = {"timed_out"}
VERDICTS = ("PASS", "FAIL")


def verify_attestation(path, repository=REPOSITORY):
    """Run `gh attestation verify` for this workflow and return the signed claims. The token is never printed."""
    env = ci.gh_environment(repository)
    command = ["gh", "attestation", "verify", str(path), "--repo", repository,
               "--signer-workflow", repository + "/" + WORKFLOW, "--format", "json"]
    done = ci.run_gh(command, env)
    secret = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or "\0"
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").replace(secret, "***").strip().splitlines()
        raise ValueError("Attestation verification failed: " + (detail[-1] if detail else "no output"))
    try:
        claims = []
        for item in json.loads(done.stdout):
            certificate = item["verificationResult"]["signature"]["certificate"]
            claims.append({key: certificate.get(key) for key in (
                "sourceRepositoryDigest", "sourceRepositoryURI", "runInvocationURI", "buildSignerURI",
                "sourceRepositoryRef", "runnerEnvironment")})
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("Attestation verification returned an unreadable result") from error
    if not claims:
        raise ValueError("Attestation verification returned no attestation")
    return claims


def check_binding(bundle, local, claims, repository=REPOSITORY):
    binding = bundle.get("binding")
    ci.require(isinstance(binding, dict), "Bundle has no binding")
    ci.require(binding.get("repository") == repository, "Bundle names another repository")
    ci.require(binding.get("commit") == local["commit"], "Bundle commit differs from this checkout's HEAD")
    for key in ("product_hashes_lf", "toolkit_hashes_lf"):
        ci.require(binding.get(key) == local[key], "Bundle product hashes differ from this checkout (stale or edited product)")
    for key in ("scorer_sha256_lf", "adapter_requirements_sha256_lf", "rubric_sha256"):
        ci.require(binding.get(key) == local[key], "Bundle was graded by a different scorer, adapter or rubric: " + key)
    ci.require(binding.get("producer_sha256_lf") == ci.lf_sha(Path(producer.__file__)), "Bundle was produced by a different clean-restore producer")
    ci.require(binding.get("adapter_sha256_lf") == ci.lf_sha(__file__), "Bundle names a different clean-restore adapter")
    ci.require(binding.get("support_sha256_lf") == {name: ci.lf_sha(HERE / name) for name in producer.SUPPORT},
               "Bundle was produced with different support scripts")
    for key in ("run_id", "run_attempt"):
        ci.require(isinstance(binding.get(key), str) and binding[key].isdigit(), "Bundle lacks its " + key)
    ci.require(binding.get("runner_environment") == "github-hosted", "The restore runner was not GitHub-hosted")
    ci.require(binding.get("platform", {}).get("system") == "Windows", "The restore runner was not a Windows machine")
    run = "/actions/runs/{}/attempts/{}".format(binding["run_id"], binding["run_attempt"])
    suffix = "/" + repository.lower()
    matching = [claim for claim in claims
                if claim.get("sourceRepositoryDigest") == binding["commit"]
                and str(claim.get("sourceRepositoryURI", "")).lower().endswith(suffix)
                and run in str(claim.get("runInvocationURI", ""))
                and WORKFLOW in str(claim.get("buildSignerURI", ""))
                and claim.get("runnerEnvironment") == "github-hosted"]
    ci.require(matching, "Signed attestation does not match the bundle's commit, run and workflow")
    return binding


def row_verdict(row):
    """What a case row's own observed values say. Every boolean is a required condition."""
    observed = row["observed"]
    if "error" in observed:
        return "FAIL"
    flags = {key: value for key, value in observed.items() if isinstance(value, bool)}
    if not flags:
        return "FAIL"
    good = all(value is False if key in FALSE_IS_GOOD else value is True for key, value in flags.items())
    return "PASS" if good else "FAIL"


def check_cell(kind, cell, binding):
    ci.require(isinstance(cell, dict) and cell.get("cell") == ["Windows", kind], "Cell identity is wrong: " + kind)
    cases = cell.get("cases")
    ci.require(isinstance(cases, list) and [row.get("id") for row in cases if isinstance(row, dict)] == list(producer.CASE_IDS),
               "Cases are missing, extra, duplicated or reordered in the " + kind + " cell")
    for row in cases:
        name = row["id"].partition(".")[2]
        ci.require(set(row) == {"id", "verdict", "expected", "observed", "evidence"}, "Case row has unexpected fields: " + row["id"])
        ci.require(row["verdict"] in VERDICTS, "Case verdict is invalid: " + row["id"])
        ci.require(row["expected"] == producer.EXPECTED[name], "Case wording differs from the frozen text: " + row["id"])
        ci.require(isinstance(row["observed"], dict) and row["observed"], "Case has no observed result: " + row["id"])
        ci.require(row_verdict(row) == row["verdict"], "Case verdict does not follow from its observed values: " + row["id"])
    devices = cell.get("devices", {})
    ci.require(set(devices) == {"origin", "restore"}, "Both devices must be described in the " + kind + " cell")
    for role, device in devices.items():
        ci.require(device.get("github_actions") == "true" and device.get("runner_environment") == "github-hosted"
                   and device.get("run_id") == binding["run_id"] and device.get("role") == role and device.get("kind") == kind
                   and str(device.get("platform", "")).startswith("Windows-"),
                   "The " + role + " device was not a GitHub-hosted Windows runner of this run")
    ci.require(devices["origin"].get("hostname") and devices["origin"].get("hostname") != devices["restore"].get("hostname")
               and devices["origin"].get("runner_name") and devices["origin"].get("runner_name") != devices["restore"].get("runner_name")
               and devices["origin"].get("github_job") != devices["restore"].get("github_job"),
               "Origin and restore must be two different machines")
    install = cell.get("install", {})
    ci.require(set(install) == {"origin", "restore"} and all(
        item.get("kind") == kind and item.get("product_bound") is True and item.get("product_hashes") == binding["product_hashes"]
        for item in install.values()), "Both devices must install this commit's " + kind + " product")
    ci.require(cell.get("frozen_before_first_command") is True, "The case list was not frozen before the first command")
    ci.require(cell.get("origin_processes_stopped") is True and cell.get("restore_processes_stopped") is True,
               "Started processes were not all stopped")
    ci.require(isinstance(cell.get("report_sha256"), str) and ci.HEX64.fullmatch(cell["report_sha256"]), "Cell lacks its report hash")
    computed = "PASS" if (all(row["verdict"] == "PASS" for row in cases) and cell.get("error") is None
                          and cell.get("origin_error") is None) else "FAIL"
    ci.require(cell.get("verdict") == computed, "Cell verdict differs from its recomputed cases")
    return computed


def grade(api, paths, current, *, verify=None):
    paths = [Path(p) for p in paths]
    if len(paths) != 1:
        raise ValueError("Exactly one clean-restore bundle is required")
    path = paths[0]
    raw = path.read_bytes()
    digest = ci.sha256_bytes(raw)
    try:
        bundle = json.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise ValueError("Clean-restore bundle is not JSON: " + str(path)) from error
    ci.require(isinstance(bundle, dict) and bundle.get("schema") == producer.SCHEMA, "Bundle schema is unknown")
    claims = (verify or verify_attestation)(path, REPOSITORY)
    graded = bundle.get("graded")
    ci.require(isinstance(graded, dict) and bundle.get("graded_sha256") == ci.sha256_bytes(ci.canonical(graded).encode()),
               "Bundle rows were altered after grading")
    raw_reports = bundle.get("raw_reports")
    ci.require(isinstance(raw_reports, dict) and raw_reports and all(
        isinstance(k, str) and isinstance(v, str) and ci.HEX64.fullmatch(v) for k, v in raw_reports.items()),
        "Bundle lacks raw report hashes")
    binding = check_binding(bundle, ci.local_binding(api), claims)
    cells = graded.get("cells")
    ci.require(isinstance(cells, dict) and set(cells) == set(producer.KINDS), "Both the wheel and the executable cell are required")
    verdicts = {kind: check_cell(kind, cells[kind], binding) for kind in producer.KINDS}
    failed = {kind: sorted(row["id"] for row in cells[kind]["cases"] if row["verdict"] != "PASS") for kind in producer.KINDS}
    verdict = "PASS" if all(value == "PASS" for value in verdicts.values()) else "FAIL"
    observed = {
        "cell_verdicts": verdicts, "failed_cases": failed, "run_id": binding["run_id"], "run_attempt": binding["run_attempt"],
        "commit": binding["commit"], "workflow": WORKFLOW, "bundle_sha256": digest,
        "devices": {kind: {role: {k: cells[kind]["devices"][role].get(k) for k in ("hostname", "runner_name", "github_job")}
                           for role in ("origin", "restore")} for kind in producer.KINDS},
        "raw_report_count": len(raw_reports)}
    return [{"path": str(path), "report_sha256": digest, "scope": SCOPE, "producer": producer.PRODUCER,
             "checks": {CHECK: {"id": CHECK, "verdict": verdict, "expected": EXPECTED, "observed": observed,
                                "evidence": [path.name]}}}]
