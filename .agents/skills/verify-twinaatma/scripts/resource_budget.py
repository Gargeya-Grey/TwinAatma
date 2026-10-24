"""Measure startup, capture and recall latency, context bytes and memory against the owner-approved budget.

Deterministic synthetic vaults of exactly 100, 1000 and 10000 indexed notes are driven through the
real source MCP server over stdio. Every sample keeps its raw protocol so a grader can recompute
the latencies, context size and peak memory without trusting this report's summary."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import random
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
PRODUCER = "verify-twinaatma.resource-budget/v1"
SCALES = (100, 1000, 10000)
MIN_SAMPLES = 20
GENERATOR = "verify-twinaatma.resource-budget.vault/v1"
SEED = 20261021
STATE_FILES = ("knowledge_index.db", "knowledge_index.db-wal", "knowledge_index.db-shm", "knowledge_index.db-journal")
RESPONSE_TIMEOUT_SECONDS = 600
BUDGET_RELATIVE = "work/gc-artifacts/.knowledgeos/resource-budget-20261019"
BUDGET_FILES = ("approved-budget.json", "human-budget-source.jsonl", "bind_budget.py")
HINTS = (
    "Help me prepare for this week's planning review and remind me what we decided about pricing.",
    "I want to continue the research on onboarding friction from last week.",
    "Let's plan the next experiment for the launch and check what we learned from the last one.",
    "Draft a reply to the new supplier using what I already noted about their delivery terms.",
    "Review my open decisions and tell me which ones are due for a check.",
)
CAPTURE_TOPICS = (
    "pricing", "onboarding", "hiring", "roadmap", "research", "launch", "retention", "partnerships",
    "support", "budget", "migration", "analytics")
CAPTURE_SENTENCES = (
    "We agreed to postpone the change until the next review and to keep the current plan unchanged.",
    "The main risk is that the schedule depends on one supplier, so I want a second option noted.",
    "A customer said the setup felt confusing, and I want to test a shorter first step.",
    "I prefer short written updates before meetings, and I do not want extra recurring calls.",
    "The numbers from last month were lower than expected, so the forecast needs another look.",
    "Maya will own the follow-up and send a summary after the next conversation.",
)

VOCABULARY = {
    "topic": ["pricing", "onboarding", "retention", "hiring", "roadmap", "analytics", "billing", "support",
              "partnerships", "migration", "security", "forecasting", "research", "launch", "documentation",
              "procurement", "scheduling", "feedback", "reporting", "training", "planning", "inventory",
              "budgeting", "logistics", "compliance", "outreach", "pilot", "integration", "quality", "growth"],
    "adjective": ["weekly", "quarterly", "customer", "internal", "regional", "early", "revised", "shared",
                  "manual", "automated", "strategic", "operational", "draft", "final", "pending", "recurring"],
    "noun": ["review", "experiment", "decision", "framework", "checklist", "proposal", "interview", "summary",
             "workshop", "retrospective", "estimate", "audit", "backlog", "handoff", "baseline", "survey"],
    "verb": ["compare", "measure", "simplify", "schedule", "document", "validate", "prioritize", "revisit",
             "negotiate", "automate", "explain", "track", "reduce", "align", "test", "summarize"],
    "name": ["Maya", "Arjun", "Elena", "Tomas", "Priya", "Noah", "Sana", "Lukas", "Ines", "Kenji", "Amara",
             "Diego", "Hana", "Omar", "Freya", "Ravi"],
    "unicode": ["café meeting notes", "résumé review", "naïve estimate", "データ分析",
                "नमस्ते टीम", "übergabe plan", "señor approval"],
}
KINDS = (
    ("concept", "Concepts", 20), ("decision", "Decisions", 12), ("project", "Projects", 8),
    ("research", "Research", 20), ("experiment", "Experiments", 10), ("person", "People", 5),
    ("meeting", "Projects/Meetings", 10), ("synthesis", "Research/Syntheses", 5), ("inbox", "Inbox", 10))
SENTENCES = (
    "The {adjective} {topic} {noun} showed that we should {verb} the process before the next cycle.",
    "{name} suggested we {verb} the {topic} numbers and share the result with the team.",
    "We still need to {verb} the {adjective} {topic} approach because the last {noun} was inconclusive.",
    "The main constraint for {topic} is time, so the plan keeps the {adjective} {noun} small.",
    "After the {noun}, {name} and I agreed to {verb} the open questions about {topic}.",
    "A {adjective} {noun} on {topic} gave a clearer picture than the earlier estimate.",
    "I prefer to {verb} {topic} work in the morning and keep the afternoon for {adjective} {noun} follow-ups.",
    "The risk with {topic} is that the {adjective} data is incomplete, which {name} flagged last week.",
)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def product_hashes():
    paths = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT / "AGENTS.md"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths) if p.is_file()}


def percentile(values, quantile):
    """Nearest-rank percentile: the smallest value with at least `quantile` of the sample at or below it."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("A percentile needs at least one sample")
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def stats(values):
    return {"n": len(values), "min": min(values), "p50": percentile(values, 0.5),
            "p95": percentile(values, 0.95), "max": max(values)}


