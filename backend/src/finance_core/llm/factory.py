from __future__ import annotations

from finance_core.config import Settings
from finance_core.llm.base import LLMClient
from finance_core.llm.resilient import ResilientLLMClient
from finance_core.llm.rules import RulesLLMClient


def build_llm_client(settings: Settings) -> LLMClient:
    rules = RulesLLMClient()
    if settings.llm_provider == "rules":
        return rules
    from finance_core.llm.gemini import GeminiLLMClient  # heavy import; only when used

    return ResilientLLMClient(
        GeminiLLMClient(settings),
        rules if settings.llm_fallback_to_rules else None,
        timeout_seconds=settings.llm_total_budget_seconds,
    )
