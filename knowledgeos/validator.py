"""Validate a vault's notes against the portable metadata schema (stdlib only)."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from knowledgeos.indexer import _is_conflict_copy
from knowledgeos.links import build_note_lookup, extract_raw_links, link_candidates
from knowledgeos.parser import split_frontmatter
from knowledgeos.schema import (
    ID_PATTERN,
    NOTE_TYPES_V03,
    OPTIONAL_V03_FIELDS,
    OUTCOME_STATUS_VALUES,
    RECOMMENDED_FOR_SOURCE,
    REQUIRED_FIELDS,
    SCHEMA_V02,
    SCHEMA_V03,
    SELF_PROPOSAL_STATUS_VALUES,
    STATUS_VALUES,
)

ID_RE = re.compile(ID_PATTERN)


def _is_template(rel_parts: tuple[str, ...]) -> bool:
    return "Templates" in rel_parts


def _existing_link_file(vault: Path, raw: str, source: str) -> bool:
    """Allow links to existing non-note files without traversing linked directories."""
    import urllib.parse
    from knowledgeos.indexer import _is_link

    target = urllib.parse.unquote(raw.split("|", 1)[0].split("#", 1)[0].strip()).replace("\\", "/")
    if not target:
        return True
    destinations = [vault / target.lstrip("/")]
    if getattr(raw, "markdown", False) and not target.startswith("/"):
        destinations.insert(0, vault / Path(source).parent / target)
    for destination in destinations:
        try:
            resolved = destination.resolve()
            resolved.relative_to(vault)
            if any(_is_link(parent) for parent in (destination, *destination.parents) if parent != vault and vault in parent.parents):
                continue
            if resolved.is_file():
                return True
        except (OSError, ValueError):
            continue
    return False


def _is_index_or_moc(fm: dict) -> bool:
    return fm.get("type") in ("index", "moc")


def validate_vault(vault: Path | str) -> dict[str, Any]:
    vault = Path(vault).resolve()
    notes: list[str] = []
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_ids: dict[str, str] = {}

    # `iter_markdown` walks without following links and confirms each file resolves
    # inside the vault, so `validate` cannot be pointed at files outside it — and it
    # reports the same file set the indexer uses, instead of a silently different one.
    from knowledgeos.indexer import iter_markdown

    # One definition of "a note", used by both this module and the indexer. They used to
    # keep separate skip lists, which drifted (`.cursor`, `docs`, `.commandcode` were in
    # one and not the other), so `validate` reported errors for files `search` had never
    # indexed and vice versa.
    files = iter_markdown(vault)
    lookup = build_note_lookup(files, vault)
    for path in files:
        rel_parts = path.relative_to(vault).parts
        # `init` keeps an unmerged conflict copy beside a user's file as `*.new.md`.
        # It is not a note, and validating it reports the user's own edit as an error.
        # `iter_markdown` already drops these; the check stays because this loop should
        # not depend on a second module's private behaviour for correctness.
        if _is_conflict_copy(path):
            continue
        rel = path.relative_to(vault).as_posix()
        notes.append(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, body = split_frontmatter(text)
        links = extract_raw_links(body)
        is_template = _is_template(rel_parts)

        if not fm:
            errors.append({"path": rel, "issue": "missing_frontmatter"})
            continue

        missing = [k for k in REQUIRED_FIELDS if not fm.get(k)]
        if is_template:
            missing = [k for k in missing if k not in {"description", "tags"}]
        if missing:
            errors.append({"path": rel, "issue": "missing_required_fields", "fields": missing})

        note_type = fm.get("type")
        if note_type and (not isinstance(note_type, str) or note_type not in NOTE_TYPES_V03) and not is_template:
            warnings.append({"path": rel, "issue": "unknown_type", "type": note_type})

        schema_ver = fm.get("schema")
        if schema_ver and (not isinstance(schema_ver, str) or schema_ver not in {SCHEMA_V02, SCHEMA_V03}):
            errors.append({"path": rel, "issue": "unknown_schema_version", "schema": schema_ver})

        if not is_template:
            status = fm.get("status")
            status_values = STATUS_VALUES
            if (path.parent == vault / "People" / "Self-Proposals"
                    and note_type == "research"
                    and fm.get("proposal_target") == "People/Self.md"
                    and fm.get("proposal_origin") == "memory_propose_self_update"):
                status_values = SELF_PROPOSAL_STATUS_VALUES
            if status and (not isinstance(status, str) or status not in status_values):
                errors.append({"path": rel, "issue": "invalid_status", "status": status})
            for field in ("created", "updated", "last_reviewed", "review_after"):
                value = fm.get(field)
                if value in (None, ""):
                    continue
                try:
                    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                        raise ValueError("Expected YYYY-MM-DD")
                    date.fromisoformat(value)
                except ValueError:
                    errors.append({"path": rel, "issue": "invalid_date", "field": field, "value": value})
            tags = fm.get("tags")
            if tags is not None and (not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags)):
                errors.append({"path": rel, "issue": "invalid_tags", "tags": tags})
            for raw in links:
                matches = link_candidates(raw, rel, lookup)
                if len(matches) > 1:
                    errors.append({"path": rel, "issue": "ambiguous_link", "target": str(raw), "candidates": matches})
                elif not matches and not _existing_link_file(vault, raw, rel):
                    errors.append({"path": rel, "issue": "broken_link", "target": str(raw)})

        entity_id = fm.get("id")
        if entity_id:
            if not ID_RE.match(str(entity_id)):
                errors.append({"path": rel, "issue": "invalid_id_format", "id": entity_id})
            elif entity_id in seen_ids:
                errors.append(
                    {"path": rel, "issue": "duplicate_id", "id": entity_id, "other": seen_ids[entity_id]}
                )
            else:
                seen_ids[entity_id] = rel

        outcome_status = fm.get("outcome_status")
        if outcome_status and (not isinstance(outcome_status, str) or outcome_status not in OUTCOME_STATUS_VALUES):
            errors.append(
                {"path": rel, "issue": "invalid_outcome_status", "outcome_status": outcome_status}
            )

        confidence = fm.get("confidence")
        if confidence not in (None, ""):
            try:
                c = float(confidence)
                if c < 0 or c > 1:
                    warnings.append({"path": rel, "issue": "confidence_out_of_range", "confidence": confidence})
            except (TypeError, ValueError):
                warnings.append({"path": rel, "issue": "confidence_not_numeric", "confidence": confidence})

        if not links and not _is_index_or_moc(fm) and not is_template:
            warnings.append({"path": rel, "issue": "no_links"})

        sourceish = bool(fm.get("source_type") or fm.get("resource"))
        if sourceish and not is_template:
            missing_source = [k for k in RECOMMENDED_FOR_SOURCE if not fm.get(k)]
            if missing_source:
                warnings.append(
                    {"path": rel, "issue": "missing_source_provenance", "fields": missing_source}
                )

    from knowledgeos.remembering import RememberingPolicy
    policy = RememberingPolicy(vault)
    for diagnostics in (errors, warnings):
        for index, diagnostic in enumerate(diagnostics):
            path = diagnostic.get("path")
            if path and policy.read(vault / path) is None:
                diagnostics[index] = {key: value for key, value in diagnostic.items()
                                      if key in {"issue", "field", "fields"}}
                diagnostics[index].update(path="[Excluded source]", redacted=True)
            else:
                diagnostics[index] = policy.scrub(diagnostic)
    return {
        "schema": SCHEMA_V02,
        "supported_schemas": [SCHEMA_V02, SCHEMA_V03],
        "optional_v03_fields": sorted(OPTIONAL_V03_FIELDS),
        "notes_checked": len(notes),
        "errors": errors,
        "warnings": warnings,
        "summary": {"errors": len(errors), "warnings": len(warnings)},
    }