def summarize(rows, peaks, scale):
    """Statistics and budget comparison for one scale, from the raw sample rows and per-process peaks."""
    pick = lambda operation, kind=None: [r for r in rows if r["scale"] == scale and r["operation"] == operation
                                          and (kind is None or r["kind"] == kind)]
    return {"startup_all": stats([r["latency_ms"] for r in pick("startup")]),
            "startup_cold": stats([r["latency_ms"] for r in pick("startup", "cold")]),
            "startup_warm": stats([r["latency_ms"] for r in pick("startup", "warm")]),
            "capture": stats([r["latency_ms"] for r in pick("capture")]),
            "recall": stats([r["latency_ms"] for r in pick("recall")]),
            "context_bytes": stats([r["context_bytes"] for r in pick("startup")]),
            "context_field_bytes": stats([r["context_field_bytes"] for r in pick("startup")]),
            "peak_working_set_bytes": stats([p["peak_working_set_bytes"] for p in peaks]),
            "peak_pagefile_usage_bytes": stats([p["peak_pagefile_usage_bytes"] for p in peaks])}


def compare(summary, limits):
    rows = (("startup_p95_all_samples", "startup_all", "p95", limits["startup_ms"], "ms"),
            ("startup_p95_cold_samples", "startup_cold", "p95", limits["startup_ms"], "ms"),
            ("startup_p95_warm_samples", "startup_warm", "p95", limits["startup_ms"], "ms"),
            ("capture_p95", "capture", "p95", limits["capture_ms"], "ms"),
            ("recall_p95", "recall", "p95", limits["recall_ms"], "ms"),
            ("memory_process_peak_working_set_max", "peak_working_set_bytes", "max",
             limits["memory_process_peak_ram_bytes"], "bytes"),
            ("context_bytes_max", "context_bytes", "max", limits["context_bytes"], "bytes"),
            ("context_field_bytes_max", "context_field_bytes", "max", limits["context_bytes"], "bytes"))
    return [{"metric": metric, "observed": summary[group][statistic], "limit": limit, "unit": unit,
             "within": summary[group][statistic] <= limit} for metric, group, statistic, limit, unit in rows]


