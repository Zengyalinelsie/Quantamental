import unittest
from datetime import UTC, date, datetime, timedelta

from a_share_platform.adapters.memory.backfill import InMemoryBackfillRepository
from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.application.backfill import (
    BackfillPlanner,
    BackfillService,
    build_private_local_backfill_plan,
)
from a_share_platform.application.provider_registry import build_p2_provider_registry
from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    BackfillDataDomain,
    BackfillJob,
    BackfillJobStatus,
    BackfillPlan,
    ProviderRetrievalMetadata,
)
from a_share_platform.domain.market_data import PriceAdjustment
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import (
    DataField,
    LicenseStatus,
    ProviderFieldPolicy,
    ProviderTier,
    ProviderUse,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


class PrivateLocalBackfillTest(unittest.TestCase):
    def test_private_local_research_is_narrow_and_normalized_current_only(self) -> None:
        registry = build_p2_provider_registry()

        raw = registry.require(
            DataField.RAW_DAILY_BAR,
            ProviderUse.PRIVATE_LOCAL_RESEARCH,
            market="XSHG",
        )
        self.assertEqual(raw.provider_id, "baostock_sdk")
        self.assertEqual(raw.trust_ceiling, DataTrustState.NORMALIZED_CURRENT)
        self.assertNotIn(ProviderUse.STRICT_HISTORICAL, raw.permitted_uses)
        self.assertNotIn(ProviderUse.EXTERNAL_REDISTRIBUTION, raw.permitted_uses)
        self.assertNotIn(ProviderUse.PRODUCTION_DECISION, raw.permitted_uses)

    def test_explicit_provider_retention_prohibition_overrides_local_ack(self) -> None:
        with self.assertRaisesRegex(ValueError, "retention"):
            ProviderFieldPolicy(
                provider_id="prohibited_provider",
                field=DataField.RAW_DAILY_BAR,
                tier=ProviderTier.FALLBACK,
                markets=frozenset({"XSHG"}),
                permitted_uses=frozenset({ProviderUse.PRIVATE_LOCAL_RESEARCH}),
                license_status=LicenseStatus.DATA_TERMS_REVIEW_REQUIRED,
                trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
                retention_prohibited=True,
            )

    def test_targeted_plan_has_only_selected_symbols_markets_and_domains(self) -> None:
        plan = build_private_local_backfill_plan(
            plan_id="private:bars:v1",
            provider_id="baostock_sdk",
            symbols=("SH.600519", "SZ.000001"),
            domains=(BackfillDataDomain.RAW_DAILY_BAR,),
            start_date=date(2018, 1, 1),
            end_date=date(2019, 2, 1),
            created_at=NOW,
        )

        self.assertEqual(plan.provider_use, ProviderUse.PRIVATE_LOCAL_RESEARCH)
        self.assertEqual(plan.output_trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(plan.symbols, ("SH.600519", "SZ.000001"))
        self.assertEqual(plan.markets, ("XSHG", "XSHE"))
        self.assertEqual(len(plan.scopes), 1)
        self.assertEqual(plan.scopes[0].symbols, plan.symbols)
        units = BackfillPlanner().work_units(plan)
        self.assertEqual(len(units), 4)
        self.assertEqual({unit.domain for unit in units}, {BackfillDataDomain.RAW_DAILY_BAR})
        self.assertEqual({unit.market for unit in units}, {"XSHG", "XSHE"})

    def test_private_local_plan_cannot_self_promote_to_pit_verified(self) -> None:
        value = build_private_local_backfill_plan(
            plan_id="private:bars:v1",
            provider_id="baostock_sdk",
            symbols=("SH.600519",),
            domains=(BackfillDataDomain.RAW_DAILY_BAR,),
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 5),
            created_at=NOW,
        )
        with self.assertRaisesRegex(ValueError, "normalized_current"):
            BackfillPlan(
                plan_id=value.plan_id,
                provider_id=value.provider_id,
                scopes=value.scopes,
                domains=value.domains,
                start_date=value.start_date,
                end_date=value.end_date,
                created_at=value.created_at,
                output_trust_state=DataTrustState.PIT_VERIFIED,
                price_adjustment=PriceAdjustment.UNADJUSTED,
                provider_use=ProviderUse.PRIVATE_LOCAL_RESEARCH,
                symbols=value.symbols,
                markets=value.markets,
            )

    def test_resume_skips_already_succeeded_checkpoint(self) -> None:
        plan = build_private_local_backfill_plan(
            plan_id="private:resume:v1",
            provider_id="baostock_sdk",
            symbols=("SH.600519",),
            domains=(BackfillDataDomain.RAW_DAILY_BAR,),
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 5),
            created_at=NOW,
        )
        repository = InMemoryBackfillRepository()
        governance = InMemoryGovernanceRepository()
        service = BackfillService(
            registry=build_p2_provider_registry(),
            repository=repository,
            governance_repository=governance,
            clock=lambda: NOW,
        )
        qualification = service.preview(plan).qualification
        job = repository.save_job(BackfillJob.planned(plan, qualification))
        running = repository.append_job_state(
            job.transition(BackfillJobStatus.RUNNING, at=NOW)
        )
        unit = BackfillPlanner().work_units(plan)[0]
        checkpoint = BackfillCheckpoint.pending(
            job_id=running.job_id,
            checkpoint_key=unit.checkpoint_key,
            scope_id=unit.scope_id,
            domain=unit.domain,
            market=unit.market,
            start_date=unit.start_date,
            end_date=unit.end_date,
            at=NOW,
        ).transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        checkpoint = checkpoint.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=NOW,
            processed_rows=1,
            content_hash="sha256:" + "a" * 64,
            retrieval_metadata=ProviderRetrievalMetadata(
                provider_id="baostock_sdk",
                retrieved_at=NOW,
                cutoff_date=date(2018, 1, 2),
                adjustment_mode="unadjusted",
                units=(("volume", "shares"),),
                warnings=("normalized_current only",),
            ),
        )
        repository.save_checkpoint(checkpoint)
        repository.append_job_state(
            running.transition(
                BackfillJobStatus.FAILED,
                at=NOW,
                failure_reason=("later checkpoint failed",),
            )
        )

        class NeverCalledSource:
            provider_id = "baostock_sdk"

            def fetch(self, *_args: object, **_kwargs: object) -> object:
                raise AssertionError("succeeded checkpoint must not be fetched again")

        class NeverCalledSink:
            def persist(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("succeeded checkpoint must not be persisted again")

        resumed = service.start(
            plan,
            source=NeverCalledSource(),  # type: ignore[arg-type]
            sink=NeverCalledSink(),
        )
        self.assertEqual(resumed.status, BackfillJobStatus.SUCCEEDED)
        self.assertIsNotNone(resumed.dataset_version_id)

    def test_resume_accepts_same_plan_identity_with_a_new_cli_created_at(self) -> None:
        original = build_private_local_backfill_plan(
            plan_id="private:stable-resume:v1",
            provider_id="baostock_sdk",
            symbols=("SH.600519",),
            domains=(BackfillDataDomain.RAW_DAILY_BAR,),
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 5),
            created_at=NOW,
        )
        retried = build_private_local_backfill_plan(
            plan_id=original.plan_id,
            provider_id=original.provider_id,
            symbols=original.symbols,
            domains=original.domains,
            start_date=original.start_date,
            end_date=original.end_date,
            created_at=NOW + timedelta(hours=1),
        )
        repository = InMemoryBackfillRepository()
        governance = InMemoryGovernanceRepository()
        service = BackfillService(
            registry=build_p2_provider_registry(),
            repository=repository,
            governance_repository=governance,
            clock=lambda: NOW,
        )

        first = service.start(original, source=None, sink=None)
        self.assertEqual(first.status, BackfillJobStatus.FAILED)

        resumed = service.start(retried, source=None, sink=None)

        self.assertEqual(resumed.status, BackfillJobStatus.FAILED)
        self.assertEqual(resumed.plan.created_at, original.created_at)

    def test_failure_checkpoint_is_rolled_back_then_committed_durably(self) -> None:
        class DurableRepository(InMemoryBackfillRepository):
            def __init__(self) -> None:
                super().__init__()
                self.transaction_events: list[str] = []

            def commit(self) -> None:
                self.transaction_events.append("commit")

            def rollback(self) -> None:
                self.transaction_events.append("rollback")

        class FailingSource:
            provider_id = "baostock_sdk"

            def fetch(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError("provider interrupted")

        class NeverCalledSink:
            def persist(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("a failed fetch cannot reach the sink")

        plan = build_private_local_backfill_plan(
            plan_id="private:durable-failure:v1",
            provider_id="baostock_sdk",
            symbols=("SH.600519",),
            domains=(BackfillDataDomain.RAW_DAILY_BAR,),
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 5),
            created_at=NOW,
        )
        repository = DurableRepository()
        service = BackfillService(
            registry=build_p2_provider_registry(),
            repository=repository,
            governance_repository=InMemoryGovernanceRepository(),
            clock=lambda: NOW,
        )

        with self.assertRaisesRegex(RuntimeError, "provider interrupted"):
            service.start(
                plan,
                source=FailingSource(),  # type: ignore[arg-type]
                sink=NeverCalledSink(),
            )

        checkpoints = repository.list_checkpoints(f"job:{plan.plan_id}")
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0].status, BackfillCheckpointStatus.FAILED)
        self.assertIn("rollback", repository.transaction_events)
        self.assertEqual(repository.transaction_events[-1], "commit")


if __name__ == "__main__":
    unittest.main()
