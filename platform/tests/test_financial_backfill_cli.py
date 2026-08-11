import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from a_share_platform.workers.financial_backfill import main


def plan_document() -> dict[str, object]:
    return {
        "plan_id": "financial-backfill:csi300:2024:v1",
        "provider_id": "factor_service_ths",
        "provider_profile_version": "financial-source:factor-service-ths:v1",
        "cohort": "csi300",
        "universe_version_id": "universe:index-000300:2026-08-10:v1",
        "mapping_version_id": "mapping:factor-service-ths:v1",
        "statements": [
            {"statement_type": "balance_sheet", "provider_table": "balance_sheet"}
        ],
        "report_period_ends": ["2024-12-31"],
        "symbols": ["SH.600000"],
        "symbol_bucket_size": 1,
        "created_at": "2026-08-10T18:00:00+00:00",
        "data_mode": "current_research",
        "output_trust_state": "normalized_current",
        "allow_read_through_cache": True,
        "bulk_persistence_acknowledged": True,
        "predecessor_coverage_report_id": None,
    }


def profile_document(*, qualification: str = "normalized_current_approved") -> dict[str, object]:
    return {
        "profile_version": "financial-source:factor-service-ths:v1",
        "provider_id": "factor_service_ths",
        "role": "primary",
        "markets": ["XSHG", "XSHE"],
        "statements": ["balance_sheet", "income_statement", "cash_flow_statement"],
        "access_mode": "read_through_cache",
        "qualification": qualification,
        "trust_ceiling": "normalized_current",
        "retention_allowed": True,
        "bulk_persistence_allowed": True,
        "supplies_revision_history": False,
        "supplies_exact_available_at": False,
        "max_rows_per_request": 5000,
        "warnings": ["private local research only"],
    }


class FinancialBackfillCliTest(unittest.TestCase):
    def _manifests(
        self,
        root: Path,
        *,
        qualification: str = "normalized_current_approved",
    ) -> tuple[Path, Path]:
        plan_path = root / "plan.json"
        profile_path = root / "profile.json"
        plan_path.write_text(json.dumps(plan_document()), encoding="utf-8")
        profile_path.write_text(
            json.dumps(profile_document(qualification=qualification)),
            encoding="utf-8",
        )
        return plan_path, profile_path

    def test_default_is_a_read_only_preview_without_credentials_or_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path, profile_path = self._manifests(Path(directory))
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    ["--plan", str(plan_path), "--profile", str(profile_path)]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertFalse(payload["writes_performed"])
        self.assertTrue(payload["qualified"])
        self.assertEqual(payload["work_unit_count"], 1)
        self.assertEqual(payload["output_trust_state"], "normalized_current")
        self.assertEqual(payload["data_mode"], "current_research")

    def test_execute_without_local_database_acks_or_credentials_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path, profile_path = self._manifests(Path(directory))
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
                exit_code = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--profile",
                        str(profile_path),
                        "--execute",
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["execution_status"], "blocked")
        blockers = " ".join(payload["blockers"])
        self.assertIn("local database", blockers)
        self.assertIn("private-local-research ack", blockers)
        self.assertIn("bulk-persistence ack", blockers)
        self.assertIn("mapping approval ack", blockers)
        self.assertIn("FACTOR_SERVICE_BASE_URL", blockers)
        self.assertIn("FACTOR_SERVICE_BEARER_TOKEN", blockers)
        self.assertNotIn("secret-token", output.getvalue())

    def test_candidate_profile_blocks_execution_even_when_runtime_inputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path, profile_path = self._manifests(
                Path(directory), qualification="candidate"
            )
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "FACTOR_SERVICE_BASE_URL": "https://factor.example.internal",
                        "FACTOR_SERVICE_BEARER_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "a_share_platform.workers.financial_backfill._execute_financial_backfill"
                ) as execute,
                redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--profile",
                        str(profile_path),
                        "--database-url",
                        "postgresql://127.0.0.1/research",
                        "--private-local-research-ack",
                        "--bulk-persistence-ack",
                        "--mapping-approved-ack",
                        "--execute",
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertIn("only a candidate", " ".join(payload["blockers"]))
        execute.assert_not_called()

    def test_explicit_gates_reach_injected_runtime_without_printing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path, profile_path = self._manifests(Path(directory))
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "FACTOR_SERVICE_BASE_URL": "https://factor.example.internal",
                        "FACTOR_SERVICE_BEARER_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "a_share_platform.workers.financial_backfill._execute_financial_backfill",
                    return_value={
                        "execution_status": "succeeded",
                        "completed_work_units": 1,
                        "dataset_version_ids": ["dataset:financial:test"],
                    },
                ) as execute,
                redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--profile",
                        str(profile_path),
                        "--database-url",
                        "postgresql://127.0.0.1/research",
                        "--private-local-research-ack",
                        "--bulk-persistence-ack",
                        "--mapping-approved-ack",
                        "--execute",
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["writes_performed"])
        self.assertTrue(payload["credentials_configured"])
        self.assertNotIn("secret-token", output.getvalue())
        execute.assert_called_once()

    def test_remote_postgres_is_never_an_executable_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path, profile_path = self._manifests(Path(directory))
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "FACTOR_SERVICE_BASE_URL": "https://factor.example.internal",
                        "FACTOR_SERVICE_BEARER_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "a_share_platform.workers.financial_backfill._execute_financial_backfill"
                ) as execute,
                redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--profile",
                        str(profile_path),
                        "--database-url",
                        "postgresql://db.example.com/research",
                        "--private-local-research-ack",
                        "--bulk-persistence-ack",
                        "--mapping-approved-ack",
                        "--execute",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("loopback or Unix socket", output.getvalue())
        execute.assert_not_called()

    def test_akshare_execute_is_blocked_until_source_aware_grouping_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_value = plan_document()
            plan_value["provider_id"] = "akshare_eastmoney"
            plan_value["provider_profile_version"] = "financial-source:akshare:v1"
            profile_value = profile_document()
            profile_value["provider_id"] = "akshare_eastmoney"
            profile_value["profile_version"] = "financial-source:akshare:v1"
            plan_path = root / "plan.json"
            profile_path = root / "profile.json"
            plan_path.write_text(json.dumps(plan_value), encoding="utf-8")
            profile_path.write_text(json.dumps(profile_value), encoding="utf-8")
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "FACTOR_SERVICE_BASE_URL": "https://factor.example.internal",
                        "FACTOR_SERVICE_BEARER_TOKEN": "secret-token",
                    },
                    clear=True,
                ),
                patch(
                    "a_share_platform.workers.financial_backfill._execute_financial_backfill"
                ) as execute,
                redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "--plan",
                        str(plan_path),
                        "--profile",
                        str(profile_path),
                        "--database-url",
                        "postgresql://127.0.0.1/research",
                        "--private-local-research-ack",
                        "--bulk-persistence-ack",
                        "--mapping-approved-ack",
                        "--execute",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("source-aware retrieval grouping", output.getvalue())
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
