import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from a_share_platform.workers.factor_qualification import main

LOCAL_DSN = (
    "postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_dev"
)


class Service:
    def __init__(self) -> None:
        self.calls: list[str] = []
        audits = tuple(
            SimpleNamespace(
                audit_id=f"audit:{factor}:001",
                artifact_hash=marker * 64,
                experiment_run=SimpleNamespace(run_id=f"run:{factor}:001"),
                validation_report=SimpleNamespace(report_id=f"report:{factor}:001"),
                target=SimpleNamespace(factor_key=factor),
                readiness=SimpleNamespace(permitted=False, blockers=("real blocker",)),
            )
            for factor, marker in (
                ("quality", "a"),
                ("valuation_expectation_gap", "b"),
                ("fundamental_improvement", "c"),
            )
        )
        self.plan = SimpleNamespace(audits=audits)

    def evaluate(self, **_: object):  # type: ignore[no-untyped-def]
        self.calls.append("evaluate")
        return self.plan

    def ensure(self, **_: object):  # type: ignore[no-untyped-def]
        self.calls.append("ensure")
        return SimpleNamespace(plan=self.plan, writes_performed=True)


class FactorQualificationCliTest(unittest.TestCase):
    def invoke(self, arguments: list[str], service: Service):  # type: ignore[no-untyped-def]
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(arguments, service_factory=lambda _dsn: service)
        return code, json.loads(output.getvalue())

    def test_dry_run_is_read_only_and_reports_all_three_failures(self) -> None:
        service = Service()
        code, document = self.invoke(
            [
                "--database-url",
                LOCAL_DSN,
                "--evaluated-at",
                "2026-08-11T12:00:00Z",
                "--code-sha",
                "1" * 40,
            ],
            service,
        )

        self.assertEqual(code, 0)
        self.assertEqual(service.calls, ["evaluate"])
        self.assertFalse(document["writes_performed"])
        self.assertFalse(document["pit_qualification_passed"])
        self.assertEqual(len(document["audits"]), 3)

    def test_execute_requires_ack_and_uses_only_private_local_postgres(self) -> None:
        service = Service()
        base = [
            "--database-url",
            LOCAL_DSN,
            "--evaluated-at",
            "2026-08-11T12:00:00Z",
            "--code-sha",
            "1" * 40,
            "--execute",
        ]
        code, document = self.invoke(base, service)
        self.assertEqual(code, 2)
        self.assertEqual(service.calls, [])
        self.assertTrue(document["blockers"])

        code, document = self.invoke(
            [*base, "--private-local-research-ack"],
            service,
        )
        self.assertEqual(code, 0)
        self.assertEqual(service.calls, ["ensure"])
        self.assertTrue(document["writes_performed"])
        self.assertFalse(document["pit_qualification_passed"])


if __name__ == "__main__":
    unittest.main()
