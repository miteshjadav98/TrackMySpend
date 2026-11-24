"""Category precedence and model fallback through the statement import API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from finance_core.categories.schemas import CategoryView
from finance_core.imports.categorise import StatementCategoryRow
from tests.conftest import register
from tests.integration.test_statement_imports import confirm, confirm_layout, make_account, upload


class _ScriptedCategorizer:
    """Capture model input and return controlled category labels."""

    def __init__(self, labels: dict[int, str], *, unavailable: bool = False) -> None:
        self.labels = labels
        self.unavailable = unavailable
        self.batches: list[list[StatementCategoryRow]] = []

    async def guess(
        self, categories: Sequence[CategoryView], rows: Sequence[StatementCategoryRow]
    ) -> dict[int, str]:
        assert categories
        self.batches.append(list(rows))
        if self.unavailable:
            raise RuntimeError("Model temporarily unavailable")
        return {
            row.position: self.labels[row.position] for row in rows if row.position in self.labels
        }


async def test_rules_win_and_invalid_model_labels_choose_other(
    client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)
    categories = await client.get("/api/v1/categories", params={"kind": "expense"})
    assert categories.status_code == 200, categories.text
    food = next(category for category in categories.json() if category["slug"] == "food")
    recorded = await client.post(
        "/api/v1/transactions",
        json={"type": "expense", "amount": "99", "merchant": "Swiggy", "categoryId": food["id"]},
    )
    assert recorded.status_code == 201, recorded.text
    model = _ScriptedCategorizer({1: "shopping", 2: "groceries", 3: "unknown_slug", 4: "salary"})
    monkeypatch.setattr(app.state.container, "statement_categorizer", model)
    statement = (
        "Date,Narration,Debit,Credit\n"
        "01/10/2026,UPI/100000999001/SWIGGY/syntheticfood@upi/DINNER ORDER,450.00,\n"
        "02/10/2026,POS/100000999002/DEMO STORE syntheticshop@upi ₹ 706.39,37.05,\n"
        "03/10/2026,UPI/100000999003/UBER/cabdemo@upi/CAB FARE,120.00,\n"
        "04/10/2026,POS/100000999004/PHARMACY,299.00,\n"
    ).encode()

    preview = await upload(client, await make_account(client), statement)

    assert [(row["category"]["slug"], row["categorySource"]) for row in preview["rows"]] == [
        ("food", "rule"),
        ("groceries", "ai"),
        ("other", "default"),
        ("other", "default"),
    ]
    [batch] = model.batches
    assert [row.position for row in batch] == [2, 3, 4]
    assert all(row.kind == "expense" for row in batch)
    model_text = " ".join(row.text for row in batch)
    assert "DEMO STORE" in model_text
    assert not any(token in model_text for token in ("100000999002", "@", "706.39", "37.05"))
    assert preview["rows"][1]["amountMinor"] == 3705


async def test_model_failure_uses_offline_keywords_and_the_statement_can_be_imported(
    client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)
    model = _ScriptedCategorizer({}, unavailable=True)
    monkeypatch.setattr(app.state.container, "statement_categorizer", model)
    statement = (
        b"Date,Narration,Debit,Credit\n"
        b"01/10/2026,POS/100000999005/APOLLO PHARMACY,450.00,\n"
        b"02/10/2026,NEFT CR/EXAMPLE TECH/PAYROLL SALARY/100000999006,,45000.00\n"
        b"03/10/2026,IMPS DR/EXAMPLE BENEFICIARY/100000999007,100.00,\n"
    )

    preview = await confirm_layout(
        client, await upload(client, await make_account(client), statement)
    )

    assert model.batches
    assert [(row["category"]["slug"], row["categorySource"]) for row in preview["rows"]] == [
        ("health", "keyword"),
        ("salary", "keyword"),
        ("other", "default"),
    ]
    saved = await confirm(client, preview["id"])
    assert saved["importedCount"] == 3


async def test_model_labels_are_requested_in_bounded_batches(
    client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)
    model = _ScriptedCategorizer({})
    monkeypatch.setattr(app.state.container, "statement_categorizer", model)
    lines = ["Date,Narration,Debit,Credit"]
    lines.extend(f"01/10/2026,DEMO SHOP {index},10.00," for index in range(51))

    preview = await upload(client, await make_account(client), "\n".join(lines).encode())

    assert preview["rowsTotal"] == 51
    assert sorted(len(batch) for batch in model.batches) == [1, 50]
    assert sorted(row.position for batch in model.batches for row in batch) == list(range(1, 52))
