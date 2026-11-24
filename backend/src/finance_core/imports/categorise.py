"""Choose statement categories from merchant rules, model labels and offline keywords."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from finance_core.categories.defaults import (
    FALLBACK_SLUG,
    FALLBACK_SLUGS,
    CategoryKind,
    infer_category_slug,
)
from finance_core.categories.schemas import CategoryView
from finance_core.categories.service import CategoryService
from finance_core.imports.schemas import CategorySourceField
from finance_core.merchants.keys import merchant_key
from finance_core.merchants.service import MerchantRuleService

_BATCH_SIZE = 50
_PARALLEL_BATCHES = 4
_PREVIEW_BUDGET_SECONDS = 12.0
_HANDLES_AND_NUMBERS = re.compile(
    r"\b[\w.+-]+@[\w.]+\b"
    r"|(?:₹\s*|\b(?:INR|RS\.?)\s*)[+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:DR|CR)\b)?"
    r"|(?<!\w)[+-]?\d[\d,.]*(?:\s*(?:DR|CR)\b)?(?!\w)"
    r"|\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,}\b",
    re.IGNORECASE,
)
_BANK_DELIMITERS = re.compile(r"[/|;]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StatementCategoryRow:
    """Only the row reference, transaction direction and text needed to choose a category."""

    position: int
    kind: CategoryKind
    text: str


class StatementCategorizer(Protocol):
    """Batch labeler injected by the API when a model is configured."""

    async def guess(
        self, categories: Sequence[CategoryView], rows: Sequence[StatementCategoryRow]
    ) -> Mapping[int, str | None]: ...


@dataclass(frozen=True, slots=True)
class CategoryChoice:
    """The category shown in the preview and its source."""

    category_id: uuid.UUID | None
    source: CategorySourceField


def category_text(merchant: str | None, narration: str | None) -> str:
    """Keep useful words while removing handles, numeric amounts and bank references."""
    text = " ".join(dict.fromkeys(part[:1000] for part in (merchant, narration) if part))
    redacted = _HANDLES_AND_NUMBERS.sub(" ", text)
    return " ".join(_BANK_DELIMITERS.sub(" ", redacted).split())[:240]


async def pick_categories(
    user_id: uuid.UUID,
    *,
    categories: CategoryService,
    rules: MerchantRuleService,
    wanted: Sequence[tuple[StatementCategoryRow, str | None]],
    categorizer: StatementCategorizer | None,
) -> dict[int, CategoryChoice]:
    """Resolve rules first, then batch only the rows needing a category."""
    if not wanted:
        return {}
    visible = await categories.list_visible(user_id)
    # A personal category with the same slug takes priority over its system counterpart.
    ids = {
        (item.kind, item.slug): item.id
        for item in sorted(visible, key=lambda item: not item.is_system)
    }
    kinds: tuple[CategoryKind, ...] = ("expense", "income")
    merchant_rules = {
        kind: await rules.categories_for_many(
            user_id,
            type=kind,
            merchants=[merchant for row, merchant in wanted if row.kind == kind and merchant],
        )
        for kind in kinds
        if any(row.kind == kind and merchant for row, merchant in wanted)
    }
    choices: dict[int, CategoryChoice] = {}
    remaining = []
    for row, merchant in wanted:
        category_id = merchant_rules.get(row.kind, {}).get(merchant_key(merchant or ""))
        if category_id is None:
            remaining.append(row)
        else:
            choices[row.position] = CategoryChoice(category_id, "rule")
    await _guess_categories(remaining, visible, ids, categorizer, choices)
    return choices


async def _guess_categories(
    remaining: list[StatementCategoryRow],
    visible: list[CategoryView],
    ids: dict[tuple[CategoryKind, str], uuid.UUID],
    categorizer: StatementCategorizer | None,
    choices: dict[int, CategoryChoice],
) -> None:
    def fallback(row: StatementCategoryRow) -> CategoryChoice:
        slug = infer_category_slug(row.text, row.kind)
        if slug is not None and (key := ids.get((row.kind, slug))) is not None:
            return CategoryChoice(key, "keyword")
        return other(row)

    def other(row: StatementCategoryRow) -> CategoryChoice:
        return CategoryChoice(ids.get((row.kind, FALLBACK_SLUG[row.kind])), "default")

    if categorizer is None:
        choices.update((row.position, fallback(row)) for row in remaining)
        return
    for row in remaining:
        choices[row.position] = other(row)
    candidates = [row for row in remaining if row.text]
    pending = iter(
        candidates[start : start + _BATCH_SIZE] for start in range(0, len(candidates), _BATCH_SIZE)
    )
    finished: set[int] = set()

    async def worker() -> None:
        for batch in pending:
            try:
                labels = await categorizer.guess(visible, batch)
            except Exception as error:
                logger.warning(
                    "statement categorization failed", extra={"errorType": type(error).__name__}
                )
                for row in batch:
                    choices[row.position] = fallback(row)
            else:
                for row in batch:
                    label = labels.get(row.position)
                    if (
                        label
                        and label not in FALLBACK_SLUGS
                        and (key := ids.get((row.kind, label))) is not None
                    ):
                        choices[row.position] = CategoryChoice(key, "ai")
            finished.update(row.position for row in batch)

    try:
        async with asyncio.timeout(_PREVIEW_BUDGET_SECONDS):
            async with asyncio.TaskGroup() as tasks:
                for _ in range(
                    min(_PARALLEL_BATCHES, (len(candidates) + _BATCH_SIZE - 1) // _BATCH_SIZE)
                ):
                    tasks.create_task(worker())
    except TimeoutError:
        logger.warning("statement categorization timed out")
        for row in candidates:
            if row.position not in finished:
                choices[row.position] = fallback(row)
