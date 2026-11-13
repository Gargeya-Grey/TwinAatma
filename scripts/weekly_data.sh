#!/bin/bash
# Usage: bash scripts/weekly_data.sh
set -euo pipefail
VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python "$VAULT_DIR/scripts/weekly_data.py"
