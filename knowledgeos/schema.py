"""Schema contracts for KnowledgeOS portable notes."""
from __future__ import annotations

SCHEMA_V02 = "knowledgeos-v0.2"
SCHEMA_V03 = "knowledgeos-v0.3"

REQUIRED_FIELDS = [
    "type",
    "title",
    "description",
    "status",
    "schema",
    "created",
    "updated",
    "tags",
]

RECOMMENDED_FOR_SOURCE = ["resource", "timestamp", "source_type"]

NOTE_TYPES_V02 = {
    "project",
    "research",
    "concept",
    "decision",
    "experiment",
    "synthesis",
    "meeting",
    "person",
    "moc",
    "index",
}

# Additive in v0.3 — validators warn, don't fail, on unknown until fully adopted
NOTE_TYPES_V03 = NOTE_TYPES_V02 | {
    "belief",
    "heuristic",
    "mental_model",
}

STATUS_VALUES = {"draft", "active", "refined", "archived", "completed"}

OUTCOME_STATUS_VALUES = {"pending", "confirmed", "invalidated", "superseded"}

# Optional additive fields introduced in v0.3
OPTIONAL_V03_FIELDS = {
    "id",
    "aliases",
    "confidence",
    "last_reviewed",
    "supersedes",
    "invalidates",
    "relations",
    "expected_outcome",
    "actual_outcome",
    "outcome_status",
    "lesson",
    "review_after",
    "publish_to_notion",
}

ID_PATTERN = r"^kos:[a-z0-9_]+:[a-z0-9][a-z0-9_-]*$"
