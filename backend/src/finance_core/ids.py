"""Identifier helpers.

Primary keys are UUIDv7 (RFC 9562): globally unique like v4, but time-ordered, so B-tree
inserts stay append-mostly and indexes do not fragment as tables grow.
"""

from __future__ import annotations

import os
import time
import uuid

# Namespace for deterministic ids derived from other ids (e.g. drafts within a message).
_DERIVED_NAMESPACE = uuid.UUID("5b8f0f5e-3a4b-4f9b-9a0e-6d1c2b7a8e90")


def uuid7() -> uuid.UUID:
    """Return a new UUIDv7 (48-bit unix-ms timestamp + 74 random bits)."""
    timestamp_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 9562 variant
    value |= rand_b
    return uuid.UUID(int=value)


def derived_id(*parts: object) -> uuid.UUID:
    """Deterministic UUID (v5) from stable parts.

    Used where a retried operation must produce the same id, e.g. a transaction draft
    extracted from a given chat message.
    """
    return uuid.uuid5(_DERIVED_NAMESPACE, ":".join(str(part) for part in parts))
