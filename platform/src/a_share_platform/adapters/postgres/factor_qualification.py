"""PostgreSQL inspection and append-only persistence for P4 factor audits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Protocol, cast

import psycopg

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.adapters.postgres.experiments import (
    PostgresExperimentRunRepository,
)
from a_share_platform.domain.backfill import DatasetQualityStatus
from a_share_platform.domain.factor_lifecycle import ValidationReport
from a_share_platform.domain.factor_qualification import (
    FactorQualificationAudit,
    FactorQualificationRequest,
    FactorQualificationRoleEvidence,
    FactorQualificationSnapshot,
    FactorQualificationTarget,
    FactorRoleAvailability,
)
from a_share_platform.domain.factor_readiness import FactorDataRole
from a_share_platform.domain.pit import DataTrustState


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "obj"):
        return value.obj
    return value


def _array(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("stored qualification array must be a sequence")
    return tuple(sorted(str(item) for item in value if item is not None))


def _query_hash(query: str, parameters: tuple[object, ...]) -> str:
    payload = json.dumps(
        {
            "query": " ".join(query.split()),
            "parameters": [
                value.isoformat() if isinstance(value, (date, datetime)) else value
                for value in parameters
            ],
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[Connection]: ...


_CANDIDATE_QUERY = """
    WITH ranked AS (
        SELECT uv.universe_version_id, uv.dataset_version_id, uv.definition_id,
               ROW_NUMBER() OVER (
                   PARTITION BY uv.definition_id ORDER BY uv.created_at DESC,
                   uv.universe_version_id DESC
               ) AS rank
        FROM universe_versions AS uv
        WHERE uv.definition_id IN ('csi:000300', 'csi:000905')
          AND uv.observation_mode = 'continuous_daily'
    )
    SELECT ranked.universe_version_id, ranked.dataset_version_id,
           COUNT(memberships.listing_id) AS member_count
    FROM ranked
    JOIN universe_memberships AS memberships USING (universe_version_id)
    WHERE ranked.rank = 1
    GROUP BY ranked.universe_version_id, ranked.dataset_version_id
    ORDER BY member_count DESC, ranked.universe_version_id
"""

_TARGET_CTE = """
    WITH ranked AS (
        SELECT uv.universe_version_id, uv.definition_id,
               ROW_NUMBER() OVER (
                   PARTITION BY uv.definition_id ORDER BY uv.created_at DESC,
                   uv.universe_version_id DESC
               ) AS rank
        FROM universe_versions AS uv
        WHERE uv.definition_id IN ('csi:000300', 'csi:000905')
          AND uv.observation_mode = 'continuous_daily'
    ), target AS (
        SELECT DISTINCT memberships.listing_id, listings.security_id
        FROM ranked
        JOIN universe_memberships AS memberships USING (universe_version_id)
        JOIN listings USING (listing_id)
        WHERE ranked.rank = 1
    )
