"""Replies for settlements and balance questions.

Every amount is formatted from a balance or settlement the database computed; the model never
writes a figure into these replies.
"""

from __future__ import annotations

from collections.abc import Sequence

from finance_core.friends.schemas import BalanceView, FriendView
from finance_core.workflows.settling import AskReason


def _join(parts: Sequence[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _friend_sentence(friend: FriendView) -> str:
    """ "Jaymin owes you ₹500.00, and you owe Jaymin $20.00." or "" when settled up."""
    owes_you = [b.formatted for b in friend.balances if b.amount_minor > 0]
    you_owe = [b.formatted for b in friend.balances if b.amount_minor < 0]
    parts = []
    if owes_you:
        parts.append(f"{friend.name} owes you {_join(owes_you)}")
    if you_owe:
        parts.append(f"you owe {friend.name} {_join(you_owe)}")
    if not parts:
        return ""
    sentence = ", and ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def compose_balances(friends: Sequence[FriendView], *, asked_about: str | None) -> str:
    """The answer to a balance question: one friend's balances, or everyone who is owed."""
    if asked_about is not None and len(friends) == 1:
        return _friend_sentence(friends[0]) or f"You and {friends[0].name} are settled up."
    sentences = [s for s in (_friend_sentence(f) for f in friends) if s]
    if not sentences:
        return "Nobody owes anything: you are settled up with everyone."
    return " ".join(sentences)


def compose_unclear_balance_question(reason: str, name: str, options: Sequence[str]) -> str:
    if reason == "ambiguous_friend":
        return f"Which one do you mean: {' or '.join(options)}? Ask again with the full name."
    return f"I don't have a friend called {name}. You can add {name} on the Friends page."


def compose_unclear_settlement(reason: AskReason, name: str, options: Sequence[str]) -> str:
    """What to say when a settlement cannot be recorded yet. Nothing was saved."""
    if reason == "unknown_friend":
        return f"I don't have a friend called {name}. Add {name} on the Friends page, then tell me again."
    if reason == "ambiguous_friend":
        return f"Which one do you mean: {' or '.join(options)}? Tell me again with the full name."
    if reason == "no_amount":
        return "How much was it? Tell me again with the amount, like “Jaymin paid me 500”."
    if reason == "no_direction":
        return "Did they pay you, or did you pay them? Tell me again, like “Jaymin paid me 500”."
    return "Which friend was that? Tell me again with their name."


def compose_settlement_saved(
    *,
    direction: str,
    friend: str,
    amount_formatted: str,
    currency: str,
    balances: Sequence[BalanceView],
    account: str | None,
    warning: str | None,
    unmatched_account: str | None,
) -> str:
    """ "Recorded: Jaymin paid you ₹500.00 into HDFC. Jaymin now owes you ₹300.00." """
    if direction == "friend_paid_you":
        via = f" into {account}" if account else ""
        text = f"Recorded: {friend} paid you {amount_formatted}{via}."
    else:
        via = f" from {account}" if account else ""
        text = f"Recorded: you paid {friend} {amount_formatted}{via}."
    now = next((b for b in balances if b.currency == currency and b.amount_minor != 0), None)
    if now is None:
        text += f" You and {friend} are settled up."
    elif now.amount_minor > 0:
        text += f" {friend} now owes you {now.formatted}."
    else:
        text += f" You now owe {friend} {now.formatted}."
    if warning:
        text += " " + warning
    if unmatched_account:
        text += (
            f" I couldn't match “{unmatched_account}” to one of your accounts, "
            "so I saved it without an account."
        )
    return text
