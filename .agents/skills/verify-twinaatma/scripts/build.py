"""Build fresh candidates from an enumerated copy; retain commands and input bytes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
BASE=args.output.resolve()
relative=BASE.relative_to((ROOT/"work/gc-artifacts").resolve())
if ".knowledgeos" not in relative.parts:
    parser.error("Output must contain .knowledgeos beneath work/gc-artifacts")
BASE.mkdir(parents=True,exist_ok=True)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
run = BASE / "build" / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
source = run / "source"
source.mkdir(parents=True)
paths = [*ROOT.glob("knowledgeos/*.py"), ROOT / "knowledgeos/py.typed"]
for folder in ["Templates", ".cursor/hooks", ".cursor/rules"]:
    paths += [p for p in (ROOT/folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
paths += [ROOT/p for p in ["setup.py", "pyproject.toml", "MANIFEST.in", "pyinstaller.spec", "AGENTS.md", "LICENSE", "README.md", "knowledgeos.config.example.json", ".cursor/hooks.json"]]
inputs = {}
for path in sorted(set(paths)):
    relative = path.relative_to(ROOT)
    target = source/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    inputs[relative.as_posix()] = sha(path)
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
           TEMP=str(run/"tmp"), TMP=str(run/"tmp"), PYINSTALLER_CONFIG_DIR=str(run/"pyinstaller-cache"))
(run/"tmp").mkdir()
env.pop("PYTHONPATH", None)
commands = []
for label, command in [
    ("wheel", [sys.executable, "-B", "setup.py", "bdist_wheel", "--dist-dir", str(run/"wheel")]),
    ("binary", [sys.executable, "-B", "-m", "PyInstaller", "pyinstaller.spec", "--noconfirm", "--distpath", str(run/"dist"), "--workpath", str(run/"pyinstaller-work")]),
]:
    started = time.monotonic()
    p = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    for suffix, value in [("stdout.txt", p.stdout), ("stderr.txt", p.stderr)]:
        (run/f"{label}.{suffix}").write_text(value, encoding="utf-8")
    commands.append({"command":command, "cwd":str(source), "exit_code":p.returncode, "seconds":time.monotonic()-started})
    (run/"commands.json").write_text(json.dumps(commands, indent=2), encoding="utf-8")
    print(label, "exit", p.returncode, "seconds", round(commands[-1]["seconds"], 2), flush=True)
    if p.returncode:
        print(p.stderr[-2000:]); print("Retained:", run); sys.exit(p.returncode)
assert all(sha(ROOT/p)==h for p,h in inputs.items()), "Build inputs changed"
distribution = run/"dist/twinaatma"
executable = distribution/("twinaatma.exe" if os.name=="nt" else "twinaatma")
products = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT/"AGENTS.md"]
manifest = {"producer":"verify-twinaatma.build/v1", "product_hashes":{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(products)},
    "inputs":inputs, "build_commands":commands, "distribution_root":str(distribution), "executable":str(executable),
    "outputs":{p.relative_to(distribution).as_posix():sha(p) for p in sorted(distribution.rglob("*")) if p.is_file() and not p.is_symlink()},
    "links":{p.relative_to(distribution).as_posix():os.readlink(p) for p in sorted(distribution.rglob("*")) if p.is_symlink()},
    "wheel":str(next((run/"wheel").glob("*.whl"))), "build_producer_sha256":sha(__file__)}
(run/"build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("Build manifest:", run/"build-manifest.json", flush=True)
