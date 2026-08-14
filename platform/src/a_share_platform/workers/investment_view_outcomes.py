"""Scan InvestmentView maturities and optionally freeze outcomes; dry-run by default."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from a_share_platform.adapters.memory.expected_return import (
    UnavailableInvestmentViewOutcomeSource,
)
from a_share_platform.adapters.postgres.expected_return import (
    PostgresExpectedReturnLedgerRepository,
)
from a_share_platform.application.investment_view_outcomes import (
    InvestmentViewOutcomeMaturityService,
    OutcomeMaturityBatch,
)
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local


class MaturityService(Protocol):
    def evaluate(self, *, evaluated_at: datetime) -> OutcomeMaturityBatch: ...

    def ensure(self, *, evaluated_at: datetime) -> OutcomeMaturityBatch: ...


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("evaluated-at must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("evaluated-at must include a timezone offset")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--evaluated-at", required=True, type=_aware_datetime)
    parser.add_argument("--private-local-research-ack", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def _default_service(dsn: str) -> InvestmentViewOutcomeMaturityService:
    return InvestmentViewOutcomeMaturityService(
        PostgresExpectedReturnLedgerRepository.from_dsn(dsn),
        UnavailableInvestmentViewOutcomeSource(
            reason=(
                "P5-D1-01 outcome price/calendar/corporate-action policy is not approved"
            ),
            source_policy_version="outcome-price-policy:unapproved:v1",
        ),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: Callable[[str], MaturityService] | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    blockers: list[str] = []
    if not _postgres_endpoint_is_private_local(arguments.database_url):
        blockers.append("outcome maturity scan requires private-local PostgreSQL")
    if arguments.execute and not arguments.private_local_research_ack:
        blockers.append("private-local-research ack is required for execution")
    if blockers:
        _print(
            {
                "blockers": blockers,
                "execution_status": "blocked",
                "mode": "execute_requested" if arguments.execute else "dry_run",
                "writes_performed": False,
            }
        )
        return 2

    try:
        service = (
            service_factory(arguments.database_url)
            if service_factory is not None
            else _default_service(arguments.database_url)
        )
        result = (
            service.ensure(evaluated_at=arguments.evaluated_at)
            if arguments.execute
            else service.evaluate(evaluated_at=arguments.evaluated_at)
        )
    except Exception as error:  # noqa: BLE001 - CLI boundary emits safe type/message only
        _print(
            {
                "execution_error": f"{type(error).__name__}: {error}",
                "execution_status": "failed",
                "mode": "execute_requested" if arguments.execute else "dry_run",
                "writes_performed": False,
            }
        )
        return 1

    _print(
        {
            "counts": result.counts,
            "evaluated_at": result.evaluated_at.isoformat(),
            "execution_status": "succeeded",
            "items": [
                {
                    "dataset_version_id": (
                        None
                        if item.outcome is None
                        else item.outcome.dataset_version_id
                    ),
                    "outcome_id": (
                        None if item.outcome is None else item.outcome.outcome_id
                    ),
                    "reason": item.reason,
                    "reason_code": item.reason_code,
                    "source_policy_version": item.source_policy_version,
                    "status": item.status.value,
                    "view_id": item.view_id,
                    "write_performed": item.write_performed,
                }
                for item in result.items
            ],
            "mode": "execute_requested" if arguments.execute else "dry_run",
            "writes_performed": result.writes_performed,
        }
    )
    return 0


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
