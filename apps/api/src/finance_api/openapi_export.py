"""Write the OpenAPI document: `python -m finance_api.openapi_export <path>`.

The frontend's TypeScript types are generated from this file (packages/contracts), so the
API and the UI share one contract. CI regenerates it and fails on drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from finance_api.main import create_app
from finance_core.config import Settings


def main() -> None:
    app = create_app(Settings(_env_file=None, environment="test", log_json=False))
    document = json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)


if __name__ == "__main__":
    main()
