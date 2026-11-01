"""Choosing a preview row's category.

`CategoryPicker.pick` is the one place a row's category is decided. Today the order is the
user's merchant rule, else Other. Later steps (AI guesses, keyword fallback) slot in here
without the rest of the import code changing.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from finance_core.categories.defaults import FALLBACK_SLUG, CategoryKind
from finance_core.categories.service import CategoryService
from finance_core.imports.schemas import CategorySourceField
from finance_core.merchants.keys import merchant_key
from finance_core.merchants.service import MerchantRuleService


@dataclass(frozen=True, slots=True)
class CategoryChoice:
    category_id: uuid.UUID | None
    source: CategorySourceField


class CategoryPicker:
    """Picks categories for one import's rows.

    `prepare` looks up everything the rows need in a few queries; `pick` then answers per row
    without touching the database. Later steps (AI guesses) also run inside `prepare`, once
    per batch of rows.
    """

    def __init__(
        self,
        user_id: uuid.UUID,
        *,
        rules: MerchantRuleService,
        fallbacks: dict[str, uuid.UUID | None],
    ) -> None:
        self._user_id = user_id
        self._rules = rules
        self._fallbacks = fallbacks  # "expense"/"income" -> the Other category
        self._rule_categories: dict[tuple[str, str], uuid.UUID] = {}  # (type, merchant key)

    @classmethod
    async def for_user(
        cls, user_id: uuid.UUID, *, categories: CategoryService, rules: MerchantRuleService
    ) -> CategoryPicker:
        fallbacks: dict[str, uuid.UUID | None] = {}
        kinds: tuple[CategoryKind, ...] = ("expense", "income")
        for kind in kinds:
            other = await categories.by_slug(user_id, FALLBACK_SLUG[kind], kind)
            fallbacks[kind] = other.id if other else None
        return cls(user_id, rules=rules, fallbacks=fallbacks)

    async def prepare(self, wanted: Sequence[tuple[str, str | None]]) -> None:
        """Load the user's merchant rules for these (row type, merchant) pairs."""
        for row_type in ("expense", "income"):
            merchants = [merchant for kind, merchant in wanted if kind == row_type and merchant]
            found = await self._rules.categories_for_many(
                self._user_id, type=row_type, merchants=merchants
            )
            self._rule_categories.update({(row_type, key): cid for key, cid in found.items()})

    def pick(self, *, row_type: str, merchant: str | None) -> CategoryChoice:
        """`row_type` is "expense" or "income". The merchant rule wins; otherwise Other."""
        rule_category = self._rule_categories.get((row_type, merchant_key(merchant or "")))
        if rule_category is not None:
            return CategoryChoice(rule_category, "rule")
        return CategoryChoice(self._fallbacks[row_type], "default")
