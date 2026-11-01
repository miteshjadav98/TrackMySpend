"""Reads who a shared expense is shared with, from the user's own words.

Part of the offline parser: it finds the friends, who paid, and whether the user said what each
person had. It only reads names and amounts; the shares themselves are worked out later by the
split functions in `friends/splits.py`, never here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finance_core.money import AmountMention, find_amounts

_I = re.IGNORECASE

_SPLIT_WORD = re.compile(
    r"\b(split|splitting|go(?:ing)? dutch|50[/-]50|fifty[- ]fifty|half and half)\b", _I
)
_NAME = r"[A-Za-z][\w'-]*"
_NAME_LIST = rf"{_NAME}(?:\s*(?:,|&|\band\b)\s*{_NAME})*"
# "me and Jaymin spent", "me, Jaymin and Riya paid"
_ME_AND_FRIENDS = re.compile(
    rf"\b(?:me|i)\s*(?:,|&|\band\b)\s*(?P<names>{_NAME_LIST})\s+"
    r"(?:spent|paid|had|bought|ordered|booked|owe|owed)\b",
    _I,
)
# "Jaymin paid 1000 for pizza"
_FRIEND_PAID = re.compile(rf"^\W*(?P<name>{_NAME})\s+paid\b", _I)
# "with Jaymin", "between Jaymin and Riya"
_WITH_FRIENDS = re.compile(rf"\b(?:with|between|among)\s+(?P<names>{_NAME_LIST})", _I)
_NAME_SEPARATOR = re.compile(r"\s*(?:,|&|\band\b)\s*", _I)

_SELF_WORDS = frozenset({"i", "me", "myself", "my"})
_PRONOUNS = frozenset({"he", "she", "they"})
# Words that are not a person's name, so "me and my friends" shares with nobody by name.
_NOT_NAMES = (
    _SELF_WORDS
    | _PRONOUNS
    | {
        "we",
        "us",
        "you",
        "him",
        "her",
        "them",
        "friend",
        "friends",
        "everyone",
        "everybody",
        "others",
        "colleagues",
        "family",
        "group",
        "the",
        "a",
        "an",
        "some",
    }
)
_SAYING_WHAT_EACH_HAD = frozenset(
    {
        "had",
        "have",
        "paid",
        "pays",
        "owe",
        "owes",
        "owed",
        "for",
        "is",
        "was",
        "got",
        "gets",
        "took",
    }
)
_FOR_PERSON = re.compile(rf"^\s*(?:each\s+)?(?:for|by|from)\s+(?P<who>{_NAME})", _I)


@dataclass(frozen=True, slots=True)
class Sharing:
    """What the user said about sharing: the friends, who paid, and any exact amounts."""

    participants: list[str]
    payer: str | None
    split: Literal["equal", "exact"]
    shares: list[tuple[str, Decimal]]  # ("me" or a friend's name, amount)
    share_mentions: list[AmountMention]  # the amounts in `shares`, so the total can be found


def _tidy_name(name: str) -> str:
    # "jaymin" typed in lower case reads better as "Jaymin"; "McKay" is left alone.
    return name.title() if name.islower() else name


def _names_in(chunk: str) -> list[str]:
    names = [
        _tidy_name(name)
        for name in _NAME_SEPARATOR.split(chunk.strip())
        if name and name.casefold() not in _NOT_NAMES
    ]
    return names


def _add_all(into: list[str], names: Sequence[str]) -> None:
    for name in names:
        if name.casefold() not in {existing.casefold() for existing in into}:
            into.append(name)


def _owner_of_amount(
    text: str, mention: AmountMention, boundary: int, others: Sequence[str], known: Sequence[str]
) -> str | None:
    """Who an amount belongs to: "I had 400" -> "me", "he had 600" -> the one friend,
    "Jaymin 600" and "600 for Jaymin" -> Jaymin. None when it belongs to nobody (the total)."""
    tokens = re.findall(r"[\w'-]+", text[boundary : mention.start])
    while tokens and tokens[-1].casefold() in _SAYING_WHAT_EACH_HAD:
        tokens.pop()
    word = tokens[-1] if tokens else None
    if word is None:
        after = _FOR_PERSON.match(text[mention.end :])
        word = after.group("who") if after else None
    if word is None:
        return None
    lowered = word.casefold()
    if lowered in _SELF_WORDS:
        return "me"
    if lowered in _PRONOUNS:
        return others[0] if len(others) == 1 else None
    for name in (*others, *known):
        if lowered == name.casefold().split()[0]:
            return next((o for o in others if o.casefold() == lowered), _tidy_name(word))
    return None


def amounts_by_person(text: str, friends_said: Sequence[str]) -> dict[str, Decimal]:
    """What each person had, from a reply like "I had 400, Jaymin 600" or just "400 600".

    Keys are "me" and each friend, in lower case. A reply with one amount per person and no
    names is read in order: the user first, then the friends as listed.
    """
    mentions = find_amounts(text)
    owned: dict[str, Decimal] = {}
    boundary = 0
    for mention in mentions:
        owner = _owner_of_amount(text, mention, boundary, friends_said, ())
        boundary = mention.end
        if owner is not None:
            owned.setdefault(owner.casefold(), mention.value)
    if not owned and len(mentions) == len(friends_said) + 1:
        owned["me"] = mentions[0].value
        for name, mention in zip(friends_said, mentions[1:], strict=True):
            owned[name.casefold()] = mention.value
    return owned


def read_sharing(text: str, friend_names: Sequence[str] = ()) -> Sharing | None:
    """The sharing in `text`, or None when the message is not about a shared expense.

    A message is shared when it says "me and X spent ...", or names friends together with a
    split ("Jaymin paid 1000, split it", "split 900 with Riya") or with what each had.
    """
    splitting = bool(_SPLIT_WORD.search(text))
    participants: list[str] = []
    payer: str | None = None
    said_me_and = _ME_AND_FRIENDS.search(text)
    if said_me_and:
        _add_all(participants, _names_in(said_me_and.group("names")))
    if splitting and (paid := _FRIEND_PAID.match(text)):
        names = _names_in(paid.group("name"))
        if names:
            payer = names[0]
            _add_all(participants, names)
    if with_friends := _WITH_FRIENDS.search(text):
        _add_all(participants, _names_in(with_friends.group("names")))

    shares: list[tuple[str, Decimal]] = []
    share_mentions: list[AmountMention] = []
    if participants:
        boundary = 0
        for mention in find_amounts(text):
            owner = _owner_of_amount(text, mention, boundary, participants, friend_names)
            boundary = mention.end
            if owner is not None:
                shares.append((owner, mention.value))
                share_mentions.append(mention)
    if len({owner for owner, _ in shares}) < 2:
        # "coffee with Jaymin 200" names one amount beside a friend; it is not what each had.
        shares, share_mentions = [], []
    if not participants or not (said_me_and or splitting or shares):
        return None
    if payer is not None and payer.casefold() not in {p.casefold() for p in participants}:
        participants.append(payer)
    return Sharing(
        participants=participants,
        payer=payer,
        split="exact" if shares else "equal",
        shares=shares,
        share_mentions=share_mentions,
    )
