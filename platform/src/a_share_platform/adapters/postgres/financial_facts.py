"""PostgreSQL repository for bitemporal financial fact observations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol, cast

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.metrics import MetricUnit, StatementType
from a_share_platform.domain.pit import (
    DataQualityState,
    DataTrustState,
    FactObservation,
    FactValue,
    FinancialPeriodType,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class PostgresFinancialFactRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, value: FactObservation) -> FactObservation:
        existing = self.get(value.fact_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable financial fact identifier conflict: {value.fact_id}"
                )
            return existing
        self._connection.execute(
            """
            INSERT INTO financial_fact_observations (
                fact_id, company_id, security_id, metric_code, fact_value, unit, currency,
                report_period_end, period_type, statement_type, announced_at, available_at,
                known_from, known_to, revision_sequence, provider_id, source_field,
                raw_object_hash, trust_state, quality_state, mapping_version_id,
                source_object_id, dataset_version_id, quality_issue_ids
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (fact_id) DO NOTHING
            """,
            (
                value.fact_id,
                value.company_id,
                value.security_id,
                value.metric_code,
                _json_parameter(value.value),
                value.unit.value,
                value.currency,
                value.report_period_end,
                value.period_type.value,
                value.statement_type.value,
                value.announced_at,
                value.available_at,
                value.known_from,
                value.known_to,
                value.revision_sequence,
                value.provider_id,
                value.source_field,
                value.raw_object_hash,
                value.trust_state.value,
                value.quality_state.value,
                value.mapping_version_id,
                value.source_object_id,
                value.dataset_version_id,
                _json_parameter(list(value.quality_issue_ids)),
            ),
        )
        return value

    def get(self, fact_id: str) -> FactObservation | None:
        row = self._connection.execute(
            self._select() + " WHERE fact_id = %s",
            (fact_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def close_system_interval(
        self,
        fact_id: str,
        known_to: datetime,
    ) -> FactObservation:
        row = self._connection.execute(
            self._select(
                prefix="""
                UPDATE financial_fact_observations
                SET known_to = %s
                WHERE fact_id = %s AND known_to IS NULL AND known_from < %s
                RETURNING
                """
            ),
            (known_to, fact_id, known_to),
        ).fetchone()
        if row is None:
            existing = self.get(fact_id)
            if existing is None:
                raise KeyError(fact_id)
            if existing.known_to == known_to:
                return existing
            raise VersionConflictError("financial fact system interval could not be closed")
        return self._from_row(row)

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
        rows = self._connection.execute(
            self._select()
            + """
            WHERE company_id = %s AND security_id = %s AND metric_code = %s
              AND report_period_end = %s AND period_type = %s AND statement_type = %s
            ORDER BY provider_id, revision_sequence, known_from, fact_id
            """,
            (
                company_id,
                security_id,
                metric_code,
                report_period_end,
                FinancialPeriodType(period_type).value,
                StatementType(statement_type).value,
            ),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _columns() -> str:
        return """
            fact_id, company_id, security_id, metric_code, fact_value, unit, currency,
            report_period_end, period_type, statement_type, announced_at, available_at,
            known_from, known_to, revision_sequence, provider_id, source_field,
            raw_object_hash, trust_state, quality_state, mapping_version_id,
            source_object_id, dataset_version_id, quality_issue_ids
        """

    @classmethod
    def _select(cls, *, prefix: str = "SELECT") -> str:
        if prefix == "SELECT":
            return "SELECT " + cls._columns() + " FROM financial_fact_observations"
        return prefix + cls._columns()

    @staticmethod
    def _json_array(raw: object) -> object:
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        return raw

    @classmethod
    def _from_row(cls, row: Sequence[object]) -> FactObservation:
        # psycopg already decodes JSONB. Numeric financial text intentionally
        # remains a string and must never be reparsed through binary float.
        raw_value = row[4]
        if type(raw_value) not in {str, int, float, bool}:
            raise ValueError("stored financial fact value has an unsupported JSON type")
        raw_issues = cls._json_array(row[23])
        if not isinstance(raw_issues, (list, tuple)):
            raise TypeError("stored quality_issue_ids must be an array")
        return FactObservation(
            fact_id=str(row[0]),
            company_id=str(row[1]),
            security_id=str(row[2]),
            metric_code=str(row[3]),
            value=cast(FactValue, raw_value),
            unit=MetricUnit(str(row[5])),
            currency=None if row[6] is None else str(row[6]),
            report_period_end=cast(date, row[7]),
            period_type=FinancialPeriodType(str(row[8])),
            statement_type=StatementType(str(row[9])),
            announced_at=cast(datetime, row[10]),
            available_at=cast(datetime, row[11]),
            known_from=cast(datetime, row[12]),
            known_to=None if row[13] is None else cast(datetime, row[13]),
            revision_sequence=int(cast(int, row[14])),
            provider_id=str(row[15]),
            source_field=str(row[16]),
            raw_object_hash=str(row[17]),
            trust_state=DataTrustState(str(row[18])),
            quality_state=DataQualityState(str(row[19])),
            mapping_version_id=str(row[20]),
            source_object_id=str(row[21]),
            dataset_version_id=str(row[22]),
            quality_issue_ids=tuple(str(issue) for issue in raw_issues),
        )
