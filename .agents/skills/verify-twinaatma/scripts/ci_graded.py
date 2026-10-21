"""Natively graded evidence from attested GitHub-hosted runners: build the bundle there, import it here.

Route: each runner runs the unchanged producers, grades its own raw reports with the unchanged grading
functions in acceptance.py and identity_writers_grade.py, and writes one bundle of the normalized report
dictionaries those functions returned. The workflow attests the bundle. The importer refuses a bundle unless
`gh attestation verify` accepts it and every binding below matches this checkout, then hands the rows to
acceptance.snapshot() beside the locally graded rows. A FAIL row stays FAIL. The route never awards host,
human or clean-device outcomes: it only accepts artifact- and source-scoped rows with known check IDs.

Commands (CI): freeze, interpreter, bundle.  Command (laptop): inspect.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = "twinaatma.ci-graded/v1"
REPOSITORY = "Gargeya-Grey/TwinAatma"
WORKFLOW = ".github/workflows/acceptance-evidence.yml"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
MINORS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")
EXPECTED = {
    "Linux": ["artifact-wheel", "artifact-binary", *("hooks-wheel-" + m for m in MINORS), "hooks-binary",
              "recovery-write-faults", "maintenance-hooks", "writers"],
    "Windows": [*("hooks-wheel-" + m for m in MINORS), "hooks-binary"],
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def lf_sha(path):
    """Hash with CRLF folded to LF. Git checks the same commit out as LF or CRLF; the content is the same."""
    return sha256_bytes(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- binding

@contextlib.contextmanager
def _lf_reads():
    original = pathlib.Path.read_bytes

    def read_bytes(self):
        return original(self).replace(b"\r\n", b"\n")
    pathlib.Path.read_bytes = read_bytes
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        pathlib.Path.read_bytes = original
        sys.dont_write_bytecode = previous


def adapter_requirements_hashes(base):
    """Raw hash, as snapshot() records it, plus the same structure rebuilt over LF-folded script bytes."""
    raw = sha256_bytes(json.dumps(base.ADAPTER_REQUIREMENTS, sort_keys=True).encode())
    spec = importlib.util.spec_from_file_location("acceptance_lf_probe", base.__file__)
    probe = importlib.util.module_from_spec(spec)
    with _lf_reads():
        spec.loader.exec_module(probe)
    return raw, sha256_bytes(json.dumps(probe.ADAPTER_REQUIREMENTS, sort_keys=True).encode())


def git_head(root):
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=30)
    head = done.stdout.strip()
    if done.returncode != 0 or not HEX40.fullmatch(head):
        raise ValueError("Cannot read the local git HEAD")
    return head


def local_binding(base):
    """What this checkout is, in the terms a bundle declares. Built the same way on a runner and on the laptop."""
    root = Path(base.ROOT)
    adapter_raw, adapter_lf = adapter_requirements_hashes(base)
    product = base.product_hashes()
    toolkit = base.data_toolkit_hashes()
    return {
        "commit": git_head(root),
        "product_hashes": product,
        "product_hashes_lf": {name: lf_sha(root / name) for name in product},
        "toolkit_hashes_lf": {name: lf_sha(root / name) for name in toolkit},
        "scorer_sha256": base.sha(base.__file__),
        "scorer_sha256_lf": lf_sha(base.__file__),
        "adapter_requirements_sha256": adapter_raw,
        "adapter_requirements_sha256_lf": adapter_lf,
        "rubric_sha256": base.sha(base.RUBRIC),
    }


# --------------------------------------------------------------------------- attestation

def run_gh(command, env):
    """The one subprocess boundary of the importer: the GitHub CLI."""
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=180)


def gh_environment(repository):
    env = dict(os.environ)
    if not env.get("GH_TOKEN") and not env.get("GITHUB_TOKEN"):
        account = env.get("TWINAATMA_GH_ACCOUNT") or repository.split("/")[0]
        done = run_gh(["gh", "auth", "token", "--hostname", "github.com", "--user", account], env)
        token = done.stdout.strip()
        if done.returncode == 0 and token:
            env["GH_TOKEN"] = token
    return env


def verify_attestation(path, repository=REPOSITORY):
    """Run `gh attestation verify` and return the signed claims. The token is never printed or stored."""
    env = gh_environment(repository)
    command = ["gh", "attestation", "verify", str(path), "--repo", repository,
               "--signer-workflow", repository + "/" + WORKFLOW, "--format", "json"]
    done = run_gh(command, env)
    secret = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or "\0"
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").replace(secret, "***").strip().splitlines()
        raise ValueError("Attestation verification failed: " + (detail[-1] if detail else "no output"))
    try:
        results = json.loads(done.stdout)
        claims = []
        for item in results:
            certificate = item["verificationResult"]["signature"]["certificate"]
            claims.append({key: certificate.get(key) for key in (
                "sourceRepositoryDigest", "sourceRepositoryURI", "runInvocationURI", "buildSignerURI",
                "sourceRepositoryRef", "runnerEnvironment")})
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("Attestation verification returned an unreadable result") from error
    if not claims:
        raise ValueError("Attestation verification returned no attestation")
    return claims


# --------------------------------------------------------------------------- importer

def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_rows(checks, allowed, label):
    require(isinstance(checks, dict) and checks, label + " has no check rows")
    for key, row in checks.items():
        require(isinstance(row, dict) and row.get("id") == key and key in allowed, label + " has an unknown or mismatched check: " + str(key))
        require(row.get("verdict") in ("PASS", "FAIL", "BLOCKED", "NOT CHECKED"), label + " has an invalid verdict: " + str(key))
        if row["verdict"] == "PASS" and "observed" in row:
            require(row["observed"] not in (None, "", {}, []), label + " has a PASS without an observed result: " + str(key))


def check_report(report, scope, label):
    require(isinstance(report, dict) and report.get("scope") == scope, label + " has the wrong scope")
    require(isinstance(report.get("path"), str) and report["path"], label + " lacks its original report path")
    require(isinstance(report.get("report_sha256"), str) and HEX64.fullmatch(report["report_sha256"]), label + " lacks its original report hash")


def validate_graded(graded, system, base):
    """Well-formedness and scope limits. Each row must be one the local graders could have produced."""
    require(isinstance(graded, dict) and set(graded) <= {"artifacts", "hooks", "data", "recovery", "writers"}, "Graded section is unknown")
    for key in ("artifacts", "hooks", "data", "recovery"):
        require(isinstance(graded.get(key, []), list), "Graded section is not a list: " + key)
    for report in graded.get("artifacts", []):
        check_report(report, "artifact", "Artifact row")
        cell = report.get("cell")
        require(isinstance(cell, list) and tuple(cell) in base.ARTIFACT_MATRIX and cell[0] == system, "Artifact cell is outside this platform's release matrix")
        check_rows(report.get("checks"), base.ARTIFACT_IDS, "Artifact row")
    for report in graded.get("hooks", []):
        check_report(report, "artifact", "Runtime hook row")
        cell = report.get("cell")
        require(isinstance(cell, list) and tuple(cell) in base.RUNTIME_MATRIX and cell[0] == system, "Runtime hook cell is outside this platform's matrix")
        check_rows(report.get("checks"), base.HOOK_IDS, "Runtime hook row")
    for report in graded.get("data", []):
        check_report(report, "source", "Data row")
        spec = base.ALL_DATA_PRODUCERS.get(report.get("producer"))
        require(spec is not None, "Data row names an unknown producer")
        check_rows(report.get("checks"), {*spec["cases"], spec["aggregate"]}, "Data row")
        require(spec["aggregate"] in report["checks"], "Data row lacks its aggregate verdict")
    for report in graded.get("recovery", []):
        check_report(report, "source", "Recovery row")
        spec = base.RECOVERY_SPECS.get(report.get("producer"))
        require(spec is not None, "Recovery row names an unknown producer")
        check_rows(report.get("checks"), {spec[2]}, "Recovery row")
    writers = graded.get("writers", {})
    require(isinstance(writers, dict) and set(writers) <= {"focused", "reused"}, "Writer section is unknown")
    expected_os = {"Linux": "posix", "Windows": "nt"}[system]
    for report in writers.get("focused", []):
        require(isinstance(report, dict) and report.get("os_name") == expected_os and report.get("verdict") == "PASS"
                and isinstance(report.get("path"), str) and HEX64.fullmatch(str(report.get("report_sha256"))), "Writer row is malformed or from another platform")
        for key in ("actual_scripts", "actual_tools", "nested_processes", "safe_manifest_detachments", "successful_refreshes"):
            require(isinstance(report.get(key), list), "Writer row lacks " + key)
    for report in writers.get("reused", []):
        require(isinstance(report, dict) and report.get("verdict") == "PASS" and report.get("family") in
                {"export", "generated", "census", "maintenance", "hooks", "validation"}
                and isinstance(report.get("path"), str) and HEX64.fullmatch(str(report.get("report_sha256"))), "Reused writer row is malformed")


def check_binding(bundle, local, claims, repository):
    binding = bundle.get("binding")
    require(isinstance(binding, dict), "Bundle has no binding")
    require(binding.get("repository") == repository, "Bundle names another repository")
    require(binding.get("commit") == local["commit"], "Bundle commit differs from this checkout's HEAD")
    for key in ("product_hashes_lf", "toolkit_hashes_lf"):
        require(binding.get(key) == local[key], "Bundle product hashes differ from this checkout (stale or edited product)")
    for key in ("scorer_sha256_lf", "adapter_requirements_sha256_lf", "rubric_sha256"):
        require(binding.get(key) == local[key], "Bundle was graded by a different scorer, adapter or rubric: " + key)
    for key in ("run_id", "run_attempt"):
        require(isinstance(binding.get(key), str) and binding[key].isdigit(), "Bundle lacks its " + key)
    system = binding.get("platform", {}).get("system")
    require(system in EXPECTED, "Bundle platform is not a supported native platform")
    # The signed claims must agree with what the bundle says about itself.
    run = "/actions/runs/{}/attempts/{}".format(binding["run_id"], binding["run_attempt"])
    suffix = "/" + repository.lower()
    matching = [claim for claim in claims
                if claim.get("sourceRepositoryDigest") == binding["commit"]
                and str(claim.get("sourceRepositoryURI", "")).lower().endswith(suffix)
                and run in str(claim.get("runInvocationURI", ""))
                and WORKFLOW in str(claim.get("buildSignerURI", ""))
                and claim.get("runnerEnvironment") == "github-hosted"]
    require(matching, "Signed attestation does not match the bundle's commit, run and workflow")
    return system


def import_bundles(paths, base, current, *, verify=None):
    """Verify each bundle and return rows for snapshot(): artifacts, hooks, reports and pre-graded writers."""
    verify = verify or verify_attestation
    result = {"artifacts": [], "hooks": [], "reports": [], "writers": {}, "bundles": []}
    if not paths:
        return result
    local = local_binding(base)
    seen = set()
    focused, reused, recovery = [], [], []
    for path in paths:
        path = Path(path)
        raw = path.read_bytes()
        digest = sha256_bytes(raw)
        require(digest not in seen, "The same bundle was supplied twice")
        seen.add(digest)
        try:
            bundle = json.loads(raw.decode("utf-8"))
        except ValueError as error:
            raise ValueError("Bundle is not JSON: " + str(path)) from error
        require(isinstance(bundle, dict) and bundle.get("schema") == SCHEMA, "Bundle schema is unknown")
        claims = verify(path, REPOSITORY)
        graded = bundle.get("graded")
        require(isinstance(graded, dict) and bundle.get("graded_sha256") == sha256_bytes(canonical(graded).encode()), "Bundle rows were altered after grading")
        raw_reports = bundle.get("raw_reports")
        require(isinstance(raw_reports, dict) and all(isinstance(k, str) and isinstance(v, str) and HEX64.fullmatch(v) for k, v in raw_reports.items()),
                "Bundle lacks raw report hashes")
        system = check_binding(bundle, local, claims, REPOSITORY)
        validate_graded(graded, system, base)
        for line in bundle.get("rejected", []):
            print("ci-graded: runner could not grade {}: {}".format(line.get("report"), line.get("error")), file=sys.stderr)
        result["artifacts"] += graded.get("artifacts", [])
        result["hooks"] += graded.get("hooks", [])
        result["reports"] += graded.get("data", []) + graded.get("recovery", [])
        recovery += graded.get("recovery", [])
        focused += graded.get("writers", {}).get("focused", [])
        reused += graded.get("writers", {}).get("reused", [])
        result["bundles"].append({"path": str(path), "sha256": digest, "run_id": bundle["binding"]["run_id"],
                                  "platform": system, "commit": bundle["binding"]["commit"]})
    if focused or reused:
        result["writers"] = {"focused": focused, "reused": reused, "recovery": recovery}
    return result


# --------------------------------------------------------------------------- runner side

def find_report(directory):
    reports = sorted(Path(directory).rglob("report.json"), key=lambda p: (len(p.parts), str(p)))
    require(reports, "no report.json was produced")
    return reports[0]


def build_bundle(root_dir, kind, output, base, grade):
    """Grade every raw report natively on this runner and write the (unattested) bundle."""
    system = platform.system()
    require(system == kind, "Bundle kind differs from the runner platform")
    environment = os.environ
    root = Path(base.ROOT)
    local = local_binding(base)
    commit = environment.get("GITHUB_SHA")
    require(commit == local["commit"], "Runner HEAD differs from GITHUB_SHA")
    current = base.product_hashes()
    graded = {"artifacts": [], "hooks": [], "data": [], "recovery": [], "writers": {"focused": [], "reused": []}}
    rejected, raw_reports, verdicts = [], {}, []
    for label in EXPECTED[system]:
        directory = Path(root_dir) / label
        try:
            report = find_report(directory).absolute()
        except (ValueError, OSError) as error:
            rejected.append({"report": label, "error": str(error)})
            continue
        raw_reports[report.relative_to(root.absolute()).as_posix()] = base.sha(report)
        manifest = report.parent / "build-manifest.json"
        if manifest.is_file():
            raw_reports[manifest.relative_to(root.absolute()).as_posix()] = base.sha(manifest)
        try:
            if label.startswith("artifact-"):
                graded["artifacts"].append(base.artifact_report(report, current))
            elif label.startswith("hooks-"):
                graded["hooks"].append(base.runtime_hook_report(report, current))
            elif label == "recovery-write-faults":
                graded["recovery"].append(base.recovery_report(report, current))
            elif label == "maintenance-hooks":
                graded["data"].append(base.data_report(report, current))
                graded["writers"]["reused"].append(grade.reused_data(report, base, current))
            elif label == "writers":
                graded["writers"]["focused"].append(grade.focus_report(report, base))
        except (ValueError, KeyError, OSError, TypeError) as error:
            rejected.append({"report": report.relative_to(root.absolute()).as_posix(), "error": str(error)})
    for section in ("artifacts", "hooks", "data", "recovery"):
        for report in graded[section]:
            verdicts.extend((report["path"], cid, row["verdict"]) for cid, row in report["checks"].items())
    graded["writers"] = {key: value for key, value in graded["writers"].items() if value}
    graded = json.loads(json.dumps({key: value for key, value in graded.items() if value}))
    adapter = {key: local[key] for key in ("adapter_requirements_sha256", "adapter_requirements_sha256_lf")}
    binding = {
        "repository": environment.get("GITHUB_REPOSITORY", REPOSITORY),
        "commit": commit, "ref": environment.get("GITHUB_REF"), "event": environment.get("GITHUB_EVENT_NAME"),
        "workflow_ref": environment.get("GITHUB_WORKFLOW_REF"),
        "run_id": environment.get("GITHUB_RUN_ID"), "run_attempt": environment.get("GITHUB_RUN_ATTEMPT"),
        "platform": {"system": system, "os_name": os.name, "machine": platform.machine(), "platform": platform.platform(),
                     "python": sys.version, "runner_os": environment.get("RUNNER_OS"),
                     "image": environment.get("ImageOS"), "image_version": environment.get("ImageVersion")},
        **{key: local[key] for key in ("product_hashes", "product_hashes_lf", "toolkit_hashes_lf", "scorer_sha256",
                                       "scorer_sha256_lf", "rubric_sha256")}, **adapter,
        "builder_sha256_lf": lf_sha(__file__),
    }
    bundle = {"schema": SCHEMA, "binding": binding, "raw_reports": raw_reports, "rejected": rejected,
              "graded": graded, "graded_sha256": sha256_bytes(canonical(graded).encode())}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for report, check, verdict in verdicts:
        print("{:<11} {}  ({})".format(verdict, check, Path(report).parent.parent.name + "/" + Path(report).parent.name))
    for line in rejected:
        print("REJECTED    {}: {}".format(line["report"], line["error"]))
    print("writers sections:", {key: len(value) for key, value in graded.get("writers", {}).items()})
    complete = not rejected and all(verdict == "PASS" for _, _, verdict in verdicts)
    print("bundle:", output, "all-pass" if complete else "NOT ALL PASS")
    return 0 if complete else 1


def interpreter(minor):
    cache = Path(os.environ["RUNNER_TOOL_CACHE"]) / "Python"
    found = []
    for folder in cache.glob(minor + ".*"):
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", folder.name)
        executable = folder / "x64" / ("python.exe" if os.name == "nt" else "bin/python")
        if match and executable.is_file():
            found.append((tuple(map(int, match.groups())), executable))
    require(found, "No CPython " + minor + " in the runner tool cache")
    return str(max(found)[1])


def write_freeze(output):
    from data_preservation import ROOT, sha, source_files
    revision = git_head(ROOT)
    freeze = {"schema": "twinaatma.C-product-freeze/v1", "source_revision": revision,
              "product": {path.relative_to(ROOT).as_posix(): sha(path) for path in source_files()}}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("freeze:", output, revision, len(freeze["product"]), "toolkit files")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze").add_argument("--output", required=True)
    commands.add_parser("interpreter").add_argument("minor")
    build = commands.add_parser("bundle")
    build.add_argument("--kind", choices=sorted(EXPECTED), required=True)
    build.add_argument("--reports-root", required=True)
    build.add_argument("--output", required=True)
    inspect = commands.add_parser("inspect", help="Verify bundles against this checkout without scoring")
    inspect.add_argument("bundles", nargs="+", type=Path)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(HERE))
    try:
        if args.command == "interpreter":
            print(interpreter(args.minor))
            return 0
        if args.command == "freeze":
            write_freeze(args.output)
            return 0
        import acceptance as base
        if args.command == "bundle":
            import identity_writers_grade as grade
            return build_bundle(args.reports_root, args.kind, args.output, base, grade)
        imported = import_bundles([p.absolute() for p in args.bundles], base, base.product_hashes())
        print(json.dumps({"bundles": imported["bundles"], "artifacts": len(imported["artifacts"]), "hooks": len(imported["hooks"]),
                          "reports": len(imported["reports"]), "writers": {k: len(v) for k, v in imported["writers"].items()}}, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print("ci-graded rejected: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
