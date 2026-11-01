"""Friend names as people say them in chat: find the friend a name means.

Pure functions, so the chat's friend rules are unit-tested without a database. They follow
the same rules as `accounts/names.py`: an exact name wins, else words contained in each other.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Protocol


class _Named(Protocol):
    @property
    def name(self) -> str: ...


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold()))


def matching_friends[FriendLike: _Named](
    name: str, friends: Sequence[FriendLike]
) -> list[FriendLike]:
    """Every friend `name` could mean: the exact name if there is one, else every friend whose
    words contain the name's words ("Jaymin" and "Jaymin Shah"), else none."""
    said = name.strip().casefold()
    if not said:
        return []
    exact = [f for f in friends if f.name.casefold() == said]
    if exact:
        return exact
    said_words = _words(said)
    return [f for f in friends if said_words and said_words <= _words(f.name)]


class _Identified(_Named, Protocol):
    @property
    def id(self) -> uuid.UUID: ...

    @property
    def email(self) -> str | None: ...


def names_telling_duplicates_apart(friends: Sequence[_Identified]) -> dict[uuid.UUID, str]:
    """Each friend's name for a chat reply: the plain name, or "Name (email)" when another
    friend has the same name, so two Jaymins never read as one. A duplicate with no email
    keeps the plain name; there is nothing better to say."""
    counts = Counter(f.name.casefold() for f in friends)
    return {
        f.id: f"{f.name} ({f.email})" if counts[f.name.casefold()] > 1 and f.email else f.name
        for f in friends
    }


def resolve_friend_name[FriendLike: _Named](
    name: str, friends: Sequence[FriendLike]
) -> FriendLike | None:
    """The one friend `name` means, or None when it means none or several."""
    found = matching_friends(name, friends)
    return found[0] if len(found) == 1 else None
