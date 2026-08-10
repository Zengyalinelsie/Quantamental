"""Run the private-local CSI passive timing baseline, dry-run by default."""

from __future__ import annotations

import argparse
import json
import platform as runtime_platform
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import psycopg

from a_share_platform.adapters.postgres.timing import (
    PostgresTimingForecastRepository,
)
from a_share_platform.adapters.postgres.timing_baseline import (
    PostgresTimingBaselineStore,
)
from a_share_platform.adapters.providers.baostock_timing import (
    BaostockTimingBenchmarkSource,
)
from a_share_platform.application.timing_baseline import (
    TimingBaselineRequest,
    TimingBaselineRunner,
)
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("session must be an ISO date") from error


def _positive_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("target volatility must be a decimal") from error
    if not parsed.is_finite() or parsed <= 0:
        raise argparse.ArgumentTypeError("target volatility must be positive")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-id",
        choices=("index:000300", "index:000905"),
        required=True,
    )
    parser.add_argument("--universe-version-id", required=True)
    parser.add_argument("--session", type=_date, required=True)
    parser.add_argument(
        "--target-volatility-ratio",
        type=_positive_decimal,
        default=Decimal("0.12"),
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument(
        "--environment-fingerprint",
        default=f"python:{runtime_platform.python_version()}",
    )
    parser.add_argument("--private-local-research-ack", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output: dict[str, object] = {
        "mode": "execute_requested" if args.execute else "dry_run",
        "benchmark_id": args.benchmark_id,
        "universe_version_id": args.universe_version_id,
        "session": args.session.isoformat(),
        "target_volatility_ratio": str(args.target_volatility_ratio),
        "data_mode": "current_research",
        "deployment_stage": "shadow",
        "trust_state": "normalized_current",
        "adjustment_mode": "unadjusted",
        "writes_performed": False,
        "blockers": [],
    }
    if not args.execute:
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    blockers: list[str] = []
    if not args.private_local_research_ack:
        blockers.append("private-local research ack is required")
    if not _postgres_endpoint_is_private_local(args.database_url):
        blockers.append("database must use a loopback or Unix socket endpoint")
    output["blockers"] = blockers
    if blockers:
        output["execution_status"] = "blocked"
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    try:
        result = _execute(args)
    except Exception as error:  # noqa: BLE001 - the CLI emits a safe failure summary
        output["execution_status"] = "failed"
        output["execution_error"] = f"{type(error).__name__}: {error}"
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    output.update(result)
    output["writes_performed"] = bool(result.get("created"))
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _execute(args: argparse.Namespace) -> dict[str, object]:
    with psycopg.connect(args.database_url) as connection:
        repository = PostgresTimingForecastRepository(connection)
        runner = TimingBaselineRunner(
            source=BaostockTimingBenchmarkSource(clock=lambda: datetime.now(UTC)),
            store=PostgresTimingBaselineStore(connection),
            forecast_repository=repository,
            clock=lambda: datetime.now(UTC),
        )
        result = runner.run(
            TimingBaselineRequest(
                benchmark_id=args.benchmark_id,
                universe_version_id=args.universe_version_id,
                effective_session=args.session,
                target_volatility_ratio=args.target_volatility_ratio,
                code_version=args.code_version,
                environment_fingerprint=args.environment_fingerprint,
            )
        )
    return {
        "execution_status": "succeeded",
        "forecast_id": result.forecast.forecast_id,
        "dataset_version_ids": list(result.forecast.dataset_version_ids),
        "created": result.created,
    }


if __name__ == "__main__":
    raise SystemExit(main())
