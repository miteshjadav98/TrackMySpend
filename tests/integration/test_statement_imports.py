"""Importing a CSV statement end to end, through the HTTP API with real sample files."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from finance_core.clock import FixedClock
from tests.conftest import NOW, register

IMPORTS = "/api/v1/imports"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "statements"
HDFC = "hdfc_savings.csv"
SBI = "sbi_savings.csv"


async def make_account(client: httpx.AsyncClient, name: str = "HDFC Savings") -> str:
    created = await client.post("/api/v1/accounts", json={"name": name, "kind": "bank"})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def upload(
    client: httpx.AsyncClient,
    account_id: str,
    content: bytes | str = HDFC,
    *,
    file_name: str | None = None,
    expect: int = 201,
) -> dict[str, Any]:
    """Upload a fixture (by name) or raw bytes as a statement."""
    name = content if isinstance(content, str) else "statement.csv"
    data = (FIXTURES / content).read_bytes() if isinstance(content, str) else content
    response = await client.post(
        IMPORTS,
        data={"accountId": account_id},
        files={"file": (file_name or name, data, "text/csv")},
    )
    assert response.status_code == expect, response.text
    return response.json()  # type: ignore[no-any-return]


async def confirm_layout(client: httpx.AsyncClient, detail: dict[str, Any]) -> dict[str, Any]:
    """Accept the guessed layout as it is."""
    response = await client.put(f"{IMPORTS}/{detail['id']}/layout", json=detail["layout"])
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def confirm(
    client: httpx.AsyncClient, import_id: str, *, expect: int = 200
) -> dict[str, Any]:
    response = await client.post(f"{IMPORTS}/{import_id}/confirm")
    assert response.status_code == expect, response.text
    return response.json()  # type: ignore[no-any-return]


async def import_statement(
    client: httpx.AsyncClient, account_id: str, name: str = HDFC
) -> dict[str, Any]:
    """Upload, accept the layout and confirm: the whole happy path."""
    detail = await upload(client, account_id, name)
    if not detail["layoutConfirmed"]:
        detail = await confirm_layout(client, detail)
    return await confirm(client, detail["id"])


async def transactions(client: httpx.AsyncClient, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/transactions", params={"limit": "100", **params})
    return response.json()["items"]  # type: ignore[no-any-return]


@pytest.fixture
def clock_restored(clock: FixedClock) -> Iterator[FixedClock]:
    yield clock
    clock.set(NOW)


# -- the preview ---------------------------------------------------------------------------


async def test_an_uploaded_statement_is_previewed_with_its_guessed_layout(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    detail = await upload(client, account_id)

    assert detail["status"] == "previewing"
    assert detail["fileName"] == HDFC
    assert detail["account"]["name"] == "HDFC Savings"
    assert detail["headers"][:2] == ["Date", "Narration"]
    assert detail["layoutConfirmed"] is False
    assert detail["layout"] == {
        "dateColumn": 0, "descriptionColumn": 1, "amountColumn": None, "debitColumn": 4,
        "creditColumn": 5, "referenceColumn": 2, "dateOrder": "day_first",
    }  # fmt: skip
    assert len(detail["sampleRows"]) == 5
    assert detail["rowCount"] == detail["rowsTotal"] == 6

    first, salary = detail["rows"][0], detail["rows"][3]
    assert (first["occurredOn"], first["direction"], first["amountMinor"]) == (
        "2026-10-01", "out", 45000,
    )  # fmt: skip
    assert first["merchant"] == "SWIGGY"
    assert (salary["direction"], salary["amountMinor"]) == ("in", 12345678)
    assert first["category"]["slug"] == "other"
    assert first["categorySource"] == "default"
    assert salary["category"]["slug"] == "other_income"
    assert first["status"] == "to_import"
    assert first["isSelected"] is True
    assert detail["counts"] == {
        "toImport": 6, "skipped": 0, "likelyDuplicates": 0, "transfers": 0, "selected": 6,
        "selectedOutMinor": 45000 + 21800 * 2 + 231040 + 500000, "selectedInMinor": 12345678,
    }  # fmt: skip


async def test_nothing_is_saved_until_the_import_is_confirmed(client: httpx.AsyncClient) -> None:
    await register(client)
    await upload(client, await make_account(client))
    assert await transactions(client) == []


async def test_a_statement_with_account_details_above_the_table_is_read(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    detail = await upload(client, await make_account(client, "SBI Savings"), SBI)
    assert detail["headers"][0] == "Txn Date"
    assert detail["rowCount"] == 4
    assert detail["rows"][0]["occurredOn"] == "2026-10-01"
    assert detail["rows"][0]["merchant"] == "ZOMATO"
    assert detail["rows"][3]["amountMinor"] == 1234567


async def test_a_merchant_rule_files_a_row_instead_of_other(client: httpx.AsyncClient) -> None:
    await register(client)
    food = next(
        c for c in (await client.get("/api/v1/categories", params={"kind": "expense"})).json()
        if c["slug"] == "food"
    )  # fmt: skip
    await client.post(
        "/api/v1/transactions",
        json={"type": "expense", "amount": "99", "merchant": "SWIGGY", "categoryId": food["id"]},
    )
    detail = await upload(client, await make_account(client))
    swiggy = detail["rows"][0]
    assert swiggy["category"]["slug"] == "food"
    assert swiggy["categorySource"] == "rule"
    assert detail["rows"][1]["categorySource"] == "default"


async def test_changing_the_date_order_re_reads_every_date(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    month_first = {**detail["layout"], "dateOrder": "month_first"}
    response = await client.put(f"{IMPORTS}/{detail['id']}/layout", json=month_first)
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["occurredOn"] == "2026-01-10"


async def test_a_layout_naming_a_column_the_file_does_not_have_is_refused(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    response = await client.put(
        f"{IMPORTS}/{detail['id']}/layout", json={**detail["layout"], "dateColumn": 40}
    )
    assert response.status_code == 422


# -- confirming -----------------------------------------------------------------------------


async def test_a_new_layout_must_be_confirmed_before_the_import_is_saved(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    refused = await confirm(client, detail["id"], expect=409)
    assert refused["error"]["code"] == "layout_not_confirmed"


async def test_confirming_saves_every_ticked_row_as_an_imported_transaction(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    done = await import_statement(client, account_id)

    assert done["status"] == "imported"
    assert (done["importedCount"], done["skippedCount"]) == (6, 0)
    saved = await transactions(client)
    assert len(saved) == 6
    assert {t["source"] for t in saved} == {"import"}
    assert {t["account"]["id"] for t in saved} == {account_id}
    salary = next(t for t in saved if t["type"] == "income")
    assert (salary["amountMinor"], salary["occurredOn"]) == (12345678, "2026-10-05")
    assert salary["merchant"] == "ACME CORP"
    assert salary["description"].startswith("NEFT CR-")
    assert sorted(t["amountMinor"] for t in saved if t["type"] == "expense") == [
        21800,
        21800,
        45000,
        231040,
        500000,
    ]  # the two identical Uber rides are both kept


async def test_unticked_rows_are_not_imported(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await confirm_layout(client, await upload(client, await make_account(client)))
    atm = detail["rows"][5]
    changed = await client.patch(
        f"{IMPORTS}/{detail['id']}/rows", json={"rows": [{"id": atm["id"], "isSelected": False}]}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["counts"]["selected"] == 5

    done = await confirm(client, detail["id"])
    assert done["importedCount"] == 5
    assert 500000 not in [t["amountMinor"] for t in await transactions(client)]


async def test_a_rows_category_can_be_changed_in_the_preview(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await confirm_layout(client, await upload(client, await make_account(client)))
    groceries = next(
        c for c in (await client.get("/api/v1/categories", params={"kind": "expense"})).json()
        if c["slug"] == "groceries"
    )  # fmt: skip
    bigbasket = detail["rows"][4]
    changed = await client.patch(
        f"{IMPORTS}/{detail['id']}/rows",
        json={"rows": [{"id": bigbasket["id"], "categoryId": groceries["id"]}]},
    )
    row = next(r for r in changed.json()["rows"] if r["id"] == bigbasket["id"])
    assert (row["category"]["slug"], row["categorySource"]) == ("groceries", "user")

    await confirm(client, detail["id"])
    saved = next(t for t in await transactions(client) if t["amountMinor"] == 231040)
    assert saved["category"]["slug"] == "groceries"


async def test_an_income_category_cannot_be_put_on_an_expense_row(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    salary_category = next(
        c for c in (await client.get("/api/v1/categories", params={"kind": "income"})).json()
        if c["slug"] == "salary"
    )  # fmt: skip
    response = await client.patch(
        f"{IMPORTS}/{detail['id']}/rows",
        json={"rows": [{"id": detail["rows"][0]["id"], "categoryId": salary_category["id"]}]},
    )
    assert response.status_code == 422


async def test_only_categories_the_user_picked_teach_merchant_rules(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    detail = await confirm_layout(client, await upload(client, await make_account(client)))
    food = next(
        c for c in (await client.get("/api/v1/categories", params={"kind": "expense"})).json()
        if c["slug"] == "food"
    )  # fmt: skip
    await client.patch(
        f"{IMPORTS}/{detail['id']}/rows",
        json={"rows": [{"id": detail["rows"][0]["id"], "categoryId": food["id"]}]},
    )
    await confirm(client, detail["id"])

    rules = (await client.get("/api/v1/merchant-rules")).json()["items"]
    assert [(r["merchant"], r["category"]["slug"]) for r in rules] == [("SWIGGY", "food")]


async def test_confirming_twice_does_not_save_anything_twice(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await confirm_layout(client, await upload(client, await make_account(client)))
    await confirm(client, detail["id"])
    again = await confirm(client, detail["id"], expect=409)
    assert again["error"]["code"] == "import_not_previewing"
    assert len(await transactions(client)) == 6


async def test_every_import_and_its_transactions_are_audited(
    app: Any, client: httpx.AsyncClient
) -> None:
    me = await register(client)
    done = await import_statement(client, await make_account(client))
    await client.post(f"{IMPORTS}/{done['id']}/undo")
    async with app.state.container.session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.user_id == uuid.UUID(me["user"]["id"]))
                .where(AuditEvent.action.like("import.%") | AuditEvent.action.like("statement%"))
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
        created = (
            await session.scalars(
                select(AuditEvent.id).where(
                    AuditEvent.user_id == uuid.UUID(me["user"]["id"]),
                    AuditEvent.action == "transaction.created",
                )
            )
        ).all()
    assert actions == [
        "import.started", "statement_layout.saved", "import.confirmed", "import.undone"
    ]  # fmt: skip
    assert len(created) == 6


# -- importing again ------------------------------------------------------------------------


async def test_the_layout_is_remembered_for_the_account(client: httpx.AsyncClient) -> None:
    await register(client)
    account_id = await make_account(client)
    await import_statement(client, account_id)
    second = await upload(client, account_id)
    assert second["layoutConfirmed"] is True


async def test_another_accounts_statement_asks_for_its_own_layout(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    await import_statement(client, await make_account(client))
    other = await upload(client, await make_account(client, "HDFC Joint"))
    assert other["layoutConfirmed"] is False


async def test_importing_the_same_file_again_skips_every_row(client: httpx.AsyncClient) -> None:
    await register(client)
    account_id = await make_account(client)
    await import_statement(client, account_id)

    again = await upload(client, account_id)
    assert again["counts"]["skipped"] == 6
    assert again["counts"]["toImport"] == 0
    assert {r["status"] for r in again["rows"]} == {"skipped"}
    assert {r["isSelected"] for r in again["rows"]} == {False}
    assert again["rows"][0]["note"] == "Already imported"

    done = await confirm(client, again["id"])
    assert (done["importedCount"], done["skippedCount"]) == (0, 6)
    assert len(await transactions(client)) == 6


async def test_a_skipped_row_cannot_be_ticked(client: httpx.AsyncClient) -> None:
    await register(client)
    account_id = await make_account(client)
    await import_statement(client, account_id)
    again = await upload(client, account_id)
    response = await client.patch(
        f"{IMPORTS}/{again['id']}/rows",
        json={"rows": [{"id": again["rows"][0]["id"], "isSelected": True}]},
    )
    assert response.status_code == 422


async def test_undo_removes_everything_the_import_created(client: httpx.AsyncClient) -> None:
    await register(client)
    done = await import_statement(client, await make_account(client))
    undone = await client.post(f"{IMPORTS}/{done['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "undone"
    assert undone.json()["undoneAt"] is not None
    assert await transactions(client) == []


async def test_an_undone_import_can_be_imported_again(client: httpx.AsyncClient) -> None:
    await register(client)
    account_id = await make_account(client)
    first = await import_statement(client, account_id)
    await client.post(f"{IMPORTS}/{first['id']}/undo")

    redo = await upload(client, account_id)
    assert redo["counts"]["toImport"] == 6
    done = await confirm(client, redo["id"])
    assert done["importedCount"] == 6
    assert len(await transactions(client)) == 6


async def test_undo_only_works_on_a_saved_import(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    response = await client.post(f"{IMPORTS}/{detail['id']}/undo")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "import_not_imported"


async def test_a_preview_can_be_discarded(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    assert (await client.delete(f"{IMPORTS}/{detail['id']}")).status_code == 204
    assert (await client.get(f"{IMPORTS}/{detail['id']}")).status_code == 404


async def test_imports_are_listed_newest_first_without_their_rows(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    first = await import_statement(client, account_id)
    second = await upload(client, account_id)
    listed = (await client.get(IMPORTS)).json()
    assert [item["id"] for item in listed] == [second["id"], first["id"]]
    assert [item["status"] for item in listed] == ["previewing", "imported"]
    assert "rows" not in listed[0]


async def test_preview_rows_are_returned_a_page_at_a_time(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    page = await client.get(f"{IMPORTS}/{detail['id']}", params={"limit": 2, "offset": 4})
    body = page.json()
    assert [r["position"] for r in body["rows"]] == [5, 6]
    assert body["rowsTotal"] == 6
    only_income = await client.get(f"{IMPORTS}/{detail['id']}", params={"status": "to_import"})
    assert only_income.json()["rowsTotal"] == 6


# -- safety ---------------------------------------------------------------------------------


async def test_another_users_import_is_a_404_everywhere(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    intruder = make_client()
    await register(intruder)
    path = f"{IMPORTS}/{detail['id']}"
    row = {"rows": [{"id": detail["rows"][0]["id"], "isSelected": False}]}
    responses = [
        await intruder.get(path),
        await intruder.put(f"{path}/layout", json=detail["layout"]),
        await intruder.patch(f"{path}/rows", json=row),
        await intruder.post(f"{path}/confirm"),
        await intruder.post(f"{path}/undo"),
        await intruder.delete(path),
    ]
    assert [r.status_code for r in responses] == [404] * 6
    assert (await intruder.get(IMPORTS)).json() == []


async def test_another_users_account_cannot_be_imported_into(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    account_id = await make_account(client)
    intruder = make_client()
    await register(intruder)
    response = await intruder.post(
        IMPORTS,
        data={"accountId": account_id},
        files={"file": (HDFC, (FIXTURES / HDFC).read_bytes(), "text/csv")},
    )
    assert response.status_code == 404


async def test_an_archived_account_cannot_be_imported_into(client: httpx.AsyncClient) -> None:
    await register(client)
    account_id = await make_account(client)
    await client.patch(f"/api/v1/accounts/{account_id}", json={"isArchived": True})
    await upload(client, account_id, expect=422)


async def test_an_unconfirmed_preview_expires_after_a_day(
    client: httpx.AsyncClient, clock_restored: FixedClock
) -> None:
    await register(client)
    detail = await upload(client, await make_account(client))
    clock_restored.set(NOW + timedelta(hours=25))
    assert (await client.get(f"{IMPORTS}/{detail['id']}")).status_code == 404
    assert (await client.get(IMPORTS)).json() == []


async def test_a_saved_import_does_not_expire(
    client: httpx.AsyncClient, clock_restored: FixedClock
) -> None:
    await register(client)
    done = await import_statement(client, await make_account(client))
    clock_restored.set(NOW + timedelta(days=3))
    assert (await client.get(f"{IMPORTS}/{done['id']}")).status_code == 200


# -- limits and bad files -------------------------------------------------------------------


async def test_a_file_over_five_megabytes_is_refused(client: httpx.AsyncClient) -> None:
    await register(client)
    refused = await upload(
        client, await make_account(client), b"Date,Narration,Debit\n" + b"x" * (5 * 1024 * 1024),
        expect=413,
    )  # fmt: skip
    assert refused["error"]["code"] == "file_too_large"


async def test_a_file_over_five_thousand_rows_is_refused(client: httpx.AsyncClient) -> None:
    await register(client)
    lines = ["Date,Narration,Debit,Credit"] + ["01/10/2026,Coffee,10.00,"] * 5001
    refused = await upload(
        client, await make_account(client), "\n".join(lines).encode(), expect=413
    )
    assert refused["error"]["code"] == "too_many_rows"


async def test_five_thousand_rows_import_in_one_go(client: httpx.AsyncClient) -> None:
    await register(client)
    lines = ["Date,Narration,Debit,Credit"]
    lines += [f"{1 + i % 28:02d}/09/2026,Shop {i},{10 + i % 90}.00," for i in range(5000)]
    detail = await upload(client, await make_account(client), "\n".join(lines).encode())
    assert detail["counts"]["toImport"] == 5000
    detail = await confirm_layout(client, detail)
    done = await confirm(client, detail["id"])
    assert done["importedCount"] == 5000


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "empty_file"),
        (b"\n\n  \n", "empty_file"),
        (b"Date,Narration,Debit,Credit\n", "empty_file"),
        (b"hello,world\nnothing,here\n", "not_a_statement"),
        (b"PK\x03\x04\x00\x00binary", "not_a_statement"),
    ],
)
async def test_a_file_that_is_not_a_statement_gets_a_clear_error(
    client: httpx.AsyncClient, content: bytes, code: str
) -> None:
    await register(client)
    refused = await upload(client, await make_account(client), content, expect=422)
    assert refused["error"]["code"] == code


async def test_rows_that_cannot_be_read_are_shown_as_skipped_with_a_reason(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    csv = b"Date,Narration,Debit,Credit\n01/10/2026,Coffee,10.00,\nTotal,,10.00,\n"
    detail = await upload(client, await make_account(client), csv)
    coffee, total = detail["rows"]
    assert coffee["status"] == "to_import"
    assert (total["status"], total["isSelected"]) == ("skipped", False)
    assert "date" in total["note"]
    assert detail["counts"]["skipped"] == 1
