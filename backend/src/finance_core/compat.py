"""Platform compatibility helpers.

psycopg's async mode cannot run on Windows' default ProactorEventLoop, so local Windows
development (CLI scripts, uvicorn, tests) uses a SelectorEventLoop. Linux, which is what
runs in containers and on Cloud Run, is unaffected.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

IS_WINDOWS = sys.platform == "win32"


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    return asyncio.SelectorEventLoop if IS_WINDOWS else None


def run(coro: Coroutine[Any, Any, T]) -> T:
    """`asyncio.run` with a psycopg-compatible event loop on every platform."""
    return asyncio.run(coro, loop_factory=loop_factory())
