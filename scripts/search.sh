#!/bin/bash
# Usage: bash scripts/search.sh <query>
set -euo pipefail
VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python "$VAULT_DIR/scripts/search.py" "$@"
