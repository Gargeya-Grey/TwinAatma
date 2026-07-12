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

__version__ = "0.3.0-dev"
