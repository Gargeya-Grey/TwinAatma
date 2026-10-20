#!/usr/bin/env python
"""Forward the end event to the installed toolkit's serialized session lifecycle."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    args=sys.argv[1:]
    raw=sys.stdin.read()
    vault=os.environ.get('KNOWLEDGEOS_VAULT','')
    if '--vault' in args and args.index('--vault')+1 < len(args):
        vault=args[args.index('--vault')+1]
    if not vault:
        vault=str(Path(__file__).resolve().parents[2])
    env=dict(os.environ)
    env.pop('PYTHONPATH',None)
    for candidate in Path(__file__).resolve().parents:
        if (candidate/'knowledgeos/__init__.py').is_file():
            env['PYTHONPATH']=str(candidate)
            break
    command=[sys.executable,'-P','-m','knowledgeos','hook','twin_session_end','--vault',vault]
    try:
        result=subprocess.run(command,input=raw,capture_output=True,text=True,timeout=120,
                              cwd=vault,env=env)
        if result.returncode:
            print('Session handoff unavailable; unfinished memory remains retained.',file=sys.stderr)
    except (OSError,subprocess.SubprocessError):
        print('Session handoff unavailable; unfinished memory remains retained.',file=sys.stderr)
    print(json.dumps({}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
