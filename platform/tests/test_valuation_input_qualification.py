import unittest
from dataclasses import replace
from datetime import timedelta

from a_share_platform.adapters.memory.valuation_inputs import (
    MemoryValuationImprovementInputRepository,
)
from a_share_platform.application.valuation_input_freeze import (
    ValuationInputFreezeBlocked,
    ValuationInputFreezeService,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_input_qualification import (
    ValuationInputDomain,
    ValuationInputDomainEvidence,
    ValuationInputQualification,
)
from tests.test_valuation_improvement_service import (
    AVAILABLE_AT,
    DECISION_TIME,
    bundle,
    request,
)


def evidence(
    domain: ValuationInputDomain,
    dataset_version_id: str,
    *,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    blockers: tuple[str, ...] = (),
) -> ValuationInputDomainEvidence:
    return ValuationInputDomainEvidence(
        domain=domain,
        trust_state=trust_state,
        dataset_version_ids=(dataset_version_id,),
        source_ids=(f"source:{domain.value}:v1",),
        observation_ids=(f"observation:{domain.value}:v1",),
        content_hashes=("sha256:" + "a" * 64,),
        observation_count=1,
        latest_source_available_at=AVAILABLE_AT,
        blockers=blockers,
    )


def qualification(
    *,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    price_blockers: tuple[str, ...] = (),
) -> ValuationInputQualification:
    return ValuationInputQualification(
        security_id="security:000001.XSHE",
        decision_time=DECISION_TIME,
        data_mode=data_mode,
        requested_trust_state=trust_state,
        domain_evidence=(
            evidence(
                ValuationInputDomain.FINANCIAL,
                "dataset:improvement:2025q1:v1",
                trust_state=trust_state,
            ),
            evidence(
                ValuationInputDomain.PRICE,
                "dataset:valuation:2025q1:v1",
                trust_state=trust_state,
                blockers=price_blockers,
            ),
            evidence(
                ValuationInputDomain.COMPARABLE,
                "dataset:scenario:2025q1:v1",
                trust_state=trust_state,
            ),
        ),
    )


class ValuationInputQualificationTest(unittest.TestCase):
    def test_all_three_domains_are_required_and_qualified_is_derived(self) -> None:
        value = qualification()
        self.assertTrue(value.is_qualified)
        self.assertEqual(value.blockers, ())
        self.assertEqual(
            {item.domain for item in value.domain_evidence},
            set(ValuationInputDomain),
        )

        with self.assertRaisesRegex(ValueError, "financial, price, and comparable"):
            ValuationInputQualification(
                security_id=value.security_id,
                decision_time=value.decision_time,
                data_mode=value.data_mode,
                requested_trust_state=value.requested_trust_state,
                domain_evidence=value.domain_evidence[:-1],
            )

    def test_blockers_missing_lineage_and_future_availability_are_never_qualified(self) -> None:
        self.assertFalse(qualification(price_blockers=("price is stale",)).is_qualified)
        with self.assertRaisesRegex(ValueError, "lineage"):
            ValuationInputDomainEvidence(
                domain=ValuationInputDomain.PRICE,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
                dataset_version_ids=(),
                source_ids=(),
                observation_ids=(),
                content_hashes=(),
                observation_count=1,
                latest_source_available_at=AVAILABLE_AT,
                blockers=(),
            )
        values = qualification().domain_evidence
        future_comparable = replace(
            next(
                item for item in values if item.domain is ValuationInputDomain.COMPARABLE
            ),
            latest_source_available_at=DECISION_TIME + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ValueError, "decision_time"):
            ValuationInputQualification(
                security_id="security:000001.XSHE",
                decision_time=DECISION_TIME,
                data_mode=DataMode.CURRENT_RESEARCH,
                requested_trust_state=DataTrustState.NORMALIZED_CURRENT,
                domain_evidence=(
                    *(item for item in values if item.domain is not ValuationInputDomain.COMPARABLE),
                    future_comparable,
                ),
            )

    def test_strict_report_can_explain_current_evidence_but_cannot_qualify_it(self) -> None:
        strict = ValuationInputQualification(
            security_id="security:000001.XSHE",
            decision_time=DECISION_TIME,
            data_mode=DataMode.STRICT_HISTORICAL,
            requested_trust_state=DataTrustState.PIT_VERIFIED,
            domain_evidence=tuple(
                evidence(domain, dataset)
                for domain, dataset in (
                    (ValuationInputDomain.FINANCIAL, "dataset:improvement:2025q1:v1"),
                    (ValuationInputDomain.PRICE, "dataset:valuation:2025q1:v1"),
                    (ValuationInputDomain.COMPARABLE, "dataset:scenario:2025q1:v1"),
                )
            ),
        )
        self.assertFalse(strict.is_qualified)
        self.assertTrue(any("pit_verified" in blocker for blocker in strict.blockers))

    def test_freeze_persists_only_exact_qualified_lineage_and_is_idempotent(self) -> None:
        repository = MemoryValuationImprovementInputRepository()
        service = ValuationInputFreezeService(repository)
        frozen = bundle()

        self.assertEqual(service.freeze(frozen, qualification()), frozen)
        self.assertEqual(service.freeze(frozen, qualification()), frozen)
        self.assertEqual(repository.load(request()), frozen)

        with self.assertRaisesRegex(ValuationInputFreezeBlocked, "price is stale"):
            service.freeze(frozen, qualification(price_blockers=("price is stale",)))

    def test_freeze_rejects_axis_or_dataset_mismatch(self) -> None:
        service = ValuationInputFreezeService(MemoryValuationImprovementInputRepository())
        frozen = bundle()
        with self.assertRaisesRegex(ValuationInputFreezeBlocked, "security_id"):
            service.freeze(
                frozen,
                ValuationInputQualification(
                    security_id="security:other",
                    decision_time=DECISION_TIME,
                    data_mode=DataMode.CURRENT_RESEARCH,
                    requested_trust_state=DataTrustState.NORMALIZED_CURRENT,
                    domain_evidence=qualification().domain_evidence,
                ),
            )
        values = qualification().domain_evidence
        wrong_dataset = ValuationInputQualification(
            security_id=qualification().security_id,
            decision_time=qualification().decision_time,
            data_mode=qualification().data_mode,
            requested_trust_state=qualification().requested_trust_state,
            domain_evidence=(
                *(item for item in values if item.domain is not ValuationInputDomain.COMPARABLE),
                evidence(
                    ValuationInputDomain.COMPARABLE,
                    "dataset:not-in-bundle:v1",
                ),
            ),
        )
        with self.assertRaisesRegex(ValuationInputFreezeBlocked, "dataset lineage"):
            service.freeze(frozen, wrong_dataset)


if __name__ == "__main__":
    unittest.main()
