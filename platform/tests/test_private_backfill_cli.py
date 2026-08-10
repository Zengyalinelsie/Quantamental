import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from a_share_platform.workers.backfill import PRIVATE_LOCAL_STORAGE_ROOT, main


class PrivateBackfillCliTest(unittest.TestCase):
    def test_universe_dry_run_can_select_one_explicit_csi_benchmark(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--provider",
                    "a_share_identity_universe",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-08-10",
                    "--all-a-share",
                    "--domains",
                    "universe",
                    "--benchmarks",
                    "000905",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["scopes"], ["index:000905"])
        self.assertEqual(payload["work_unit_count"], 1)

    def test_execute_requires_explicit_private_ack_database_symbols_and_domains(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--provider",
                    "baostock_sdk",
                    "--end",
                    "2026-08-08",
                    "--execute",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["execution_status"], "blocked")
        self.assertTrue(any("ack" in item for item in payload["blockers"]))
        self.assertTrue(any("database" in item for item in payload["blockers"]))
        self.assertTrue(any("symbols" in item for item in payload["blockers"]))
        self.assertTrue(any("domains" in item for item in payload["blockers"]))

    def test_fully_explicit_private_execution_can_reach_injected_runtime(self) -> None:
        output = io.StringIO()
        args = [
            "--provider",
            "baostock_sdk",
            "--start",
            "2018-01-01",
            "--end",
            "2018-01-05",
            "--symbols",
            "SH.600519",
            "--domains",
            "raw_daily_bar",
            "--database-url",
            "postgresql://localhost/research",
            "--parquet-root",
            str(PRIVATE_LOCAL_STORAGE_ROOT / "test-bars"),
            "--private-local-research-ack",
            "--execute",
        ]
        with patch(
            "a_share_platform.workers.backfill._execute_backfill",
            return_value={
                "execution_status": "succeeded",
                "dataset_version_id": "dataset:private:v1",
            },
        ) as execute, redirect_stdout(output):
            exit_code = main(args)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["execution_status"], "succeeded")
        self.assertTrue(payload["writes_performed"])
        self.assertEqual(payload["output_trust_state"], "normalized_current")
        self.assertEqual(payload["provider_use"], "private_local_research")
        execute.assert_called_once()

    def test_full_market_identity_execution_requires_explicit_all_a_share_flag(self) -> None:
        output = io.StringIO()
        args = [
            "--provider",
            "a_share_identity_universe",
            "--start",
            "2018-01-01",
            "--end",
            "2026-08-08",
            "--all-a-share",
            "--domains",
            "security_master",
            "universe",
            "--database-url",
            "postgresql://localhost/research",
            "--parquet-root",
            str(PRIVATE_LOCAL_STORAGE_ROOT / "test-identity"),
            "--private-local-research-ack",
            "--execute",
        ]
        with patch(
            "a_share_platform.workers.backfill._execute_backfill",
            return_value={
                "execution_status": "succeeded",
                "dataset_version_id": "dataset:identity:v1",
            },
        ) as execute, redirect_stdout(output):
            exit_code = main(args)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["all_a_share"])
        self.assertEqual(payload["symbols"], [])
        execute.assert_called_once()

    def test_explicit_identity_security_master_can_reach_injected_runtime(self) -> None:
        output = io.StringIO()
        args = [
            "--provider",
            "a_share_identity_universe",
            "--start",
            "2018-01-01",
            "--end",
            "2026-08-10",
            "--symbols",
            "SH.600519",
            "SZ.000001",
            "--domains",
            "security_master",
            "--database-url",
            "postgresql://localhost/research",
            "--parquet-root",
            str(PRIVATE_LOCAL_STORAGE_ROOT / "test-explicit-identity"),
            "--private-local-research-ack",
            "--execute",
        ]
        with patch(
            "a_share_platform.workers.backfill._execute_backfill",
            return_value={
                "execution_status": "succeeded",
                "dataset_version_id": "dataset:explicit-identity:v1",
            },
        ) as execute, redirect_stdout(output):
            exit_code = main(args)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["all_a_share"])
        self.assertEqual(payload["symbols"], ["SH.600519", "SZ.000001"])
        execute.assert_called_once()

    def test_explicit_identity_universe_still_requires_all_a_share(self) -> None:
        output = io.StringIO()
        args = [
            "--provider",
            "a_share_identity_universe",
            "--start",
            "2018-01-01",
            "--end",
            "2018-12-31",
            "--symbols",
            "SH.600519",
            "--domains",
            "universe",
            "--database-url",
            "postgresql://localhost/research",
            "--parquet-root",
            str(PRIVATE_LOCAL_STORAGE_ROOT / "test-explicit-universe"),
            "--private-local-research-ack",
            "--execute",
        ]
        with (
            patch("a_share_platform.workers.backfill._execute_backfill") as execute,
            redirect_stdout(output),
        ):
            exit_code = main(args)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertTrue(
            any("only security_master" in item for item in payload["blockers"])
        )
        execute.assert_not_called()

    def test_execute_rejects_remote_postgres_and_parquet_outside_controlled_root(self) -> None:
        cases = (
            (
                "postgresql://research@db.example.com/research",
                PRIVATE_LOCAL_STORAGE_ROOT / "allowed",
                "loopback or Unix socket",
            ),
            (
                "postgresql://research@127.0.0.1/research",
                Path("/tmp/outside-private-research"),
                "controlled private-local root",
            ),
        )
        for database_url, parquet_root, expected in cases:
            with self.subTest(expected=expected):
                output = io.StringIO()
                args = [
                    "--provider",
                    "baostock_sdk",
                    "--start",
                    "2018-01-01",
                    "--end",
                    "2018-01-05",
                    "--symbols",
                    "SH.600519",
                    "--domains",
                    "raw_daily_bar",
                    "--database-url",
                    database_url,
                    "--parquet-root",
                    str(parquet_root),
                    "--private-local-research-ack",
                    "--execute",
                ]
                with (
                    patch("a_share_platform.workers.backfill._execute_backfill") as execute,
                    redirect_stdout(output),
                ):
                    exit_code = main(args)

                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, 2)
                self.assertTrue(any(expected in item for item in payload["blockers"]))
                execute.assert_not_called()

    def test_execute_accepts_postgres_unix_socket_dsn(self) -> None:
        output = io.StringIO()
        args = [
            "--provider",
            "baostock_sdk",
            "--start",
            "2018-01-01",
            "--end",
            "2018-01-05",
            "--symbols",
            "SH.600519",
            "--domains",
            "raw_daily_bar",
            "--database-url",
            "postgresql:///research?host=/var/run/postgresql",
            "--parquet-root",
            str(PRIVATE_LOCAL_STORAGE_ROOT / "unix-socket"),
            "--private-local-research-ack",
            "--execute",
        ]
        with patch(
            "a_share_platform.workers.backfill._execute_backfill",
            return_value={"execution_status": "succeeded", "dataset_version_id": "dataset:test"},
        ) as execute, redirect_stdout(output):
            exit_code = main(args)

        self.assertEqual(exit_code, 0)
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
