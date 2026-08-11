"""Dry-run-by-default audit entry point for completed financial cohort jobs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from typing import Protocol

from a_share_platform.adapters.postgres.financial_cohort_audit import (
    PostgresFinancialCohortAuditRepository,
)
from a_share_platform.application.financial_cohort_audit import (
    FinancialCohortAuditEvidence,
    FinancialCohortAuditOutcome,
    FinancialCohortAuditService,
)
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local


class AuditService(Protocol):
    def evaluate(
        self,
        *,
        job_ids: tuple[str, ...],
        expected_security_count: int,
    ) -> FinancialCohortAuditEvidence: ...

    def ensure(
        self,
        *,
        job_ids: tuple[str, ...],
        expected_security_count: int,
    ) -> FinancialCohortAuditOutcome: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-ids", nargs="+", required=True)
    parser.add_argument("--expected-security-count", type=int, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--private-local-research-ack", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: Callable[[str], AuditService] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    blockers: list[str] = []
    if not _postgres_endpoint_is_private_local(args.database_url):
        blockers.append("financial cohort audit requires private-local PostgreSQL")
    if args.execute and not args.private_local_research_ack:
        blockers.append("private-local-research ack is required for execution")
    if blockers:
        _print(
            {
                "blockers": blockers,
                "execution_status": "blocked",
                "mode": "execute_requested" if args.execute else "dry_run",
                "writes_performed": False,
            }
        )
        return 2
    job_ids = tuple(sorted(str(value) for value in args.job_ids))
    try:
        if service_factory is not None:
            return _run(
                service_factory(args.database_url),
                job_ids=job_ids,
                expected_security_count=args.expected_security_count,
                execute=args.execute,
            )
        import psycopg

        with psycopg.connect(args.database_url) as connection:
            service = FinancialCohortAuditService(
                PostgresFinancialCohortAuditRepository(connection)
            )
            return _run(
                service,
                job_ids=job_ids,
                expected_security_count=args.expected_security_count,
                execute=args.execute,
            )
    except Exception as error:  # noqa: BLE001 - CLI boundary emits safe type/message only
        _print(
            {
                "execution_error": f"{type(error).__name__}: {error}",
                "execution_status": "failed",
                "mode": "execute_requested" if args.execute else "dry_run",
                "writes_performed": False,
            }
        )
        return 1


def _run(
    service: AuditService,
    *,
    job_ids: tuple[str, ...],
    expected_security_count: int,
    execute: bool,
) -> int:
    if execute:
        outcome = service.ensure(
            job_ids=job_ids,
            expected_security_count=expected_security_count,
        )
        evidence = outcome.evidence
        writes_performed = outcome.writes_performed
    else:
        evidence = service.evaluate(
            job_ids=job_ids,
            expected_security_count=expected_security_count,
        )
        writes_performed = False
    _print(
        {
            "completed_work_units": evidence.completed_work_units,
            "dataset_version_id": evidence.dataset.dataset_version_id,
            "expected_work_units": evidence.expected_work_units,
            "job_ids": list(job_ids),
            "mode": "execute_requested" if execute else "dry_run",
            "observation_count": evidence.observation_count,
            "output_trust_state": "normalized_current",
            "pit_verified": False,
            "redistribution_allowed": False,
            "security_count": evidence.security_count,
            "writes_performed": writes_performed,
        }
    )
    return 0


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
