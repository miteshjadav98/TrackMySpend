from __future__ import annotations

import os
from datetime import date

import pytest

from finance_core.categories.defaults import SYSTEM_CATEGORIES
from finance_core.llm.base import CategoryHint, UnderstandRequest
from finance_core.llm.rules import RulesLLMClient
from tests.evals.understanding_cases import CASES, check

TODAY = date(2026, 10, 24)
CATEGORIES = [CategoryHint(c.slug, c.name, c.kind) for c in SYSTEM_CATEGORIES]


def _request(text: str) -> UnderstandRequest:
    return UnderstandRequest(
        text=text,
        today=TODAY,
        timezone="Asia/Kolkata",
        base_currency="INR",
        locale="en-IN",
        categories=CATEGORIES,
    )


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:40] for c in CASES])
async def test_rules_engine_understanding(case: dict) -> None:
    result = await RulesLLMClient().understand(_request(case["text"]))
    assert check(case, result.understanding) == []


@pytest.mark.live_llm
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1", reason="set RUN_LIVE_LLM=1 to call Gemini"
)
async def test_gemini_understanding_eval() -> None:
    """Scores the production pipeline (live model + reconciliation); fails below 90%."""
    from finance_core.config import get_settings
    from finance_core.llm.gemini import GeminiLLMClient
    from finance_core.workflows.reconcile import reconcile

    client = GeminiLLMClient(get_settings())
    failures = {}
    for case in CASES:
        result = await client.understand(_request(case["text"]))
        understanding = reconcile(result.understanding, case["text"], today=TODAY, locale="en-IN")
        problems = check(case, understanding)
        if problems:
            failures[case["text"]] = problems
    score = 1 - len(failures) / len(CASES)
    assert score >= 0.9, f"score {score:.0%}; failures: {failures}"
