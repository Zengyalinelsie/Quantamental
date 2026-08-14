"""Qualify and optionally freeze real valuation inputs; dry-run by default."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from a_share_platform.adapters.postgres.valuation_input_qualification import (
    PostgresValuationInputCompilation,
    PostgresValuationInputQualificationSource,
)
from a_share_platform.adapters.postgres.valuation_inputs import (
    PostgresValuationImprovementInputRepository,
)
from a_share_platform.application.valuation_input_freeze import (
    ValuationInputFreezeService,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_input_qualification import (
    ValuationInputQualificationRequest,
)
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local


class CompilationService(Protocol):
    def evaluate(
        self,
        request: ValuationInputQualificationRequest,
    ) -> PostgresValuationInputCompilation: ...

    def ensure(
        self,
        request: ValuationInputQualificationRequest,
    ) -> tuple[PostgresValuationInputCompilation, bool]: ...


class PostgresValuationInputFreezeWorkerService:
    """Keep read qualification separate from the explicitly gated write path."""

    def __init__(
        self,
        source: PostgresValuationInputQualificationSource,
        freeze_service: ValuationInputFreezeService,
    ) -> None:
        self._source = source
        self._freeze_service = freeze_service

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresValuationInputFreezeWorkerService:
        return cls(
            PostgresValuationInputQualificationSource.from_dsn(dsn),
            ValuationInputFreezeService(
                PostgresValuationImprovementInputRepository.from_dsn(dsn)
            ),
        )

    def evaluate(
        self,
        request: ValuationInputQualificationRequest,
    ) -> PostgresValuationInputCompilation:
        return self._source.compile(request)

    def ensure(
        self,
        request: ValuationInputQualificationRequest,
    ) -> tuple[PostgresValuationInputCompilation, bool]:
        compilation = self._source.compile(request)
        if compilation.bundle is None:
            return compilation, False
        self._freeze_service.freeze(compilation.bundle, compilation.qualification)
        return compilation, True


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("decision-time must include a timezone offset")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--security-id", required=True)
    parser.add_argument("--decision-time", required=True, type=_aware_datetime)
    parser.add_argument(
        "--data-mode",
        required=True,
        choices=[value.value for value in DataMode],
    )
    parser.add_argument(
        "--trust-state",
        required=True,
        choices=[
            DataTrustState.NORMALIZED_CURRENT.value,
            DataTrustState.PIT_VERIFIED.value,
        ],
    )
    parser.add_argument("--max-price-age-days", type=int, default=7)
    parser.add_argument("--private-local-research-ack", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: Callable[[str], CompilationService] | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    blockers: list[str] = []
    if not _postgres_endpoint_is_private_local(arguments.database_url):
        blockers.append("valuation input compilation requires private-local PostgreSQL")
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
        request = ValuationInputQualificationRequest(
            security_id=arguments.security_id,
            decision_time=arguments.decision_time,
            data_mode=DataMode(arguments.data_mode),
            requested_trust_state=DataTrustState(arguments.trust_state),
            max_price_age_days=arguments.max_price_age_days,
        )
        service = (
            service_factory(arguments.database_url)
            if service_factory is not None
            else PostgresValuationInputFreezeWorkerService.from_dsn(
                arguments.database_url
            )
        )
        if arguments.execute:
            compilation, writes_performed = service.ensure(request)
        else:
            compilation = service.evaluate(request)
            writes_performed = False
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

    qualification = compilation.qualification
    domains = []
    for evidence in qualification.domain_evidence:
        evidence_blockers = tuple(evidence.blockers)
        observation_count = int(evidence.observation_count)
        latest_available = getattr(evidence, "latest_source_available_at", None)
        domains.append(
            {
                "blockers": list(evidence_blockers),
                "content_hashes": list(getattr(evidence, "content_hashes", ())),
                "dataset_version_ids": list(evidence.dataset_version_ids),
                "domain": evidence.domain.value,
                "latest_source_available_at": (
                    None if latest_available is None else latest_available.isoformat()
                ),
                "observation_count": observation_count,
                "qualified": bool(
                    getattr(
                        evidence,
                        "is_qualified",
                        observation_count > 0 and not evidence_blockers,
                    )
                ),
                "source_ids": list(getattr(evidence, "source_ids", ())),
                "trust_state": (
                    None
                    if evidence.trust_state is None
                    else evidence.trust_state.value
                ),
            }
        )
    _print(
        {
            "blockers": list(qualification.blockers),
            "bundle_version_id": (
                None
                if compilation.bundle is None
                else compilation.bundle.bundle_version_id
            ),
            "data_mode": request.data_mode.value,
            "decision_time": request.decision_time.isoformat(),
            "domains": domains,
            "execution_status": (
                "succeeded"
                if qualification.is_qualified
                else "blocked"
            ),
            "mode": "execute_requested" if arguments.execute else "dry_run",
            "qualified": qualification.is_qualified,
            "security_id": request.security_id,
            "trust_state": request.requested_trust_state.value,
            "writes_performed": writes_performed,
        }
    )
    if arguments.execute and not qualification.is_qualified:
        return 2
    return 0


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


__all__ = ["PostgresValuationInputFreezeWorkerService", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
