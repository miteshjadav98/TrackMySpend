"""Labelled cases for the understanding step (today = Saturday 2026-10-24, Asia/Kolkata).

Each case lists only what must be true; unspecified fields are not asserted. The same cases
run against the offline rules engine (always) and against live Gemini (RUN_LIVE_LLM=1), so a
prompt or model change can be evaluated before it ships.
"""

from __future__ import annotations

from typing import Any

CASES: list[dict[str, Any]] = [
    {
        "text": "I spent ₹350 on dinner yesterday using UPI",
        "intent": "record_transactions",
        "transactions": [
            {"type": "expense", "amount": "350", "category": "food", "date": "2026-10-23",
             "payment_method": "upi"},
        ],
    },
    {
        "text": "uber 220 and lunch 180",
        "intent": "record_transactions",
        "transactions": [
            {"type": "expense", "amount": "220", "category": "transport"},
            {"type": "expense", "amount": "180", "category": "food"},
        ],
    },
    {
        "text": "Got salary 50k today",
        "intent": "record_transactions",
        "transactions": [{"type": "income", "amount": "50000", "category": "salary",
                          "date": "2026-10-24"}],
    },
    {
        "text": "paid 1,200 for electricity bill on 12 oct by credit card",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1200", "category": "utilities",
                          "date": "2026-10-12", "payment_method": "credit_card"}],
    },
    {
        "text": "received 2 lakh from a client for the freelance project",
        "intent": "record_transactions",
        "transactions": [{"type": "income", "amount": "200000", "category": "business"}],
    },
    {
        "text": "bought groceries from Blinkit for 845.50 via gpay",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "845.5", "category": "groceries",
                          "payment_method": "upi"}],
    },
    {
        "text": "I spent 500",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "500", "category": None}],
    },
    {"text": "how much did I spend this month?", "intent": "spending_summary",
     "period": {"kind": "this_month"}},
    {"text": "summarise last month for me", "intent": "spending_summary",
     "period": {"kind": "last_month"}},
    {"text": "show my food expenses last week", "intent": "search_transactions",
     "period": {"kind": "last_week"}, "search": {"category": "food"}},
    {"text": "what was my biggest expense in september", "intent": "search_transactions",
     "period": {"kind": "month", "month": "2026-09"}, "search": {"sort": "largest"}},
    {"text": "hi there", "intent": "smalltalk"},
    {"text": "what can you do?", "intent": "help"},
]  # fmt: skip


def check(case: dict[str, Any], understanding: Any) -> list[str]:
    """Return human-readable mismatches (empty list = pass)."""
    problems: list[str] = []
    if understanding.intent != case["intent"]:
        problems.append(f"intent {understanding.intent!r} != {case['intent']!r}")
        return problems
    expected_txs = case.get("transactions")
    if expected_txs is not None:
        if len(understanding.transactions) != len(expected_txs):
            problems.append(
                f"{len(understanding.transactions)} transactions != {len(expected_txs)}"
            )
            return problems
        for index, (got, want) in enumerate(
            zip(understanding.transactions, expected_txs, strict=True)
        ):
            for field, value in want.items():
                actual = getattr(got, field)
                if field == "amount" and actual is not None and value is not None:
                    from decimal import Decimal

                    if Decimal(actual) != Decimal(value):
                        problems.append(f"tx{index}.amount {actual!r} != {value!r}")
                    continue
                if actual != value:
                    problems.append(f"tx{index}.{field} {actual!r} != {value!r}")
    for section in ("period", "search"):
        expected = case.get(section)
        if expected:
            got = getattr(understanding, section)
            if got is None:
                problems.append(f"{section} missing")
                continue
            for field, value in expected.items():
                if getattr(got, field) != value:
                    problems.append(f"{section}.{field} {getattr(got, field)!r} != {value!r}")
    return problems
