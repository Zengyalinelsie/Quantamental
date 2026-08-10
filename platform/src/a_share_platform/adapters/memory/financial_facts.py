"""In-memory bitemporal financial fact repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import FactObservation, FinancialPeriodType


class InMemoryFinancialFactRepository:
    def __init__(self) -> None:
        self._facts: dict[str, FactObservation] = {}

    def save(self, value: FactObservation) -> FactObservation:
        existing = self._facts.get(value.fact_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable financial fact identifier conflict: {value.fact_id}"
                )
            return existing
        self._facts[value.fact_id] = value
        return value

    def get(self, fact_id: str) -> FactObservation | None:
        return self._facts.get(fact_id)

    def close_system_interval(
        self,
        fact_id: str,
        known_to: datetime,
    ) -> FactObservation:
        existing = self._facts.get(fact_id)
        if existing is None:
            raise KeyError(fact_id)
        if existing.known_to is not None:
            if existing.known_to == known_to:
                return existing
            raise VersionConflictError("financial fact system interval is already closed")
        closed = replace(existing, known_to=known_to)
        self._facts[fact_id] = closed
        return closed

    def find(
        self,
        *,
        company_id: str,
        security_id: str,
        metric_code: str,
        report_period_end: date,
        period_type: FinancialPeriodType,
        statement_type: StatementType,
    ) -> tuple[FactObservation, ...]:
        period_type = FinancialPeriodType(period_type)
        statement_type = StatementType(statement_type)
        return tuple(
            sorted(
                (
                    value
                    for value in self._facts.values()
                    if value.company_id == company_id
                    and value.security_id == security_id
                    and value.metric_code == metric_code
                    and value.report_period_end == report_period_end
                    and value.period_type is period_type
                    and value.statement_type is statement_type
                ),
                key=lambda value: (
                    value.provider_id,
                    value.revision_sequence,
                    value.known_from,
                    value.fact_id,
                ),
            )
        )
