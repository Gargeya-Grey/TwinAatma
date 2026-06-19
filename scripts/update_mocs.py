#!/usr/bin/env python
"""Refresh generated operational dashboards."""
import subprocess, sys
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parent
for name in ['experiment_dashboard.py']:
    print(f'Running {name}...')
    subprocess.check_call([sys.executable, str(SCRIPTS/name)])
print('Generated dashboards updated.')
