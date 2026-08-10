import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from a_share_platform.workers.backfill import main


class PrivateBackfillCliTest(unittest.TestCase):
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
            "/tmp/a-share-private-research",
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


if __name__ == "__main__":
    unittest.main()
