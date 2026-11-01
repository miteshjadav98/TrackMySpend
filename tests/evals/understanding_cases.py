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
    # Transfers between the user's own accounts (the eval's accounts: HDFC, Paytm, SBI, ICICI).
    {
        "text": "moved 5000 from HDFC to Paytm",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "5000", "account": "HDFC",
                          "to_account": "Paytm", "category": None}],
    },
    {
        "text": "transferred 12,000 from SBI to my ICICI account yesterday",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "12000", "account": "SBI",
                          "to_account": "ICICI", "date": "2026-10-23"}],
    },
    {
        "text": "withdrew 2000 from SBI",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "2000", "account": "SBI",
                          "to_account": "Cash", "category": None}],
    },
    {
        "text": "paid 15000 credit card bill from HDFC",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "15000", "account": "HDFC",
                          "to_account": "Credit card", "category": None}],
    },
    {
        "text": "sent 3000 from Paytm to HDFC on 20 oct",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "3000", "account": "Paytm",
                          "to_account": "HDFC", "date": "2026-10-20"}],
    },
    {
        "text": "moved 800 to Paytm",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "800", "account": None,
                          "to_account": "Paytm"}],
    },
    {
        "text": "transfer 2.5k from ICICI to SBI today",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "2500", "account": "ICICI",
                          "to_account": "SBI", "date": "2026-10-24"}],
    },
    {
        "text": "cash withdrawal of 1500 from ICICI ATM",
        "intent": "record_transactions",
        "transactions": [{"type": "transfer", "amount": "1500", "account": "ICICI",
                          "to_account": "Cash"}],
    },
    {"text": "show my transfers this month", "intent": "search_transactions",
     "period": {"kind": "this_month"}, "search": {"type": "transfer"}},
    # Ordinary bills and card spending are not transfers.
    {
        "text": "paid 800 for the phone bill from HDFC",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "800"}],
    },
    {"text": "hi there", "intent": "smalltalk"},
    {"text": "what can you do?", "intent": "help"},
    # Expenses and income tagged with one of the user's accounts: the account is never the merchant.
    {
        "text": "paid 300 for lunch from HDFC",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "300", "category": "food",
                          "account": "HDFC", "merchant": None}],
    },
    {
        "text": "salary 50000 into HDFC",
        "intent": "record_transactions",
        "transactions": [{"type": "income", "amount": "50000", "category": "salary",
                          "account": "HDFC", "merchant": None}],
    },
    {
        "text": "bought groceries for 1200 using my SBI account yesterday",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1200", "category": "groceries",
                          "account": "SBI", "date": "2026-10-23", "merchant": None}],
    },
    {
        "text": "spent 450 on dinner at Dominos from Paytm",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "450", "category": "food",
                          "account": "Paytm", "merchant": "Dominos"}],
    },
    {
        "text": "received 2000 refund on ICICI account today",
        "intent": "record_transactions",
        "transactions": [{"type": "income", "amount": "2000", "account": "ICICI",
                          "merchant": None, "date": "2026-10-24"}],
    },
    {
        "text": "paid 250 for a taxi from the office",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "250", "category": "transport",
                          "account": None}],
    },
    # -- shared expenses (Phase 3) --
    {
        "text": "me and Jaymin spent 1000 on pizza, split it",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1000", "category": "food",
                          "participants": ["Jaymin"], "payer": None, "split": "equal"}],
    },
    {
        "text": "Jaymin paid 1000 for pizza, split it",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1000", "category": "food",
                          "participants": ["Jaymin"], "payer": "Jaymin", "split": "equal"}],
    },
    {
        "text": "me, Jaymin and Riya spent 1500 on cab, split it",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1500", "category": "transport",
                          "participants": ["Jaymin", "Riya"], "payer": None, "split": "equal"}],
    },
    {
        "text": "dinner 1000 with Jaymin, I had 400 and he had 600",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1000", "category": "food",
                          "participants": ["Jaymin"], "split": "exact",
                          "shares": [{"person": "me", "amount": "400"},
                                     {"person": "Jaymin", "amount": "600"}]}],
    },
    {
        "text": "split 1200 for movie tickets with Riya",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "1200", "category": "entertainment",
                          "participants": ["Riya"], "split": "equal"}],
    },
    {
        "text": "I paid 2400 for the hotel, split equally with Jaymin and Riya yesterday",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "2400", "participants": ["Jaymin", "Riya"],
                          "payer": None, "date": "2026-10-23"}],
    },
    {
        "text": "Riya paid 900 for groceries, split with me",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "900", "category": "groceries",
                          "participants": ["Riya"], "payer": "Riya"}],
    },
    {
        "text": "me and Jaymin spent 800 on lunch from HDFC, split it",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "800", "category": "food",
                          "participants": ["Jaymin"], "account": "HDFC"}],
    },
    {
        "text": "coffee with Jaymin 200",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "200", "participants": []}],
    },
    # -- settlements, balances and the shared list (Phase 3) --
    {
        "text": "Jaymin paid me 500",
        "intent": "record_settlement",
        "settlement": {"friend": "Jaymin", "direction": "friend_paid_me", "amount": "500"},
    },
    {
        "text": "Riya gave me back 1200",
        "intent": "record_settlement",
        "settlement": {"friend": "Riya", "direction": "friend_paid_me", "amount": "1200"},
    },
    {
        "text": "paid Jaymin back 500",
        "intent": "record_settlement",
        "settlement": {"friend": "Jaymin", "direction": "i_paid_friend", "amount": "500"},
    },
    {
        "text": "I paid Riya 300 to settle up",
        "intent": "record_settlement",
        "settlement": {"friend": "Riya", "direction": "i_paid_friend", "amount": "300"},
    },
    {
        "text": "Jaymin paid me 500 to HDFC",
        "intent": "record_settlement",
        "settlement": {"friend": "Jaymin", "direction": "friend_paid_me", "amount": "500",
                       "account": "HDFC"},
    },
    {
        "text": "Riya sent me 750 yesterday",
        "intent": "record_settlement",
        "settlement": {"friend": "Riya", "direction": "friend_paid_me", "amount": "750",
                       "date": "2026-10-23"},
    },
    {
        "text": "paid Ramesh 2000 for his old phone",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "2000"}],
    },
    {
        "text": "paid Riya 800 for the movie tickets",
        "intent": "record_transactions",
        "transactions": [{"type": "expense", "amount": "800"}],
    },
    {
        "text": "how much does Jaymin owe me?",
        "intent": "balance_question",
        "balance": {"friend": "Jaymin"},
    },
    {
        "text": "do I owe Riya anything?",
        "intent": "balance_question",
        "balance": {"friend": "Riya"},
    },
    {"text": "who owes me money?", "intent": "balance_question", "balance": {"friend": None}},
    {
        "text": "show my shared expenses this month",
        "intent": "search_transactions",
        "search": {"shared": True},
        "period": {"kind": "this_month"},
    },
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
                if field == "participants":  # names in order, ignoring case
                    if [n.casefold() for n in actual] != [n.casefold() for n in value]:
                        problems.append(f"tx{index}.participants {actual!r} != {value!r}")
                    continue
                if field == "payer":
                    if (actual or "").casefold() != (value or "").casefold():
                        problems.append(f"tx{index}.payer {actual!r} != {value!r}")
                    continue
                if field == "shares":  # who had what, ignoring case and number formatting
                    from decimal import Decimal

                    got_shares = {(x.person.casefold(), Decimal(x.amount)) for x in actual}
                    want_shares = {(x["person"].casefold(), Decimal(x["amount"])) for x in value}
                    if got_shares != want_shares:
                        problems.append(
                            f"tx{index}.shares {sorted(got_shares)} != {sorted(want_shares)}"
                        )
                    continue
                if field in ("account", "to_account") and isinstance(value, str):
                    if (actual or "").casefold() != value.casefold():  # names ignore case
                        problems.append(f"tx{index}.{field} {actual!r} != {value!r}")
                    continue
                if actual != value:
                    problems.append(f"tx{index}.{field} {actual!r} != {value!r}")
    for section in ("settlement", "balance"):
        expected = case.get(section)
        if expected:
            got = getattr(understanding, section)
            if got is None:
                problems.append(f"{section} missing")
                continue
            for field, value in expected.items():
                actual = getattr(got, field)
                if field == "amount":
                    from decimal import Decimal

                    if actual is None or Decimal(actual) != Decimal(value):
                        problems.append(f"{section}.amount {actual!r} != {value!r}")
                elif isinstance(value, str) and field in ("friend", "account"):
                    if (actual or "").casefold() != value.casefold():  # names ignore case
                        problems.append(f"{section}.{field} {actual!r} != {value!r}")
                elif actual != value:
                    problems.append(f"{section}.{field} {actual!r} != {value!r}")
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
