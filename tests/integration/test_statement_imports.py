"""Importing CSV and Excel statements through the HTTP API with sample files."""

from __future__ import annotations

import asyncio
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
from tests.conftest import NOW, new_conversation, register, say

IMPORTS = "/api/v1/imports"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "statements"
HDFC = "hdfc_savings.csv"
SBI = "sbi_savings.csv"
AXIS = "axis_savings.csv"
ICICI = "icici_savings.xlsx"


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
    response = await client.put(
        f"{IMPORTS}/{detail['id']}/layout",
        params={"previewRevision": detail["previewRevision"]},
        json=detail["layout"],
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def confirm(
    client: httpx.AsyncClient,
    import_id: str,
    *,
    expect: int = 200,
    revision: int | None = None,
) -> dict[str, Any]:
    params = {"previewRevision": revision} if revision is not None else None
    response = await client.post(f"{IMPORTS}/{import_id}/confirm", params=params)
    assert response.status_code == expect, response.text
    return response.json()  # type: ignore[no-any-return]


async def import_statement(
    client: httpx.AsyncClient, account_id: str, name: str = HDFC
) -> dict[str, Any]:
    """Upload, accept the layout and confirm: the whole happy path."""
    detail = await upload(client, account_id, name)
    if not detail["layoutConfirmed"]:
        detail = await confirm_layout(client, detail)
    return await confirm(client, detail["id"], revision=detail["previewRevision"])


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
    assert (first["category"]["slug"], first["categorySource"]) == ("food", "keyword")
    assert (salary["category"]["slug"], salary["categorySource"]) == ("salary", "keyword")
    assert first["status"] == "to_import"
    assert first["isSelected"] is True
    assert detail["counts"] == {
        "toImport": 6, "skipped": 0, "likelyDuplicates": 0, "transfers": 0, "matchedTransfers": 0, "selected": 6,
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


async def test_a_semicolon_csv_with_a_ragged_preamble_is_read(client: httpx.AsyncClient) -> None:
    await register(client)
    detail = await upload(client, await make_account(client, "Axis Savings"), AXIS)
    assert detail["headers"][0] == "Tran Date"
    assert detail["sheetNames"] == []
    assert [(row["direction"], row["amountMinor"]) for row in detail["rows"]] == [
        ("out", 32550),
        ("in", 3500000),
    ]


async def test_excel_skips_the_cover_sheet_and_remembers_the_worksheet_the_user_chose(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client, "ICICI Savings")
    first = await upload(client, account_id, ICICI)
    assert first["sheetNames"] == ["Read me", "Savings", "Alternate"]
    assert first["sheetName"] == "Savings"
    date, amount = first["rows"][0]["occurredOn"], first["rows"][0]["amountMinor"]
    assert (date, amount) == ("2026-10-02", 45025)

    url = f"{IMPORTS}/{first['id']}/sheet"
    data = {"sheetName": "Alternate"}
    params = {"previewRevision": first["previewRevision"]}
    rejected = await client.put(
        url, params=params, data=data, files={"file": (ICICI, b"Different file")}
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "wrong_workbook"
    assert (await client.get(f"{IMPORTS}/{first['id']}")).json()["sheetName"] == "Savings"

    files = {"file": (ICICI, (FIXTURES / ICICI).read_bytes())}
    response = await client.put(url, params=params, data=data, files=files)
    assert response.status_code == 200, response.text
    switched = response.json()
    assert switched["id"] == first["id"]
    assert switched["sheetName"] == "Alternate"
    assert switched["layoutConfirmed"] is False  # The alternate sheet has the same headers.
    assert [row["amountMinor"] for row in switched["rows"]] == [12575]

    confirmed = await confirm_layout(client, switched)
    assert confirmed["layoutConfirmed"] is True
    done = await confirm(client, confirmed["id"], revision=confirmed["previewRevision"])
    assert done["importedCount"] == 1
    assert done["sheetName"] == "Alternate"
    assert done["sheetNames"] == []
    assert (await client.put(url, data={"sheetName": "Savings"}, files=files)).status_code == 409

    uploaded_again = await upload(client, account_id, ICICI)
    assert uploaded_again["sheetName"] == "Alternate"
    assert uploaded_again["layoutConfirmed"] is True
    assert uploaded_again["rows"][0]["status"] == "skipped"


async def test_a_stale_excel_preview_cannot_save_a_different_worksheet(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client, "ICICI Savings")
    first = await confirm_layout(client, await upload(client, account_id, ICICI))
    path = f"{IMPORTS}/{first['id']}"
    params = {"previewRevision": first["previewRevision"]}
    response = await client.put(
        f"{path}/sheet",
        params=params,
        data={"sheetName": "Alternate"},
        files={"file": (ICICI, (FIXTURES / ICICI).read_bytes())},
    )
    assert response.status_code == 200, response.text
    refused = await client.put(f"{path}/layout", params=params, json=first["layout"])
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "stale_preview"

    current = await confirm_layout(client, response.json())
    refused = await confirm(client, first["id"], expect=409, revision=first["previewRevision"])
    assert refused["error"]["code"] == "stale_preview"
    refused = await confirm(client, first["id"], expect=409)
    assert refused["error"]["code"] == "stale_preview"
    assert await transactions(client) == []
    saved = await confirm(client, first["id"], revision=current["previewRevision"])
    assert saved["importedCount"] == 1


async def test_a_blank_header_slot_cannot_reuse_a_layout_by_mistake(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    await confirm_layout(
        client, await upload(client, account_id, b"Date,Description,Amount\n02/10/2026,Tea,-50\n")
    )
    new = await upload(
        client, account_id, b"Date,Description,,Amount\n03/10/2026,Coffee,12345,-60\n"
    )
    assert new["layoutConfirmed"] is False
    assert new["layout"]["amountColumn"] == 3


@pytest.mark.parametrize(
    ("file_name", "data", "code"),
    [
        ("statement.xls", b"old binary file", "unsupported_workbook"),
        ("statement.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "protected_workbook"),
        ("statement.xlsx", b"PK\x03\x04corrupt workbook", "not_a_statement"),
    ],
)
async def test_excel_errors_explain_what_to_upload(
    client: httpx.AsyncClient, file_name: str, data: bytes, code: str
) -> None:
    await register(client)
    account_id = await make_account(client)
    response = await upload(client, account_id, data, file_name=file_name, expect=422)
    assert response["error"]["code"] == code
    assert ".xlsx" in response["error"]["message"]


async def test_a_merchant_rule_takes_priority_in_the_preview(client: httpx.AsyncClient) -> None:
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
    assert detail["rows"][1]["categorySource"] == "keyword"


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


async def test_two_previews_can_confirm_a_first_layout_for_the_same_account(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    first = await upload(client, account_id)
    second = await upload(client, account_id)

    results = await asyncio.gather(confirm_layout(client, first), confirm_layout(client, second))

    assert all(result["layoutConfirmed"] for result in results)
    assert (await upload(client, account_id))["layoutConfirmed"] is True


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
    assert again["counts"]["likelyDuplicates"] == 0
    assert {r["status"] for r in again["rows"]} == {"skipped"}
    assert {r["isSelected"] for r in again["rows"]} == {False}
    assert again["rows"][0]["note"] == "Already imported"

    done = await confirm(client, again["id"])
    assert (done["importedCount"], done["skippedCount"]) == (0, 6)
    assert len(await transactions(client)) == 6


async def test_a_chat_expense_matches_only_one_identical_row_and_can_be_ticked_back_on(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client, "HDFC")
    chat = await new_conversation(client)
    await say(client, chat, "paid 300 for lunch from HDFC")
    [saved] = await transactions(client)
    assert saved["source"] == "chat"
    assert saved["account"]["id"] == account_id
    csv = b"Date,Narration,Debit,Credit\n24/10/2026,Cafe,300.00,\n24/10/2026,Cafe,300.00,\n"

    detail = await confirm_layout(client, await upload(client, account_id, csv))
    first, second = detail["rows"]
    assert detail["counts"]["likelyDuplicates"] == 1
    assert detail["counts"]["selected"] == 1
    assert detail["counts"]["selectedOutMinor"] == 30000
    assert (first["status"], first["isSelected"]) == ("likely_duplicate", False)
    assert first["matchedTransaction"] == {
        "id": saved["id"],
        "description": saved["description"],
        "source": "chat",
    }
    assert (second["status"], second["isSelected"], second["matchedTransaction"]) == (
        "to_import", True, None,
    )  # fmt: skip

    filtered = await client.get(f"{IMPORTS}/{detail['id']}", params={"status": "likely_duplicate"})
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["rows"] == [first]

    ticked = await client.patch(
        f"{IMPORTS}/{detail['id']}/rows",
        json={"rows": [{"id": first["id"], "isSelected": True}]},
    )
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["counts"]["selected"] == 2
    assert ticked.json()["counts"]["selectedOutMinor"] == 60000
    done = await confirm(client, detail["id"])
    assert done["importedCount"] == 2
    assert len(await transactions(client)) == 3


async def test_an_exactly_reimported_row_does_not_match_a_new_payment(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    csv = b"Date,Narration,Debit,Credit\n24/10/2026,Lunch debit,300.00,\n"
    detail = await confirm_layout(client, await upload(client, account_id, csv))
    await confirm(client, detail["id"])

    again = await upload(client, account_id, csv + b"24/10/2026,Another lunch debit,300.00,\n")
    exact, new = again["rows"]
    assert (exact["status"], exact["note"]) == ("skipped", "Already imported")
    assert (new["status"], new["isSelected"]) == ("to_import", True)
    assert again["counts"]["likelyDuplicates"] == 0


@pytest.mark.parametrize("delete_match", [False, True])
async def test_confirming_rechecks_likely_duplicate_matches(
    client: httpx.AsyncClient, delete_match: bool
) -> None:
    await register(client)
    account_id = await make_account(client)
    saved = await client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount": "300",
            "accountId": account_id,
            "occurredOn": "2026-10-24",
        },
    )
    saved.raise_for_status()
    csv = b"Date,Narration,Debit,Credit\n24/10/2026,Cafe,300.00,\n24/10/2026,Tea,50.00,\n"
    first = await confirm_layout(client, await upload(client, account_id, csv))
    assert first["rows"][0]["status"] == "likely_duplicate"
    tx_path = f"/api/v1/transactions/{saved.json()['id']}"
    changed = (
        await client.delete(tx_path)
        if delete_match
        else await client.patch(tx_path, json={"version": 1, "amount": "350"})
    )
    changed.raise_for_status()

    refused = await confirm(client, first["id"], expect=409, revision=first["previewRevision"])
    assert refused["error"]["code"] == "stale_preview"
    path = f"{IMPORTS}/{first['id']}"
    refreshed = (await client.get(path)).json()
    row = refreshed["rows"][0]
    assert refreshed["previewRevision"] > first["previewRevision"]
    assert (row["status"], row["isSelected"], row["matchedTransaction"]) == (
        "to_import", False, None,
    )  # fmt: skip

    picked = await client.patch(
        f"{path}/rows",
        params={"previewRevision": refreshed["previewRevision"]},
        json={"rows": [{"id": row["id"], "isSelected": True}]},
    )
    picked.raise_for_status()
    done = await confirm(client, first["id"], revision=picked.json()["previewRevision"])
    assert done["importedCount"] == 2


async def test_matching_uses_only_live_transactions_for_the_same_account_date_and_direction(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    other = await make_account(client, "Other Savings")
    for kind, account, day in (
        ("income", account_id, "24"),
        ("expense", other, "24"),
        ("expense", account_id, "23"),
        ("expense", account_id, "24"),
    ):
        recorded = await client.post(
            "/api/v1/transactions",
            json={
                "type": kind,
                "amount": "300",
                "accountId": account,
                "occurredOn": f"2026-10-{day}",
            },
        )
        assert recorded.status_code == 201, recorded.text
        if (kind, account, day) == ("expense", account_id, "24"):
            deleted = await client.delete(f"/api/v1/transactions/{recorded.json()['id']}")
            assert deleted.status_code == 204, deleted.text

    csv = b"Date,Narration,Debit,Credit\n24/10/2026,Lunch debit,300.00,\n"
    preview = await upload(client, account_id, csv)
    [row] = preview["rows"]
    assert (row["status"], row["isSelected"]) == ("to_import", True)
    assert preview["counts"]["likelyDuplicates"] == 0


async def test_a_recorded_transfer_matches_the_direction_in_each_accounts_statement(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    sender = await make_account(client, "Sending account")
    receiver = await make_account(client, "Receiving account")
    recorded = await client.post(
        "/api/v1/transactions",
        json={
            "type": "transfer",
            "amount": "300",
            "accountId": sender,
            "toAccountId": receiver,
            "description": "Between my accounts",
            "occurredOn": "2026-10-24",
        },
    )
    assert recorded.status_code == 201, recorded.text
    csv = b"Date,Narration,Debit,Credit\n24/10/2026,Debit,300.00,\n24/10/2026,Credit,,300.00\n"

    outgoing = await upload(client, sender, csv)
    incoming = await upload(client, receiver, csv)

    assert [row["status"] for row in outgoing["rows"]] == ["likely_duplicate", "to_import"]
    assert [row["status"] for row in incoming["rows"]] == ["to_import", "likely_duplicate"]
    assert outgoing["rows"][0]["matchedTransaction"] == incoming["rows"][1]["matchedTransaction"]
    assert outgoing["rows"][0]["matchedTransaction"]["id"] == recorded.json()["id"]


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


async def test_rows_after_five_hundred_can_be_reviewed_and_changed(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account_id = await make_account(client)
    csv = "Date,Narration,Debit,Credit\n" + "24/10/2026,Tea,50.00,\n" * 601
    detail = await confirm_layout(client, await upload(client, account_id, csv.encode()))
    path = f"{IMPORTS}/{detail['id']}"
    page = await client.get(path, params={"limit": 200, "offset": 600})
    page.raise_for_status()
    body = page.json()
    assert body["rowsTotal"] == 601
    [last] = body["rows"]
    assert last["position"] == 601
    changed = await client.patch(
        f"{path}/rows",
        params={"previewRevision": body["previewRevision"]},
        json={"rows": [{"id": last["id"], "isSelected": False}]},
    )
    changed.raise_for_status()
    assert changed.json()["counts"]["selected"] == 600


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
