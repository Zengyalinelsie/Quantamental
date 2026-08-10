"""Read-only PostgreSQL financial evidence and mismatch catalog."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Protocol, cast

import psycopg

from a_share_platform.application.financial_evidence import (
    DisclosureTimelineEntry,
    FactComparisonEntry,
    FactComparisonQuery,
    FactIdentityQuery,
    FactRevisionEntry,
    FinancialMismatchEntry,
    RawEvidenceEntry,
    compare_fact_modes,
    fact_entry,
)
from a_share_platform.domain.metrics import MetricUnit, StatementType
from a_share_platform.domain.pit import (
    AuthorityRule,
    DataQualityState,
    DataTrustState,
    FactObservation,
    FactValue,
    FinancialPeriodType,
)


class QueryResult(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


def _strings(value: object) -> tuple[str, ...]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, (list, tuple)):
        raise TypeError("stored JSON value is not an array")
    return tuple(str(item) for item in parsed)


class PostgresFinancialEvidenceReader:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresFinancialEvidenceReader:
        if not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(read_only=True)"

    def _read(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> list[tuple[object, ...]]:
        with self._connection_factory() as connection, connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            return connection.execute(query, params).fetchall()

    def list_disclosures(
        self,
        company_id: str | None = None,
    ) -> tuple[DisclosureTimelineEntry, ...]:
        where = "" if company_id is None else "WHERE company_id = %s"
        params: tuple[object, ...] = () if company_id is None else (company_id,)
        rows = self._read(
            f"""
            SELECT disclosure_id, document_key, external_document_id, company_id,
                   security_id, source_system, title, document_type, report_period_end,
                   published_at, available_at, first_tradable_at,
                   publication_time_precision, version_sequence,
                   status, raw_object_id, supersedes_disclosure_id, status_reason
            FROM official_disclosures {where}
            ORDER BY document_key, version_sequence, published_at
            LIMIT 500
            """,
            params,
        )
        return tuple(self._disclosure(row) for row in rows)

    def list_fact_revisions(
        self,
        query: FactIdentityQuery,
    ) -> tuple[FactRevisionEntry, ...]:
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (
            ("company_id", query.company_id),
            ("security_id", query.security_id),
            ("metric_code", query.metric_code),
            ("report_period_end", query.report_period_end),
            ("period_type", query.period_type),
            ("statement_type", query.statement_type),
        ):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        where = "" if not clauses else "WHERE " + " AND ".join(clauses)
        rows = self._read(
            self._fact_select()
            + f" {where} ORDER BY report_period_end DESC, revision_sequence, known_from LIMIT 1000",
            tuple(params),
        )
        return tuple(fact_entry(self._fact(row)) for row in rows)

    def compare_fact(self, query: FactComparisonQuery) -> FactComparisonEntry | None:
        rows = self._read(
            self._fact_select()
            + """
            WHERE company_id = %s AND security_id = %s AND metric_code = %s
              AND report_period_end = %s AND period_type = %s AND statement_type = %s
            ORDER BY provider_id, revision_sequence, known_from
            """,
            (
                query.company_id,
                query.security_id,
                query.metric_code,
                query.report_period_end,
                query.period_type,
                query.statement_type,
            ),
        )
        rule_rows = self._read(
            """
            SELECT rule_version, provider_priority
            FROM financial_authority_rules WHERE rule_version = %s
            """,
            (query.authority_rule_version,),
        )
        if not rows or not rule_rows:
            return None
        return compare_fact_modes(
            tuple(self._fact(row) for row in rows),
            query,
            AuthorityRule(str(rule_rows[0][0]), _strings(rule_rows[0][1])),
        )

    def list_mismatches(self) -> tuple[FinancialMismatchEntry, ...]:
        result: list[FinancialMismatchEntry] = []
        unmapped = self._read(
            """
            SELECT unmapped_field_id, provider_id, source_field, raw_object_id
            FROM unmapped_metric_fields WHERE status = 'pending'
            ORDER BY discovered_at DESC, unmapped_field_id LIMIT 500
            """
        )
        result.extend(
            FinancialMismatchEntry(
                mismatch_id=str(row[0]),
                mismatch_type="unmapped_field",
                status="blocking",
                company_id=None,
                security_id=None,
                metric_code=None,
                report_period_end=None,
                provider_ids=(str(row[1]),),
                related_ids=(str(row[3]),),
                reason=f"unmapped provider field: {row[2]}",
            )
            for row in unmapped
        )
        fact_rows = self._read(
            self._fact_select()
            + """
            WHERE known_to IS NULL
            ORDER BY company_id, security_id, metric_code, report_period_end, provider_id
            LIMIT 10000
            """
        )
        groups: defaultdict[tuple[object, ...], list[FactObservation]] = defaultdict(list)
        for row in fact_rows:
            fact = self._fact(row)
            groups[fact.economic_identity].append(fact)
            if fact.quality_state.blocks_downstream:
                result.append(
                    FinancialMismatchEntry(
                        mismatch_id=f"quality:{fact.fact_id}",
                        mismatch_type="quality_block",
                        status="blocking",
                        company_id=fact.company_id,
                        security_id=fact.security_id,
                        metric_code=fact.metric_code,
                        report_period_end=fact.report_period_end,
                        provider_ids=(fact.provider_id,),
                        related_ids=(fact.fact_id, *fact.quality_issue_ids),
                        reason=f"quality state is {fact.quality_state.value}",
                    )
                )
        for identity, facts in groups.items():
            semantic_values = {json.dumps(fact.semantic_value, default=str) for fact in facts}
            if len({fact.provider_id for fact in facts}) < 2 or len(semantic_values) < 2:
                continue
            digest = hashlib.sha256("|".join(map(str, identity)).encode()).hexdigest()[:16]
            result.append(
                FinancialMismatchEntry(
                    mismatch_id=f"provider-value:{digest}",
                    mismatch_type="provider_value_conflict",
                    status="blocking",
                    company_id=str(identity[0]),
                    security_id=str(identity[1]),
                    metric_code=str(identity[2]),
                    report_period_end=cast(date, identity[3]),
                    provider_ids=tuple(sorted({fact.provider_id for fact in facts})),
                    related_ids=tuple(sorted(fact.fact_id for fact in facts)),
                    reason="current provider observations disagree on value, unit, or currency",
                )
            )
        return tuple(sorted(result, key=lambda row: (row.mismatch_type, row.mismatch_id)))

    def get_evidence(self, raw_object_id: str) -> RawEvidenceEntry | None:
        rows = self._read(
            """
            SELECT raw_object_id, object_kind, content_hash, source_url, provider_id,
                   retrieved_at, media_type, license_id, retention_policy,
                   retention_until, redistribution_allowed
            FROM raw_objects WHERE raw_object_id = %s
            """,
            (raw_object_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return RawEvidenceEntry(
            raw_object_id=str(row[0]),
            object_kind=str(row[1]),
            content_hash=str(row[2]),
            source_url=str(row[3]),
            provider_id=str(row[4]),
            retrieved_at=cast(datetime, row[5]),
            media_type=str(row[6]),
            license_id=str(row[7]),
            retention_policy=str(row[8]),
            retention_until=None if row[9] is None else cast(date, row[9]),
            redistribution_allowed=cast(bool, row[10]),
        )

    @staticmethod
    def _fact_select() -> str:
        return """
            SELECT fact_id, company_id, security_id, metric_code, fact_value, unit, currency,
                   report_period_end, period_type, statement_type, announced_at, available_at,
                   known_from, known_to, revision_sequence, provider_id, source_field,
                   raw_object_hash, trust_state, quality_state, mapping_version_id,
                   source_object_id, dataset_version_id, quality_issue_ids
            FROM financial_fact_observations
        """

    @staticmethod
    def _fact(row: Sequence[object]) -> FactObservation:
        # psycopg already decodes JSONB. A JSON string containing a decimal is
        # therefore Python ``str`` here and must not be parsed a second time.
        value = row[4]
        if type(value) not in {str, int, float, bool}:
            raise TypeError("stored fact value has an unsupported type")
        return FactObservation(
            fact_id=str(row[0]),
            company_id=str(row[1]),
            security_id=str(row[2]),
            metric_code=str(row[3]),
            value=cast(FactValue, value),
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
            quality_issue_ids=_strings(row[23]),
        )

    @staticmethod
    def _disclosure(row: Sequence[object]) -> DisclosureTimelineEntry:
        return DisclosureTimelineEntry(
            disclosure_id=str(row[0]),
            document_key=str(row[1]),
            external_document_id=str(row[2]),
            company_id=str(row[3]),
            security_id=None if row[4] is None else str(row[4]),
            source_system=str(row[5]),
            title=str(row[6]),
            document_type=str(row[7]),
            report_period_end=None if row[8] is None else cast(date, row[8]),
            published_at=cast(datetime, row[9]),
            available_at=cast(datetime, row[10]),
            first_tradable_at=cast(datetime, row[11]),
            publication_time_precision=str(row[12]),
            version_sequence=int(cast(int, row[13])),
            status=str(row[14]),
            raw_object_id=str(row[15]),
            supersedes_disclosure_id=None if row[16] is None else str(row[16]),
            status_reason=None if row[17] is None else str(row[17]),
        )
