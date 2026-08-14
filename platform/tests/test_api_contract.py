import unittest

from fastapi.testclient import TestClient

from a_share_platform.api.app import create_app
from tests.market_data_fixtures import build_market_data_fixture
from tests.security_master_fixtures import build_security_master_fixture
from tests.universe_fixtures import build_universe_fixture


class ApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())
        cls.security_client = TestClient(
            create_app(security_master=build_security_master_fixture())
        )
        cls.universe_client = TestClient(
            create_app(
                security_master=build_security_master_fixture(),
                universe_catalog=build_universe_fixture(),
            )
        )
        cls.market_client = TestClient(
            create_app(market_data_catalog=build_market_data_fixture())
        )

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

    def test_public_dataset_resource_is_honestly_empty(self) -> None:
        for resource in ("datasets",):
            with self.subTest(resource=resource):
                response = self.client.get(f"/api/{resource}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"], [])

    def test_anonymous_cannot_enumerate_private_artifacts(self) -> None:
        for resource in ("artifacts", "runs"):
            with self.subTest(resource=resource):
                response = self.client.get(f"/api/{resource}")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["type"], "permission_denied")

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

    def test_openapi_exposes_only_permission_guarded_research_write_endpoints(self) -> None:
        schema = self.client.get("/openapi.json").json()
        methods = {
            (path, method)
            for path, definition in schema["paths"].items()
            for method in definition
            if method in {"post", "put", "patch", "delete"}
        }
        self.assertEqual(
            methods,
            {
                ("/api/experiments/runs", "post"),
                ("/api/factors/reviews", "post"),
            },
        )

    def test_security_mapping_api_resolves_historical_code(self) -> None:
        response = self.security_client.get(
            "/api/listings/resolve",
            params={"exchange": "XSHE", "code": "000043", "as_of": "2018-01-05"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["listing_id"], "listing:cmre:xshe")
        self.assertEqual(payload["data"]["company_id"], "company:cmre")
        self.assertEqual(payload["data"]["name"], "中航善达")

    def test_security_list_requires_as_of_and_does_not_hide_delisted_sample(self) -> None:
        self.assertEqual(self.security_client.get("/api/securities").status_code, 422)
        response = self.security_client.get(
            "/api/securities",
            params={"as_of": "2020-05-22"},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        meidu = next(row for row in rows if row["listing_id"] == "listing:meidu:xshg")
        self.assertEqual(meidu["special_treatment"], "star_st")

    def test_default_runtime_has_no_security_fixture(self) -> None:
        response = self.client.get("/api/securities", params={"as_of": "2020-05-22"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    def test_company_mapping_preserves_multiple_securities(self) -> None:
        response = self.security_client.get("/api/companies/company:spg")
        self.assertEqual(response.status_code, 200)
        securities = response.json()["data"]["securities"]
        self.assertEqual(
            {item["security"]["security_id"] for item in securities},
            {"security:spg:a", "security:spg:b"},
        )

    def test_unknown_company_uses_problem_details(self) -> None:
        response = self.security_client.get("/api/companies/company:missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["type"], "resource_not_found")

    def test_universe_snapshot_returns_separate_eligibility(self) -> None:
        response = self.universe_client.get(
            "/api/universes/universe-version:core-a-share:v1/snapshot",
            params={"as_of": "2020-05-22"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        meidu = next(row for row in payload["rows"] if row["listing_id"] == "listing:meidu:xshg")
        self.assertTrue(meidu["research_eligible"])
        self.assertFalse(meidu["tradable_eligible"])
        self.assertEqual(meidu["delisted_on"], "2020-08-14")
        self.assertEqual(payload["dataset_version_id"], "dataset:p2-contract-fixture:v1")
        self.assertEqual(
            response.json()["context"]["dataset_version_ids"],
            ["dataset:p2-contract-fixture:v1"],
        )

    def test_universe_diff_and_coverage_are_readable(self) -> None:
        diff = self.universe_client.get(
            "/api/universes/universe-version:core-a-share:v1/diff",
            params={"from_date": "2018-01-05", "to_date": "2020-05-22"},
        )
        coverage = self.universe_client.get(
            "/api/universes/universe-version:core-a-share:v1/coverage",
            params={"as_of": "2020-05-22"},
        )
        self.assertEqual(diff.status_code, 200)
        self.assertEqual(
            diff.json()["data"]["added_listing_ids"],
            ["listing:meidu:xshg"],
        )
        self.assertEqual(coverage.status_code, 200)
        self.assertEqual(coverage.json()["data"]["identity_coverage"], 1.0)

    def test_default_runtime_has_no_universe_fixture(self) -> None:
        response = self.client.get("/api/universes")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    def test_market_data_api_returns_raw_observations_and_derived_summary(self) -> None:
        params = {"listing_id": "listing:cmre:xshe", "session_date": "2018-01-02"}
        bars = self.market_client.get("/api/market-data/bars", params=params)
        summary = self.market_client.get("/api/market-data/summary", params=params)
        self.assertEqual(bars.status_code, 200)
        self.assertEqual(bars.json()["data"][0]["adjustment"], "unadjusted")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["data"]["adjusted_close"], "6.150")
        self.assertEqual(summary.json()["data"]["market_cap"], "8203625416.80")

    def test_market_calendar_and_quality_are_read_only(self) -> None:
        next_session = self.market_client.get(
            "/api/calendars/XSHE/next-session",
            params={"after": "2018-01-01"},
        )
        quality = self.market_client.get("/api/market-data/quality")
        self.assertEqual(next_session.status_code, 200)
        self.assertEqual(next_session.json()["data"]["next_session"], "2018-01-02")
        self.assertEqual(quality.status_code, 200)
        self.assertEqual(quality.json()["data"]["issues"], [])

    def test_default_runtime_has_no_market_data_fixture(self) -> None:
        response = self.client.get(
            "/api/market-data/bars",
            params={"listing_id": "listing:cmre:xshe", "session_date": "2018-01-02"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])


if __name__ == "__main__":
    unittest.main()
