"""Repository port for bitemporal financial fact observations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import FactObservation, FinancialPeriodType


class FinancialFactRepository(Protocol):
    def save(self, value: FactObservation) -> FactObservation: ...

    def get(self, fact_id: str) -> FactObservation | None: ...

    def close_system_interval(
        self,
        fact_id: str,
        known_to: datetime,
    ) -> FactObservation: ...

    def find(
        self,
        *,
        company_id: str,
        security_id: str,
        metric_code: str,
        report_period_end: date,
        period_type: FinancialPeriodType,
        statement_type: StatementType,
    ) -> tuple[FactObservation, ...]: ...
