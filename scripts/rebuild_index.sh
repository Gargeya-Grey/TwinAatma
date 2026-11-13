#!/bin/bash
# Run with: bash scripts/rebuild_index.sh
set -euo pipefail
VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python "$VAULT_DIR/scripts/rebuild_index.py"
