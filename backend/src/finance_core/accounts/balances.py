"""Account cash movements and dated balances, read in one Postgres snapshot."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.accounts.models import LIABILITY_KINDS
from finance_core.accounts.schemas import (
    AccountBalanceView,
    AccountOverview,
    AccountRef,
    BalanceAnchor,
    BalanceLedger,
    BalanceMovement,
    CurrencyPosition,
)
from finance_core.clock import Clock
from finance_core.errors import NotFoundError
from finance_core.schemas import MoneyAmount
from finance_core.users.context import UserContext

# A share transaction provides its owner's account tag. Only the actual payer moved cash.
# Imported transactions already include both sides of reconciled transfers.
_MOVEMENTS = """
SELECT a.id AS account_id, m.* FROM target a
CROSS JOIN LATERAL (
    SELECT CASE WHEN t.shared_expense_id IS NULL THEN 'transaction' ELSE 'shared_expense' END AS source_kind,
           coalesce(t.shared_expense_id, t.id) AS source_id, t.occurred_on, t.currency,
           CASE WHEN s.id IS NOT NULL THEN -s.total_minor
                WHEN t.type = 'income' OR t.to_account_id = a.id THEN t.amount_minor
                ELSE -t.amount_minor END AS cash
    FROM ledger.transactions t
    LEFT JOIN ledger.shared_expenses s ON s.id = t.shared_expense_id
    LEFT JOIN ledger.friends f ON f.id = s.payer_friend_id
    WHERE t.user_id = a.user_id AND t.deleted_at IS NULL
      AND (t.account_id = a.id OR t.to_account_id = a.id)
      AND (s.id IS NULL OR (s.payer_friend_id IS NULL AND s.recorder_id = a.user_id)
           OR f.linked_user_id = a.user_id)
    UNION ALL
    SELECT 'settlement', p.id, p.occurred_on, p.currency,
           CASE WHEN (p.recorder_id = a.user_id) = p.paid_by_recorder
                THEN -p.amount_minor ELSE p.amount_minor END
    FROM ledger.settlements p
    JOIN ledger.friends f ON f.id = p.friend_id
    WHERE (p.recorder_id = a.user_id AND p.recorder_account_id = a.id)
       OR (f.linked_user_id = a.user_id AND p.friend_account_id = a.id)
) m
WHERE m.occurred_on >= a.anchor_date AND m.occurred_on <= :today
"""


class AccountBalanceService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def accounts(
        self,
        ctx: UserContext,
        *,
        include_archived: bool = False,
        account_id: uuid.UUID | None = None,
    ) -> list[AccountBalanceView]:
        where = "user_id = :user_id"
        if account_id is not None:
            where += " AND id = :account_id"
        elif not include_archived:
            where += " AND NOT is_archived"
        sql = f"""
            WITH target AS (SELECT * FROM ledger.accounts WHERE {where}), movements AS ({_MOVEMENTS}),
            totals AS (
                SELECT m.account_id, sum(m.cash) FILTER (WHERE m.currency = a.currency) AS cash,
                       bool_or(m.currency <> a.currency) AS mismatch
                FROM movements m JOIN target a ON a.id = m.account_id GROUP BY m.account_id
            )
            SELECT a.*, totals.cash, totals.mismatch
            FROM target a LEFT JOIN totals ON totals.account_id = a.id
            ORDER BY a.is_archived, lower(a.name), a.id
        """  # noqa: S608
        rows = (
            await self.session.execute(
                text(sql),
                {"user_id": ctx.user_id, "account_id": account_id, "today": ctx.today(self.clock)},
            )
        ).mappings()
        result = []
        for row in rows:
            anchor = None
            amount = None
            state = "missing_anchor"
            if row.anchor_date is not None:
                anchor = BalanceAnchor(as_of=row.anchor_date, amount_minor=row.anchor_minor)
                state = "currency_mismatch"
                if not row.mismatch:
                    cash = int(row.cash or 0)
                    liability = row.kind in LIABILITY_KINDS
                    minor = row.anchor_minor + (-cash if liability else cash)
                    amount = MoneyAmount.of(minor, row.currency, ctx.locale)
                    state = (
                        ("owed" if minor >= 0 else "credit")
                        if liability
                        else ("held" if minor >= 0 else "overdraft")
                    )
            result.append(
                AccountBalanceView.model_validate(
                    dict(row, balance_anchor=anchor, balance=amount, balance_state=state)
                )
            )
        return result

    async def one(self, ctx: UserContext, account_id: uuid.UUID) -> AccountBalanceView:
        rows = await self.accounts(ctx, account_id=account_id)
        if not rows:
            raise NotFoundError("Account not found")
        return rows[0]

    async def overview(self, ctx: UserContext) -> AccountOverview:
        accounts = await self.accounts(ctx)
        groups: dict[str, list[AccountBalanceView]] = defaultdict(list)
        for account in accounts:
            groups[account.currency].append(account)
        positions = []
        for currency in sorted(groups, key=lambda c: (c != ctx.base_currency, c)):
            assets = liabilities = 0
            excluded = []
            for account in groups[currency]:
                if account.balance is None:
                    excluded.append(AccountRef.model_validate(account))
                elif account.kind in LIABILITY_KINDS:
                    liabilities += account.balance.amount_minor
                else:
                    assets += account.balance.amount_minor
            positions.append(
                CurrencyPosition(
                    currency=currency,
                    assets=MoneyAmount.of(assets, currency, ctx.locale),
                    liabilities=MoneyAmount.of(liabilities, currency, ctx.locale),
                    net=MoneyAmount.of(assets - liabilities, currency, ctx.locale),
                    excluded_accounts=excluded,
                )
            )
        return AccountOverview(accounts=accounts, positions=positions)

    async def ledger(
        self, ctx: UserContext, account_id: uuid.UUID, limit: int, offset: int
    ) -> BalanceLedger:
        sql = f"""
            WITH target AS (SELECT * FROM ledger.accounts WHERE user_id = :user_id AND id = :account_id),
            movements AS ({_MOVEMENTS}), running AS (
              SELECT m.*, a.currency AS account_currency,
                     CASE WHEN NOT bool_or(m.currency <> a.currency) OVER w THEN
                       a.anchor_minor + sum(m.cash) OVER w *
                       CASE WHEN a.kind IN ('loan','credit_card') THEN -1 ELSE 1 END
                     END AS balance_after
              FROM movements m JOIN target a ON m.account_id = a.id
              WINDOW w AS (ORDER BY occurred_on, source_id, source_kind ROWS UNBOUNDED PRECEDING)
            ), page AS (SELECT * FROM running ORDER BY occurred_on DESC,source_id DESC,source_kind DESC
                       LIMIT :limit OFFSET :offset)
            SELECT p.* FROM target LEFT JOIN page p ON true
            ORDER BY p.occurred_on DESC,p.source_id DESC,p.source_kind DESC
        """  # noqa: S608 -- only the constant movement query is interpolated
        rows = (
            (
                await self.session.execute(
                    text(sql),
                    {
                        "user_id": ctx.user_id,
                        "account_id": account_id,
                        "today": ctx.today(self.clock),
                        "limit": limit + 1,
                        "offset": offset,
                    },
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            raise NotFoundError("Account not found")
        items = [
            BalanceMovement(
                source_kind=r.source_kind,
                source_id=r.source_id,
                occurred_on=r.occurred_on,
                cash_effect=MoneyAmount.of(r.cash, r.currency, ctx.locale),
                balance_after=MoneyAmount.of(int(r.balance_after), r.account_currency, ctx.locale)
                if r.balance_after is not None
                else None,
            )
            for r in rows[:limit]
            if r.source_id is not None
        ]
        return BalanceLedger(items=items, next_offset=offset + limit if len(rows) > limit else None)
