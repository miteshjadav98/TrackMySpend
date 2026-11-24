# ruff: noqa: T201
"""Measure the statement prompt against labelled synthetic bank narrations on Vertex."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from statistics import median, quantiles
from typing import TypedDict, cast

import pytest

from finance_core.categories.defaults import SYSTEM_CATEGORIES, CategoryKind
from finance_core.categories.schemas import CategoryView
from finance_core.config import Settings
from finance_core.imports.categorise import StatementCategoryRow, category_text
from finance_core.imports.merchant import extract_merchant
from finance_core.llm.statement_categories import GeminiStatementCategorizer

CASES_PATH = Path(__file__).resolve().parents[1] / "evals" / "statement_categories_v1.json"


class Example(TypedDict):
    kind: CategoryKind
    description: str
    slug: str | None


@pytest.mark.live_llm
async def test_statement_categories_against_synthetic_bank_narrations() -> None:
    if os.environ.get("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 to call Gemini")
    env_file = os.environ.get("STATEMENT_EVAL_ENV_FILE", ".env")
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.gcp_project, "Set GCP_PROJECT for the Vertex categorization eval"
    labeler = GeminiStatementCategorizer(settings)
    cases = cast(list[Example], json.loads(CASES_PATH.read_text(encoding="utf-8")))
    assert 40 <= len(cases) <= 50
    options = [
        CategoryView(
            id=uuid.uuid4(),
            slug=entry.slug,
            name=entry.name,
            kind=entry.kind,
            icon=entry.icon,
            is_system=True,
        )
        for entry in SYSTEM_CATEGORIES
    ]
    rows = [
        StatementCategoryRow(
            position, case["kind"], category_text(extract_merchant(description), description)
        )
        for position, case in enumerate(cases, start=1)
        if (description := case["description"])
    ]
    latencies = []
    for run in range(1, 6):
        start = time.perf_counter()
        observed = await labeler.guess(options, rows)
        latency = (time.perf_counter() - start) * 1000
        latencies.append(latency)
        expected = {position: case["slug"] for position, case in enumerate(cases, start=1)}
        hits = sum(
            position in observed and observed[position] == slug
            for position, slug in expected.items()
        )
        print(f"Run {run}: {hits}/{len(cases)} ({hits / len(cases):.1%}), batch {latency:.0f} ms")
        mismatches = {
            position: (slug, observed.get(position))
            for position, slug in expected.items()
            if position not in observed or observed[position] != slug
        }
        if mismatches:
            print(f"Mismatches (expected, observed): {mismatches}")
        assert set(observed) == set(expected)
    p95 = quantiles(latencies, n=100, method="inclusive")[94]
    print(f"Batch latency across five runs: p50 {median(latencies):.0f} ms, p95 {p95:.0f} ms")
