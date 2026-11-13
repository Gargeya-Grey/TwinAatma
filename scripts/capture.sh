#!/bin/bash
# KnowledgeOS Hermes Capture Script
# Called by Hermes agent to index new notes
# Usage: ./scripts/capture.sh <path-to-note>

set -euo pipefail

VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB="$VAULT_DIR/knowledge_index.db"

note_path="$1"

if [ -z "$note_path" ]; then
    echo "Usage: $0 <path-to-note>"
    exit 1
fi

# Resolve relative to vault
if [[ "$note_path" != /* ]]; then
    note_path="$VAULT_DIR/$note_path"
fi

if [ ! -f "$note_path" ]; then
    echo "Error: File not found: $note_path"
    exit 1
fi

rel_path="${note_path#$VAULT_DIR/}"

# Rebuild full index (fast enough for single-file, ensures consistency)
"$VAULT_DIR/scripts/rebuild_index.sh" "$DB"

echo "Captured: $rel_path"