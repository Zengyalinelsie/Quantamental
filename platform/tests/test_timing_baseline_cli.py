import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from a_share_platform.workers.timing_baseline import main


class TimingBaselineCliTest(unittest.TestCase):
    def test_cli_is_dry_run_by_default(self) -> None:
        output = io.StringIO()
        with patch(
            "a_share_platform.workers.timing_baseline._execute"
        ) as execute, redirect_stdout(output):
            exit_code = main(
                [
                    "--benchmark-id",
                    "index:000300",
                    "--universe-version-id",
                    "universe:000300:test",
                    "--session",
                    "2026-08-10",
                    "--database-url",
                    "postgresql://127.0.0.1/research",
                    "--code-version",
                    "git:test",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertFalse(payload["writes_performed"])
        execute.assert_not_called()

    def test_execute_requires_private_local_ack_and_local_database(self) -> None:
        output = io.StringIO()
        with patch(
            "a_share_platform.workers.timing_baseline._execute"
        ) as execute, redirect_stdout(output):
            exit_code = main(
                [
                    "--benchmark-id",
                    "index:000300",
                    "--universe-version-id",
                    "universe:000300:test",
                    "--session",
                    "2026-08-10",
                    "--database-url",
                    "postgresql://db.example.com/research",
                    "--code-version",
                    "git:test",
                    "--execute",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["execution_status"], "blocked")
        self.assertTrue(any("ack" in item for item in payload["blockers"]))
        self.assertTrue(any("loopback" in item for item in payload["blockers"]))
        execute.assert_not_called()

    def test_execute_reaches_injected_quote_only_runtime(self) -> None:
        output = io.StringIO()
        with patch(
            "a_share_platform.workers.timing_baseline._execute",
            return_value={
                "execution_status": "succeeded",
                "forecast_id": "timing:000300:2026-08-10:test",
                "created": True,
            },
        ) as execute, redirect_stdout(output):
            exit_code = main(
                [
                    "--benchmark-id",
                    "index:000300",
                    "--universe-version-id",
                    "universe:000300:test",
                    "--session",
                    "2026-08-10",
                    "--database-url",
                    "postgresql://127.0.0.1/research",
                    "--code-version",
                    "git:test",
                    "--private-local-research-ack",
                    "--execute",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["writes_performed"])
        execute.assert_called_once()

    def test_idempotent_execute_reports_that_no_new_write_was_performed(self) -> None:
        output = io.StringIO()
        with patch(
            "a_share_platform.workers.timing_baseline._execute",
            return_value={
                "execution_status": "succeeded",
                "forecast_id": "timing:000905:2026-08-10:test",
                "created": False,
            },
        ), redirect_stdout(output):
            exit_code = main(
                [
                    "--benchmark-id",
                    "index:000905",
                    "--universe-version-id",
                    "universe:000905:test",
                    "--session",
                    "2026-08-10",
                    "--database-url",
                    "postgresql://127.0.0.1/research",
                    "--code-version",
                    "git:test",
                    "--private-local-research-ack",
                    "--execute",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["created"])
        self.assertFalse(payload["writes_performed"])

    def test_cli_and_runtime_contain_no_account_or_execution_adapter(self) -> None:
        root = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "a_share_platform"
        )
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                root / "workers" / "timing_baseline.py",
                root / "adapters" / "providers" / "baostock_timing.py",
            )
        )
        for forbidden in ("Trade" + "Context", "place_" + "order", "get_" + "accounts"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
