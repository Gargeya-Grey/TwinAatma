"""KnowledgeOS core library — portable markdown knowledge operations."""

from knowledgeos.parser import parse_frontmatter, split_frontmatter
from knowledgeos.schema import REQUIRED_FIELDS, SCHEMA_V02, SCHEMA_V03

__all__ = [
    "parse_frontmatter",
    "split_frontmatter",
    "REQUIRED_FIELDS",
    "SCHEMA_V02",
    "SCHEMA_V03",
]

FALLBACK_VERSION = "0.4.0"


def _detect_version() -> str:
    """Prefer the installed distribution's version.

    ``__version__`` used to be a hand-written string that disagreed with
    ``pyproject.toml``, so `twinaatma version` and the wheel metadata could report
    different numbers and a bug report would name the wrong build.
    """
    try:
        from importlib.metadata import version as _dist_version

        return _dist_version("twinaatma")
    except Exception:
        return FALLBACK_VERSION


__version__ = _detect_version()
