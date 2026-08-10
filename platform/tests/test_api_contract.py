import unittest

from fastapi.testclient import TestClient

from a_share_platform.api.app import create_app


class ApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def test_health_uses_unified_context_envelope(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["status"], "ok")
        self.assertEqual(payload["context"]["data_mode"], "current_research")
        self.assertEqual(payload["context"]["deployment_stage"], "research")
        self.assertEqual(payload["context"]["warnings"], [])
        self.assertIn("as_of", payload["context"])
        self.assertIn("system_as_of", payload["context"])

    def test_governance_resources_are_honestly_empty(self) -> None:
        for resource in ("datasets", "runs", "artifacts"):
            with self.subTest(resource=resource):
                response = self.client.get(f"/api/{resource}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"], [])

    def test_client_cannot_promote_run_context_with_query_parameters(self) -> None:
        response = self.client.get(
            "/api/datasets",
            params={"data_mode": "current_research", "deployment_stage": "limited_live"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["type"], "run_context_override_denied")
        self.assertEqual(payload["status"], 400)

    def test_role_header_cannot_impersonate_an_authenticated_user(self) -> None:
        response = self.client.get("/api/identity", headers={"X-Role": "administrator"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["subject_id"], "anonymous")
        self.assertEqual(response.json()["data"]["roles"], [])

    def test_openapi_exposes_no_anonymous_write_endpoints(self) -> None:
        schema = self.client.get("/openapi.json").json()
        methods = {
            method
            for path in schema["paths"].values()
            for method in path
            if method in {"post", "put", "patch", "delete"}
        }
        self.assertEqual(methods, set())


if __name__ == "__main__":
    unittest.main()
