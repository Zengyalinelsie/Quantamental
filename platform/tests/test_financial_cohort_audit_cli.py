import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from a_share_platform.workers.financial_cohort_audit import main

LOCAL_DSN = (
    "postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_dev"
)


class Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], int]] = []
        evidence = SimpleNamespace(
            dataset=SimpleNamespace(dataset_version_id="dataset:cohort:audit:v1"),
            expected_work_units=12000,
            completed_work_units=12000,
            security_count=500,
            observation_count=35505,
        )
        self.evidence = evidence

    def evaluate(self, *, job_ids: tuple[str, ...], expected_security_count: int):  # type: ignore[no-untyped-def]
        self.calls.append(("evaluate", job_ids, expected_security_count))
        return self.evidence

    def ensure(self, *, job_ids: tuple[str, ...], expected_security_count: int):  # type: ignore[no-untyped-def]
        self.calls.append(("ensure", job_ids, expected_security_count))
        return SimpleNamespace(evidence=self.evidence, writes_performed=True)


class FinancialCohortAuditCliTest(unittest.TestCase):
    def invoke(self, args: list[str], service: Service) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(args, service_factory=lambda _dsn: service)
        return code, json.loads(output.getvalue())

    def test_default_is_read_only_and_reports_frozen_counts(self) -> None:
        service = Service()
        code, output = self.invoke(
            [
                "--job-ids",
                "job:pilot",
                "job:remaining",
                "--expected-security-count",
                "500",
                "--database-url",
                LOCAL_DSN,
            ],
            service,
        )

        self.assertEqual(code, 0)
        self.assertEqual(service.calls[0][0], "evaluate")
        self.assertFalse(output["writes_performed"])
        self.assertEqual(output["completed_work_units"], 12000)
        self.assertFalse(output["pit_verified"])

    def test_execute_requires_ack_and_then_persists_only_the_audit(self) -> None:
        blocked_service = Service()
        code, output = self.invoke(
            [
                "--job-ids",
                "job:pilot",
                "job:remaining",
                "--expected-security-count",
                "500",
                "--database-url",
                LOCAL_DSN,
                "--execute",
            ],
            blocked_service,
        )
        self.assertEqual(code, 2)
        self.assertEqual(blocked_service.calls, [])
        self.assertTrue(
            any("private-local-research ack" in blocker for blocker in output["blockers"])
        )

        service = Service()
        code, output = self.invoke(
            [
                "--job-ids",
                "job:pilot",
                "job:remaining",
                "--expected-security-count",
                "500",
                "--database-url",
                LOCAL_DSN,
                "--private-local-research-ack",
                "--execute",
            ],
            service,
        )
        self.assertEqual(code, 0)
        self.assertEqual(service.calls[0][0], "ensure")
        self.assertTrue(output["writes_performed"])


if __name__ == "__main__":
    unittest.main()
