"""PostgreSQL unit of work for lossless normalized-current financial backfills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Protocol, cast

from a_share_platform.adapters.postgres.backfill import PostgresBackfillRepository
from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    DatasetCoverageReport,
    DatasetQualityReport,
)
from a_share_platform.domain.disclosure import RawObject
from a_share_platform.domain.financial_backfill import (
    CURRENT_KNOWN_FINANCIAL_IDENTITY_WARNING,
    EMPTY_FINANCIAL_WORK_UNIT_WARNING,
    FinancialIdentityResolutionMethod,
    FinancialListingIdentity,
    FinancialMappingResult,
    FinancialPersistResult,
    MappedFinancialRow,
    NormalizedCurrentFinancialObservation,
    financial_identity_retrieval_date,
)
from a_share_platform.domain.financial_sources import (
    AvailabilityMethod,
    FinancialStatementScope,
    FinancialValueBasis,
    ReportVersionType,
)
from a_share_platform.domain.governance import DatasetVersion, LineageEdge, VersionConflictError
from a_share_platform.domain.metrics import MetricUnit, StatementType
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType
from a_share_platform.domain.run_context import DataMode
from a_share_platform.ports.financial_backfill import (
    CurrentKnownFinancialIdentityResolver,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, (dict, list)):
        return value
    obj = getattr(value, "obj", None)
    return value if obj is None else obj


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgresFinancialIdentityResolver:
    """Resolve canonical symbols through effective-dated Security Master rows."""

    _EXCHANGE_PREFIX: ClassVar[dict[str, str]] = {"SH": "XSHG", "SZ": "XSHE"}

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def resolve(
        self,
        canonical_symbol: str,
        *,
        as_of: date,
    ) -> FinancialListingIdentity:
        try:
            prefix, code = canonical_symbol.split(".", maxsplit=1)
            exchange = self._EXCHANGE_PREFIX[prefix]
        except (KeyError, ValueError) as error:
            raise ValueError("canonical_symbol must use SH.000000 or SZ.000000 form") from error
        if len(code) != 6 or not code.isdigit():
            raise ValueError("canonical_symbol must use SH.000000 or SZ.000000 form")
        rows = self._connection.execute(
            """
            SELECT securities.company_id, securities.security_id, listings.listing_id
            FROM identifier_history
            JOIN listings ON listings.listing_id = identifier_history.listing_id
            JOIN securities ON securities.security_id = listings.security_id
            WHERE listings.exchange = %s
              AND identifier_history.kind = 'code'
              AND identifier_history.value = %s
              AND identifier_history.valid_from <= %s
              AND (
                    identifier_history.valid_to IS NULL
                    OR %s < identifier_history.valid_to
              )
              AND listings.listed_on <= %s
              AND (listings.delisted_on IS NULL OR %s <= listings.delisted_on)
            ORDER BY listings.listing_id
            """,
            (exchange, code, as_of, as_of, as_of, as_of),
        ).fetchall()
        if not rows:
            raise LookupError(f"unresolved financial identity: {canonical_symbol}/{as_of}")
        if len(rows) != 1:
            raise LookupError(f"ambiguous financial identity: {canonical_symbol}/{as_of}")
        company_id, security_id, listing_id = rows[0]
        return FinancialListingIdentity(
            canonical_symbol=canonical_symbol,
            company_id=str(company_id),
            security_id=str(security_id),
            listing_id=str(listing_id),
            resolved_as_of=as_of,
        )


class PostgresCurrentKnownFinancialIdentityResolver:
    """Resolve normalized-current rows at the provider retrieval date only."""

    resolution_method = (
        FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
    )

    def __init__(self, connection: Connection) -> None:
        self._effective_dated = PostgresFinancialIdentityResolver(connection)

    def resolve(
        self,
        canonical_symbol: str,
        *,
        as_of: date,
    ) -> FinancialListingIdentity:
        return self._effective_dated.resolve(canonical_symbol, as_of=as_of)


class PostgresFinancialBackfillUnitOfWork:
    """Persist one financial work unit atomically after identity resolution."""

    _SCHEMA_VERSION = "normalized-current-financial-observation:v2"

    def __init__(
        self,
        connection: Connection,
        *,
        job_id: str,
        identity_resolver: CurrentKnownFinancialIdentityResolver,
    ) -> None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id must not be empty")
        if (
            getattr(identity_resolver, "resolution_method", None)
            is not FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
        ):
            raise ValueError(
                "normalized_current financial persistence requires a current-known "
                "identity resolver"
            )
        self._connection = connection
        self._job_id = job_id
        self._identity_resolver = identity_resolver
        self._backfill = PostgresBackfillRepository(connection)
        self._datasets = PostgresDatasetVersionRepository(connection)

    def get_checkpoint(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> BackfillCheckpoint | None:
        self._require_job(job_id)
        return self._backfill.get_checkpoint(job_id, checkpoint_key)

    def save_checkpoint(self, value: BackfillCheckpoint) -> BackfillCheckpoint:
        self._require_job(value.job_id)
        return self._backfill.save_checkpoint(value)

    def save_quality_report(self, value: DatasetQualityReport) -> DatasetQualityReport:
        self._require_job(value.job_id)
        return self._backfill.save_quality_report(value)

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport:
        self._require_job(value.job_id)
        return self._backfill.save_coverage_report(value)

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        self._connection.execute(
            """
            INSERT INTO lineage_edges (upstream_id, downstream_id, relation)
            VALUES (%s, %s, %s)
            ON CONFLICT (upstream_id, downstream_id, relation) DO NOTHING
            """,
            (value.upstream_id, value.downstream_id, value.relation),
        )
        return value

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def persist(self, value: FinancialMappingResult) -> FinancialPersistResult:
        if not isinstance(value, FinancialMappingResult):
            raise TypeError("value must be a FinancialMappingResult")
        batch = value.provider_batch
        work_unit = batch.work_unit
        if batch.trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("PostgreSQL financial sink only accepts normalized_current")
        if not value.mapped_rows and batch.rows:
            raise ValueError("financial work unit has provider rows but no mapped observations")

        resolved = self._resolve_identities(value.mapped_rows, work_unit.symbols)
        dataset, metadata = self._dataset(value, resolved)
        observations = self._observations(value, dataset.dataset_version_id, resolved)

        self._save_raw_object(batch.evidence)
        self._datasets.register_dataset(dataset, metadata=metadata)
        self._save_work_unit(value)
        for observation in observations:
            self._save_observation(observation)

        identity_method = (
            FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
            if value.mapped_rows
            else FinancialIdentityResolutionMethod.NO_OBSERVATIONS
        )
        identity_warning = (
            CURRENT_KNOWN_FINANCIAL_IDENTITY_WARNING
            if value.mapped_rows
            else EMPTY_FINANCIAL_WORK_UNIT_WARNING
        )
        warnings = tuple(
            dict.fromkeys(
                (
                    *batch.warnings,
                    *value.warnings,
                    *(warning for row in value.mapped_rows for warning in row.source_row.warnings),
                    identity_warning,
                )
            )
        )
        result = FinancialPersistResult(
            dataset_version_id=dataset.dataset_version_id,
            observation_ids=tuple(item.observation_id for item in observations),
            identity_resolution_method=identity_method,
            warnings=warnings,
        )
        self._save_receipt(
            work_unit.checkpoint_key,
            result,
            created_at=batch.retrieved_at,
        )
        stored = self.get_persist_result(self._job_id, work_unit.checkpoint_key)
        if stored != result:
            raise VersionConflictError("immutable financial persist receipt conflict")
        return result

    def get_persist_result(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> FinancialPersistResult | None:
        self._require_job(job_id)
        row = self._connection.execute(
            """
            SELECT dataset_version_id, observation_ids, warnings,
                   identity_resolution_method
            FROM financial_backfill_persist_receipts
            WHERE job_id = %s AND checkpoint_key = %s
            """,
            (job_id, checkpoint_key),
        ).fetchone()
        if row is None:
            return None
        raw_observations = _json_value(row[1])
        raw_warnings = _json_value(row[2])
        if not isinstance(raw_observations, (list, tuple)) or not isinstance(
            raw_warnings, (list, tuple)
        ):
            raise TypeError("stored financial persist receipt JSON is invalid")
        return FinancialPersistResult(
            dataset_version_id=str(row[0]),
            observation_ids=tuple(str(item) for item in raw_observations),
            identity_resolution_method=FinancialIdentityResolutionMethod(str(row[3])),
            warnings=tuple(str(item) for item in raw_warnings),
        )

    def _resolve_identities(
        self,
        rows: tuple[MappedFinancialRow, ...],
        symbols: tuple[str, ...],
    ) -> dict[tuple[str, date], FinancialListingIdentity]:
        resolved: dict[tuple[str, date], FinancialListingIdentity] = {}
        for row in rows:
            canonical = self._canonical_symbol(row, symbols)
            key = (
                canonical,
                financial_identity_retrieval_date(row.source_row.retrieved_at),
            )
            if key not in resolved:
                resolved[key] = self._identity_resolver.resolve(canonical, as_of=key[1])
            identity = resolved[key]
            if identity.canonical_symbol != canonical or identity.resolved_as_of != key[1]:
                raise ValueError("identity resolver returned a mismatched financial identity")
        return resolved

    @staticmethod
    def _canonical_symbol(row: MappedFinancialRow, symbols: tuple[str, ...]) -> str:
        prefix = {"XSHG": "SH", "XSHE": "SZ"}.get(row.source_row.market)
        if prefix is None:
            raise ValueError("financial work unit only supports XSHG/XSHE canonical symbols")
        raw_symbol = row.source_row.source_symbol
        code = raw_symbol.split(".")[-1]
        candidate = f"{prefix}.{code}"
        if candidate not in symbols:
            raise ValueError("provider financial symbol is not in the immutable work unit")
        return candidate

    def _dataset(
        self,
        value: FinancialMappingResult,
        identities: Mapping[tuple[str, date], FinancialListingIdentity],
    ) -> tuple[DatasetVersion, dict[str, object]]:
        batch = value.provider_batch
        rows = tuple(
            {
                "mapped_row_id": row.mapped_row_id,
                "canonical_symbol": self._canonical_symbol(row, batch.work_unit.symbols),
                "company_id": identities[
                    (
                        self._canonical_symbol(row, batch.work_unit.symbols),
                        financial_identity_retrieval_date(row.source_row.retrieved_at),
                    )
                ].company_id,
                "security_id": identities[
                    (
                        self._canonical_symbol(row, batch.work_unit.symbols),
                        financial_identity_retrieval_date(row.source_row.retrieved_at),
                    )
                ].security_id,
                "listing_id": identities[
                    (
                        self._canonical_symbol(row, batch.work_unit.symbols),
                        financial_identity_retrieval_date(row.source_row.retrieved_at),
                    )
                ].listing_id,
                "identity_as_of": identities[
                    (
                        self._canonical_symbol(row, batch.work_unit.symbols),
                        financial_identity_retrieval_date(row.source_row.retrieved_at),
                    )
                ].resolved_as_of.isoformat(),
                "identity_resolution_method": (
                    FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE.value
                ),
                "identity_warnings": [CURRENT_KNOWN_FINANCIAL_IDENTITY_WARNING],
                "provider_id": row.provider_id,
                "provider_table": row.source_row.provider_table,
                "metric_code": row.metric_code,
                "mapping_id": row.mapping_id,
                "mapping_version_id": row.mapping_version_id,
                "provider_record_id": row.source_row.provider_record_id,
                "provider_field": row.source_row.provider_field,
                "statement_type": row.statement_type.value,
                "statement_scope": row.source_row.statement_scope.value,
                "report_period_start": row.source_row.report_period_start.isoformat(),
                "report_period_end": row.source_row.report_period_end.isoformat(),
                "period_type": row.source_row.period_type.value,
                "value_basis": row.source_row.value_basis.value,
                "raw_value": str(row.source_row.raw_value),
                "provider_unit": row.source_row.provider_unit,
                "scale_to_canonical": str(row.source_row.scale_to_canonical),
                "canonical_value": str(row.value),
                "canonical_unit": row.unit.value,
                "currency": row.currency,
                "report_version_type": row.source_row.report_version_type.value,
                "revision_sequence": row.source_row.revision_sequence,
                "announced_at": (
                    None
                    if row.source_row.announced_at is None
                    else row.source_row.announced_at.isoformat()
                ),
                "available_at": (
                    None
                    if row.source_row.available_at is None
                    else row.source_row.available_at.isoformat()
                ),
                "availability_method": row.source_row.availability_method.value,
                "provider_updated_at": (
                    None
                    if row.source_row.provider_updated_at is None
                    else row.source_row.provider_updated_at.isoformat()
                ),
                "retrieved_at": row.source_row.retrieved_at.isoformat(),
                "raw_object_id": row.raw_object_id,
                "raw_object_hash": row.raw_object_hash,
                "source_url": row.source_row.source_url,
                "trust_state": row.trust_state.value,
                "warnings": list(
                    dict.fromkeys(
                        (
                            *row.source_row.warnings,
                            CURRENT_KNOWN_FINANCIAL_IDENTITY_WARNING,
                        )
                    )
                ),
            }
            for row in sorted(value.mapped_rows, key=lambda item: item.mapped_row_id)
        )
        identity_method = (
            FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
            if value.mapped_rows
            else FinancialIdentityResolutionMethod.NO_OBSERVATIONS
        )
        identity_warning = (
            CURRENT_KNOWN_FINANCIAL_IDENTITY_WARNING
            if value.mapped_rows
            else EMPTY_FINANCIAL_WORK_UNIT_WARNING
        )
        manifest: dict[str, object] = {
            "schema_version": self._SCHEMA_VERSION,
            "job_id": self._job_id,
            "checkpoint_key": batch.work_unit.checkpoint_key,
            "plan_id": batch.work_unit.plan_id,
            "provider_id": batch.work_unit.provider_id,
            "provider_profile_version": batch.work_unit.provider_profile_version,
            "universe_version_id": batch.work_unit.universe_version_id,
            "mapping_version_id": batch.work_unit.mapping_version_id,
            "raw_object_id": batch.raw_object_id,
            "raw_object_hash": batch.content_hash,
            "data_mode": DataMode.CURRENT_RESEARCH.value,
            "trust_state": DataTrustState.NORMALIZED_CURRENT.value,
            "identity_resolution_method": identity_method.value,
            "warnings": [identity_warning],
            "rows": rows,
        }
        payload = json.dumps(
            manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        dataset = DatasetVersion(
            dataset_version_id=f"dataset:financial-normalized-current:{digest[:32]}",
            content_hash=f"sha256:{digest}",
            created_at=batch.retrieved_at,
            schema_version=self._SCHEMA_VERSION,
        )
        return dataset, {"manifest": manifest}

    def _observations(
        self,
        value: FinancialMappingResult,
        dataset_version_id: str,
        identities: Mapping[tuple[str, date], FinancialListingIdentity],
    ) -> tuple[NormalizedCurrentFinancialObservation, ...]:
        batch = value.provider_batch
        observations: list[NormalizedCurrentFinancialObservation] = []
        for row in sorted(value.mapped_rows, key=lambda item: item.mapped_row_id):
            source = row.source_row
            canonical = self._canonical_symbol(row, batch.work_unit.symbols)
            identity = identities[
                (canonical, financial_identity_retrieval_date(source.retrieved_at))
            ]
            digest = hashlib.sha256(
                f"{dataset_version_id}|{row.mapped_row_id}|{identity.listing_id}".encode()
            ).hexdigest()[:32]
            observations.append(
                NormalizedCurrentFinancialObservation(
                    observation_id=f"normalized-financial-observation:{digest}",
                    dataset_version_id=dataset_version_id,
                    job_id=self._job_id,
                    checkpoint_key=batch.work_unit.checkpoint_key,
                    company_id=identity.company_id,
                    security_id=identity.security_id,
                    listing_id=identity.listing_id,
                    canonical_symbol=canonical,
                    identity_as_of=identity.resolved_as_of,
                    identity_resolution_method=(
                        FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
                    ),
                    mapped_row_id=row.mapped_row_id,
                    provider_id=source.provider_id,
                    provider_table=source.provider_table,
                    provider_record_id=source.provider_record_id,
                    provider_field=source.provider_field,
                    statement_type=source.statement_type,
                    statement_scope=source.statement_scope,
                    report_period_start=source.report_period_start,
                    report_period_end=source.report_period_end,
                    period_type=source.period_type,
                    value_basis=source.value_basis,
                    raw_value=source.raw_value,
                    provider_unit=source.provider_unit,
                    scale_to_canonical=source.scale_to_canonical,
                    canonical_value=row.value,
                    canonical_unit=row.unit,
                    currency=row.currency,
                    report_version_type=source.report_version_type,
                    revision_sequence=source.revision_sequence,
                    announced_at=source.announced_at,
                    available_at=source.available_at,
                    availability_method=source.availability_method,
                    provider_updated_at=source.provider_updated_at,
                    retrieved_at=source.retrieved_at,
                    raw_object_id=source.raw_object_id,
                    raw_object_hash=source.raw_object_hash,
                    source_url=source.source_url,
                    mapping_id=row.mapping_id,
                    mapping_version_id=row.mapping_version_id,
                    metric_code=row.metric_code,
                    trust_state=DataTrustState.NORMALIZED_CURRENT,
                    data_mode=DataMode.CURRENT_RESEARCH,
                    warnings=tuple(
                        dict.fromkeys(
                            (
                                *source.warnings,
                                CURRENT_KNOWN_FINANCIAL_IDENTITY_WARNING,
                            )
                        )
                    ),
                )
            )
        return tuple(observations)

    def _save_raw_object(self, value: RawObject) -> None:
        row = (
            value.raw_object_id,
            value.object_kind.value,
            value.content_hash,
            value.source_url,
            value.provider_id,
            value.retrieved_at,
            value.media_type,
            value.storage_uri,
            value.license_id,
            value.retention_policy.value,
            value.retention_until,
            value.redistribution_allowed,
            value.parent_raw_object_id,
        )
        self._connection.execute(
            """
            INSERT INTO raw_objects (
                raw_object_id, object_kind, content_hash, source_url, provider_id,
                retrieved_at, media_type, storage_uri, license_id, retention_policy,
                retention_until, redistribution_allowed, parent_raw_object_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (raw_object_id) DO NOTHING
            """,
            row,
        )
        stored = self._connection.execute(
            """
            SELECT raw_object_id, object_kind, content_hash, source_url, provider_id,
                   retrieved_at, media_type, storage_uri, license_id, retention_policy,
                   retention_until, redistribution_allowed, parent_raw_object_id
            FROM raw_objects WHERE raw_object_id = %s
            """,
            (value.raw_object_id,),
        ).fetchone()
        if stored != row:
            raise VersionConflictError(f"immutable raw object conflict: {value.raw_object_id}")

    def _save_work_unit(self, value: FinancialMappingResult) -> None:
        unit = value.provider_batch.work_unit
        row = (
            self._job_id,
            unit.checkpoint_key,
            unit.plan_id,
            unit.provider_id,
            unit.provider_profile_version,
            unit.benchmark_id,
            unit.universe_version_id,
            unit.mapping_version_id,
            unit.statement_type.value,
            unit.provider_table,
            unit.report_period_end,
            unit.symbol_bucket_id,
            list(unit.symbols),
            len(unit.symbols),
        )
        self._connection.execute(
            """
            INSERT INTO financial_backfill_work_units (
                job_id, checkpoint_key, plan_id, provider_id, provider_profile_version,
                benchmark_id, universe_version_id, mapping_version_id, statement_type,
                provider_table, report_period_end, symbol_bucket_id, symbols, symbol_count
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (job_id, checkpoint_key) DO NOTHING
            """,
            (
                *row[:12],
                _json_parameter(row[12]),
                row[13],
            ),
        )
        stored = self._connection.execute(
            """
            SELECT job_id, checkpoint_key, plan_id, provider_id,
                   provider_profile_version, benchmark_id, universe_version_id,
                   mapping_version_id, statement_type, provider_table,
                   report_period_end, symbol_bucket_id, symbols, symbol_count
            FROM financial_backfill_work_units
            WHERE job_id = %s AND checkpoint_key = %s
            """,
            (self._job_id, unit.checkpoint_key),
        ).fetchone()
        if stored is None:
            raise RuntimeError("financial work-unit insert was not observable")
        stored_symbols = _json_value(stored[12])
        normalized = (*stored[:12], stored_symbols, stored[13])
        if normalized != row:
            raise VersionConflictError("immutable financial backfill work-unit conflict")

    def _save_observation(self, value: NormalizedCurrentFinancialObservation) -> None:
        row = self._observation_row(value)
        self._connection.execute(
            """
            INSERT INTO normalized_current_financial_observations (
                observation_id, dataset_version_id, job_id, checkpoint_key,
                company_id, security_id, listing_id, canonical_symbol, identity_as_of,
                mapped_row_id, provider_id, provider_table, provider_record_id,
                provider_field, statement_type, statement_scope, report_period_start,
                report_period_end, period_type, value_basis, raw_value, provider_unit,
                scale_to_canonical, canonical_value, canonical_unit, currency,
                report_version_type, revision_sequence, announced_at, available_at,
                availability_method, provider_updated_at, retrieved_at, raw_object_id,
                raw_object_hash, source_url, mapping_id, mapping_version_id, metric_code,
                trust_state, data_mode, identity_resolution_method, warnings
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            ON CONFLICT (observation_id) DO NOTHING
            """,
            row,
        )
        stored = self._connection.execute(
            self._observation_select() + " WHERE observation_id = %s",
            (value.observation_id,),
        ).fetchone()
        if stored is None or self._observation_from_row(stored) != value:
            raise VersionConflictError(
                f"immutable normalized-current financial observation conflict: "
                f"{value.observation_id}"
            )

    def _save_receipt(
        self,
        checkpoint_key: str,
        value: FinancialPersistResult,
        *,
        created_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO financial_backfill_persist_receipts (
                job_id, checkpoint_key, dataset_version_id, observation_count,
                observation_ids, warnings, trust_state, created_at,
                identity_resolution_method
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id, checkpoint_key) DO NOTHING
            """,
            (
                self._job_id,
                checkpoint_key,
                value.dataset_version_id,
                len(value.observation_ids),
                _json_parameter(list(value.observation_ids)),
                _json_parameter(list(value.warnings)),
                DataTrustState.NORMALIZED_CURRENT.value,
                created_at,
                value.identity_resolution_method.value,
            ),
        )

    @staticmethod
    def _observation_row(value: NormalizedCurrentFinancialObservation) -> tuple[object, ...]:
        return (
            value.observation_id,
            value.dataset_version_id,
            value.job_id,
            value.checkpoint_key,
            value.company_id,
            value.security_id,
            value.listing_id,
            value.canonical_symbol,
            value.identity_as_of,
            value.mapped_row_id,
            value.provider_id,
            value.provider_table,
            value.provider_record_id,
            value.provider_field,
            value.statement_type.value,
            value.statement_scope.value,
            value.report_period_start,
            value.report_period_end,
            value.period_type.value,
            value.value_basis.value,
            value.raw_value,
            value.provider_unit,
            value.scale_to_canonical,
            value.canonical_value,
            value.canonical_unit.value,
            value.currency,
            value.report_version_type.value,
            value.revision_sequence,
            value.announced_at,
            value.available_at,
            value.availability_method.value,
            value.provider_updated_at,
            value.retrieved_at,
            value.raw_object_id,
            value.raw_object_hash,
            value.source_url,
            value.mapping_id,
            value.mapping_version_id,
            value.metric_code,
            value.trust_state.value,
            value.data_mode.value,
            value.identity_resolution_method.value,
            _json_parameter(list(value.warnings)),
        )

    @staticmethod
    def _observation_select() -> str:
        return """
            SELECT observation_id, dataset_version_id, job_id, checkpoint_key,
                   company_id, security_id, listing_id, canonical_symbol, identity_as_of,
                   mapped_row_id, provider_id, provider_table, provider_record_id,
                   provider_field, statement_type, statement_scope, report_period_start,
                   report_period_end, period_type, value_basis, raw_value, provider_unit,
                   scale_to_canonical, canonical_value, canonical_unit, currency,
                   report_version_type, revision_sequence, announced_at, available_at,
                   availability_method, provider_updated_at, retrieved_at, raw_object_id,
                   raw_object_hash, source_url, mapping_id, mapping_version_id, metric_code,
                   trust_state, data_mode, identity_resolution_method, warnings
            FROM normalized_current_financial_observations
        """

    @staticmethod
    def _observation_from_row(row: Sequence[object]) -> NormalizedCurrentFinancialObservation:
        warnings = _json_value(row[42])
        if not isinstance(warnings, (list, tuple)):
            raise TypeError("stored normalized financial warnings must be an array")
        return NormalizedCurrentFinancialObservation(
            observation_id=str(row[0]),
            dataset_version_id=str(row[1]),
            job_id=str(row[2]),
            checkpoint_key=str(row[3]),
            company_id=str(row[4]),
            security_id=str(row[5]),
            listing_id=str(row[6]),
            canonical_symbol=str(row[7]),
            identity_as_of=cast(date, row[8]),
            mapped_row_id=str(row[9]),
            provider_id=str(row[10]),
            provider_table=str(row[11]),
            provider_record_id=str(row[12]),
            provider_field=str(row[13]),
            statement_type=StatementType(str(row[14])),
            statement_scope=FinancialStatementScope(str(row[15])),
            report_period_start=cast(date, row[16]),
            report_period_end=cast(date, row[17]),
            period_type=FinancialPeriodType(str(row[18])),
            value_basis=FinancialValueBasis(str(row[19])),
            raw_value=Decimal(str(row[20])),
            provider_unit=str(row[21]),
            scale_to_canonical=Decimal(str(row[22])),
            canonical_value=Decimal(str(row[23])),
            canonical_unit=MetricUnit(str(row[24])),
            currency=None if row[25] is None else str(row[25]),
            report_version_type=ReportVersionType(str(row[26])),
            revision_sequence=int(cast(int, row[27])),
            announced_at=None if row[28] is None else cast(datetime, row[28]),
            available_at=None if row[29] is None else cast(datetime, row[29]),
            availability_method=AvailabilityMethod(str(row[30])),
            provider_updated_at=None if row[31] is None else cast(datetime, row[31]),
            retrieved_at=cast(datetime, row[32]),
            raw_object_id=str(row[33]),
            raw_object_hash=str(row[34]),
            source_url=str(row[35]),
            mapping_id=str(row[36]),
            mapping_version_id=str(row[37]),
            metric_code=str(row[38]),
            trust_state=DataTrustState(str(row[39])),
            data_mode=DataMode(str(row[40])),
            identity_resolution_method=FinancialIdentityResolutionMethod(str(row[41])),
            warnings=tuple(str(item) for item in warnings),
        )

    def _require_job(self, job_id: str) -> None:
        if job_id != self._job_id:
            raise ValueError("financial unit of work is bound to one job_id")


__all__ = [
    "PostgresCurrentKnownFinancialIdentityResolver",
    "PostgresFinancialBackfillUnitOfWork",
    "PostgresFinancialIdentityResolver",
]
