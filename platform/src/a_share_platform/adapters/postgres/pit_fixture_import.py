"""Transactional private-local import of the real P3 PIT fixture pack."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.pit_fixtures import (
    FixtureEvidence,
    FixtureRevisionVersion,
    PITFixturePack,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return Jsonb(value)


def _json_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _time(value: object, field_name: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, field_name))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO datetime") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return result


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


@dataclass(frozen=True)
class PITFixtureImportSummary:
    pack_version: str
    dataset_version_id: str
    company_count: int
    official_evidence_count: int
    provider_evidence_count: int
    disclosure_count: int
    revision_chain_count: int
    official_fact_count: int
    persisted_fact_count: int
    blocking_mismatch_count: int
    writes_performed: bool


@dataclass(frozen=True)
class _Identity:
    company_id: str
    security_id: str


@dataclass(frozen=True)
class _Metric:
    code: str
    name: str
    unit: str
    currency_requirement: str


@dataclass(frozen=True)
class _IdentitySnapshotRow:
    code: str
    code_name: str
    listed_on: date
    delisted_on: date | None
    status: str


@dataclass(frozen=True)
class _IdentitySnapshot:
    retrieved_at: datetime
    provider_id: str
    source_url: str
    content_hash: str
    rows: tuple[_IdentitySnapshotRow, ...]

    @classmethod
    def load(cls, path: Path) -> _IdentitySnapshot:
        payload = Path(path).read_bytes()
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise TypeError("private identity snapshot must be a JSON object")
        rows_raw = raw.get("rows")
        if not isinstance(rows_raw, list) or not rows_raw:
            raise ValueError("private identity snapshot requires rows")
        rows: list[_IdentitySnapshotRow] = []
        for item in rows_raw:
            if not isinstance(item, dict):
                raise TypeError("private identity snapshot row must be an object")
            code = _text(item.get("code"), "identity code")
            if not code.startswith(("SH.", "SZ.")) or len(code) != 9:
                raise ValueError("private identity code must use SH.000000 or SZ.000000")
            try:
                listed_on = date.fromisoformat(_text(item.get("listed_on"), "listed_on"))
                delisted_raw = item.get("delisted_on")
                delisted_on = (
                    None
                    if delisted_raw is None
                    else date.fromisoformat(_text(delisted_raw, "delisted_on"))
                )
            except ValueError as error:
                raise ValueError("identity listing dates must be ISO dates") from error
            status = _text(item.get("status"), "identity status")
            if status not in {"active", "terminated"}:
                raise ValueError("identity status must be active or terminated")
            if (status == "terminated") != (delisted_on is not None):
                raise ValueError("terminated identity requires delisted_on and active forbids it")
            rows.append(
                _IdentitySnapshotRow(
                    code=code,
                    code_name=_text(item.get("code_name"), "code_name"),
                    listed_on=listed_on,
                    delisted_on=delisted_on,
                    status=status,
                )
            )
        if len({row.code for row in rows}) != len(rows):
            raise ValueError("private identity snapshot contains duplicate codes")
        return cls(
            retrieved_at=_time(raw.get("retrieved_at"), "retrieved_at"),
            provider_id=_text(raw.get("provider_id"), "provider_id"),
            source_url=_text(raw.get("source_url"), "source_url"),
            content_hash="sha256:" + hashlib.sha256(payload).hexdigest(),
            rows=tuple(rows),
        )


_METRICS = {
    "income.operating_revenue": _Metric(
        "income.operating_revenue", "营业收入", "currency", "required"
    ),
    "income.operating_cost": _Metric(
        "income.operating_cost", "营业成本", "currency", "required"
    ),
    "income.net_profit_parent": _Metric(
        "income.net_profit_parent", "归属于母公司股东的净利润", "currency", "required"
    ),
    "income.basic_eps": _Metric(
        "income.basic_eps", "基本每股收益", "currency_per_share", "required"
    ),
}


class PostgresPITFixtureImporter:
    """Fail-closed importer; preview never touches files, network, or PostgreSQL."""

    def __init__(
        self,
        pack: PITFixturePack,
        evidence_root: Path,
        *,
        identity_snapshot_path: Path | None = None,
    ) -> None:
        self._pack = pack
        self._evidence_root = Path(evidence_root)
        self._identity_snapshot_path = (
            None if identity_snapshot_path is None else Path(identity_snapshot_path)
        )
        pack.require_w04_capability_coverage()
        self._validate_expected_metrics()

    @property
    def dataset_version_id(self) -> str:
        version = self._pack.pack_version.replace(":", "-")
        return f"dataset:{version}"

    def preview(self) -> PITFixtureImportSummary:
        official_fact_count = sum(
            len(version.expected_facts)
            for chain in self._pack.revision_chains
            for version in (chain.original, chain.corrected)
        )
        provider_fact_count = sum(
            1
            for item in self._pack.provider_conflicts
            if item.get("provider_operating_revenue") is not None
        )
        return PITFixtureImportSummary(
            pack_version=self._pack.pack_version,
            dataset_version_id=self.dataset_version_id,
            company_count=len(self._pack.company_codes),
            official_evidence_count=len(self._pack.evidence),
            provider_evidence_count=len(self._pack.provider_conflicts),
            disclosure_count=len(self._pack.evidence),
            revision_chain_count=len(self._pack.revision_chains),
            official_fact_count=official_fact_count,
            persisted_fact_count=official_fact_count + provider_fact_count,
            blocking_mismatch_count=len(self._pack.provider_conflicts),
            writes_performed=False,
        )

    def execute(
        self,
        connection: Connection,
        *,
        private_local_research_ack: bool,
    ) -> PITFixtureImportSummary:
        if not private_local_research_ack:
            raise PermissionError("private-local research acknowledgement is required")
        root = self._evidence_root.resolve()
        if "private-research" not in root.parts:
            raise PermissionError("P3 raw evidence must remain under private-research storage")
        self._pack.verify_raw_evidence(root)
        try:
            try:
                identities = self._resolve_identities(connection)
            except ValueError:
                if self._identity_snapshot_path is None:
                    raise
                snapshot = _IdentitySnapshot.load(self._identity_snapshot_path)
                self._bootstrap_identities(connection, snapshot)
                identities = self._resolve_identities(connection)
            self._persist(connection, identities, root)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        preview = self.preview()
        return PITFixtureImportSummary(
            **{
                **preview.__dict__,
                "writes_performed": True,
            }
        )

    def _validate_expected_metrics(self) -> None:
        unknown = {
            code
            for chain in self._pack.revision_chains
            for version in (chain.original, chain.corrected)
            for code, _ in version.expected_facts
            if code not in _METRICS
        }
        if unknown:
            raise ValueError(f"fixture uses unregistered canonical metrics: {sorted(unknown)}")
        for chain in self._pack.revision_chains:
            for version in (chain.original, chain.corrected):
                for code, encoded in version.expected_facts:
                    self._parse_fact(code, encoded)

    @staticmethod
    def _parse_fact(metric_code: str, encoded: str) -> tuple[str, _Metric, str]:
        try:
            value, supplied_unit = encoded.rsplit(" ", 1)
            number = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"invalid expected fact for {metric_code}: {encoded}") from error
        if not number.is_finite():
            raise ValueError(f"expected fact for {metric_code} must be finite")
        metric = _METRICS[metric_code]
        required_unit = "CNY/share" if metric.unit == "currency_per_share" else "CNY"
        if supplied_unit != required_unit:
            raise ValueError(
                f"expected fact unit for {metric_code} must be {required_unit}"
            )
        return value, metric, "CNY"

    def _resolve_identities(self, connection: Connection) -> dict[str, _Identity]:
        return {
            code: self._resolve_identity(connection, code, self._identity_as_of(code))
            for code in sorted(self._pack.company_codes)
        }

    def _identity_as_of(self, code: str) -> date:
        dates = tuple(
            item.available_at.date()
            for item in self._pack.evidence
            if item.company_code == code
        )
        if not dates:
            raise ValueError(f"fixture company {code} lacks official evidence")
        return min(dates)

    @staticmethod
    def _resolve_identity(connection: Connection, code: str, as_of: date) -> _Identity:
        rows = connection.execute(
            """
            SELECT DISTINCT company.company_id, security.security_id
            FROM identifier_history identifier
            JOIN listings listing ON listing.listing_id = identifier.listing_id
            JOIN securities security ON security.security_id = listing.security_id
            JOIN companies company ON company.company_id = security.company_id
            WHERE identifier.kind = 'code' AND identifier.value = %s
              AND identifier.valid_from <= %s
              AND (identifier.valid_to IS NULL OR identifier.valid_to > %s)
            ORDER BY company.company_id, security.security_id
            LIMIT 2
            """,
            (code, as_of, as_of),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(
                f"fixture company code {code} resolves to multiple securities as of {as_of}"
            )
        if len(rows) == 1:
            return _Identity(str(rows[0][0]), str(rows[0][1]))
        exchange = "XSHG" if code.startswith(("6", "9")) else "XSHE"
        listing_id = f"listing:{exchange}:{code}"
        fallback = connection.execute(
            """
            SELECT company.company_id, security.security_id
            FROM listings listing
            JOIN securities security ON security.security_id = listing.security_id
            JOIN companies company ON company.company_id = security.company_id
            WHERE listing.listing_id = %s
              AND listing.listed_on <= %s
              AND (listing.delisted_on IS NULL OR %s <= listing.delisted_on)
            """,
            (listing_id, as_of, as_of),
        ).fetchall()
        if len(fallback) != 1:
            raise ValueError(
                f"fixture company code {code} must resolve to one compatible security "
                f"as of {as_of}"
            )
        return _Identity(str(fallback[0][0]), str(fallback[0][1]))

    def _bootstrap_identities(
        self,
        connection: Connection,
        snapshot: _IdentitySnapshot,
    ) -> None:
        rows = {
            row.code.split(".", 1)[1]: row
            for row in snapshot.rows
            if row.code.split(".", 1)[1] in self._pack.company_codes
        }
        unresolved = tuple(
            code
            for code in sorted(self._pack.company_codes)
            if self._try_resolve_identity(connection, code) is None
        )
        missing = set(unresolved).difference(rows)
        if missing:
            raise ValueError(
                f"private identity snapshot does not cover unresolved codes: {sorted(missing)}"
            )
        digest = snapshot.content_hash.removeprefix("sha256:")[:20]
        raw_object_id = f"raw:baostock:security-basic:{digest}"
        dataset_version_id = f"dataset:baostock:security-basic:{digest}"
        self._immutable_insert(
            connection,
            "raw_objects",
            "raw_object_id",
            (
                "raw_object_id",
                "object_kind",
                "content_hash",
                "source_url",
                "provider_id",
                "retrieved_at",
                "media_type",
                "storage_uri",
                "license_id",
                "retention_policy",
                "retention_until",
                "redistribution_allowed",
                "parent_raw_object_id",
            ),
            (
                raw_object_id,
                "response",
                snapshot.content_hash,
                snapshot.source_url,
                snapshot.provider_id,
                snapshot.retrieved_at,
                "application/json",
                self._identity_snapshot_path.resolve().as_uri(),  # type: ignore[union-attr]
                "license:baostock-private-local-research:v1",
                "indefinite",
                None,
                False,
                None,
            ),
        )
        self._immutable_insert(
            connection,
            "dataset_versions",
            "dataset_version_id",
            (
                "dataset_version_id",
                "content_hash",
                "created_at",
                "schema_version",
                "metadata",
            ),
            (
                dataset_version_id,
                snapshot.content_hash,
                snapshot.retrieved_at,
                "security-identity-snapshot:v1",
                _json_parameter(
                    {
                        "manifest": {
                            "provider_id": snapshot.provider_id,
                            "retrieved_at": snapshot.retrieved_at.isoformat(),
                            "trust_state": "normalized_current",
                            "usage": "private_local_research",
                            "symbols": sorted(row.code for row in snapshot.rows),
                        }
                    }
                ),
            ),
        )
        legal_names = dict(self._pack.company_legal_names)
        official_by_code = {
            code: min(
                (item for item in self._pack.evidence if item.company_code == code),
                key=lambda item: item.available_at,
            )
            for code in unresolved
        }
        for code in unresolved:
            row = rows[code]
            exchange = "XSHG" if row.code.startswith("SH.") else "XSHE"
            board = "chinext" if row.code.startswith("SZ.30") else "main"
            company_id = f"company:cn:{exchange}:{code}"
            security_id = f"security:cn:{exchange}:{code}:a-share"
            listing_id = f"listing:{exchange}:{code}"
            official = official_by_code[code]
            self._immutable_insert(
                connection,
                "companies",
                "company_id",
                (
                    "company_id",
                    "legal_name",
                    "legal_name_source_id",
                    "observed_on",
                    "dataset_version_id",
                    "trust_state",
                ),
                (
                    company_id,
                    legal_names[code],
                    self._official_raw_id(official.external_document_id),
                    self._pack.assembled_at.date(),
                    dataset_version_id,
                    "normalized_current",
                ),
            )
            self._immutable_insert(
                connection,
                "securities",
                "security_id",
                ("security_id", "company_id", "security_class", "currency"),
                (security_id, company_id, "a_share", "CNY"),
            )
            self._immutable_insert(
                connection,
                "listings",
                "listing_id",
                (
                    "listing_id",
                    "security_id",
                    "exchange",
                    "board",
                    "listed_on",
                    "delisted_on",
                ),
                (
                    listing_id,
                    security_id,
                    exchange,
                    board,
                    row.listed_on,
                    row.delisted_on,
                ),
            )
            identifier = connection.execute(
                """
                INSERT INTO identifier_history (
                    listing_id, kind, value, valid_from, valid_to, source_id
                ) VALUES (%s, 'code', %s, %s, %s, %s)
                ON CONFLICT (listing_id, kind, valid_from) DO UPDATE SET
                    value = identifier_history.value
                WHERE identifier_history.value = EXCLUDED.value
                  AND identifier_history.valid_to IS NOT DISTINCT FROM EXCLUDED.valid_to
                  AND identifier_history.source_id = EXCLUDED.source_id
                RETURNING identifier_history_id
                """,
                (
                    listing_id,
                    code,
                    row.listed_on,
                    row.delisted_on,
                    snapshot.provider_id,
                ),
            ).fetchone()
            if identifier is None:
                raise VersionConflictError(
                    f"immutable identifier conflict in identifier_history: {code}"
                )
            state_from = row.delisted_on or snapshot.retrieved_at.date()
            state = connection.execute(
                """
                INSERT INTO listing_state_periods (
                    listing_id, valid_from, valid_to, state, special_treatment, source_id
                ) VALUES (%s, %s, NULL, %s, NULL, %s)
                ON CONFLICT (listing_id, valid_from) DO UPDATE SET
                    state = listing_state_periods.state
                WHERE listing_state_periods.valid_to IS NULL
                  AND listing_state_periods.state = EXCLUDED.state
                  AND listing_state_periods.special_treatment IS NULL
                  AND listing_state_periods.source_id = EXCLUDED.source_id
                RETURNING listing_state_period_id
                """,
                (listing_id, state_from, row.status, snapshot.provider_id),
            ).fetchone()
            if state is None:
                raise VersionConflictError(
                    f"immutable listing-state conflict: {listing_id}:{state_from}"
                )
            self._insert_lineage(connection, raw_object_id, dataset_version_id, "source_for")
            self._insert_lineage(connection, dataset_version_id, company_id, "contains")
            self._insert_lineage(connection, dataset_version_id, listing_id, "contains")

    def _try_resolve_identity(self, connection: Connection, code: str) -> _Identity | None:
        try:
            return self._resolve_identity(connection, code, self._identity_as_of(code))
        except ValueError as error:
            if "must resolve to one compatible security" not in str(error):
                raise
            return None

    def _persist(
        self,
        connection: Connection,
        identities: dict[str, _Identity],
        root: Path,
    ) -> None:
        official_by_external = {
            item.external_document_id: item for item in self._pack.evidence
        }
        for evidence in self._pack.evidence:
            self._insert_raw_evidence(connection, evidence, root)
        for conflict in self._pack.provider_conflicts:
            self._insert_provider_evidence(connection, conflict)

        self._insert_dataset(connection)
        self._insert_metrics_and_mappings(connection)
        self._insert_authority_rule(connection)

        for evidence in sorted(
            self._pack.evidence,
            key=lambda item: (item.document_key, item.version_sequence),
        ):
            self._insert_disclosure(connection, evidence, identities[evidence.company_code])

        fact_ids: list[str] = []
        for chain in self._pack.revision_chains:
            identity = identities[chain.company_code]
            for version in (chain.original, chain.corrected):
                evidence = official_by_external[version.external_document_id]
                fact_ids.extend(
                    self._insert_official_facts(
                        connection,
                        chain.company_code,
                        identity,
                        chain.report_period_end,
                        evidence,
                        version,
                    )
                )
        for conflict in self._pack.provider_conflicts:
            fact_id = self._insert_provider_conflict_fact(
                connection,
                conflict,
                identities[_text(conflict.get("company_code"), "company_code")],
            )
            if fact_id is not None:
                fact_ids.append(fact_id)
        self._insert_job_and_quality(connection)
        for fact_id in fact_ids:
            self._insert_lineage(
                connection,
                self.dataset_version_id,
                fact_id,
                "contains",
            )

    def _insert_raw_evidence(
        self,
        connection: Connection,
        evidence: FixtureEvidence,
        root: Path,
    ) -> None:
        path = (root / evidence.local_filename).resolve()
        if not path.is_relative_to(root):
            raise PermissionError("fixture evidence path escapes the private root")
        self._immutable_insert(
            connection,
            "raw_objects",
            "raw_object_id",
            (
                "raw_object_id",
                "object_kind",
                "content_hash",
                "source_url",
                "provider_id",
                "retrieved_at",
                "media_type",
                "storage_uri",
                "license_id",
                "retention_policy",
                "retention_until",
                "redistribution_allowed",
                "parent_raw_object_id",
            ),
            (
                self._official_raw_id(evidence.external_document_id),
                "file",
                f"sha256:{evidence.content_sha256}",
                evidence.source_url,
                "provider:cninfo",
                evidence.retrieved_at,
                "application/pdf",
                path.as_uri(),
                "license:cninfo-private-local-research:v1",
                "indefinite",
                None,
                False,
                None,
            ),
        )

    def _insert_provider_evidence(
        self,
        connection: Connection,
        conflict: dict[str, object],
    ) -> None:
        conflict_id = _text(conflict.get("conflict_id"), "conflict_id")
        provider_id = self._provider_id(conflict)
        self._immutable_insert(
            connection,
            "raw_objects",
            "raw_object_id",
            (
                "raw_object_id",
                "object_kind",
                "content_hash",
                "source_url",
                "provider_id",
                "retrieved_at",
                "media_type",
                "storage_uri",
                "license_id",
                "retention_policy",
                "retention_until",
                "redistribution_allowed",
                "parent_raw_object_id",
            ),
            (
                self._provider_raw_id(conflict_id),
                "response",
                _json_hash(conflict),
                _text(conflict.get("source_url"), "source_url"),
                provider_id,
                _time(conflict.get("retrieved_at"), "retrieved_at"),
                "application/json",
                f"metadata://p3-fixture/{conflict_id}",
                "license:provider-observation-metadata-only:v1",
                "metadata_only",
                None,
                False,
                None,
            ),
        )

    def _insert_dataset(self, connection: Connection) -> None:
        metadata = {
            "manifest": {
                "pack_version": self._pack.pack_version,
                "assembled_at": self._pack.assembled_at.isoformat(),
                "company_codes": sorted(self._pack.company_codes),
                "official_evidence_hashes": sorted(
                    f"sha256:{item.content_sha256}" for item in self._pack.evidence
                ),
                "scenarios": sorted(self._pack.declared_scenarios),
                "usage": "private_local_research",
                "strict_eligibility": "official_facts_only",
            }
        }
        self._immutable_insert(
            connection,
            "dataset_versions",
            "dataset_version_id",
            (
                "dataset_version_id",
                "content_hash",
                "created_at",
                "schema_version",
                "metadata",
            ),
            (
                self.dataset_version_id,
                self._pack.manifest_content_hash,
                self._pack.assembled_at,
                "p3-pit-fixture-pack:v1",
                _json_parameter(metadata),
            ),
        )

    def _insert_metrics_and_mappings(self, connection: Connection) -> None:
        for metric in sorted(_METRICS.values(), key=lambda item: item.code):
            self._immutable_insert(
                connection,
                "canonical_metrics",
                "metric_code",
                (
                    "metric_code",
                    "canonical_name",
                    "statement_type",
                    "unit",
                    "currency_requirement",
                    "sign_convention",
                    "description",
                ),
                (
                    metric.code,
                    metric.name,
                    "income_statement",
                    metric.unit,
                    metric.currency_requirement,
                    "natural",
                    f"P3 人工核验官方披露指标：{metric.name}",
                ),
            )
        providers = ["provider:cninfo"] + sorted(
            {
                self._provider_id(conflict)
                for conflict in self._pack.provider_conflicts
                if conflict.get("provider_operating_revenue") is not None
            }
        )
        for provider_id in providers:
            mapping_version = self._mapping_version_id(provider_id)
            mapping_specs = [
                (metric.code, metric.code)
                for metric in sorted(_METRICS.values(), key=lambda item: item.code)
            ]
            if provider_id != "provider:cninfo":
                mapping_specs = [("营业总收入", "income.operating_revenue")]
            self._immutable_insert(
                connection,
                "metric_mapping_versions",
                "mapping_version_id",
                (
                    "mapping_version_id",
                    "provider_id",
                    "created_at",
                    "content_hash",
                    "code_version",
                ),
                (
                    mapping_version,
                    provider_id,
                    self._pack.assembled_at,
                    _json_hash(mapping_specs),
                    "p3-pit-fixture-import:v1",
                ),
            )
            for source_field, metric_code in mapping_specs:
                mapping_id = f"mapping:{provider_id.removeprefix('provider:')}:{metric_code}:v1"
                self._immutable_insert(
                    connection,
                    "provider_field_mappings",
                    "mapping_id",
                    (
                        "mapping_id",
                        "mapping_version_id",
                        "provider_id",
                        "statement_type",
                        "source_field",
                        "metric_code",
                        "method",
                        "formula",
                        "production_allowed",
                    ),
                    (
                        mapping_id,
                        mapping_version,
                        provider_id,
                        "income_statement",
                        source_field,
                        metric_code,
                        "manual_verified" if provider_id == "provider:cninfo" else "exact",
                        None,
                        True,
                    ),
                )

    def _insert_authority_rule(self, connection: Connection) -> None:
        providers = ["provider:cninfo"] + sorted(
            {self._provider_id(item) for item in self._pack.provider_conflicts}
        )
        self._immutable_insert(
            connection,
            "financial_authority_rules",
            "rule_version",
            ("rule_version", "provider_priority", "created_at", "code_version"),
            (
                "authority:p3-official-first:v1",
                _json_parameter(providers),
                self._pack.assembled_at,
                "p3-pit-fixture-import:v1",
            ),
        )

    def _insert_disclosure(
        self,
        connection: Connection,
        evidence: FixtureEvidence,
        identity: _Identity,
    ) -> None:
        supersedes = (
            None
            if evidence.supersedes_external_document_id is None
            else self._disclosure_id(evidence.supersedes_external_document_id)
        )
        self._immutable_insert(
            connection,
            "official_disclosures",
            "disclosure_id",
            (
                "disclosure_id",
                "document_key",
                "external_document_id",
                "company_id",
                "security_id",
                "source_system",
                "title",
                "document_type",
                "report_period_end",
                "published_at",
                "available_at",
                "first_tradable_at",
                "version_sequence",
                "status",
                "raw_object_id",
                "supersedes_disclosure_id",
                "status_reason",
                "publication_time_precision",
            ),
            (
                self._disclosure_id(evidence.external_document_id),
                evidence.document_key,
                evidence.external_document_id,
                identity.company_id,
                identity.security_id,
                "cninfo",
                evidence.title,
                evidence.document_type,
                evidence.report_period_end,
                evidence.official_reported_at,
                evidence.available_at,
                evidence.first_tradable_at,
                evidence.version_sequence,
                evidence.status,
                self._official_raw_id(evidence.external_document_id),
                supersedes,
                evidence.status_reason,
                evidence.publication_time_precision,
            ),
        )
        self._insert_lineage(
            connection,
            self._official_raw_id(evidence.external_document_id),
            self._disclosure_id(evidence.external_document_id),
            "evidence_for",
        )

    def _insert_official_facts(
        self,
        connection: Connection,
        company_code: str,
        identity: _Identity,
        report_period_end: str,
        evidence: FixtureEvidence,
        version: FixtureRevisionVersion,
    ) -> list[str]:
        result: list[str] = []
        period_end = date.fromisoformat(report_period_end)
        period_type = self._period_type(period_end)
        mapping_version = self._mapping_version_id("provider:cninfo")
        for metric_code, encoded in version.expected_facts:
            value, metric, currency = self._parse_fact(metric_code, encoded)
            fact_id = (
                f"fact:cninfo:{company_code}:{period_end.isoformat()}:{metric_code}:"
                f"r{evidence.version_sequence}"
            )
            self._insert_fact(
                connection,
                fact_id=fact_id,
                identity=identity,
                metric=metric,
                value=value,
                currency=currency,
                report_period_end=period_end,
                period_type=period_type,
                announced_at=evidence.official_reported_at,
                available_at=evidence.available_at,
                revision_sequence=evidence.version_sequence,
                provider_id="provider:cninfo",
                source_field=metric_code,
                raw_object_hash=f"sha256:{evidence.content_sha256}",
                trust_state="pit_verified",
                quality_state="passed",
                mapping_version_id=mapping_version,
                source_object_id=self._official_raw_id(evidence.external_document_id),
                quality_issue_ids=(),
            )
            self._insert_fact_lineage(
                connection,
                fact_id,
                self._official_raw_id(evidence.external_document_id),
                mapping_version,
            )
            result.append(fact_id)
        return result

    def _insert_provider_conflict_fact(
        self,
        connection: Connection,
        conflict: dict[str, object],
        identity: _Identity,
    ) -> str | None:
        raw_value = conflict.get("provider_operating_revenue")
        if raw_value is None:
            return None
        value = _text(raw_value, "provider_operating_revenue")
        try:
            if not Decimal(value).is_finite():
                raise ValueError
        except (InvalidOperation, ValueError) as error:
            raise ValueError("provider_operating_revenue must be finite numeric text") from error
        provider_id = self._provider_id(conflict)
        conflict_id = _text(conflict.get("conflict_id"), "conflict_id")
        report_period_end = date.fromisoformat(
            _text(conflict.get("provider_report_period"), "provider_report_period")
        )
        retrieved_at = _time(conflict.get("retrieved_at"), "retrieved_at")
        quality_issues_raw = conflict.get("quality_issues")
        if not isinstance(quality_issues_raw, list) or not quality_issues_raw:
            raise ValueError("provider conflict requires quality_issues")
        quality_issues = tuple(_text(item, "quality issue") for item in quality_issues_raw)
        fact_id = f"fact:provider-conflict:{hashlib.sha256(conflict_id.encode()).hexdigest()[:20]}"
        mapping_version = self._mapping_version_id(provider_id)
        self._insert_fact(
            connection,
            fact_id=fact_id,
            identity=identity,
            metric=_METRICS["income.operating_revenue"],
            value=value,
            currency="CNY",
            report_period_end=report_period_end,
            period_type=self._period_type(report_period_end),
            announced_at=retrieved_at,
            available_at=retrieved_at,
            revision_sequence=0,
            provider_id=provider_id,
            source_field=_text(conflict.get("provider_source_field"), "provider_source_field"),
            raw_object_hash=_json_hash(conflict),
            trust_state="normalized_current",
            quality_state="blocked",
            mapping_version_id=mapping_version,
            source_object_id=self._provider_raw_id(conflict_id),
            quality_issue_ids=quality_issues,
        )
        self._insert_fact_lineage(
            connection,
            fact_id,
            self._provider_raw_id(conflict_id),
            mapping_version,
        )
        return fact_id

    def _insert_fact(
        self,
        connection: Connection,
        *,
        fact_id: str,
        identity: _Identity,
        metric: _Metric,
        value: str,
        currency: str,
        report_period_end: date,
        period_type: str,
        announced_at: datetime,
        available_at: datetime,
        revision_sequence: int,
        provider_id: str,
        source_field: str,
        raw_object_hash: str,
        trust_state: str,
        quality_state: str,
        mapping_version_id: str,
        source_object_id: str,
        quality_issue_ids: tuple[str, ...],
    ) -> None:
        self._immutable_insert(
            connection,
            "financial_fact_observations",
            "fact_id",
            (
                "fact_id",
                "company_id",
                "security_id",
                "metric_code",
                "fact_value",
                "unit",
                "currency",
                "report_period_end",
                "period_type",
                "statement_type",
                "announced_at",
                "available_at",
                "known_from",
                "known_to",
                "revision_sequence",
                "provider_id",
                "source_field",
                "raw_object_hash",
                "trust_state",
                "quality_state",
                "mapping_version_id",
                "source_object_id",
                "dataset_version_id",
                "quality_issue_ids",
            ),
            (
                fact_id,
                identity.company_id,
                identity.security_id,
                metric.code,
                _json_parameter(value),
                metric.unit,
                currency,
                report_period_end,
                period_type,
                "income_statement",
                announced_at,
                available_at,
                self._pack.assembled_at,
                None,
                revision_sequence,
                provider_id,
                source_field,
                raw_object_hash,
                trust_state,
                quality_state,
                mapping_version_id,
                source_object_id,
                self.dataset_version_id,
                _json_parameter(list(quality_issue_ids)),
            ),
        )

    def _insert_fact_lineage(
        self,
        connection: Connection,
        fact_id: str,
        source_object_id: str,
        mapping_version_id: str,
    ) -> None:
        self._insert_lineage(connection, source_object_id, fact_id, "evidence_for")
        self._insert_lineage(connection, mapping_version_id, fact_id, "mapped_by")

    def _insert_job_and_quality(self, connection: Connection) -> None:
        report_dates = tuple(
            date.fromisoformat(chain.report_period_end) for chain in self._pack.revision_chains
        )
        job_id = "job:p3-pit-fixture-pack:v1"
        plan = {
            "pack_version": self._pack.pack_version,
            "companies": sorted(self._pack.company_codes),
            "domain": "financial_statement",
            "mode": "private_local_research",
        }
        qualification = {
            "official_evidence": "pit_verified",
            "provider_conflicts": "blocked",
            "redistribution_allowed": False,
        }
        self._immutable_insert(
            connection,
            "ingestion_jobs",
            "job_id",
            (
                "job_id",
                "plan_id",
                "provider_id",
                "status",
                "plan",
                "qualification",
                "output_trust_state",
                "adjustment_mode",
                "start_date",
                "end_date",
                "created_at",
                "updated_at",
                "dataset_version_id",
                "failure_reasons",
            ),
            (
                job_id,
                "plan:p3-pit-fixture-pack:v1",
                "provider:cninfo",
                "succeeded",
                _json_parameter(plan),
                _json_parameter(qualification),
                "pit_verified",
                "unadjusted",
                min(report_dates),
                max(report_dates),
                self._pack.assembled_at,
                self._pack.assembled_at,
                self.dataset_version_id,
                _json_parameter([]),
            ),
        )
        self._immutable_insert(
            connection,
            "dataset_quality_reports",
            "quality_report_id",
            (
                "quality_report_id",
                "dataset_version_id",
                "job_id",
                "status",
                "checks_passed",
                "checks_failed",
                "issue_counts",
                "warnings",
                "created_at",
            ),
            (
                "quality:p3-pit-fixture-pack:v1",
                self.dataset_version_id,
                job_id,
                "warned",
                9,
                len(self._pack.provider_conflicts),
                _json_parameter(
                    {
                        "blocking_provider_observations": len(
                            self._pack.provider_conflicts
                        )
                    }
                ),
                _json_parameter(
                    [
                        "provider conflicts remain blocking and do not reduce official PIT trust",
                        "fixture coverage is not full-universe financial coverage",
                    ]
                ),
                self._pack.assembled_at,
            ),
        )
        self._insert_lineage(
            connection,
            self._pack.pack_version,
            self.dataset_version_id,
            "materialized_as",
        )

    @staticmethod
    def _period_type(report_period_end: date) -> str:
        return {3: "q1", 6: "half_year", 9: "q3", 12: "annual"}.get(
            report_period_end.month,
            "annual",
        )

    @staticmethod
    def _official_raw_id(external_document_id: str) -> str:
        return f"raw:cninfo:{external_document_id}"

    @staticmethod
    def _provider_raw_id(conflict_id: str) -> str:
        digest = hashlib.sha256(conflict_id.encode()).hexdigest()[:20]
        return f"raw:provider-observation:{digest}"

    @staticmethod
    def _disclosure_id(external_document_id: str) -> str:
        return f"disclosure:cninfo:{external_document_id}"

    @staticmethod
    def _provider_id(conflict: dict[str, object]) -> str:
        return f"provider:{_text(conflict.get('provider_id'), 'provider_id')}"

    @staticmethod
    def _mapping_version_id(provider_id: str) -> str:
        return f"metric-mapping:{provider_id.removeprefix('provider:')}:p3-v1"

    @staticmethod
    def _insert_lineage(
        connection: Connection,
        upstream_id: str,
        downstream_id: str,
        relation: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO lineage_edges (upstream_id, downstream_id, relation)
            VALUES (%s, %s, %s)
            ON CONFLICT (upstream_id, downstream_id, relation)
            DO UPDATE SET relation = EXCLUDED.relation
            RETURNING upstream_id
            """,
            (upstream_id, downstream_id, relation),
        )

    @staticmethod
    def _immutable_insert(
        connection: Connection,
        table: str,
        primary_key: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
    ) -> None:
        if columns[0] != primary_key or len(columns) != len(values):
            raise AssertionError("immutable insert declaration is invalid")
        column_sql = ", ".join(columns)
        placeholders = ", ".join("%s" for _ in columns)
        comparisons = ", ".join(f"{table}.{column}" for column in columns[1:])
        excluded = ", ".join(f"EXCLUDED.{column}" for column in columns[1:])
        query = f"""
            INSERT INTO {table} ({column_sql})
            VALUES ({placeholders})
            ON CONFLICT ({primary_key}) DO UPDATE
            SET {primary_key} = {table}.{primary_key}
            WHERE ({comparisons}) IS NOT DISTINCT FROM ({excluded})
            RETURNING {primary_key}
        """
        if connection.execute(query, values).fetchone() is None:
            raise VersionConflictError(f"immutable identifier conflict in {table}: {values[0]}")


__all__ = ["PITFixtureImportSummary", "PostgresPITFixtureImporter"]
