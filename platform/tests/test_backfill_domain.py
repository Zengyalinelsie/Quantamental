import unittest
from datetime import UTC, date, datetime

from a_share_platform.domain.backfill import (
    A_SHARE_SECURITY_MASTER_SCOPE,
    CSI_300_SCOPE,
    CSI_500_SCOPE,
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    BackfillDataDomain,
    BackfillJob,
    BackfillJobStatus,
    BackfillPlan,
    BackfillQualification,
)
from a_share_platform.domain.market_data import PriceAdjustment
from a_share_platform.domain.pit import DataTrustState

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def plan() -> BackfillPlan:
    return BackfillPlan(
        plan_id="backfill:csi-2018-2020:v1",
        provider_id="licensed_provider",
        scopes=(A_SHARE_SECURITY_MASTER_SCOPE, CSI_300_SCOPE, CSI_500_SCOPE),
        domains=tuple(BackfillDataDomain),
        start_date=date(2018, 1, 1),
        end_date=date(2020, 12, 31),
        created_at=NOW,
        output_trust_state=DataTrustState.NORMALIZED_CURRENT,
        price_adjustment=PriceAdjustment.UNADJUSTED,
    )


class BackfillDomainTest(unittest.TestCase):
    def test_canonical_scopes_are_unambiguous(self) -> None:
        self.assertEqual(CSI_300_SCOPE.scope_id, "index:000300")
        self.assertEqual(CSI_300_SCOPE.benchmark_code, "000300")
        self.assertEqual(CSI_500_SCOPE.scope_id, "index:000905")
        self.assertEqual(CSI_500_SCOPE.benchmark_code, "000905")
        self.assertIsNone(A_SHARE_SECURITY_MASTER_SCOPE.benchmark_code)

    def test_plan_requires_raw_unadjusted_prices_and_aware_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "unadjusted"):
            BackfillPlan(
                plan_id="bad",
                provider_id="provider",
                scopes=(CSI_300_SCOPE,),
                domains=(BackfillDataDomain.RAW_DAILY_BAR,),
                start_date=date(2018, 1, 1),
                end_date=date(2018, 1, 2),
                created_at=NOW,
                output_trust_state=DataTrustState.NORMALIZED_CURRENT,
                price_adjustment="forward_adjusted",  # type: ignore[arg-type]
            )

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            BackfillPlan(
                plan_id="bad-time",
                provider_id="provider",
                scopes=(CSI_300_SCOPE,),
                domains=(BackfillDataDomain.UNIVERSE,),
                start_date=date(2018, 1, 1),
                end_date=date(2018, 1, 2),
                created_at=NOW.replace(tzinfo=None),
                output_trust_state=DataTrustState.NORMALIZED_CURRENT,
                price_adjustment=PriceAdjustment.UNADJUSTED,
            )

    def test_job_and_checkpoint_transitions_fail_closed(self) -> None:
        qualification = BackfillQualification(
            provider_id="licensed_provider",
            permitted=True,
            evaluated_at=NOW,
            blockers=(),
            warnings=(),
        )
        job = BackfillJob.planned(plan(), qualification)
        running = job.transition(BackfillJobStatus.RUNNING, at=NOW)
        succeeded = running.transition(
            BackfillJobStatus.SUCCEEDED,
            at=NOW,
            dataset_version_id="dataset:backfill:csi:v1",
        )
        self.assertEqual(succeeded.status, BackfillJobStatus.SUCCEEDED)
        with self.assertRaisesRegex(ValueError, "terminal"):
            succeeded.transition(BackfillJobStatus.RUNNING, at=NOW)

        checkpoint = BackfillCheckpoint.pending(
            job_id=job.job_id,
            checkpoint_key="raw_daily_bar:index-000300:XSHG:2018",
            scope_id=CSI_300_SCOPE.scope_id,
            domain=BackfillDataDomain.RAW_DAILY_BAR,
            market="XSHG",
            start_date=date(2018, 1, 1),
            end_date=date(2018, 12, 31),
            at=NOW,
        )
        checkpoint = checkpoint.transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        checkpoint = checkpoint.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=NOW,
            processed_rows=242,
            rejected_rows=0,
            content_hash="sha256:" + "a" * 64,
        )
        self.assertEqual(checkpoint.processed_rows, 242)
        with self.assertRaisesRegex(ValueError, "terminal"):
            checkpoint.transition(BackfillCheckpointStatus.RUNNING, at=NOW)

    def test_blocked_job_preserves_every_license_reason(self) -> None:
        qualification = BackfillQualification(
            provider_id="free_provider",
            permitted=False,
            evaluated_at=NOW,
            blockers=("raw persistence is not licensed", "XBSE is unsupported"),
            warnings=("current data cannot become PIT",),
        )
        job = BackfillJob.blocked(plan(), qualification)
        self.assertEqual(job.status, BackfillJobStatus.BLOCKED)
        self.assertEqual(job.failure_reason, qualification.blockers)


if __name__ == "__main__":
    unittest.main()
