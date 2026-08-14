"""Deterministic frozen Artifact export for immutable InvestmentView records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerService,
)
from a_share_platform.application.governance_ledger import GovernanceLedger
from a_share_platform.domain.governance import (
    Artifact,
    LineageEdge,
    RunStatus,
    VersionConflictError,
)
from a_share_platform.domain.investment_view import InvestmentView
from a_share_platform.ports.disclosure import RawObjectStore

_ARTIFACT_SCHEMA_VERSION = "investment-view:v1"
_MEDIA_TYPE = "application/json"


@dataclass(frozen=True)
class InvestmentViewArtifactExportResult:
    artifact: Artifact
    writes_performed: bool


def _canonical_payload(view: InvestmentView) -> bytes:
    document = view.hash_payload()
    document["content_hash"] = view.content_hash
    envelope = {
        "artifact_schema_version": _ARTIFACT_SCHEMA_VERSION,
        "investment_view_content_hash": view.content_hash,
        "investment_view": document,
    }
    return json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _lineage(view: InvestmentView, artifact_id: str) -> tuple[LineageEdge, ...]:
    edges = [
        LineageEdge(view.view_id, artifact_id, "frozen_as"),
        *(LineageEdge(value, artifact_id, "contributed_to") for value in view.dataset_version_ids),
        *(LineageEdge(value, artifact_id, "contributed_to") for value in view.feature_version_ids),
        LineageEdge(view.model_version_id, artifact_id, "generated_with"),
        LineageEdge(view.run_id, artifact_id, "produced"),
        *(LineageEdge(value, artifact_id, "evidences") for value in view.all_evidence_ids),
    ]
    return tuple(dict.fromkeys(edges))


class InvestmentViewArtifactExporter:
    """Export a persisted View only after its compilation run succeeded."""

    def __init__(
        self,
        expected_returns: ExpectedReturnLedgerService,
        governance: GovernanceLedger,
        object_store: RawObjectStore,
    ) -> None:
        self._expected_returns = expected_returns
        self._governance = governance
        self._object_store = object_store

    def export(
        self,
        view_id: str,
        *,
        created_at: datetime,
    ) -> InvestmentViewArtifactExportResult:
        view = self._expected_returns.get_view(view_id)
        if view is None:
            raise LookupError(f"InvestmentView does not exist: {view_id}")
        run = self._governance.get_run(view.run_id)
        if run is None or run.status is not RunStatus.SUCCEEDED:
            raise PermissionError(
                "InvestmentView Artifact export requires a succeeded run: "
                f"{view.run_id}"
            )
        if (
            not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or created_at.utcoffset() is None
        ):
            raise ValueError("Artifact created_at must be timezone-aware")
        if run.finished_at is None or created_at < run.finished_at:
            raise ValueError("Artifact created_at cannot precede the succeeded run")

        payload = _canonical_payload(view)
        digest = hashlib.sha256(payload).hexdigest()
        artifact_id = f"artifact:investment-view:{digest}"
        content_hash = f"sha256:{digest}"
        expected_lineage = _lineage(view, artifact_id)
        existing = self._governance.get_artifact(artifact_id)
        if existing is not None:
            if (
                existing.run_id != view.run_id
                or existing.content_hash != content_hash
                or existing.media_type != _MEDIA_TYPE
            ):
                raise RuntimeError(
                    f"frozen InvestmentView Artifact conflict: {artifact_id}"
                )
            prior_lineage = set(self._governance.list_lineage_for(artifact_id))
            self._governance.register_artifact_with_lineage(existing, expected_lineage)
            return InvestmentViewArtifactExportResult(
                artifact=existing,
                writes_performed=any(edge not in prior_lineage for edge in expected_lineage),
            )

        hash_owner = self._governance.get_artifact_by_hash(content_hash)
        if hash_owner is not None:
            raise RuntimeError(
                "frozen InvestmentView Artifact content hash conflict: "
                f"{content_hash} is already bound to {hash_owner.artifact_id}"
            )

        storage_uri = self._object_store.put(payload)
        candidate = Artifact(
            artifact_id=artifact_id,
            run_id=view.run_id,
            content_hash=content_hash,
            media_type=_MEDIA_TYPE,
            storage_uri=storage_uri,
            created_at=created_at,
        )
        try:
            artifact = self._governance.register_artifact_with_lineage(
                candidate,
                expected_lineage,
            )
        except VersionConflictError as error:
            winner = self._governance.get_artifact(artifact_id)
            if winner is None or (
                winner.run_id != candidate.run_id
                or winner.content_hash != candidate.content_hash
                or winner.media_type != candidate.media_type
                or winner.storage_uri != candidate.storage_uri
            ):
                raise RuntimeError(
                    f"concurrent frozen InvestmentView Artifact conflict: {artifact_id}"
                ) from error
            prior_lineage = set(self._governance.list_lineage_for(artifact_id))
            artifact = self._governance.register_artifact_with_lineage(
                winner,
                expected_lineage,
            )
            return InvestmentViewArtifactExportResult(
                artifact=artifact,
                writes_performed=any(
                    edge not in prior_lineage for edge in expected_lineage
                ),
            )
        return InvestmentViewArtifactExportResult(
            artifact=artifact,
            writes_performed=True,
        )


__all__ = [
    "InvestmentViewArtifactExportResult",
    "InvestmentViewArtifactExporter",
]
