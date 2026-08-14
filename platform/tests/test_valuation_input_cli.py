import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from a_share_platform.workers.valuation_inputs import main

LOCAL_DSN = (
    "postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/"
    "a_share_platform_layered_dev"
)


class Service:
    def __init__(self, *, qualified: bool) -> None:
        self.calls: list[str] = []
        evidence = (
            SimpleNamespace(
                domain=SimpleNamespace(value=domain),
                trust_state=SimpleNamespace(value="normalized_current"),
                dataset_version_ids=(f"dataset:{domain}:v1",),
                observation_count=1 if qualified else 0,
                blockers=() if qualified else (f"{domain} unavailable",),
            )
            for domain in ("financial", "price", "comparable")
        )
        qualification = SimpleNamespace(
            is_qualified=qualified,
            blockers=() if qualified else ("price: price unavailable",),
            domain_evidence=tuple(evidence),
        )
        self.compilation = SimpleNamespace(
            qualification=qualification,
            bundle=(
                SimpleNamespace(bundle_version_id="bundle:qualified:v1")
                if qualified
                else None
            ),
        )

    def evaluate(self, request):  # type: ignore[no-untyped-def]
        self.calls.append("evaluate")
        return self.compilation

    def ensure(self, request):  # type: ignore[no-untyped-def]
        self.calls.append("ensure")
        return self.compilation, self.compilation.bundle is not None


class ValuationInputCliTest(unittest.TestCase):
    def invoke(self, arguments: list[str], service: Service):  # type: ignore[no-untyped-def]
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(arguments, service_factory=lambda _dsn: service)
        return code, json.loads(output.getvalue())

    @staticmethod
    def base() -> list[str]:
        return [
            "--database-url",
            LOCAL_DSN,
            "--security-id",
            "security:000001.XSHE",
            "--decision-time",
            "2025-04-30T15:00:00+08:00",
            "--data-mode",
            "current_research",
            "--trust-state",
            "normalized_current",
        ]

    def test_dry_run_reports_all_domains_and_never_writes(self) -> None:
        service = Service(qualified=False)
        code, document = self.invoke(self.base(), service)

        self.assertEqual(code, 0)
        self.assertEqual(service.calls, ["evaluate"])
        self.assertFalse(document["qualified"])
        self.assertFalse(document["writes_performed"])
        self.assertIsNone(document["bundle_version_id"])
        self.assertEqual(len(document["domains"]), 3)

    def test_execute_requires_ack_and_never_writes_a_blocked_compilation(self) -> None:
        service = Service(qualified=True)
        code, document = self.invoke([*self.base(), "--execute"], service)
        self.assertEqual(code, 2)
        self.assertEqual(service.calls, [])
        self.assertFalse(document["writes_performed"])

        blocked = Service(qualified=False)
        code, document = self.invoke(
            [*self.base(), "--execute", "--private-local-research-ack"],
            blocked,
        )
        self.assertEqual(code, 2)
        self.assertEqual(blocked.calls, ["ensure"])
        self.assertFalse(document["writes_performed"])

    def test_qualified_execute_freezes_once_and_strict_current_mismatch_fails_before_service(
        self,
    ) -> None:
        service = Service(qualified=True)
        code, document = self.invoke(
            [*self.base(), "--execute", "--private-local-research-ack"],
            service,
        )
        self.assertEqual(code, 0)
        self.assertEqual(service.calls, ["ensure"])
        self.assertTrue(document["writes_performed"])
        self.assertEqual(document["bundle_version_id"], "bundle:qualified:v1")

        invalid = Service(qualified=True)
        arguments = self.base()
        arguments[arguments.index("current_research")] = "strict_historical"
        code, document = self.invoke(arguments, invalid)
        self.assertEqual(code, 1)
        self.assertEqual(invalid.calls, [])
        self.assertIn("pit_verified", document["execution_error"])


if __name__ == "__main__":
    unittest.main()
