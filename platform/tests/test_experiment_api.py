import unittest
from dataclasses import asdict
from unittest.mock import patch

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.experiments import InMemoryExperimentRunRepository
from a_share_platform.api.app import anonymous_principal, create_app
from a_share_platform.application.permissions import Principal, Role
from tests.test_experiment_application import succeeded_run


def request_payload() -> dict[str, object]:
    value = succeeded_run()
    spec = asdict(value.spec)
    for computed in ("historical_evidence_eligible", "content_hash"):
        spec.pop(computed)
    payload = {
        "run_id": value.run_id,
        "spec": spec,
        "status": value.status,
        "started_at": value.started_at,
        "finished_at": value.finished_at,
        "metrics": value.metrics,
        "artifacts": value.artifacts,
        "failure": value.failure,
    }
    return jsonable_encoder(payload)


class ExperimentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryExperimentRunRepository()
        self.app = create_app(experiment_repository=self.repository)
        self.client = TestClient(self.app)

    def test_anonymous_cannot_create_but_researcher_can_create_and_read_run(self) -> None:
        denied = self.client.post("/api/experiments/runs", json=request_payload())
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["type"], "permission_denied")

        self.app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "researcher:001", frozenset({Role.RESEARCHER})
        )
        created = self.client.post("/api/experiments/runs", json=request_payload())
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["data"]["status"], "succeeded")
        self.assertEqual(
            created.json()["context"]["data_mode"],
            "strict_historical",
        )
        self.assertEqual(
            created.json()["context"]["run_id"],
            succeeded_run().run_id,
        )

        detail = self.client.get(f"/api/experiments/runs/{succeeded_run().run_id}")
        listing = self.client.get("/api/experiments/runs")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["spec"]["code_sha"], "1" * 40)
        self.assertEqual(len(listing.json()["data"]), 1)

    def test_domain_invalid_binding_is_an_invalid_request_and_conflict_is_409(self) -> None:
        self.app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "researcher:001", frozenset({Role.RESEARCHER})
        )
        payload = request_payload()
        payload["spec"]["dataset_version_ids"] = ["dataset:pit-financials:v1"]  # type: ignore[index]
        invalid = self.client.post("/api/experiments/runs", json=payload)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["type"], "invalid_experiment_request")

        self.assertEqual(
            self.client.post("/api/experiments/runs", json=request_payload()).status_code,
            201,
        )
        conflicting = request_payload()
        conflicting["artifacts"][0]["content_hash"] = "a" * 64  # type: ignore[index]
        response = self.client.post("/api/experiments/runs", json=conflicting)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["type"], "experiment_run_conflict")

    def test_missing_database_is_explicitly_unavailable(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            client = TestClient(create_app())

        response = client.get("/api/experiments/runs")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["type"], "experiment_store_unavailable")
        self.assertIn("ASP_DATABASE_URL", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
