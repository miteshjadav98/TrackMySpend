"""Operational commands.

    python -m finance_core.manage migrate             # Alembic upgrade + LangGraph checkpoint tables
    python -m finance_core.manage prune-checkpoints   # retention job (schedule daily)

`migrate` is the single deploy-time step for the database; the API never runs DDL itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alembic import command
from alembic.config import Config

from finance_core import compat
from finance_core.agents.checkpointer import setup_checkpointer
from finance_core.agents.maintenance import prune_checkpoints
from finance_core.config import Settings, get_settings
from finance_core.observability import configure_logging

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def migrate(settings: Settings, *, database_url: str | None = None) -> None:
    config = Config(str(_ALEMBIC_INI))
    if database_url:
        config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    compat.run(setup_checkpointer(settings))


def main() -> None:
    parser = argparse.ArgumentParser(prog="finance_core.manage")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations and checkpoint tables")
    prune = sub.add_parser("prune-checkpoints", help="apply checkpoint retention")
    prune.add_argument("--inactive-days", type=int, default=30)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    if args.command == "migrate":
        migrate(settings)
        print("database is up to date")  # noqa: T201
    elif args.command == "prune-checkpoints":
        stats = compat.run(prune_checkpoints(settings, inactive_days=args.inactive_days))
        print(json.dumps(stats))  # noqa: T201


if __name__ == "__main__":
    main()