def generate_notes(count, seed=SEED):
    """Deterministic note set: a list of (vault-relative path, bytes, title, topic) for exactly `count` notes."""
    rng = random.Random(seed)
    syllables = ["ka", "lo", "mi", "ren", "tu", "vel", "sa", "do", "nex", "pi", "bar", "zu", "fen", "ori", "lum"]
    names, seen = [], set()
    while len(names) < count:
        word = "".join(rng.choice(syllables) for _ in range(rng.randint(2, 4)))
        if word not in seen:
            seen.add(word)
            names.append(word)
    kinds = [kind for kind, _, weight in KINDS for _ in range(weight)]
    plan = []
    for index in range(count):
        kind = rng.choice(kinds)
        folder = {k: f for k, f, _ in KINDS}[kind]
        topic = rng.choice(VOCABULARY["topic"])
        title = "{} {} {}".format(topic.capitalize(), rng.choice(VOCABULARY["noun"]), names[index])
        if kind == "person":
            title = "{} {}".format(rng.choice(VOCABULARY["name"]), names[index].capitalize())
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        plan.append({"kind": kind, "folder": folder, "topic": topic, "title": title, "slug": slug,
                     "project": "Project " + names[rng.randrange(min(12, count))].capitalize()})
    notes = []
    for index, item in enumerate(plan):
        kind = "inbox" if item["kind"] == "inbox" else item["kind"]
        note_type = {"inbox": "research"}.get(kind, kind)
        day = 1 + rng.randrange(28)
        created = "2026-{:02d}-{:02d}".format(1 + rng.randrange(9), day)
        tags = rng.sample(VOCABULARY["topic"], rng.randint(1, 4)) + [item["topic"]]
        paragraphs = []
        for _ in range(rng.choice([2, 3, 3, 4, 4, 5, 6, 8, 12])):
            sentences = [rng.choice(SENTENCES).format(
                adjective=rng.choice(VOCABULARY["adjective"]), topic=rng.choice(VOCABULARY["topic"]),
                noun=rng.choice(VOCABULARY["noun"]), verb=rng.choice(VOCABULARY["verb"]),
                name=rng.choice(VOCABULARY["name"])) for _ in range(rng.randint(2, 6))]
            paragraphs.append(" ".join(sentences))
        if rng.random() < 0.03:
            paragraphs.append("Also noted: " + rng.choice(VOCABULARY["unicode"]) + ".")
        links = []
        for _ in range(rng.randint(1, 5)):
            target = plan[rng.randrange(count)]
            if target is item:
                continue
            if rng.random() < 0.6:
                links.append("[[{}]]".format(target["title"]))
            else:
                depth = "../" * item["folder"].count("/") + "../"
                links.append("[{}]({}{}/{}.md)".format(target["title"], depth, target["folder"], target["slug"]))
        body = ["# " + item["title"], "", paragraphs[0], "", "## Details", ""]
        body += ["- " + p.split(". ")[0].rstrip(".") + "." for p in paragraphs[1:3]]
        body += ["", *paragraphs[3:], "", "## Related", "", *["- " + link for link in links], ""]
        if rng.random() < 0.08:
            body += ["```text", "owner=" + rng.choice(VOCABULARY["name"]), "due=" + created, "```", ""]
        front = ["---", "type: " + note_type, "title: " + item["title"],
                 "description: {} {} about {}".format(item["kind"].capitalize(), "note", item["topic"]),
                 "id: kos:{}:{}".format(note_type, item["slug"]), "schema: knowledgeos-v0.3",
                 "status: " + rng.choice(["draft", "active", "refined", "completed"]),
                 "created: " + created, "updated: " + created, "tags: [" + ", ".join(sorted(set(tags))) + "]",
                 "project: " + item["project"], "timestamp: " + created + "T00:00:00Z", "---", ""]
        data = ("\n".join(front + body)).encode("utf-8")
        notes.append((item["folder"] + "/" + item["slug"] + ".md", data, item["title"], item["topic"]))
    return notes


def generated_inventory(notes):
    return {path: {"size": len(data), "sha256": sha_bytes(data)} for path, data, _, _ in notes}


def inventory_digest(rows):
    return sha_bytes(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def file_inventory(directory):
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = {"size": path.stat().st_size, "sha256": sha(path)}
    return result


def checked_output(output):
    requested = Path(output).absolute()
    for component in (requested, *requested.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("Output may not traverse a linked/reparse component")
    base = requested.resolve(strict=False)
    generated = (ROOT / "work/gc-artifacts").resolve()
    if not base.is_relative_to(generated) or ".knowledgeos" not in base.relative_to(generated).parts:
        raise ValueError("Output must be below work/gc-artifacts and contain .knowledgeos")
    return base


def budget_directory(explicit=None):
    candidates = [Path(explicit)] if explicit else [ROOT / BUDGET_RELATIVE]
    if not explicit and ROOT.parent.name == "worktrees" and ROOT.parent.parent.name == ".claude":
        candidates.append(ROOT.parents[2] / BUDGET_RELATIVE)
    for candidate in candidates:
        if (candidate / "approved-budget.json").is_file():
            return candidate
    raise ValueError("Owner-approved budget directory not found; pass --budget-dir")


class Windows:
    """Native Windows process counters; the producer measures only on the named Windows device."""

    def __init__(self):
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

        class Power(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]
        self.Counters, self.Entry, self.Power = Counters, Entry, Power
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self.kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(Power)]

    def memory(self, pid):
        handle = self.kernel.OpenProcess(0x1000 | 0x0010, False, pid)
        if not handle:
            raise OSError("Cannot open the memory server process for memory counters")
        try:
            counters = self.Counters()
            counters.cb = ctypes.sizeof(counters)
            if not self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise OSError("GetProcessMemoryInfo failed")
            return {"peak_working_set_bytes": counters.PeakWorkingSetSize, "working_set_bytes": counters.WorkingSetSize,
                    "pagefile_usage_bytes": counters.PagefileUsage, "peak_pagefile_usage_bytes": counters.PeakPagefileUsage,
                    "page_fault_count": counters.PageFaultCount}
        finally:
            self.kernel.CloseHandle(handle)

    def children(self, pid):
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x2, 0)
        found = []
        try:
            entry = self.Entry()
            entry.dwSize = ctypes.sizeof(entry)
            more = self.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32ParentProcessID == pid:
                    found.append({"pid": entry.th32ProcessID, "exe": entry.szExeFile})
                more = self.kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(snapshot)
        return found

    def power(self):
        status = self.Power()
        self.kernel.GetSystemPowerStatus(ctypes.byref(status))
        line = {0: "battery", 1: "ac", 255: "unknown"}.get(status.ACLineStatus, "unknown")
        return {"source": line, "battery_percent": None if status.BatteryLifePercent == 255 else status.BatteryLifePercent}


