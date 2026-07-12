#!/usr/bin/env python
"""Validate KnowledgeOS notes against the portable metadata schema.

Uses the shared knowledgeos parser/schema modules (stdlib only).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
if str(VAULT_DIR) not in sys.path:
    sys.path.insert(0, str(VAULT_DIR))

from knowledgeos.links import extract_raw_links  # noqa: E402
from knowledgeos.parser import parse_frontmatter  # noqa: E402
from knowledgeos.schema import (  # noqa: E402
    ID_PATTERN,
    NOTE_TYPES_V03,
    OPTIONAL_V03_FIELDS,
    OUTCOME_STATUS_VALUES,
    RECOMMENDED_FOR_SOURCE,
    REQUIRED_FIELDS,
    SCHEMA_V02,
    SCHEMA_V03,
)

SKIP_DIRS = {".git", "node_modules", "Archive", "__pycache__", ".knowledgeos", ".cursor", "docs"}
SKIP_ROOT_FILES = {
    "readme.md",
    "license",
    "contributing.md",
    "security.md",
    "changelog.md",
    "code_of_conduct.md",
    "agents.md",
}
ID_RE = re.compile(ID_PATTERN)


def is_template(path: Path) -> bool:
    return "Templates" in path.parts


def is_index_or_moc(fm: dict) -> bool:
    return fm.get("type") in {"index", "moc"}


def main() -> int:
    notes = []
    warnings = []
    errors = []
    seen_ids: dict[str, str] = {}

    for path in VAULT_DIR.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.lower() in SKIP_ROOT_FILES and path.parent == VAULT_DIR:
            continue
        rel = path.relative_to(VAULT_DIR).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        links = extract_raw_links(text)

        if not fm:
            errors.append({"path": rel, "issue": "missing_frontmatter"})
            continue

        missing = [k for k in REQUIRED_FIELDS if not fm.get(k)]
        if is_template(path):
            missing = [k for k in missing if k not in {"description", "tags"}]
        if missing:
            errors.append({"path": rel, "issue": "missing_required_fields", "fields": missing})

        note_type = fm.get("type")
        if note_type and note_type not in NOTE_TYPES_V03 and not is_template(path):
            warnings.append({"path": rel, "issue": "unknown_type", "type": note_type})

        schema_ver = fm.get("schema")
        if schema_ver and schema_ver not in {SCHEMA_V02, SCHEMA_V03}:
            warnings.append({"path": rel, "issue": "unknown_schema_version", "schema": schema_ver})

        entity_id = fm.get("id")
        if entity_id:
            if not ID_RE.match(str(entity_id)):
                errors.append({"path": rel, "issue": "invalid_id_format", "id": entity_id})
            elif entity_id in seen_ids:
                errors.append(
                    {
                        "path": rel,
                        "issue": "duplicate_id",
                        "id": entity_id,
                        "other": seen_ids[entity_id],
                    }
                )
            else:
                seen_ids[entity_id] = rel

        outcome_status = fm.get("outcome_status")
        if outcome_status and outcome_status not in OUTCOME_STATUS_VALUES:
            errors.append(
                {
                    "path": rel,
                    "issue": "invalid_outcome_status",
                    "outcome_status": outcome_status,
                }
            )

        confidence = fm.get("confidence")
        if confidence not in (None, ""):
            try:
                c = float(confidence)
                if c < 0 or c > 1:
                    warnings.append({"path": rel, "issue": "confidence_out_of_range", "confidence": confidence})
            except (TypeError, ValueError):
                warnings.append({"path": rel, "issue": "confidence_not_numeric", "confidence": confidence})

        if not links and not is_index_or_moc(fm) and not is_template(path):
            warnings.append({"path": rel, "issue": "no_links"})

        sourceish = bool(fm.get("source_type") or fm.get("resource"))
        if sourceish and not is_template(path):
            missing_source = [k for k in RECOMMENDED_FOR_SOURCE if not fm.get(k)]
            if missing_source:
                warnings.append(
                    {
                        "path": rel,
                        "issue": "missing_source_provenance",
                        "fields": missing_source,
                    }
                )

        notes.append(rel)

    result = {
        "schema": SCHEMA_V02,
        "supported_schemas": [SCHEMA_V02, SCHEMA_V03],
        "optional_v03_fields": sorted(OPTIONAL_V03_FIELDS),
        "notes_checked": len(notes),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
        },
    }
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
