import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerService,
)
from a_share_platform.application.investment_view_outcomes import (
    InvestmentViewOutcomeMaturityService,
    OutcomeWorkItemStatus,
)
from a_share_platform.domain.expected_return import (
    ExpectedReturnCompilerV0,
    InvestmentViewOutcomeObservation,
    OutcomeObservationReason,
    OutcomeObservationStatus,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.workers.investment_view_outcomes import main
from tests.test_expected_return_compiler import DECISION_TIME, request

EVALUATED_AT = DECISION_TIME + timedelta(days=100)
POLICY_VERSION = "outcome-price-policy:test:v1"
LOCAL_DSN = (
    "postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/"
    "a_share_platform_layered_dev"
)


def observation(
    view,
    *,
    status: OutcomeObservationStatus,
    reason_code: OutcomeObservationReason | None = None,
    reason: str | None = None,
) -> InvestmentViewOutcomeObservation:
    mature = status is OutcomeObservationStatus.MATURE
    return InvestmentViewOutcomeObservation(
        view_id=view.view_id,
        security_id=view.security_id,
        decision_time=view.decision_time,
        horizon_trading_days=view.horizon_trading_days,
        evaluated_at=EVALUATED_AT,
        status=status,
        source_policy_version=POLICY_VERSION,
        reason_code=reason_code,
        reason=reason,
        realized_at=DECISION_TIME + timedelta(days=90) if mature else None,
        realized_return=Decimal("-0.03") if mature else None,
        dataset_version_id="dataset:adjusted-close:v1" if mature else None,
        source_available_at=DECISION_TIME + timedelta(days=91) if mature else None,
    )


class Source:
    def __init__(self, observations: dict[str, InvestmentViewOutcomeObservation]) -> None:
        self.observations = observations
        self.calls: list[tuple[str, datetime]] = []

    def observe(self, *, view, evaluated_at):  # type: ignore[no-untyped-def]
        self.calls.append((view.view_id, evaluated_at))
        return self.observations[view.view_id]


class InvestmentViewOutcomeMaturityServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryExpectedReturnLedgerRepository()
        self.ledger = ExpectedReturnLedgerService(self.repository)
        self.view = self.ledger.record_view(ExpectedReturnCompilerV0().compile(request()))

    def service(
        self,
        value: InvestmentViewOutcomeObservation,
    ) -> tuple[InvestmentViewOutcomeMaturityService, Source]:
        source = Source({self.view.view_id: value})
        return InvestmentViewOutcomeMaturityService(self.repository, source), source

    def test_not_matured_is_pending_and_dry_run_never_writes(self) -> None:
        service, source = self.service(
            observation(
                self.view,
                status=OutcomeObservationStatus.PENDING,
                reason_code=OutcomeObservationReason.HORIZON_NOT_REACHED,
                reason="第 60 个交易日尚未收盘",
            )
        )

        result = service.evaluate(evaluated_at=EVALUATED_AT)

        self.assertFalse(result.writes_performed)
        self.assertEqual(result.counts, {"pending": 1})
        self.assertEqual(result.items[0].status, OutcomeWorkItemStatus.PENDING)
        self.assertEqual(result.items[0].reason_code, "horizon_not_reached")
        self.assertIsNone(self.ledger.outcome_for_view(self.view.view_id))
        self.assertEqual(source.calls, [(self.view.view_id, EVALUATED_AT)])

    def test_unavailable_reasons_remain_distinct_and_never_become_zero_returns(self) -> None:
        cases = (
            (OutcomeObservationReason.PRICE_UNAVAILABLE, "到期复权收盘价不可用"),
            (
                OutcomeObservationReason.CORPORATE_ACTIONS_INCOMPLETE,
                "持有期公司行动链不完整",
            ),
            (OutcomeObservationReason.SOURCE_UNQUALIFIED, "价格来源政策尚未获批"),
        )
        for reason_code, reason in cases:
            with self.subTest(reason_code=reason_code.value):
                service, _source = self.service(
                    observation(
                        self.view,
                        status=OutcomeObservationStatus.UNAVAILABLE,
                        reason_code=reason_code,
                        reason=reason,
                    )
                )

                result = service.ensure(evaluated_at=EVALUATED_AT)

                self.assertFalse(result.writes_performed)
                self.assertEqual(result.items[0].status, OutcomeWorkItemStatus.UNAVAILABLE)
                self.assertEqual(result.items[0].reason_code, reason_code.value)
                self.assertIsNone(result.items[0].outcome)
                self.assertIsNone(self.ledger.outcome_for_view(self.view.view_id))

    def test_mature_dry_run_then_execute_is_append_only_and_idempotent(self) -> None:
        service, source = self.service(
            observation(self.view, status=OutcomeObservationStatus.MATURE)
        )

        preview = service.evaluate(evaluated_at=EVALUATED_AT)
        self.assertFalse(preview.writes_performed)
        self.assertEqual(preview.items[0].status, OutcomeWorkItemStatus.MATURE)
        self.assertEqual(
            preview.items[0].outcome.source_policy_version,  # type: ignore[union-attr]
            POLICY_VERSION,
        )
        self.assertIsNone(self.ledger.outcome_for_view(self.view.view_id))

        executed = service.ensure(evaluated_at=EVALUATED_AT)
        self.assertTrue(executed.writes_performed)
        persisted = self.ledger.outcome_for_view(self.view.view_id)
        self.assertEqual(persisted, executed.items[0].outcome)
        self.assertEqual(persisted.realized_return, Decimal("-0.03"))  # type: ignore[union-attr]

        repeated = service.ensure(evaluated_at=EVALUATED_AT + timedelta(days=1))
        self.assertFalse(repeated.writes_performed)
        self.assertEqual(
            repeated.items[0].status,
            OutcomeWorkItemStatus.ALREADY_RECORDED,
        )
        self.assertEqual(len(source.calls), 2)

    def test_source_identity_or_evaluation_time_mismatch_fails_closed(self) -> None:
        valid = observation(self.view, status=OutcomeObservationStatus.MATURE)
        mismatches = (
            replace(valid, view_id="investment-view:other"),
            replace(valid, security_id="security:CN:000001:XSHE"),
            replace(valid, decision_time=valid.decision_time - timedelta(days=1)),
            replace(valid, horizon_trading_days=20),
            replace(valid, evaluated_at=valid.evaluated_at - timedelta(minutes=1)),
        )
        for mismatched in mismatches:
            with self.subTest(value=mismatched):
                service, _source = self.service(mismatched)
                with self.assertRaisesRegex(ValueError, "outcome source identity mismatch"):
                    service.ensure(evaluated_at=EVALUATED_AT)
                self.assertIsNone(self.ledger.outcome_for_view(self.view.view_id))

    def test_p11_deployment_stages_are_not_scanned_or_written(self) -> None:
        paper_view = ExpectedReturnCompilerV0().compile(
            request(
                run_context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.PAPER)
            )
        )
        self.ledger.record_view(paper_view)
        source = Source(
            {
                self.view.view_id: observation(
                    self.view,
                    status=OutcomeObservationStatus.PENDING,
                    reason_code=OutcomeObservationReason.HORIZON_NOT_REACHED,
                    reason="未到期",
                )
            }
        )
        service = InvestmentViewOutcomeMaturityService(self.repository, source)

        result = service.ensure(evaluated_at=EVALUATED_AT)

        by_id = {item.view_id: item for item in result.items}
        self.assertEqual(
            by_id[paper_view.view_id].reason_code,
            "deployment_stage_not_authorized",
        )
        self.assertEqual(source.calls, [(self.view.view_id, EVALUATED_AT)])
        self.assertIsNone(self.ledger.outcome_for_view(paper_view.view_id))

    def test_observation_shape_rejects_ambiguous_or_manufactured_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "mature observation requires"):
            observation(self.view, status=OutcomeObservationStatus.MATURE).__class__(
                **{
                    **observation(
                        self.view,
                        status=OutcomeObservationStatus.MATURE,
                    ).__dict__,
                    "realized_return": None,
                }
            )
        with self.assertRaisesRegex(ValueError, "non-mature observation cannot carry"):
            replace(
                observation(
                    self.view,
                    status=OutcomeObservationStatus.UNAVAILABLE,
                    reason_code=OutcomeObservationReason.PRICE_UNAVAILABLE,
                    reason="价格不可用",
                ),
                realized_return=Decimal(0),
            )


