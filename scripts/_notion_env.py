"""Helper: load NOTION_API_KEY from Hermes .env file if not already in env."""
import os

def get_notion_key():
    key = os.environ.get("NOTION_API_KEY")
    if key:
        return key
    
    # Try common Hermes .env locations
    candidates = [
        os.path.expanduser("~/.hermes/.env"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "hermes", ".env"))
    else:
        candidates.append(os.path.expanduser("~/AppData/Local/hermes/.env"))
    
    for path in candidates:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("NOTION_API_KEY"):
                        # Split on first = only
                        idx = line.index("=")
                        key = line[idx + 1:]
                        os.environ["NOTION_API_KEY"] = key
                        return key
    raise SystemExit(
        "NOTION_API_KEY not found. Set it in ~/.hermes/.env "
        "or run from a Hermes session."
    )

DS_ID = os.environ.get("NOTION_DATA_SOURCE_ID") or os.environ.get("NOTION_DATABASE_ID") or "42e1f487-0860-4366-b795-7a19c7b3bc8f"