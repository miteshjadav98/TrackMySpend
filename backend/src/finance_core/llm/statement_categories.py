"""Gemini adapter for classifying statement text in batches."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from finance_core.categories.defaults import FALLBACK_SLUGS
from finance_core.categories.schemas import CategoryView
from finance_core.config import Settings
from finance_core.imports.categorise import StatementCategorizer, StatementCategoryRow
from finance_core.llm import prompts

PROMPT_VERSION = "statement_categories_v1"
logger = logging.getLogger(__name__)


class CategoryLabel(BaseModel):
    """A label and its original statement row position."""

    model_config = ConfigDict(extra="forbid")
    position: int = Field(strict=True, ge=1, le=5000)
    slug: str | None = Field(max_length=64)


class StatementLabels(BaseModel):
    """Validated labels from one statement batch."""

    model_config = ConfigDict(extra="forbid")
    labels: list[CategoryLabel] = Field(max_length=50)


def _options(categories: Sequence[CategoryView], kind: Literal["expense", "income"]) -> str:
    return json.dumps(
        {
            item.slug: item.name
            for item in categories
            if item.kind == kind and item.slug not in FALLBACK_SLUGS
        },
        ensure_ascii=False,
    )


class GeminiStatementCategorizer:
    """Label statement text with a restricted structured response."""

    def __init__(self, settings: Settings) -> None:
        from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: PLC0415

        self._model = settings.llm_understand_model
        model = ChatGoogleGenerativeAI(
            model=self._model,
            vertexai=True,
            project=settings.gcp_project,
            location=settings.vertex_location,
            thinking_level=settings.llm_understand_thinking,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            labels={"app": "moneymoney", "task": "statement-categories"},
        )
        self._labeler = model.with_structured_output(StatementLabels, method="json_schema")

    async def guess(
        self, categories: Sequence[CategoryView], rows: Sequence[StatementCategoryRow]
    ) -> Mapping[int, str | None]:
        system = prompts.load(PROMPT_VERSION).format(
            expense_categories=_options(categories, "expense"),
            income_categories=_options(categories, "income"),
        )
        data = json.dumps(
            [{"position": row.position, "kind": row.kind, "text": row.text} for row in rows],
            ensure_ascii=False,
        )
        start = time.perf_counter()
        labels = await self._labeler.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=data)]
        )
        if not isinstance(labels, StatementLabels):
            raise ValueError("Unexpected statement category output")
        logger.info(
            "llm statement categories",
            extra={"llmModel": self._model, "promptVersion": PROMPT_VERSION,
                   "latencyMs": int((time.perf_counter() - start) * 1000), "rowCount": len(rows)},
        )  # fmt: skip
        result: dict[int, str | None] = {}
        for label in labels.labels:
            result[label.position] = label.slug if label.position not in result else None
        return result


def build_statement_categorizer(settings: Settings) -> StatementCategorizer | None:
    """Use the configured Gemini model or leave categorization to the offline rules."""
    return GeminiStatementCategorizer(settings) if settings.llm_provider == "gemini" else None
