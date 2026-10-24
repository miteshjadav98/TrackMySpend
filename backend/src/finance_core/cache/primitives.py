"""Higher-level Redis patterns: per-user data generations, locks, and rate limits."""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass

from finance_core.cache.redis import RedisClient, RedisUnavailableError
from finance_core.errors import RateLimitedError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Generation-based invalidation
# ---------------------------------------------------------------------------------------


class UserDataGeneration:
    """A per-user counter that is bumped after every committed financial write.

    Cached derived data (summaries, breakdowns) embeds the generation in its key, so one
    `INCR` invalidates every cached view for that user at once without having to know
    which periods a write affected. Old entries simply expire.
    """

    _TTL_SECONDS = 7 * 24 * 3600  # must outlive every cache entry that embeds it

    _BUMP_SCRIPT = """
    local value = redis.call('INCR', KEYS[1])
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    return value
    """

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    def _key(self, user_id: uuid.UUID) -> str:
        return self._redis.key("gen", user_id)

    async def current(self, user_id: uuid.UUID) -> str:
        value = await self._redis.get(self._key(user_id))
        return value or "0"

    async def bump(self, user_id: uuid.UUID) -> None:
        try:
            await self._redis.eval(self._BUMP_SCRIPT, [self._key(user_id)], [self._TTL_SECONDS])
        except RedisUnavailableError:
            # Readers fall back to the database while Redis is down, and every cache
            # entry has a short TTL, so staleness is bounded even if this bump is lost.
            logger.warning("cache generation bump failed", extra={"targetUserId": str(user_id)})


# ---------------------------------------------------------------------------------------
# Distributed lock (single Redis instance, token-checked release)
# ---------------------------------------------------------------------------------------

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class LockBusyError(Exception):
    pass


@dataclass(slots=True)
class LockHandle:
    key: str
    token: str
    acquired: bool  # False when Redis was unavailable and we proceeded without a lock


class DistributedLock:
    """Short-lived mutual exclusion, e.g. one in-flight agent turn per conversation.

    Fails open: if Redis is down the caller proceeds unlocked (logged). The protected
    work must therefore stay correct without the lock, which ours is via idempotency keys;
    the lock only prevents interleaved turns from confusing the conversation.
    """

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def acquire(self, name: str, *, ttl_seconds: float) -> LockHandle:
        key = self._redis.key("lock", name)
        token = secrets.token_hex(16)
        try:
            ok = await self._redis.set_if_absent(key, token, ttl_ms=int(ttl_seconds * 1000))
        except RedisUnavailableError:
            logger.warning("lock unavailable, proceeding without it", extra={"lock": name})
            return LockHandle(key, token, acquired=False)
        if not ok:
            raise LockBusyError(name)
        return LockHandle(key, token, acquired=True)

    async def release(self, handle: LockHandle) -> None:
        if not handle.acquired:
            return
        try:
            await self._redis.eval(_RELEASE_SCRIPT, [handle.key], [handle.token])
        except RedisUnavailableError:
            logger.warning("lock release failed; it will expire", extra={"lock": handle.key})


# ---------------------------------------------------------------------------------------
# Rate limiting (fixed window)
# ---------------------------------------------------------------------------------------

_RATE_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('PTTL', KEYS[1])}
"""


class RateLimiter:
    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def hit(self, scope: str, identifier: str, *, limit: int, window_seconds: int) -> None:
        """Count one request; raise `RateLimitedError` once `limit` is exceeded.

        Fails open when Redis is unavailable: availability beats strict limiting here,
        and the edge (Cloud Armor) still enforces coarse per-IP limits.
        """
        key = self._redis.key("rl", scope, identifier)
        try:
            count, ttl_ms = await self._redis.eval(_RATE_SCRIPT, [key], [window_seconds * 1000])
        except RedisUnavailableError:
            logger.warning("rate limiter unavailable", extra={"scope": scope})
            return
        if int(count) > limit:
            retry_after = max(1, int(ttl_ms) // 1000 if int(ttl_ms) > 0 else window_seconds)
            raise RateLimitedError(
                "Too many requests. Please wait a moment and try again.",
                retry_after_seconds=retry_after,
            )
