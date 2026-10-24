"""Server entrypoint: `python -m finance_api.serve [--reload]`.

Cloud Run sets PORT. Behind Google's load balancer, set FORWARDED_ALLOW_IPS='*' so the
real client IP (used for rate limiting) is taken from X-Forwarded-For.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from finance_core.compat import IS_WINDOWS


def main() -> None:
    parser = argparse.ArgumentParser(prog="finance_api.serve")
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev only)")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[4]
    uvicorn.run(
        "finance_api.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(root / "backend" / "src"), str(root / "apps" / "api" / "src")]
        if args.reload
        else None,
        # psycopg's async driver needs a selector event loop on Windows.
        loop="asyncio:SelectorEventLoop" if IS_WINDOWS else "auto",
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        log_config=None,  # the app configures structured logging itself
        timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    main()