INVENTORY_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
$drive = '__DRIVE__'
$cpu = Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
$cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, TotalPhysicalMemory
$os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture, FreePhysicalMemory
$disk = $null
try { $disk = Get-Partition -DriveLetter $drive -ErrorAction Stop | Get-Disk -ErrorAction Stop | Get-PhysicalDisk -ErrorAction Stop | Select-Object FriendlyName, MediaType, BusType, Size } catch { $disk = @{ error = $_.Exception.Message } }
$load = $null
try { $load = (Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 5 -ErrorAction Stop).CounterSamples | ForEach-Object { [math]::Round($_.CookedValue, 1) } } catch { $load = @{ error = $_.Exception.Message } }
$top = Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 -Property Name, @{n='WorkingSetMiB';e={[math]::Round($_.WorkingSet64 / 1MB)}}
$plan = (powercfg /getactivescheme) -join ' '
[pscustomobject]@{ cpu = $cpu; computer = $cs; os = $os; disk = $disk; cpu_load_percent_samples = $load; largest_other_processes = $top; power_plan = $plan; process_count = (Get-Process).Count } | ConvertTo-Json -Depth 5
"""


class Run:
    def __init__(self, base, scales, samples, budget_dir, seed):
        self.directory = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.scales, self.samples, self.seed = list(scales), samples, seed
        self.budget_dir = budget_dir
        self.windows = Windows()
        self.processes, self.rows, self.scale_records, self.commands = [], [], {}, {}
        self.process_memory = {}
        self.protected = [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json"]
        self.before = self.sentinels()
        self.pycache = self.directory / "pycache"
        cache_prefix = str(self.pycache)
        if os.name == "nt" and not cache_prefix.startswith("\\\\?\\"):
            cache_prefix = ("\\\\?\\UNC\\" + cache_prefix[2:] if cache_prefix.startswith("\\\\")
                            else "\\\\?\\" + cache_prefix)
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT), PYTHONPYCACHEPREFIX=cache_prefix)
        for key in ("PYTHONHOME", "KNOWLEDGEOS_VAULT", "KNOWLEDGEOS_GATE_KEY", "VIRTUAL_ENV", "PYTHONDONTWRITEBYTECODE"):
            self.env.pop(key, None)
        (self.directory / "protocol").mkdir()
        (self.directory / "commands").mkdir()

    def sentinels(self):
        return {str(p): sha(p) if p.is_file() else None for p in self.protected}

    def save(self, name, value):
        (self.directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")

    def command(self, label, command, cwd, env=None, timeout=900):
        env = env or self.env
        started = time.perf_counter_ns()
        process = subprocess.Popen([str(c) for c in command], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        error = None
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            error = "Command exceeded the proof deadline"
        finally:
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode)
        (self.directory / "commands" / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8", newline="\n")
        (self.directory / "commands" / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8", newline="\n")
        record = {"command": [str(c) for c in command], "cwd": str(cwd), "shell": False, "pid": process.pid,
                  "exit_code": process.returncode, "seconds": (time.perf_counter_ns() - started) / 1e9,
                  "stopped": tracked["stopped"], "error": error,
                  "state_dir": env.get("KNOWLEDGEOS_STATE_DIR")}
        self.save("commands/" + label + ".command.json", record)
        self.commands[label] = record
        return record, stdout, stderr

    def device(self, label):
        script = INVENTORY_SCRIPT.replace("__DRIVE__", self.directory.drive.rstrip(":") or "C")
        record, stdout, _ = self.command("device-" + label, ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], ROOT, timeout=180)
        parsed = json.loads(stdout) if record["exit_code"] == 0 and stdout.strip() else None
        return {"inventory": parsed, "power": self.windows.power(), "python_executable": sys.executable,
                "python_version": sys.version, "python_in_virtual_environment": sys.prefix != sys.base_prefix,
                "platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count()}

    def server_command(self, vault):
        return [sys.executable, "-P", "-m", "knowledgeos", "mcp", "--vault", str(vault), "--framing", "ndjson"]

    def build_vault(self, scale):
        scope = self.directory / "scales" / str(scale)
        vault, state = scope / "vault", scope / "gate-state"
        scope.mkdir(parents=True)
        env = dict(self.env, KNOWLEDGEOS_STATE_DIR=str(state))
        record, _, stderr = self.command("init-%d" % scale, [sys.executable, "-P", "-m", "knowledgeos", "init", vault,
                                         "--name", "Resource fixture", "--non-interactive"], scope, env=env)
        if record["exit_code"] != 0:
            raise RuntimeError("Fixture initialization failed: " + stderr[-400:])
        base = self.indexed_count(vault)
        notes = generate_notes(scale - base, self.seed)
        for relative, data, _, _ in notes:
            target = vault / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        fixture = {"scale": scale, "vault": vault, "state": state, "env": env, "notes": notes}
        server = self.session(fixture, "setup-%d" % scale)
        try:
            server.spawn()
            server.initialize()
            startup = server.call("memory_session_start", {"task_hint": HINTS[0]}, from_spawn=True)
            if not startup["ok"]:
                raise RuntimeError("Untimed post-setup MCP startup failed")
        finally:
            server.close()
        if server.tracked["exit_code"] != 0 or server.forced or self.indexed_count(vault) != scale:
            raise RuntimeError("Untimed setup did not leave a complete, cleanly stopped index")
        baseline = scope / "initialized-baseline"
        shutil.copytree(vault, baseline / "vault")
        shutil.copytree(state, baseline / "gate-state")
        inventory = file_inventory(vault)
        self.save("scales/%d/vault-inventory.json" % scale, inventory)
        baseline_record = {"schema": "twinaatma.resource-initialized-baseline/v1", "scale": scale,
                           "indexed_notes": self.indexed_count(baseline / "vault"),
                           "vault": file_inventory(baseline / "vault"),
                           "gate_state": file_inventory(baseline / "gate-state"),
                           "setup_process": server.label, "setup_request_id": startup["request_id"],
                           "product_hashes": product_hashes(), "generator": GENERATOR, "seed": self.seed}
        name = "scales/%d/initialized-baseline.json" % scale
        self.save(name, baseline_record)
        fixture["baseline_sha256"] = sha(self.directory / name)
        generated = generated_inventory(notes)
        fixture["record"] = {"requested_notes": scale, "base_indexed_notes": base, "generated_notes": len(notes),
                           "initialized_baseline": {"path": name, "sha256": fixture["baseline_sha256"]},
                           "generated_inventory_sha256": inventory_digest(generated),
                           "vault_inventory_sha256": inventory_digest(inventory), "vault_files": len(inventory),
                           "vault_bytes": sum(row["size"] for row in inventory.values()),
                           "generated_bytes": sum(row["size"] for row in generated.values()),
                           "generator": GENERATOR, "seed": self.seed}
        return fixture

    @staticmethod
    def indexed_count(vault):
        connection = sqlite3.connect("file:" + (Path(vault) / "knowledge_index.db").as_posix() + "?mode=ro", uri=True)
        try:
            return connection.execute("select count(*) from notes").fetchone()[0]
        finally:
            connection.close()

    def reset_cold(self, fixture):
        scope = fixture["vault"].parent
        for name, target in (("vault", fixture["vault"]), ("gate-state", fixture["state"])):
            resolved = target.resolve()
            if resolved.parent != scope.resolve() or target.is_symlink():
                raise ValueError("Cold reset must stay inside its task-owned scale fixture")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(scope / "initialized-baseline" / name, target)

    def session(self, fixture, label):
        return Server(self, fixture, label)

    def sample_row(self, fixture, operation, kind, index, server, request_id, outcome):
        row = {"scale": fixture["scale"], "operation": operation, "kind": kind, "index": index,
               "process": server.label, "request_id": request_id, **outcome}
        self.rows.append(row)
        return row

    def measure_startup(self, fixture, kind, index):
        server = self.session(fixture, "startup-%s-%d-%03d" % (kind, fixture["scale"], index))
        try:
            server.spawn()
            server.initialize()
            outcome = server.call("memory_session_start", {"task_hint": HINTS[index % len(HINTS)]}, from_spawn=True)
            server.memory()
        finally:
            server.close()
        return self.sample_row(fixture, "startup", kind, index, server, outcome.pop("request_id"), outcome)

    def measure_steady(self, fixture, rng):
        notes = fixture["notes"]
        server = self.session(fixture, "steady-%d" % fixture["scale"])
        try:
            server.spawn()
            server.initialize()
            warm = server.call("memory_session_start", {"task_hint": HINTS[0]}, from_spawn=True)
            server.memory()
            before = self.indexed_count(fixture["vault"])
            fixture["record"]["indexed_notes_before_operations"] = before
            for index in range(self.samples):
                title, topic = notes[rng.randrange(len(notes))][2:4]
                query = title if index % 3 else "%s %s" % (topic, rng.choice(VOCABULARY["noun"]))
                outcome = server.call("memory_search", {"query": query}, expect=title)
                self.sample_row(fixture, "recall", "steady", index, server, outcome.pop("request_id"), dict(outcome, query=query))
            server.memory()
            for index in range(self.samples):
                title = "Capture %s %d %s" % (rng.choice(CAPTURE_TOPICS), index, uuid.uuid4().hex[:6])
                content = " ".join(rng.sample(CAPTURE_SENTENCES, 3)) + " Reference: " + title + "."
                outcome = server.call("memory_capture", {"title": title, "content": content}, expect=title)
                self.sample_row(fixture, "capture", "steady", index, server, outcome.pop("request_id"), dict(outcome, title=title))
            server.memory()
        finally:
            server.close()
        fixture["record"]["steady_start_response_ok"] = warm["ok"]
        fixture["record"]["indexed_notes_after_operations"] = self.indexed_count(fixture["vault"])

    def run_scale(self, scale):
        fixture = self.build_vault(scale)
        rng = random.Random(self.seed + scale)
        for index in range(self.samples):
            self.reset_cold(fixture)
            self.measure_startup(fixture, "cold", index)
        fixture["record"]["indexed_notes_after_cold_start"] = self.indexed_count(fixture["vault"])
        for index in range(self.samples):
            self.measure_startup(fixture, "warm", index)
        self.measure_steady(fixture, rng)
        self.scale_records[str(scale)] = fixture["record"]
        print("scale %d complete" % scale, flush=True)

    @staticmethod
    def excluded(parts):
        return parts[0] == "pycache" or (parts[0] == "scales" and len(parts) > 2 and parts[2] in ("vault", "gate-state", "index-seed", "initialized-baseline"))

    def complete_scale(self, scale):
        rows = [r for r in self.rows if r["scale"] == scale]
        return len(rows) == 4 * self.samples and str(scale) in self.process_memory

    def finish(self, error=None):
        after = self.sentinels()
        current = product_hashes()
        stable = current == self.product and sha(__file__) == self.producer_hash
        isolated = self.before == after
        stopped = bool(self.processes) and all(p["stopped"] for p in self.processes)
        if error is not None:
            self.save("execution-error.json", {"error": str(error)})
        with (self.directory / "samples.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for row in self.rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        report = {
            "producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": {}, "support_sha256_after": {},
            "source_root": str(ROOT), "revision": getattr(self, "revision", None), "platform": platform.platform(),
            "python": sys.version, "scope": "performance",
            "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidate": "PORT.measured_resource_budget",
            "acceptance_credit_awarded": False, "product_hashes": self.product, "product_hashes_after": current,
            "product_and_producer_unchanged": stable,
            "requested_scales": self.scales, "samples_per_operation": self.samples,
            "percentile_method": "nearest-rank", "seed": self.seed, "generator": GENERATOR,
            "budget": getattr(self, "budget", None), "device": getattr(self, "device_start", None),
            "device_end": getattr(self, "device_end", None), "scales": self.scale_records,
            "launch": {"argv_template": self.server_command("<vault>"), "pycache_prefix": self.env["PYTHONPYCACHEPREFIX"],
                       "note": "Bytecode is precompiled once before measuring, as an installed package would be."},
            "processes": self.processes, "commands": sorted(self.commands),
            "all_started_processes_stopped": stopped, "sample_count": len(self.rows),
            "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": isolated,
                          "limitation": "Selected real-vault sentinels only; this is not an exhaustive filesystem audit"},
            "limitations": ["Native Windows source checkout only; no installed package, host or other device claim",
                            "Latency excludes model response time and host rendering",
                            "Cold means a fresh process against a complete initialized baseline; warm retains prior session state",
                            "One untimed public MCP startup after generation establishes each signed, indexed scale baseline",
                            "Operating-system file caches are not flushed between samples"],
            "error": str(error) if error is not None else None}
        report["process_memory"] = {scale: sorted(peaks, key=lambda p: p["process"])
                                    for scale, peaks in sorted(self.process_memory.items())}
        report["summary"], report["budget_comparison"] = {}, {}
        limits = (getattr(self, "budget", None) or {}).get("values")
        for scale in self.scale_records:
            if self.complete_scale(int(scale)):
                report["summary"][scale] = summarize(self.rows, report["process_memory"][scale], int(scale))
                report["budget_comparison"][scale] = compare(report["summary"][scale], limits)
        report["evidence_files"] = {p.relative_to(self.directory).as_posix(): sha(p)
                                    for p in sorted(self.directory.rglob("*")) if p.is_file()
                                    and p.name != "report.json" and not self.excluded(p.relative_to(self.directory).parts)}
        report["verdict"] = "PASS" if error is None and stable and isolated and stopped else "FAIL"
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"],
                          "samples": len(self.rows)}))
        return 0 if report["verdict"] == "PASS" else 1

    def run(self):
        self.producer_hash = sha(__file__)
        self.product = product_hashes()
        error = None
        try:
            record, output, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            self.revision = output.strip()
            self.copy_budget()
            self.device_start = self.device("start")
            record, _, stderr = self.command("compile", [sys.executable, "-m", "compileall", "-q", str(ROOT / "knowledgeos")], ROOT)
            if record["exit_code"] != 0:
                raise RuntimeError("Bytecode precompile failed; measurements were not started: " + stderr[-400:])
            for scale in self.scales:
                self.run_scale(scale)
            self.device_end = self.device("end")
        except BaseException as caught:
            error = caught
        return self.finish(error)

    def copy_budget(self):
        target = self.directory / "budget"
        target.mkdir()
        for name in BUDGET_FILES:
            source = self.budget_dir / name
            if source.is_file():
                shutil.copy2(source, target / name)
        text = (target / "approved-budget.json").read_text(encoding="utf-8")
        self.budget = {"copied_to": "budget/approved-budget.json", "sha256": sha(target / "approved-budget.json"),
                       "source_directory": str(self.budget_dir), "values": json.loads(text),
                       "source_line_sha256": sha(target / "human-budget-source.jsonl")}


class Server:
    """One real MCP server process with a retained, timestamped protocol."""

    def __init__(self, run, fixture, label):
        self.run, self.fixture, self.label = run, fixture, label
        self.events, self.lines, self.next_id = [], queue.Queue(), 0
        self.stderr, self.forced = [], False

    def event(self, kind, **fields):
        self.events.append({"event": kind, "t_ns": time.perf_counter_ns(), **fields})

    def spawn(self):
        command = self.run.server_command(self.fixture["vault"])
        baseline = {}
        if self.label.startswith("startup-cold-"):
            name = "scales/%d/initialized-baseline.json" % self.fixture["scale"]
            source = self.run.directory / name
            record = json.loads(source.read_text(encoding="utf-8"))
            current = {"vault": file_inventory(self.fixture["vault"]), "gate_state": file_inventory(self.fixture["state"])}
            if sha(source) != self.fixture["baseline_sha256"] or any(current[k] != record[k] for k in current):
                raise RuntimeError("Cold sample does not start from its complete initialized baseline")
            baseline = {"initialized_baseline_sha256": sha(source),
                        "initialized_state_sha256": inventory_digest(current)}
        self.spawn_ns = time.perf_counter_ns()
        self.process = subprocess.Popen(command, cwd=self.fixture["vault"].parent, env=self.fixture["env"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.events.append({"event": "spawn", "t_ns": self.spawn_ns, "pid": self.process.pid, "argv": command,
                            "state_dir": self.fixture["env"]["KNOWLEDGEOS_STATE_DIR"], "shell": False, **baseline})
        self.tracked = {"pid": self.process.pid, "role": self.label, "scale": self.fixture["scale"], "stopped": False}
        self.run.processes.append(self.tracked)
        threading.Thread(target=self.read_stdout, daemon=True).start()
        threading.Thread(target=self.read_stderr, daemon=True).start()

    def read_stdout(self):
        for line in iter(self.process.stdout.readline, b""):
            self.lines.put((time.perf_counter_ns(), line))
        self.lines.put((time.perf_counter_ns(), None))

    def read_stderr(self):
        for line in iter(self.process.stderr.readline, b""):
            self.stderr.append(line.decode("utf-8", errors="replace"))

    def send(self, message):
        self.event("send", data=json.dumps(message, ensure_ascii=False))
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))

    def wait(self, request_id):
        deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
        while True:
            try:
                stamp, line = self.lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                self.event("timeout", id=request_id)
                return None, None
            if line is None:
                self.event("eof", id=request_id)
                return None, None
            text = line.decode("utf-8").rstrip("\r\n")
            self.events.append({"event": "recv", "t_ns": stamp, "data": text})
            try:
                message = json.loads(text)
            except ValueError:
                continue
            if message.get("id") == request_id:
                return stamp, message

    def initialize(self):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-resource-budget", "version": "1"}}})
        _, message = self.wait(self.next_id)
        if message is None or message.get("result", {}).get("serverInfo", {}).get("name") != "knowledgeos-memory":
            raise RuntimeError("Wrong or missing MCP server identity during " + self.label)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name, arguments, from_spawn=False, expect=None):
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        sent = self.events[-1]["t_ns"]
        stamp, message = self.wait(request_id)
        outcome = {"request_id": request_id, "tool": name, "ok": False}
        if message is None:
            outcome["latency_ms"] = ((time.perf_counter_ns() - (self.spawn_ns if from_spawn else sent)) / 1e6)
            return outcome
        outcome["latency_ms"] = (stamp - (self.spawn_ns if from_spawn else sent)) / 1e6
        result = message.get("result") or {}
        text = (result.get("content") or [{}])[0].get("text", "")
        outcome["response_bytes"] = len(text.encode("utf-8"))
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {}
        ok = isinstance(payload, dict) and not result.get("isError") and "error" not in payload
        if name == "memory_session_start":
            context = payload.get("context") if isinstance(payload, dict) else None
            ok = ok and bool(context) and isinstance(payload.get("session_id"), str)
            outcome["context_bytes"] = outcome["response_bytes"]
            outcome["context_field_bytes"] = len((context if isinstance(context, str) else json.dumps(context, ensure_ascii=False)).encode("utf-8")) if context else 0
        elif name == "memory_search":
            ranked = payload.get("ranked") if isinstance(payload, dict) else None
            ok = ok and isinstance(ranked, list) and bool(ranked)
            outcome["results"] = len(ranked) if isinstance(ranked, list) else 0
            outcome["expected_in_results"] = bool(ranked) and any(isinstance(h, dict) and expect and expect in json.dumps(h, ensure_ascii=False) for h in ranked)
        elif name == "memory_capture":
            path = payload.get("path") if isinstance(payload, dict) else None
            ok = ok and payload.get("ok") is True and isinstance(path, str) and (self.fixture["vault"] / path).is_file()
            outcome["path"] = path
        outcome["ok"] = bool(ok)
        return outcome

    def memory(self):
        counters = self.run.windows.memory(self.process.pid)
        self.event("memory", children=self.run.windows.children(self.process.pid), **counters)

    def close(self):
        process = getattr(self, "process", None)
        if process is None:
            return
        try:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.forced = True
                process.kill()
                process.wait(timeout=30)
        finally:
            self.tracked.update(stopped=process.poll() is not None, exit_code=process.returncode, forced_kill=self.forced)
            self.event("exit", exit_code=process.returncode, forced_kill=self.forced)
            memory = [e for e in self.events if e["event"] == "memory"]
            if memory:
                self.run.process_memory.setdefault(str(self.fixture["scale"]), []).append(
                    {"process": self.label, "peak_working_set_bytes": max(e["peak_working_set_bytes"] for e in memory),
                     "peak_pagefile_usage_bytes": max(e["peak_pagefile_usage_bytes"] for e in memory),
                     "last_pagefile_usage_bytes": memory[-1]["pagefile_usage_bytes"]})
            self.events.append({"event": "stderr", "t_ns": time.perf_counter_ns(), "text": "".join(self.stderr)})
            with (self.run.directory / "protocol" / (self.label + ".jsonl")).open("w", encoding="utf-8", newline="\n") as stream:
                for item in self.events:
                    stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=MIN_SAMPLES, help="samples per operation and kind at each scale")
    parser.add_argument("--scales", default=",".join(map(str, SCALES)),
                        help="comma-separated note counts; the grader awards PASS only for all of 100,1000,10000")
    parser.add_argument("--budget-dir", help="directory holding the owner-approved budget files")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This producer measures native Windows process memory only")
    scales = [int(value) for value in args.scales.split(",")]
    if args.samples < 1 or any(scale < 50 for scale in scales):
        parser.error("Use at least one sample and scales of at least 50 notes")
    def interrupted(signum, frame):
        raise InterruptedError("Resource-budget proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return Run(checked_output(args.output), scales, args.samples, budget_directory(args.budget_dir), args.seed).run()


if __name__ == "__main__":
    raise SystemExit(main())
