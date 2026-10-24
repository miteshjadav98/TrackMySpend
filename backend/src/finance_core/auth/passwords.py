"""Password hashing with Argon2id (RFC 9106 parameters from argon2-cffi).

Hashing is CPU- and memory-heavy by design, so it runs in a worker thread (never on the
event loop) behind a semaphore: each hash allocates ~64 MiB, and an unbounded burst of
logins could otherwise exhaust a container's memory.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
_concurrency = asyncio.Semaphore(4)

MAX_PASSWORD_LENGTH = 128


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    # Verifying against this when the account does not exist keeps the response time
    # the same, so login timing does not reveal which emails are registered.
    return _hasher.hash("timing-equaliser-not-a-real-password")


async def hash_password(password: str) -> str:
    async with _concurrency:
        return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    target = password_hash or _dummy_hash()
    async with _concurrency:
        try:
            await asyncio.to_thread(_hasher.verify, target, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