"""


class PostgresFactorQualificationSource:
    """Read only real persisted evidence; never calculates a factor or label."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresFactorQualificationSource:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def inspect(
        self,
        request: FactorQualificationRequest,
        targets: tuple[FactorQualificationTarget, ...],
    ) -> FactorQualificationSnapshot:
        with self._connection_factory() as connection, connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            candidate_rows = connection.execute(_CANDIDATE_QUERY).fetchall()
            if len(candidate_rows) != 2:
                raise LookupError(
                    "both current CSI300 and CSI500 candidate UniverseVersions are required"
                )
            candidates = tuple(str(row[0]) for row in candidate_rows)
            primary = str(candidate_rows[0][0])
            role_evidence = tuple(
                self._inspect_role(connection, request, role)
                for role in FactorDataRole
            )
            metric_rows = connection.execute(
                """
                SELECT DISTINCT metric_code
                FROM financial_fact_observations
                WHERE trust_state = 'pit_verified'
                  AND quality_state = 'passed'
                  AND available_at <= %s
                  AND report_period_end BETWEEN %s AND %s
                ORDER BY metric_code
                """,
                (request.evaluated_at, request.start_date, request.end_date),
            ).fetchall()
            feature_ids = tuple(sorted(value.feature_id for value in targets))
            feature_rows = connection.execute(
                """
                SELECT requested.feature_id, COUNT(snapshots.snapshot_id)
                FROM UNNEST(%s::TEXT[]) AS requested(feature_id)
                LEFT JOIN feature_snapshots AS snapshots
                  ON snapshots.feature_id = requested.feature_id
                 AND snapshots.as_of::DATE BETWEEN %s AND %s
                GROUP BY requested.feature_id
                ORDER BY requested.feature_id
                """,
                (list(feature_ids), request.start_date, request.end_date),
            ).fetchall()
        return FactorQualificationSnapshot(
            request=request,
            candidate_universe_version_id=primary,
            candidate_universe_version_ids=candidates,
            role_evidence=role_evidence,
            observed_pit_metric_codes=tuple(str(row[0]) for row in metric_rows),
            feature_snapshot_counts=tuple(
                (str(feature_id), int(cast(int, count)))
                for feature_id, count in feature_rows
            ),
        )

    def _inspect_role(
        self,
        connection: Connection,
        request: FactorQualificationRequest,
        role: FactorDataRole,
    ) -> FactorQualificationRoleEvidence:
        query, parameters = self._role_query(request, role)
        row = connection.execute(query, parameters).fetchone()
        if row is None:
            raise LookupError(f"qualification query returned no aggregate for {role.value}")
        row_count = int(cast(int, row[0]))
        entity_count = int(cast(int, row[1]))
        start_date = cast(date | None, row[2])
        end_date = cast(date | None, row[3])
        upstream_datasets = _array(row[4])
        upstream_sources = _array(row[5])
        unavailable = row_count == 0
        trust = (
            DataTrustState.PIT_VERIFIED
            if role is FactorDataRole.FINANCIAL_FACT and not unavailable
            else DataTrustState.NORMALIZED_CURRENT
        )
        quality = (
            DatasetQualityStatus.FAILED
            if unavailable
            else DatasetQualityStatus.PASSED
            if role is FactorDataRole.FINANCIAL_FACT
            else DatasetQualityStatus.WARNED
        )
        availability_enforced = False
        lineage_complete = bool(upstream_datasets) and role not in {
            FactorDataRole.HISTORICAL_UNIVERSE,
            FactorDataRole.INDUSTRY_CLASSIFICATION,
        }
        warnings = [
            (
                f"real query observed rows={row_count}, entities={entity_count}; "
                "qualification does not persist source observation payloads"
            )
        ]
        if role is FactorDataRole.INDUSTRY_CLASSIFICATION and unavailable:
            current_industry = connection.execute(
                """
                SELECT COUNT(*), MIN(valid_from),
                       MAX(COALESCE(valid_to, valid_from))
                FROM industry_memberships
                """
            ).fetchone()
            if current_industry is not None and int(cast(int, current_industry[0])) > 0:
                current_rows = int(cast(int, current_industry[0]))
                current_start = cast(date, current_industry[1])
                current_end = cast(date, current_industry[2])
                warnings.append(
                    "PIT-qualified frozen-window binding rows=0; separate "
                    f"current-only rows={current_rows} cover "
                    f"{current_start.isoformat()}..{current_end.isoformat()} outside "
                    "the frozen study window"
                )
        if role is FactorDataRole.FINANCIAL_FACT:
            warnings.append(
                "individual PIT facts exist, but no complete per-decision-time factor panel exists"
            )
        if role is FactorDataRole.CORPORATE_ACTION:
            warnings.append(
                "covered entities include succeeded provider work with explicit zero "
                "observations; zero-event securities are not missing or zero-filled"
            )
        if unavailable:
            warnings.append("no persisted observations matched the frozen qualification scope")
        if trust is not DataTrustState.PIT_VERIFIED:
            warnings.append("source trust ceiling is normalized_current")
        return FactorQualificationRoleEvidence(
            role=role,
            availability=(
                FactorRoleAvailability.UNAVAILABLE
                if unavailable
                else FactorRoleAvailability.OBSERVED
            ),
            upstream_dataset_version_ids=upstream_datasets,
            upstream_source_ids=upstream_sources,
            trust_state=trust,
            quality_status=quality,
            row_count=row_count,
            observed_entity_count=entity_count,
            expected_entity_count=request.expected_entity_count,
            start_date=None if unavailable else start_date,
            end_date=None if unavailable else end_date,
            availability_enforced=availability_enforced,
            lineage_complete=lineage_complete,
            query_hash=_query_hash(query, parameters),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _role_query(
        request: FactorQualificationRequest,
        role: FactorDataRole,
    ) -> tuple[str, tuple[object, ...]]:
        window = (request.start_date, request.end_date)
        if role is FactorDataRole.FINANCIAL_FACT:
            return (
                _TARGET_CTE
                + """
                SELECT COUNT(facts.fact_id), COUNT(DISTINCT target.listing_id),
                       MIN(facts.report_period_end), MAX(facts.report_period_end),
                       ARRAY_AGG(DISTINCT facts.dataset_version_id)
                           FILTER (WHERE facts.dataset_version_id IS NOT NULL),
                       ARRAY_AGG(DISTINCT facts.provider_id)
                           FILTER (WHERE facts.provider_id IS NOT NULL)
                FROM target
                JOIN financial_fact_observations AS facts
                  ON facts.security_id = target.security_id
                WHERE facts.trust_state = 'pit_verified'
                  AND facts.quality_state = 'passed'
                  AND facts.available_at <= %s
                  AND facts.known_from <= %s
                  AND (facts.known_to IS NULL OR %s < facts.known_to)
                  AND facts.report_period_end BETWEEN %s AND %s
                """,
                (
                    request.evaluated_at,
                    request.evaluated_at,
                    request.evaluated_at,
                    *window,
                ),
            )
        if role is FactorDataRole.HISTORICAL_UNIVERSE:
            return (
                """
                SELECT COUNT(memberships.universe_membership_id),
                       COUNT(DISTINCT memberships.listing_id),
                       MIN(memberships.valid_from),
                       MAX(COALESCE(memberships.valid_to, memberships.valid_from)),
                       ARRAY_AGG(DISTINCT versions.dataset_version_id),
                       ARRAY_AGG(DISTINCT memberships.source_id)
                           FILTER (WHERE memberships.source_id IS NOT NULL)
                FROM universe_versions AS versions
                JOIN universe_memberships AS memberships USING (universe_version_id)
                WHERE versions.definition_id IN ('csi:000300', 'csi:000905')
                """,
                (),
            )
        if role is FactorDataRole.CORPORATE_ACTION:
            return (
                _TARGET_CTE
                + """
                , target_codes AS (
                    SELECT DISTINCT target.listing_id, listings.listed_on,
                           CASE listings.exchange
                               WHEN 'XSHG' THEN 'SH.'
                               WHEN 'XSHE' THEN 'SZ.'
                               WHEN 'XBSE' THEN 'BJ.'
                           END || identifiers.value AS provider_symbol
                    FROM target
                    JOIN listings USING (listing_id)
                    JOIN identifier_history AS identifiers USING (listing_id)
                    WHERE identifiers.kind = 'code'
                      AND identifiers.valid_from <= %s
                      AND (
                          identifiers.valid_to IS NULL OR %s < identifiers.valid_to
                      )
                ), successful_action_work AS (
                    SELECT target_codes.listing_id, jobs.dataset_version_id,
                           jobs.provider_id, jobs.start_date, jobs.end_date,
                           COUNT(*) FILTER (
                               WHERE checkpoints.processed_rows = 0
                           ) AS zero_checkpoint_count
                    FROM target_codes
                    JOIN ingestion_jobs AS jobs
                      ON jobs.plan->'symbols' ? target_codes.provider_symbol
                    JOIN ingestion_checkpoints AS checkpoints
                      ON checkpoints.job_id = jobs.job_id
                     AND checkpoints.data_domain = 'corporate_action'
                     AND checkpoints.status = 'succeeded'
                    WHERE jobs.status = 'succeeded'
                      AND jobs.output_trust_state = 'normalized_current'
                      AND jobs.plan->'domains' ? 'corporate_action'
                      AND jobs.start_date <= GREATEST(%s, target_codes.listed_on)
                      AND jobs.end_date >= %s
                    GROUP BY target_codes.listing_id, jobs.dataset_version_id,
                             jobs.provider_id, jobs.start_date, jobs.end_date
                ), covered_action_universe AS (
                    SELECT DISTINCT listing_id FROM successful_action_work
                ), observed_actions AS (
                    SELECT actions.*
                    FROM target
                    JOIN corporate_action_observations AS actions
                      ON actions.listing_id = target.listing_id
                    WHERE actions.ex_date BETWEEN %s AND %s
                )
                SELECT (SELECT COUNT(*) FROM observed_actions),
                       (SELECT COUNT(*) FROM covered_action_universe),
                       (SELECT MIN(start_date) FROM successful_action_work),
                       (SELECT MAX(end_date) FROM successful_action_work),
                       ARRAY(
                           SELECT DISTINCT dataset_version_id
                           FROM (
                               SELECT dataset_version_id FROM observed_actions
                               UNION ALL
                               SELECT dataset_version_id FROM successful_action_work
                           ) AS datasets
                           WHERE dataset_version_id IS NOT NULL
                           ORDER BY dataset_version_id
                       ),
                       ARRAY(
                           SELECT DISTINCT source_id
                           FROM (
                               SELECT source_id FROM observed_actions
                               UNION ALL
                               SELECT provider_id AS source_id
                               FROM successful_action_work
                           ) AS sources
                           WHERE source_id IS NOT NULL
                           ORDER BY source_id
                       )
                """,
                (
                    request.evaluated_at.date(),
                    request.evaluated_at.date(),
                    request.start_date,
                    request.end_date,
                    *window,
                ),
            )
        table_contracts = {
            FactorDataRole.INDUSTRY_CLASSIFICATION: (
                "industry_memberships",
                "industry_membership_id",
                "security_id",
                "valid_from",
                "valid_to",
                None,
                "source_id",
            ),
            FactorDataRole.RAW_DAILY_BAR: (
                "daily_market_states",
                "daily_market_state_id",
                "listing_id",
                "session_date",
                "session_date",
                "dataset_version_id",
                "source_id",
            ),
            FactorDataRole.SHARE_CAPITAL: (
                "share_capital_observations",
                "observation_id",
                "listing_id",
                "effective_on",
                "effective_on",
                "dataset_version_id",
                "source_id",
            ),
        }
        if role in table_contracts:
            table, row_id, entity, start, end, dataset, source = table_contracts[role]
            join = (
                f"observed.{entity} = target.security_id"
                if role is FactorDataRole.INDUSTRY_CLASSIFICATION
                else f"observed.{entity} = target.listing_id"
            )
            dataset_expression = (
                "NULL::TEXT[]"
                if dataset is None
                else (
                    f"ARRAY_AGG(DISTINCT observed.{dataset}) "
                    f"FILTER (WHERE observed.{dataset} IS NOT NULL)"
                )
            )
            end_expression = (
                "COALESCE(observed.valid_to, observed.valid_from)"
                if role is FactorDataRole.INDUSTRY_CLASSIFICATION
                else f"observed.{end}"
            )
            return (
                _TARGET_CTE
                + f"""
                SELECT COUNT(observed.{row_id}), COUNT(DISTINCT target.listing_id),
                       MIN(observed.{start}), MAX({end_expression}),
                       {dataset_expression},
                       ARRAY_AGG(DISTINCT observed.{source})
                           FILTER (WHERE observed.{source} IS NOT NULL)
                FROM target
                JOIN {table} AS observed ON {join}
                WHERE observed.{start} BETWEEN %s AND %s
                """,
                window,
            )
        if role is FactorDataRole.BENCHMARK_BAR:
            return (
                """
                SELECT COUNT(*), COUNT(DISTINCT benchmark_id),
                       MIN(session_date), MAX(session_date),
                       ARRAY_AGG(DISTINCT dataset_version_id),
                       ARRAY_AGG(DISTINCT provider_id)
                FROM timing_benchmark_bars
                WHERE benchmark_id = %s AND session_date BETWEEN %s AND %s
                """,
                (request.benchmark_id, *window),
            )
        if role is FactorDataRole.FORWARD_RETURN_LABEL:
            return (
                _TARGET_CTE
                + """
                SELECT COUNT(labels.content_hash), COUNT(DISTINCT labels.entity_id),
                       MIN(labels.as_of::DATE), MAX(labels.as_of::DATE),
                       ARRAY_AGG(DISTINCT labels.dataset_version_id), NULL::TEXT[]
                FROM target
                JOIN research_labels AS labels
                  ON labels.entity_id IN (target.listing_id, target.security_id)
                WHERE labels.label_id = 'label:forward-return-20d'
                  AND labels.as_of::DATE BETWEEN %s AND %s
                """,
                window,
            )
        raise AssertionError(f"unsupported factor data role: {role.value}")


class PostgresFactorQualificationRepository:
    """Persist role datasets, failed runs, reports, artifacts, and lineage idempotently."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        experiment_repository: PostgresExperimentRunRepository,
    ) -> None:
        self._connection_factory = connection_factory
        self._experiments = experiment_repository

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresFactorQualificationRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect, PostgresExperimentRunRepository.from_dsn(dsn))

    def save(self, value: FactorQualificationAudit) -> bool:
        if not isinstance(value, FactorQualificationAudit):
            raise TypeError("value must be a FactorQualificationAudit")
        with self._connection_factory() as connection, connection.transaction():
            datasets = PostgresDatasetVersionRepository(connection)
            for role_dataset in value.role_datasets:
                manifest = _json_value(role_dataset.manifest.decode())
                if not isinstance(manifest, Mapping):
                    raise TypeError("qualification role manifest must be an object")
                datasets.register_dataset(
                    role_dataset.dataset,
                    metadata={
                        "manifest": dict(manifest),
                        "role": role_dataset.role.value,
                        "row_count": manifest["row_count"],
                        "status": manifest["status"],
                        "trust_state": manifest["trust_state"],
                        "query_hash": manifest["query_hash"],
                        "decision_time_policy_hash": manifest[
                            "decision_time_policy_hash"
                        ],
                    },
                )
        self._experiments.save_run(value.experiment_run)
        with self._connection_factory() as connection, connection.transaction():
            self._save_report(connection, value.validation_report)
            existing = connection.execute(
                """
                SELECT content_hash, experiment_run_id, validation_report_id,
                       artifact_hash
                FROM factor_qualification_audits WHERE audit_id = %s
                """,
                (value.audit_id,),
            ).fetchone()
            created = existing is None
            connection.execute(
                """
                INSERT INTO factor_qualification_audits (
                    audit_id, content_hash, factor_key, factor_version_id,
                    factor_version_hash, factor_lifecycle_status, study_id,
                    snapshot_hash, readiness_permitted, experiment_run_id,
                    validation_report_id, artifact_id, artifact_hash,
                    role_dataset_version_ids, readiness_document,
                    factor_version_document, artifact_document, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                ) ON CONFLICT (audit_id) DO NOTHING
                """,
                self._audit_row(value),
            )
            stored = connection.execute(
                """
                SELECT content_hash, experiment_run_id, validation_report_id,
                       artifact_hash
                FROM factor_qualification_audits WHERE audit_id = %s
                """,
                (value.audit_id,),
            ).fetchone()
            expected = (
                value.content_hash,
                value.experiment_run.run_id,
                value.validation_report.report_id,
                value.artifact_hash,
            )
            if stored != expected:
                raise RuntimeError(f"immutable factor qualification conflict: {value.audit_id}")
            self._save_lineage(connection, value)
            return created

    @staticmethod
    def _save_report(connection: Connection, value: ValidationReport) -> None:
        document = PostgresFactorQualificationRepository._report_document(value)
        connection.execute(
            """
            INSERT INTO factor_validation_reports (
                report_id, content_hash, report_kind, factor_version_id,
                experiment_run_id, input_trust_state, passes_promotion_gate,
                report_document, created_at
            ) VALUES (%s, %s, 'p4_data_qualification', %s, %s, %s, FALSE, %s, %s)
            ON CONFLICT (report_id) DO NOTHING
            """,
            (
                value.report_id,
                value.content_hash,
                value.factor_version_id,
                value.experiment_run_id,
                value.input_trust_state.value,
                _json_parameter(document),
                value.created_at,
            ),
        )
        stored = connection.execute(
            """
            SELECT content_hash, experiment_run_id, passes_promotion_gate
            FROM factor_validation_reports WHERE report_id = %s
            """,
            (value.report_id,),
        ).fetchone()
        if stored != (value.content_hash, value.experiment_run_id, False):
            raise RuntimeError(f"immutable ValidationReport conflict: {value.report_id}")

    @staticmethod
    def _audit_row(value: FactorQualificationAudit) -> tuple[object, ...]:
        artifact_document = _json_value(value.artifact_payload.decode())
        role_datasets = {
            item.role.value: item.dataset.dataset_version_id
            for item in value.role_datasets
        }
        readiness = {
            "study_id": value.readiness.study_id,
            "evaluated_at": value.readiness.evaluated_at.isoformat(),
            "permitted": value.readiness.permitted,
            "blockers": value.readiness.blockers,
            "warnings": value.readiness.warnings,
            "bound_dataset_version_ids": value.readiness.bound_dataset_version_ids,
        }
        factor = {
            "factor_version_id": value.factor_version.factor_version_id,
            "factor_id": value.factor_version.factor_id,
            "semantic_version": value.factor_version.semantic_version,
            "content_hash": value.factor_version.content_hash,
            "definition_hash": value.factor_version.definition_hash,
            "code_sha": value.factor_version.code_sha,
            "dataset_version_ids": value.factor_version.dataset_version_ids,
            "feature_version_ids": value.factor_version.feature_version_ids,
            "model_version_ids": value.factor_version.model_version_ids,
            "created_by": value.factor_version.created_by,
            "created_at": value.factor_version.created_at.isoformat(),
            "status": value.factor_version.status.value,
        }
        return (
            value.audit_id,
            value.content_hash,
            value.target.factor_key,
            value.factor_version.factor_version_id,
            value.factor_version.content_hash,
            value.factor_version.status.value,
            value.readiness.study_id,
            value.snapshot.content_hash,
            value.experiment_run.run_id,
            value.validation_report.report_id,
            value.artifact_id,
            value.artifact_hash,
            _json_parameter(role_datasets),
            _json_parameter(readiness),
            _json_parameter(factor),
            _json_parameter(artifact_document),
            value.created_at,
        )

    @staticmethod
    def _report_document(value: ValidationReport) -> dict[str, object]:
        return {
            "report_id": value.report_id,
            "report_version": value.report_version,
            "content_hash": value.content_hash,
            "factor_version_id": value.factor_version_id,
            "experiment_run_id": value.experiment_run_id,
            "dataset_version_ids": value.dataset_version_ids,
            "code_sha": value.code_sha,
            "artifact_hashes": value.artifact_hashes,
            "run_context": {
                "data_mode": value.run_context.data_mode.value,
                "deployment_stage": value.run_context.deployment_stage.value,
            },
            "input_trust_state": value.input_trust_state.value,
            "historical_evidence_eligible": value.historical_evidence_eligible,
            "passes_promotion_gate": value.passes_promotion_gate,
            "checks": [item.hash_payload() for item in value.checks],
            "created_at": value.created_at.isoformat(),
        }

    @staticmethod
    def _save_lineage(connection: Connection, value: FactorQualificationAudit) -> None:
        edges: set[tuple[str, str, str]] = set()
        by_role = {item.role: item for item in value.role_datasets}
        for evidence in value.snapshot.role_evidence:
            downstream = by_role[evidence.role].dataset.dataset_version_id
            upstream = (
                *evidence.upstream_dataset_version_ids,
                *evidence.upstream_source_ids,
                f"query:{evidence.query_hash}",
            )
            edges.update((item, downstream, "qualified_into") for item in upstream)
            edges.add((downstream, value.experiment_run.run_id, "qualification_input"))
        edges.update(
            {
                (
                    value.experiment_run.run_id,
                    value.validation_report.report_id,
                    "validated_by",
                ),
                (value.experiment_run.run_id, value.artifact_id, "produced"),
                (value.artifact_id, value.audit_id, "evidences"),
            }
        )
        for upstream_id, downstream_id, relation in sorted(edges):
            connection.execute(
                """
                INSERT INTO lineage_edges (upstream_id, downstream_id, relation)
                VALUES (%s, %s, %s)
                ON CONFLICT (upstream_id, downstream_id, relation) DO NOTHING
                """,
                (upstream_id, downstream_id, relation),
            )


__all__ = [
    "PostgresFactorQualificationRepository",
    "PostgresFactorQualificationSource",
]
