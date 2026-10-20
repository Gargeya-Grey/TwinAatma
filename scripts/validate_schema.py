#!/usr/bin/env python
"""Validate KnowledgeOS notes against the portable metadata schema.

Thin wrapper over knowledgeos.validator (stdlib only).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent.parent
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from knowledgeos.validator import validate_vault  # noqa: E402
from knowledgeos.vault_resolve import resolve_vault  # noqa: E402


def _explicit_vault() -> Path | None:
    if "--vault" in sys.argv:
        idx = sys.argv.index("--vault")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1])
    return None


def main() -> int:
    result = validate_vault(resolve_vault(_explicit_vault(), cwd=TOOLKIT_DIR))
    print(json.dumps(result, indent=2))
    return 1 if result["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
