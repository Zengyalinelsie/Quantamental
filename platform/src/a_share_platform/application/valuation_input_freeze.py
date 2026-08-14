"""Application gate for persisting qualified frozen valuation inputs."""

from __future__ import annotations

from a_share_platform.domain.valuation_input_qualification import (
    ValuationInputQualification,
)
from a_share_platform.ports.valuation_inputs import (
    ValuationImprovementInputBundle,
    ValuationImprovementInputRepository,
)


class ValuationInputFreezeBlocked(PermissionError):
    """The bundle cannot be frozen from the supplied qualification evidence."""


class ValuationInputFreezeService:
    def __init__(self, repository: ValuationImprovementInputRepository) -> None:
        self._repository = repository

    def freeze(
        self,
        value: ValuationImprovementInputBundle,
        qualification: ValuationInputQualification,
    ) -> ValuationImprovementInputBundle:
        if not isinstance(value, ValuationImprovementInputBundle):
            raise TypeError("value must be a ValuationImprovementInputBundle")
        if not isinstance(qualification, ValuationInputQualification):
            raise TypeError("qualification must be a ValuationInputQualification")
        axes = (
            ("security_id", value.security_id, qualification.security_id),
            ("decision_time", value.decision_time, qualification.decision_time),
            ("data_mode", value.data_mode, qualification.data_mode),
            ("trust_state", value.trust_state, qualification.requested_trust_state),
        )
        for label, bundle_value, qualified_value in axes:
            if bundle_value != qualified_value:
                raise ValuationInputFreezeBlocked(
                    f"bundle {label} does not match qualification evidence"
                )
        if not qualification.is_qualified:
            raise ValuationInputFreezeBlocked("; ".join(qualification.blockers))
        missing_datasets = set(qualification.dataset_version_ids) - set(
            value.dataset_version_ids
        )
        if missing_datasets:
            raise ValuationInputFreezeBlocked(
                "bundle dataset lineage does not include qualified inputs: "
                + ", ".join(sorted(missing_datasets))
            )
        latest_qualified = max(
            evidence.latest_source_available_at
            for evidence in qualification.domain_evidence
            if evidence.latest_source_available_at is not None
        )
        if latest_qualified > value.latest_source_available_at:
            raise ValuationInputFreezeBlocked(
                "bundle latest_source_available_at predates qualified input evidence"
            )
        return self._repository.append(value)


__all__ = ["ValuationInputFreezeBlocked", "ValuationInputFreezeService"]
