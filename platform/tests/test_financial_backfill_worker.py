import argparse
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from a_share_platform.application.akshare_financial_mapping_seed import (
    AKSHARE_CURRENT_MAPPING_VERSION_ID,
    akshare_current_mapping_package_v1,
)
from a_share_platform.application.financial_backfill_execution import (
    FinancialBackfillExecutionResult,
)
from a_share_platform.domain.backfill import BackfillJobStatus
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillCohort,
    FinancialBackfillPlan,
    FinancialStatementSelection,
)
from a_share_platform.domain.financial_sources import (
    FinancialSourceAccessMode,
    FinancialSourceProfile,
    FinancialSourceQualification,
    FinancialSourceRole,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.workers import financial_backfill as worker

NOW = datetime(2026, 8, 11, 6, tzinfo=UTC)


def plan(*, provider_id: str = "akshare") -> FinancialBackfillPlan:
    return FinancialBackfillPlan(
        plan_id="financial-backfill:csi300:akshare-pilot:v1",
        provider_id=provider_id,
        provider_profile_version=(
            "financial-source:akshare:v1"
            if provider_id == "akshare"
            else "financial-source:factor-service-ths:v1"
        ),
        cohort=FinancialBackfillCohort.CSI_300,
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id=(
            AKSHARE_CURRENT_MAPPING_VERSION_ID
            if provider_id == "akshare"
            else "mapping:factor-service-ths:v1"
        ),
        statements=(
            FinancialStatementSelection(
                StatementType.BALANCE_SHEET,
                "balance_sheet",
            ),
        ),
        report_period_ends=(date(2024, 12, 31),),
        symbols=("SH.600000",),
        symbol_bucket_size=1,
        created_at=NOW,
        data_mode=DataMode.CURRENT_RESEARCH,
        output_trust_state=DataTrustState.NORMALIZED_CURRENT,
        allow_read_through_cache=True,
        bulk_persistence_acknowledged=True,
    )


def profile(*, provider_id: str = "akshare") -> FinancialSourceProfile:
    return FinancialSourceProfile(
        profile_version=(
            "financial-source:akshare:v1"
            if provider_id == "akshare"
            else "financial-source:factor-service-ths:v1"
        ),
        provider_id=provider_id,
        role=(
            FinancialSourceRole.FALLBACK
            if provider_id == "akshare"
            else FinancialSourceRole.PRIMARY
        ),
        markets=frozenset({"XSHG", "XSHE"}),
        statements=frozenset(StatementType),
        access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
        qualification=FinancialSourceQualification.NORMALIZED_CURRENT_APPROVED,
        trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
        retention_allowed=True,
        bulk_persistence_allowed=True,
        supplies_revision_history=False,
        supplies_exact_available_at=False,
        max_rows_per_request=100,
        warnings=("private local current research only",),
    )


def args() -> argparse.Namespace:
    return argparse.Namespace(
        database_url="postgresql://127.0.0.1/research",
        private_local_research_ack=True,
        bulk_persistence_ack=True,
        mapping_approved_ack=True,
    )


class FinancialBackfillWorkerTest(unittest.TestCase):
    def test_direct_execution_rejects_remote_postgres_before_any_connection(self) -> None:
        remote_args = args()
        remote_args.database_url = "postgresql://research.example.com/a_share"

        with self.assertRaisesRegex(PermissionError, "private-local PostgreSQL"):
            worker._execute_financial_backfill(remote_args, plan(), profile())

    def test_only_akshare_with_exact_mapping_and_read_through_cache_is_executable(
        self,
    ) -> None:
        with patch.dict(
            "os.environ",
            {
                "FACTOR_SERVICE_BASE_URL": "https://factor.example.internal",
                "FACTOR_SERVICE_BEARER_TOKEN": "secret-token",
            },
            clear=True,
        ):
            factor_blockers = worker._execution_gate_blockers(
                args(),
                plan(provider_id="factor_service_ths"),
            )
        self.assertTrue(any("Factor Service" in item for item in factor_blockers))

        wrong_mapping = replace(plan(), mapping_version_id="mapping:akshare:unreviewed")
        self.assertTrue(
            any(
                "exact reviewed AkShare mapping" in item
                for item in worker._execution_gate_blockers(args(), wrong_mapping)
            )
        )
        without_cache = replace(plan(), allow_read_through_cache=False)
        self.assertTrue(
            any(
                "read-through cache" in item
                for item in worker._execution_gate_blockers(args(), without_cache)
            )
        )
        self.assertEqual(worker._execution_gate_blockers(args(), plan()), [])

    def test_real_composition_is_sequential_current_only_and_returns_aggregate(
        self,
    ) -> None:
        connection = MagicMock(name="connection")
        connection_context = MagicMock(name="connection_context")
        connection_context.__enter__.return_value = connection
        client = object()
        source = MagicMock(name="source")
        source.provider_id = "akshare"
        execution_result = FinancialBackfillExecutionResult(
            job_id=f"job:{plan().plan_id}",
            status=BackfillJobStatus.SUCCEEDED,
            writes_performed=True,
            completed_work_units=1,
            skipped_work_units=0,
            unit_dataset_version_ids=("dataset:financial:unit:v1",),
            aggregate_dataset_version_id="dataset:financial:aggregate:v1",
        )

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(
                patch.object(worker, "_AKSHARE_FINANCIAL_RUNTIME_ROOT", Path(directory))
            )
            connect = stack.enter_context(
                patch("psycopg.connect", return_value=connection_context)
            )
            metric_repository = stack.enter_context(
                patch.object(worker, "PostgresMetricRegistryRepository")
            )
            metric_service = stack.enter_context(
                patch.object(worker, "MetricRegistryService")
            )
            install_mapping = stack.enter_context(
                patch.object(
                    worker,
                    "install_akshare_current_mapping_v1",
                    return_value=akshare_current_mapping_package_v1(),
                )
            )
            stack.enter_context(
                patch.object(worker, "_load_akshare_client", return_value=client)
            )
            cache = stack.enter_context(
                patch.object(worker, "ContentAddressedAkShareFinancialSnapshotCache")
            )
            executor = stack.enter_context(
                patch.object(worker, "CrossProcessAkShareRequestExecutor")
            )
            object_store = stack.enter_context(
                patch.object(worker, "LocalRawObjectStore")
            )
            evidence_capture = stack.enter_context(
                patch.object(worker, "LocalFinancialEvidenceCapture")
            )
            source_type = stack.enter_context(
                patch.object(worker, "AkShareFinancialSource", return_value=source)
            )
            identity_resolver = stack.enter_context(
                patch.object(worker, "PostgresCurrentKnownFinancialIdentityResolver")
            )
            unit_of_work = stack.enter_context(
                patch.object(worker, "PostgresFinancialBackfillUnitOfWork")
            )
            job_repository = stack.enter_context(
                patch.object(worker, "PostgresFinancialBackfillJobRepository")
            )
            stack.enter_context(
                patch.object(worker, "FinancialBackfillJobCoordinator")
            )
            stack.enter_context(patch.object(worker, "FinancialBackfillRunner"))
            execution_service = stack.enter_context(
                patch.object(worker, "FinancialBackfillExecutionService")
            )
            execution_service.return_value.run.return_value = execution_result

            output = worker._execute_financial_backfill(args(), plan(), profile())

        connect.assert_called_once_with(args().database_url)
        metric_repository.assert_called_once_with(connection)
        metric_service.assert_called_once_with(metric_repository.return_value)
        install_mapping.assert_called_once_with(metric_service.return_value)
        connection.commit.assert_called_once_with()

        cache_root = cache.call_args.kwargs["root"]
        evidence_root = object_store.call_args.args[0]
        self.assertNotEqual(cache_root, evidence_root)
        self.assertEqual(cache_root.parent, evidence_root.parent)
        self.assertEqual(cache_root.name, "cache")
        self.assertEqual(evidence_root.name, "evidence")
        self.assertIn("plans", cache_root.parts)

        executor_kwargs = executor.call_args.kwargs
        self.assertGreaterEqual(executor_kwargs["minimum_interval_seconds"], 2)
        self.assertEqual(executor_kwargs["max_attempts"], 3)
        self.assertEqual(
            executor_kwargs["state_directory"],
            Path(directory) / "gate",
        )
        source_kwargs = source_type.call_args.kwargs
        self.assertIs(source_kwargs["client"], client)
        self.assertIs(source_kwargs["snapshot_cache"], cache.return_value)
        self.assertIs(source_kwargs["request_executor"], executor.return_value)
        self.assertIs(source_kwargs["evidence_capture"], evidence_capture.return_value)

        identity_resolver.assert_called_once_with(connection)
        unit_of_work.assert_called_once_with(
            connection,
            job_id=f"job:{plan().plan_id}",
            identity_resolver=identity_resolver.return_value,
        )
        job_repository.assert_called_once_with(connection)
        execution_service.return_value.run.assert_called_once_with(
            plan=plan(),
            profile=profile(),
            source=source,
        )
        self.assertEqual(output["execution_status"], "succeeded")
        self.assertTrue(output["writes_performed"])
        self.assertEqual(
            output["aggregate_dataset_version_id"],
            "dataset:financial:aggregate:v1",
        )
        self.assertEqual(
            output["unit_dataset_version_ids"],
            ["dataset:financial:unit:v1"],
        )
        self.assertFalse(output["pit_verified"])
        self.assertFalse(output["redistribution_allowed"])

    def test_plan_runtime_directory_is_deterministic_and_plan_scoped(self) -> None:
        first = worker._akshare_financial_plan_directory(plan())
        repeated = worker._akshare_financial_plan_directory(plan())
        another = worker._akshare_financial_plan_directory(
            replace(plan(), plan_id="financial-backfill:csi500:akshare:v1")
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, another)
        self.assertEqual(first.parent.name, "plans")


if __name__ == "__main__":
    unittest.main()
