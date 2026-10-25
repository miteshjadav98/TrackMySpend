"""Redis access with explicit failure semantics.

Redis is a performance layer, never a source of truth. Every helper here fails *open*
(callers get `RedisUnavailableError` and fall back to Postgres). A small circuit breaker
stops a dead Redis from adding a socket timeout to every request.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from redis.asyncio import Redis
from redis.exceptions import RedisError

from finance_core.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RedisUnavailableError(Exception):
    """Redis could not serve the call; the caller should degrade gracefully."""


class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 10.0) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._cooldown
            self._failures = 0
            logger.warning("redis circuit opened", extra={"cooldownSeconds": self._cooldown})


class RedisClient:
    def __init__(self, redis: Redis, *, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix
        self._breaker = _CircuitBreaker()

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisClient:
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            health_check_interval=30,
            decode_responses=True,
        )
        return cls(redis, prefix=settings.redis_key_prefix)

    def key(self, *parts: object) -> str:
        return ":".join([self._prefix, *(str(part) for part in parts)])

    async def _call(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self._breaker.is_open:
            raise RedisUnavailableError("circuit open")
        try:
            result = await fn()
        except (RedisError, OSError, TimeoutError) as exc:
            self._breaker.record_failure()
            raise RedisUnavailableError(str(exc)) from exc
        self._breaker.record_success()
        return result

    async def get(self, key: str) -> str | None:
        value = await self._call(lambda: self._redis.get(key))
        return value.decode() if isinstance(value, bytes) else value  # decode_responses=True

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        await self._call(lambda: self._redis.set(key, value, ex=ttl_seconds))

    async def set_if_absent(self, key: str, value: str, *, ttl_ms: int) -> bool:
        result = await self._call(lambda: self._redis.set(key, value, nx=True, px=ttl_ms))
        return bool(result)

    async def delete(self, key: str) -> None:
        await self._call(lambda: self._redis.delete(key))

    async def eval(self, script: str, keys: list[str], args: list[Any]) -> Any:
        return await self._call(lambda: self._redis.eval(script, len(keys), *keys, *args))

    async def ping(self) -> bool:
        try:
            return bool(await self._call(self._redis.ping))
        except RedisUnavailableError:
            return False

    async def flush_prefix_for_tests(self) -> None:
        """Delete every key under our prefix. Only for test suites."""
        async for key in self._redis.scan_iter(match=f"{self._prefix}:*", count=500):
            await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
