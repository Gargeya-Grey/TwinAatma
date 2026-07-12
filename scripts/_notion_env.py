"""Load Notion credentials from environment or optional local config.

Never hardcode database IDs or API keys in the repository.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
VAULT_DIR = _SCRIPTS_DIR.parent
CONFIG_CANDIDATES = [
    VAULT_DIR / "knowledgeos.config.json",
    VAULT_DIR / ".knowledgeos.json",
]


def _load_dotenv_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(path)
    if not path.exists():
        return values
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def _hermes_env_candidates() -> list[Path]:
    candidates = [Path.home() / ".hermes" / ".env"]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "hermes" / ".env")
    else:
        candidates.append(Path.home() / "AppData" / "Local" / "hermes" / ".env")
    return candidates


def _vault_config() -> dict:
    for path in CONFIG_CANDIDATES:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def get_notion_key() -> str:
    key = os.environ.get("NOTION_API_KEY")
    if key:
        return key

    for path in _hermes_env_candidates():
        values = _load_dotenv_file(path)
        if values.get("NOTION_API_KEY"):
            os.environ["NOTION_API_KEY"] = values["NOTION_API_KEY"]
            if values.get("NOTION_DATABASE_ID") and not os.environ.get("NOTION_DATABASE_ID"):
                os.environ["NOTION_DATABASE_ID"] = values["NOTION_DATABASE_ID"]
            if values.get("NOTION_DATA_SOURCE_ID") and not os.environ.get("NOTION_DATA_SOURCE_ID"):
                os.environ["NOTION_DATA_SOURCE_ID"] = values["NOTION_DATA_SOURCE_ID"]
            return values["NOTION_API_KEY"]

    cfg = _vault_config().get("notion", {})
    if cfg.get("api_key"):
        os.environ["NOTION_API_KEY"] = cfg["api_key"]
        return cfg["api_key"]

    raise SystemExit(
        "NOTION_API_KEY not found.\n"
        "Set it in the environment, in knowledgeos.config.json under notion.api_key,\n"
        "or in ~/.hermes/.env (optional Hermes integration)."
    )


def get_notion_database_id() -> str:
    """Return Notion database/data-source id. Raises if unset (no hardcoded fallback)."""
    ds_id = (
        os.environ.get("NOTION_DATA_SOURCE_ID")
        or os.environ.get("NOTION_DATABASE_ID")
    )
    if ds_id:
        return ds_id

    for path in _hermes_env_candidates():
        values = _load_dotenv_file(path)
        ds_id = values.get("NOTION_DATA_SOURCE_ID") or values.get("NOTION_DATABASE_ID")
        if ds_id:
            return ds_id

    cfg = _vault_config().get("notion", {})
    ds_id = cfg.get("data_source_id") or cfg.get("database_id")
    if ds_id:
        return ds_id

    raise SystemExit(
        "NOTION_DATABASE_ID (or NOTION_DATA_SOURCE_ID) not found.\n"
        "Set it in the environment or in knowledgeos.config.json under\n"
        "notion.database_id / notion.data_source_id.\n"
        "See knowledgeos.config.example.json."
    )


def get_notion_config() -> dict:
    """Optional Notion property mapping overrides from vault config."""
    return _vault_config().get("notion", {})


# Back-compat alias used by older scripts — resolved lazily via property pattern.
# Scripts should call get_notion_database_id() instead of reading DS_ID at import time.
def __getattr__(name: str):
    if name == "DS_ID":
        return get_notion_database_id()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
