import unittest
from dataclasses import asdict
from datetime import timedelta

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.factor_reviews import (
    InMemoryFactorReviewRepository,
)
from a_share_platform.api.app import anonymous_principal, create_app
from a_share_platform.application.permissions import Principal, Role
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope
from tests.test_factor_lifecycle import NOW, candidate, digest, report


def request_payload() -> dict[str, object]:
    factor_document = asdict(candidate())
    factor_document.pop("content_hash")
    validation_document = asdict(report())
    for computed in (
        "historical_evidence_eligible",
        "passes_promotion_gate",
        "content_hash",
    ):
        validation_document.pop(computed)
    return jsonable_encoder(
        {
            "approval_id": "approval:quality:research-backtest:v1",
            "factor_version": factor_document,
            "validation_report": validation_document,
            "scope": ApprovalScope.RESEARCH_BACKTEST,
            "decision": ApprovalDecision.APPROVED,
            "decided_at": NOW + timedelta(minutes=5),
            "reason": "Reviewed the frozen evidence pack for this exact use.",
            "evidence_hashes": (digest("c"),),
        }
    )


class FactorReviewApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryFactorReviewRepository()
        self.app = create_app(factor_review_repository=self.repository)
        self.client = TestClient(self.app)

    def test_only_review_authority_can_decide_and_actor_comes_from_principal(self) -> None:
        self.assertEqual(
            self.client.post("/api/factors/reviews", json=request_payload()).status_code,
            403,
        )
        self.app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "user:researcher", frozenset({Role.RESEARCHER})
        )
        self.assertEqual(
            self.client.post("/api/factors/reviews", json=request_payload()).status_code,
            403,
        )

        administrator_payload = request_payload()
        administrator_payload["approval_id"] = "approval:quality:administrator:v1"
        self.app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "user:administrator", frozenset({Role.ADMINISTRATOR})
        )
        administrator = self.client.post(
            "/api/factors/reviews", json=administrator_payload
        )
        self.assertEqual(administrator.status_code, 201)
        self.assertEqual(
            administrator.json()["data"]["approval"]["actor_role"],
            "administrator",
        )

        self.app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "user:reviewer-01", frozenset({Role.REVIEWER})
        )
        response = self.client.post("/api/factors/reviews", json=request_payload())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["approval"]["actor_id"], "user:reviewer-01")
        self.assertEqual(response.json()["data"]["approval"]["scope"], "research_backtest")
        self.assertTrue(response.json()["data"]["scientific_gate_passed"])
        self.assertEqual(response.json()["context"]["run_id"], report().experiment_run_id)

        detail = self.client.get(
            "/api/factors/reviews/approval:quality:research-backtest:v1"
        )
        listing = self.client.get("/api/factors/reviews")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(listing.json()["data"]), 2)

    def test_client_cannot_supply_actor_and_failed_science_cannot_be_approved(self) -> None:
        self.app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "user:reviewer-01", frozenset({Role.REVIEWER})
        )
        injected = request_payload()
        injected["actor_id"] = "forged:reviewer"
        self.assertEqual(
            self.client.post("/api/factors/reviews", json=injected).status_code,
            422,
        )

        failed = request_payload()
        checks = failed["validation_report"]["checks"]  # type: ignore[index]
        checks[0]["outcome"] = "fail"  # type: ignore[index]
        response = self.client.post("/api/factors/reviews", json=failed)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["type"], "invalid_factor_review")
        self.assertIn("scientific", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
