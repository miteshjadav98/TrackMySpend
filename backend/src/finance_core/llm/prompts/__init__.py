"""Versioned prompt templates.

Prompts are product behaviour: they live in files, are reviewed like code, and carry a
version that is logged with every model call so a behaviour change can be traced to the
prompt that caused it.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

UNDERSTAND_PROMPT_VERSION = "understand_v1"
REPLY_PROMPT_VERSION = "reply_v1"


@lru_cache(maxsize=16)
def load(name: str) -> str:
    return files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")