class CliService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result = type(
            "Result",
            (),
            {
                "evaluated_at": EVALUATED_AT,
                "writes_performed": False,
                "counts": {"pending": 1},
                "items": (
                    type(
                        "Item",
                        (),
                        {
                            "view_id": "investment-view:test",
                            "status": OutcomeWorkItemStatus.PENDING,
                            "reason_code": "horizon_not_reached",
                            "reason": "未到期",
                            "source_policy_version": POLICY_VERSION,
                            "outcome": None,
                            "write_performed": False,
                        },
                    )(),
                ),
            },
        )()

    def evaluate(self, *, evaluated_at):  # type: ignore[no-untyped-def]
        self.calls.append("evaluate")
        self.result.evaluated_at = evaluated_at
        return self.result

    def ensure(self, *, evaluated_at):  # type: ignore[no-untyped-def]
        self.calls.append("ensure")
        self.result.evaluated_at = evaluated_at
        return self.result


class InvestmentViewOutcomeWorkerCliTest(unittest.TestCase):
    @staticmethod
    def base() -> list[str]:
        return [
            "--database-url",
            LOCAL_DSN,
            "--evaluated-at",
            EVALUATED_AT.isoformat(),
        ]

    def invoke(self, arguments: list[str], service: CliService):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(arguments, service_factory=lambda _dsn: service)
        return code, json.loads(output.getvalue())

    def test_cli_is_dry_run_by_default_and_execute_requires_explicit_ack(self) -> None:
        dry_run = CliService()
        code, document = self.invoke(self.base(), dry_run)
        self.assertEqual(code, 0)
        self.assertEqual(dry_run.calls, ["evaluate"])
        self.assertEqual(document["mode"], "dry_run")
        self.assertFalse(document["writes_performed"])

        blocked = CliService()
        code, document = self.invoke([*self.base(), "--execute"], blocked)
        self.assertEqual(code, 2)
        self.assertEqual(blocked.calls, [])
        self.assertEqual(document["execution_status"], "blocked")

        executed = CliService()
        code, document = self.invoke(
            [*self.base(), "--execute", "--private-local-research-ack"],
            executed,
        )
        self.assertEqual(code, 0)
        self.assertEqual(executed.calls, ["ensure"])
        self.assertEqual(document["mode"], "execute_requested")

    def test_cli_rejects_non_local_postgresql_before_service_construction(self) -> None:
        service = CliService()
        arguments = self.base()
        arguments[1] = "postgresql://research.example.com/platform"
        code, document = self.invoke(arguments, service)

        self.assertEqual(code, 2)
        self.assertEqual(service.calls, [])
        self.assertIn("private-local PostgreSQL", document["blockers"][0])


if __name__ == "__main__":
    unittest.main()
