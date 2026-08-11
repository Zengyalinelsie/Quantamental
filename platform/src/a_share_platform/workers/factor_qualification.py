"""Dry-run-by-default real P4 three-factor qualification audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform as runtime_platform
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from a_share_platform.adapters.postgres.factor_qualification import (
    PostgresFactorQualificationRepository,
    PostgresFactorQualificationSource,
)
from a_share_platform.application.factor_qualification import (
    FactorQualificationOutcome,
    FactorQualificationPlan,
    FactorQualificationService,
)
from a_share_platform.domain.experiments import ExperimentEnvironment
from a_share_platform.domain.factor_qualification import (
    FactorQualificationRequest,
    FactorQualificationTarget,
)
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local


class AuditService(Protocol):
    def evaluate(self, **kwargs: object) -> FactorQualificationPlan: ...

    def ensure(self, **kwargs: object) -> FactorQualificationOutcome: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--private-local-research-ack", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def _time(value: str) -> datetime:
    selected = datetime.fromisoformat(value)
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise ValueError("evaluated-at must be timezone-aware")
    return selected


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _targets() -> tuple[FactorQualificationTarget, ...]:
    package = Path(__file__).resolve().parents[1]
    return (
        FactorQualificationTarget(
            factor_key="quality",
            factor_id="factor:quality",
            factor_version_id="factor-version:quality:p4-qualification:v1",
            feature_id="feature:quality",
            feature_version="v0",
            definition_hash=_file_hash(package / "domain" / "quality_factor.py"),
            required_metric_codes=(
                "balance.total_assets",
                "cashflow.operating_cash_flow",
                "income.net_profit_parent",
                "income.operating_revenue",
            ),
        ),
        FactorQualificationTarget(
            factor_key="valuation_expectation_gap",
            factor_id="factor:valuation-expectation-gap",
            factor_version_id=(
                "factor-version:valuation-expectation-gap:p4-qualification:v1"
            ),
            feature_id="feature:valuation-expectation-gap",
            feature_version="v0",
            definition_hash=_file_hash(
                package / "domain" / "valuation_expectation_gap.py"
            ),
            required_metric_codes=(
                "balance.total_equity",
                "income.net_profit_parent",
            ),
        ),
        FactorQualificationTarget(
            factor_key="fundamental_improvement",
            factor_id="factor:fundamental-improvement",
            factor_version_id=(
                "factor-version:fundamental-improvement:p4-qualification:v1"
            ),
            feature_id="feature:fundamental-improvement",
            feature_version="v0",
            definition_hash=_file_hash(
                package / "domain" / "fundamental_improvement.py"
            ),
            required_metric_codes=(
                "income.net_profit_parent",
                "income.operating_revenue",
            ),
        ),
    )


def _environment() -> ExperimentEnvironment:
    platform_root = Path(__file__).resolve().parents[3]
    return ExperimentEnvironment(
        environment_id="environment:p4-factor-qualification:local:v1",
        python_version=runtime_platform.python_version(),
        platform=runtime_platform.platform(),
        dependency_lock_hash=_file_hash(platform_root / "pyproject.toml"),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: Callable[[str], AuditService] | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    blockers = []
    if not _postgres_endpoint_is_private_local(arguments.database_url):
        blockers.append("factor qualification requires private-local PostgreSQL")
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
        request = FactorQualificationRequest(
            request_id="factor-qualification:csi800:2018-2025:v1",
            requested_universe_id="universe:csi800:pit:requested:v1",
            benchmark_id="index:000906",
            expected_entity_count=800,
            start_date=date(2018, 1, 1),
            end_date=date(2025, 12, 31),
            minimum_coverage=Decimal("0.98"),
            threshold_source="p4-factor-study-policy:v1",
            decision_time_policy_version="decision-time:close-plus-disclosure:v1",
            evaluated_at=_time(arguments.evaluated_at),
        )
        service = (
            service_factory(arguments.database_url)
            if service_factory is not None
            else FactorQualificationService(
                PostgresFactorQualificationSource.from_dsn(arguments.database_url),
                PostgresFactorQualificationRepository.from_dsn(arguments.database_url),
            )
        )
        kwargs = {
            "request": request,
            "targets": _targets(),
            "code_sha": arguments.code_sha,
            "environment": _environment(),
        }
        if arguments.execute:
            outcome = service.ensure(**kwargs)
            plan = outcome.plan
            writes_performed = outcome.writes_performed
        else:
            plan = service.evaluate(**kwargs)
            writes_performed = False
        _print(
            {
                "audits": [
                    {
                        "artifact_hash": audit.artifact_hash,
                        "audit_id": audit.audit_id,
                        "blockers": list(audit.readiness.blockers),
                        "experiment_run_id": audit.experiment_run.run_id,
                        "factor_key": audit.target.factor_key,
                        "readiness_permitted": audit.readiness.permitted,
                        "validation_report_id": audit.validation_report.report_id,
                    }
                    for audit in plan.audits
                ],
                "execution_status": "completed",
                "factor_scores_computed": False,
                "mode": "execute_requested" if arguments.execute else "dry_run",
                "pit_qualification_passed": False,
                "scientific_metrics_computed": False,
                "writes_performed": writes_performed,
            }
        )
        return 0
    except Exception as error:  # noqa: BLE001 - safe CLI boundary
        _print(
            {
                "execution_error": f"{type(error).__name__}: {error}",
                "execution_status": "failed",
                "mode": "execute_requested" if arguments.execute else "dry_run",
                "writes_performed": False,
            }
        )
        return 1


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
