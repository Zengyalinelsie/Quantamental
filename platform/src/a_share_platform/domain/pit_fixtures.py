"""Validated real-evidence fixture packs for P3 leakage and revision tests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_SCENARIOS = frozenset(
    {
        "normal_after_hours_annual_report",
        "pre_market_availability",
        "weekend_disclosure",
        "financial_correction",
        "multiple_versions_same_period",
        "unit_or_currency_conflict",
        "missing_field",
        "one_off_item",
        "provider_official_mismatch",
    }
)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _time(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, name))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _strings(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    result = frozenset(_text(item, f"{name} item") for item in value)
    if len(result) != len(value):
        raise ValueError(f"{name} must not contain duplicates")
    return result


@dataclass(frozen=True)
class FixtureEvidence:
    evidence_id: str
    company_code: str
    external_document_id: str
    title: str
    source_url: str
    content_sha256: str
    local_filename: str
    retrieved_at: datetime
    official_reported_at: datetime
    publication_time_precision: str
    available_at: datetime
    first_tradable_at: datetime
    document_key: str
    document_type: str
    report_period_end: date | None
    version_sequence: int
    status: str
    supersedes_external_document_id: str | None
    status_reason: str | None
    retention_policy: str
    scenarios: frozenset[str]

    @classmethod
    def from_document(cls, raw: object) -> FixtureEvidence:
        if not isinstance(raw, dict):
            raise TypeError("evidence item must be an object")
        digest = _text(raw.get("content_sha256"), "content_sha256")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("content_sha256 must be 64 lowercase hex characters")
        precision = _text(raw.get("publication_time_precision"), "publication_time_precision")
        if precision not in {"exact", "date_only"}:
            raise ValueError("publication_time_precision must be exact or date_only")
        published = _time(raw.get("official_reported_at"), "official_reported_at")
        if precision == "date_only" and (
            published.hour,
            published.minute,
            published.second,
            published.microsecond,
        ) != (0, 0, 0, 0):
            raise ValueError("date_only official_reported_at must use local midnight")
        available = _time(raw.get("available_at"), "available_at")
        first_tradable = _time(raw.get("first_tradable_at"), "first_tradable_at")
        if available < published:
            raise ValueError("fixture available_at cannot precede official_reported_at")
        if first_tradable < available:
            raise ValueError("fixture first_tradable_at cannot precede available_at")
        retrieved_at = _time(raw.get("retrieved_at"), "retrieved_at")
        if retrieved_at < published:
            raise ValueError("fixture retrieved_at cannot precede official_reported_at")
        report_period_raw = raw.get("report_period_end")
        try:
            report_period_end = (
                None
                if report_period_raw is None
                else date.fromisoformat(_text(report_period_raw, "report_period_end"))
            )
        except ValueError as error:
            raise ValueError("report_period_end must be an ISO date") from error
        version_sequence = raw.get("version_sequence")
        if type(version_sequence) is not int or version_sequence < 0:
            raise ValueError("version_sequence must be a non-negative integer")
        status = _text(raw.get("status"), "status")
        supersedes_raw = raw.get("supersedes_external_document_id")
        supersedes = (
            None
            if supersedes_raw is None
            else _text(supersedes_raw, "supersedes_external_document_id")
        )
        reason_raw = raw.get("status_reason")
        reason = None if reason_raw is None else _text(reason_raw, "status_reason")
        if version_sequence == 0:
            if status != "published" or supersedes is not None or reason is not None:
                raise ValueError("fixture version zero must be an original publication")
        elif status != "corrected" or supersedes is None or reason is None:
            raise ValueError("later fixture versions must be explicit corrections")
        return cls(
            evidence_id=_text(raw.get("evidence_id"), "evidence_id"),
            company_code=_text(raw.get("company_code"), "company_code"),
            external_document_id=_text(
                raw.get("external_document_id"), "external_document_id"
            ),
            title=_text(raw.get("title"), "title"),
            source_url=_text(raw.get("source_url"), "source_url"),
            content_sha256=digest,
            local_filename=_text(raw.get("local_filename"), "local_filename"),
            retrieved_at=retrieved_at,
            official_reported_at=published,
            publication_time_precision=precision,
            available_at=available,
            first_tradable_at=first_tradable,
            document_key=_text(raw.get("document_key"), "document_key"),
            document_type=_text(raw.get("document_type"), "document_type"),
            report_period_end=report_period_end,
            version_sequence=version_sequence,
            status=status,
            supersedes_external_document_id=supersedes,
            status_reason=reason,
            retention_policy=_text(raw.get("retention_policy"), "retention_policy"),
            scenarios=_strings(raw.get("scenarios", []), "scenarios"),
        )


@dataclass(frozen=True)
class FixtureRevisionVersion:
    external_document_id: str
    available_at: datetime
    expected_facts: tuple[tuple[str, str], ...]
    supersedes_external_document_id: str | None

    @classmethod
    def from_document(cls, raw: object) -> FixtureRevisionVersion:
        if not isinstance(raw, dict):
            raise TypeError("revision version must be an object")
        facts = raw.get("expected_facts")
        if not isinstance(facts, dict) or not facts:
            raise ValueError("revision version expected_facts must be a non-empty object")
        normalized = tuple(
            sorted(
                (_text(key, "metric code"), _text(value, f"expected fact {key}"))
                for key, value in facts.items()
            )
        )
        supersedes = raw.get("supersedes_external_document_id")
        return cls(
            external_document_id=_text(
                raw.get("external_document_id"), "external_document_id"
            ),
            available_at=_time(raw.get("available_at"), "available_at"),
            expected_facts=normalized,
            supersedes_external_document_id=(
                None
                if supersedes is None
                else _text(supersedes, "supersedes_external_document_id")
            ),
        )


@dataclass(frozen=True)
class FixtureRevisionChain:
    chain_id: str
    company_code: str
    report_period_end: str
    original: FixtureRevisionVersion
    corrected: FixtureRevisionVersion
    scenarios: frozenset[str]

    @classmethod
    def from_document(cls, raw: object) -> FixtureRevisionChain:
        if not isinstance(raw, dict):
            raise TypeError("revision chain must be an object")
        return cls(
            chain_id=_text(raw.get("chain_id"), "chain_id"),
            company_code=_text(raw.get("company_code"), "company_code"),
            report_period_end=_text(raw.get("report_period_end"), "report_period_end"),
            original=FixtureRevisionVersion.from_document(raw.get("original")),
            corrected=FixtureRevisionVersion.from_document(raw.get("corrected")),
            scenarios=_strings(raw.get("scenarios", []), "scenarios"),
        )


@dataclass(frozen=True)
class PITFixturePack:
    pack_version: str
    assembled_at: datetime
    manifest_content_hash: str
    company_codes: frozenset[str]
    company_legal_names: tuple[tuple[str, str], ...]
    evidence: tuple[FixtureEvidence, ...]
    revision_chains: tuple[FixtureRevisionChain, ...]
    declared_scenarios: frozenset[str]
    provider_conflicts: tuple[dict[str, object], ...]

    @classmethod
    def load(cls, path: Path) -> PITFixturePack:
        payload = Path(path).read_bytes()
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise TypeError("fixture pack must be a JSON object")
        evidence = tuple(FixtureEvidence.from_document(item) for item in raw.get("evidence", []))
        chains = tuple(
            FixtureRevisionChain.from_document(item)
            for item in raw.get("revision_chains", [])
        )
        conflicts = raw.get("provider_conflicts", [])
        if not isinstance(conflicts, list) or any(not isinstance(item, dict) for item in conflicts):
            raise TypeError("provider_conflicts must be an array of objects")
        names = raw.get("company_legal_names")
        if not isinstance(names, dict):
            raise TypeError("company_legal_names must be an object")
        return cls(
            pack_version=_text(raw.get("pack_version"), "pack_version"),
            assembled_at=_time(raw.get("assembled_at"), "assembled_at"),
            manifest_content_hash=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            company_codes=_strings(raw.get("company_codes", []), "company_codes"),
            company_legal_names=tuple(
                sorted(
                    (
                        _text(code, "company legal-name code"),
                        _text(name, f"company legal name {code}"),
                    )
                    for code, name in names.items()
                )
            ),
            evidence=evidence,
            revision_chains=chains,
            declared_scenarios=_strings(raw.get("scenarios", []), "scenarios"),
            provider_conflicts=cast(tuple[dict[str, object], ...], tuple(conflicts)),
        )

    @property
    def required_scenarios(self) -> set[str]:
        return set(_REQUIRED_SCENARIOS)

    def require_w04_capability_coverage(self) -> None:
        if not 3 <= len(self.company_codes) <= 5:
            raise ValueError("W04 fixture pack requires 3-5 companies")
        if {code for code, _ in self.company_legal_names} != set(self.company_codes):
            raise ValueError("every fixture company requires one official legal name")
        if len(self.revision_chains) < 2:
            raise ValueError("W04 fixture pack requires at least two revision chains")
        if not self.evidence:
            raise ValueError("W04 fixture pack requires raw official evidence")
        evidence_ids = {item.external_document_id for item in self.evidence}
        disclosure_ids = {
            item.external_document_id: item for item in self.evidence
        }
        scenarios = set(self.declared_scenarios)
        for item in self.evidence:
            scenarios.update(item.scenarios)
            if item.company_code not in self.company_codes:
                raise ValueError("fixture evidence references an undeclared company")
            if "static.cninfo.com.cn/" not in item.source_url:
                raise ValueError("official fixture evidence must use the CNInfo source URL")
            if item.retrieved_at > self.assembled_at:
                raise ValueError("evidence retrieval cannot follow pack assembly")
            if item.supersedes_external_document_id is not None:
                previous = disclosure_ids.get(item.supersedes_external_document_id)
                if previous is None or previous.document_key != item.document_key:
                    raise ValueError("fixture correction must supersede the same document chain")
                if previous.version_sequence + 1 != item.version_sequence:
                    raise ValueError("fixture disclosure version chain must be contiguous")
        for chain in self.revision_chains:
            scenarios.update(chain.scenarios)
            if chain.company_code not in self.company_codes:
                raise ValueError("revision chain references an undeclared company")
            if chain.original.external_document_id not in evidence_ids:
                raise ValueError("revision original lacks raw official evidence")
            if chain.corrected.external_document_id not in evidence_ids:
                raise ValueError("revision correction lacks raw official evidence")
            if chain.corrected.available_at <= chain.original.available_at:
                raise ValueError("revision availability must advance monotonically")
            if (
                chain.corrected.supersedes_external_document_id
                != chain.original.external_document_id
            ):
                raise ValueError("corrected revision must explicitly supersede the original")
            if chain.corrected.expected_facts == chain.original.expected_facts:
                raise ValueError("revision fixture must contain a changed expected fact")
        if not self.provider_conflicts:
            raise ValueError("W04 fixture pack requires a real provider conflict")
        missing = _REQUIRED_SCENARIOS - scenarios
        if missing:
            raise ValueError(f"W04 fixture scenarios are missing: {sorted(missing)}")

    def verify_raw_evidence(self, root: Path) -> None:
        for item in self.evidence:
            if item.retention_policy == "metadata_only":
                continue
            path = Path(root) / item.local_filename
            if not path.is_file():
                raise FileNotFoundError(f"raw evidence is missing: {item.local_filename}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item.content_sha256:
                raise ValueError(f"raw evidence hash mismatch: {item.local_filename}")


__all__ = [
    "FixtureEvidence",
    "FixtureRevisionChain",
    "FixtureRevisionVersion",
    "PITFixturePack",
]
