# ruff: noqa: T201
"""Repeat the live understanding evaluation and save reproducible, non-secret measurements.

Example: uv run python -m tests.evals.run_understanding --runs 5 --output eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finance_core.config import Settings
from finance_core.llm import prompts
from finance_core.llm.gemini import GeminiLLMClient
from finance_core.llm.resilient import ResilientLLMClient
from finance_core.llm.rules import RulesLLMClient
from finance_core.workflows.reconcile import reconcile
from tests.evals.understanding_cases import CASES, check
from tests.unit.test_understanding_eval import ACCOUNTS, FRIENDS, TODAY, _request


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    """Measure raw and reconciled results; never let provider errors count as correct."""
    settings = Settings(_env_file=args.env_file)
    client = ResilientLLMClient(
        GeminiLLMClient(settings), RulesLLMClient(), timeout_seconds=settings.llm_timeout_seconds
    )
    semaphore = asyncio.Semaphore(args.concurrency)

    async def score(case: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                result = await client.understand(_request(case["text"]))
                final = reconcile(
                    result.understanding,
                    case["text"],
                    today=TODAY,
                    locale="en-IN",
                    account_names=ACCOUNTS,
                    friend_names=FRIENDS,
                )
                return {
                    "text": case["text"],
                    "reportCase": case.get("intent") == "spending_report",
                    "rawProblems": ["Provider unavailable; rules fallback"]
                    if result.degraded
                    else check(case, result.understanding),
                    "degraded": result.degraded,
                    "problems": check(case, final),
                    "latencyMs": None if result.degraded else result.latency_ms,
                }
            except Exception as exc:
                # Error types are sufficient here; provider exception strings can carry headers.
                return {
                    "text": case["text"],
                    "reportCase": case.get("intent") == "spending_report",
                    "rawProblems": [type(exc).__name__],
                    "degraded": False,
                    "problems": [type(exc).__name__],
                    "latencyMs": None,
                }

    runs = []
    for index in range(args.runs):
        scores = await asyncio.gather(*(score(case) for case in CASES))
        latencies = [item["latencyMs"] for item in scores if item["latencyMs"] is not None]
        correct = sum(not item["problems"] for item in scores)
        raw_correct = sum(not item["rawProblems"] for item in scores)
        report_correct = sum(item["reportCase"] and not item["problems"] for item in scores)
        report_count = sum(item["reportCase"] for item in scores)
        run = {
            "run": index + 1,
            "cases": len(scores),
            "correct": correct,
            "rawCorrect": raw_correct,
            "fallbackCount": sum(item["degraded"] for item in scores),
            "reportCases": report_count,
            "reportCorrect": report_correct,
            "p50Ms": statistics.median(latencies) if latencies else None,
            "p95Ms": statistics.quantiles(latencies, n=20, method="inclusive")[18]
            if len(latencies) > 1
            else None,
            "failures": [item for item in scores if item["problems"]],
            "rawFailures": [item for item in scores if item["rawProblems"]],
        }
        runs.append(run)
        print(
            f"Run {index + 1}: {correct}/{len(scores)} correct, raw {raw_correct}/{len(scores)}, reports {report_correct}/{report_count}, p50 {run['p50Ms']} ms",
            flush=True,
        )
    return {
        "recordedAt": datetime.now(UTC).isoformat(),
        "pipeline": "production provider + rules fallback + reconciliation",
        "promptVersion": prompts.UNDERSTAND_PROMPT_VERSION,
        "model": settings.llm_understand_model,
        "thinking": settings.llm_understand_thinking,
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10 or not 1 <= args.concurrency <= 8:
        parser.error("Use 1–10 runs and 1–8 concurrent requests")
    report = asyncio.run(evaluate(args))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if any(
        run["correct"] < run["cases"] * 0.9 or run["reportCorrect"] != run["reportCases"]
        for run in report["runs"]
    ):
        raise SystemExit(
            "Evaluation failed: require at least 90% overall and every report case correct in each run"
        )


if __name__ == "__main__":
    main()
