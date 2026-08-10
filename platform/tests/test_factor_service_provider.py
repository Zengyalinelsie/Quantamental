import json
import unittest
from collections.abc import Mapping
from decimal import Decimal

from a_share_platform.adapters.providers.factor_service import (
    FactorServiceClient,
    FactorServiceHttpRequest,
    FactorServiceHttpResponse,
    FactorServicePayloadError,
    FactorServicePermissionError,
    FactorServiceTransportError,
)


def response(payload: Mapping[str, object], *, status_code: int = 200) -> FactorServiceHttpResponse:
    return FactorServiceHttpResponse(
        status_code=status_code,
        body=json.dumps(payload).encode("utf-8"),
    )


class StubTransport:
    def __init__(self, *responses: FactorServiceHttpResponse) -> None:
        self.responses = list(responses)
        self.requests: list[FactorServiceHttpRequest] = []

    def send(self, request: FactorServiceHttpRequest) -> FactorServiceHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected Factor Service request")
        return self.responses.pop(0)


class FailingTransport:
    def __init__(self, token: str) -> None:
        self.token = token

    def send(self, request: FactorServiceHttpRequest) -> FactorServiceHttpResponse:
        raise RuntimeError(f"upstream rejected Authorization: Bearer {self.token}")


class FactorServiceMetadataTest(unittest.TestCase):
    def test_all_documented_v1_v2_metadata_endpoints_and_success_codes(self) -> None:
        transport = StubTransport(
            response({"status": "ok"}),
            response({"code": 0, "message": "success", "data": [{"factor_name": "a"}]}),
            response({"code": 0, "message": "success", "data": [{"table_name": "a"}]}),
            response({"status": "ok"}),
            response({"code": 0, "message": "success", "data": {"table_name": "name"}}),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": {"prompt_version": "v1", "result": "table_name=balance_sheet"},
                }
            ),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": [{"table_name": "balance_sheet"}],
                }
            ),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": {"table_name": "balance_sheet", "columns": []},
                }
            ),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": [{"qualified_name": "balance_sheet.total_assets"}],
                }
            ),
        )
        client = FactorServiceClient(
            base_url="https://factor.example.internal",
            bearer_token="rotated-secret",
            transport=transport,
        )

        self.assertEqual(client.v1_health()["status"], "ok")
        self.assertEqual(client.v1_factor_list(table_name="balance_sheet")[0]["factor_name"], "a")
        self.assertEqual(client.v1_table_list()[0]["table_name"], "a")
        self.assertEqual(client.v2_health()["status"], "ok")
        self.assertEqual(client.v2_meta_schema()["table_name"], "name")
        self.assertEqual(client.v2_metadata(keyword="资产")["prompt_version"], "v1")
        self.assertEqual(client.v2_tables(keyword="资产")[0]["table_name"], "balance_sheet")
        self.assertEqual(client.v2_table_detail("balance_sheet")["columns"], [])
        self.assertEqual(
            client.v2_columns_search(keyword="资产总计", table_name="balance_sheet")[0][
                "qualified_name"
            ],
            "balance_sheet.total_assets",
        )

        self.assertEqual(
            [request.path for request in transport.requests],
            [
                "/factor/service/api/v1/health",
                "/factor/service/api/v1/factor/list",
                "/factor/service/api/v1/table/list",
                "/factor/service/api/v2/health",
                "/factor/service/api/v2/meta/schema",
                "/factor/service/api/v2/metadata",
                "/factor/service/api/v2/tables",
                "/factor/service/api/v2/table/detail",
                "/factor/service/api/v2/columns/search",
            ],
        )
        self.assertTrue(all("rotated-secret" not in repr(item) for item in transport.requests))

    def test_provider_errors_and_transport_failures_do_not_disclose_bearer_token(self) -> None:
        token = "new-secret-that-must-not-be-logged"
        client = FactorServiceClient(
            base_url="https://factor.example.internal",
            bearer_token=token,
            transport=FailingTransport(token),
        )
        self.assertNotIn(token, repr(client))
        with self.assertRaises(FactorServiceTransportError) as caught:
            client.v2_health()
        self.assertNotIn(token, str(caught.exception))
        self.assertNotIn("Bearer", str(caught.exception))

        business_error = FactorServiceClient(
            base_url="https://factor.example.internal",
            bearer_token=token,
            transport=StubTransport(
                response({"code": 2003, "message": f"Bearer {token} failed", "data": None})
            ),
        )
        with self.assertRaises(FactorServicePayloadError) as business_caught:
            business_error.v2_tables()
        self.assertNotIn(token, str(business_caught.exception))


class FactorServiceQueryTest(unittest.TestCase):
    def test_provider_financial_numbers_are_decoded_as_decimal_not_float(self) -> None:
        client = FactorServiceClient(
            base_url="https://factor.example.internal",
            bearer_token="secret",
            transport=StubTransport(
                response(
                    {
                        "code": 20000,
                        "message": "success",
                        "data": {
                            "rows": [
                                {
                                    "scode": "601089",
                                    "ths_total_assets_stock": 123456.78,
                                }
                            ]
                        },
                    }
                )
            ),
        )
        page = client.v2_table_query(
            table_name="balance_sheet",
            primary_key_name="scode",
            primary_key_values=("601089",),
            columns=("ths_total_assets_stock",),
            filter_date="report_period_end",
            start_date="2024-12-31",
            end_date="2024-12-31",
            limit=1,
            offset=0,
            allow_read_through_cache=True,
        )
        rows = page["rows"]
        self.assertIsInstance(rows, list)
        value = rows[0]["ths_total_assets_stock"]  # type: ignore[index]
        self.assertEqual(value, Decimal("123456.78"))
        self.assertNotIsInstance(value, float)

    def test_query_side_effect_requires_ack_and_uses_documented_contracts(self) -> None:
        transport = StubTransport(
            response(
                {
                    "code": 0,
                    "message": "success",
                    "data": [{"scode": "601089", "ths_total_assets_stock": 1}],
                }
            ),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": {
                        "table_name": "balance_sheet",
                        "rows": [{"scode": "601089", "ths_total_assets_stock": 1}],
                    },
                }
            ),
        )
        client = FactorServiceClient(
            base_url="http://10.21.31.242:30080",
            bearer_token=None,
            transport=transport,
        )

        with self.assertRaisesRegex(FactorServicePermissionError, "read-through"):
            client.v1_factor_query(
                scodes=("601089",),
                factors=("balance_sheet.ths_total_assets_stock",),
                report_period_end="2024-12-31",
                allow_read_through_cache=False,
            )
        with self.assertRaisesRegex(FactorServicePermissionError, "read-through"):
            client.v2_table_query(
                table_name="balance_sheet",
                primary_key_name="scode",
                primary_key_values=("601089",),
                columns=("ths_total_assets_stock",),
                filter_date="report_period_end",
                start_date="2024-12-31",
                end_date="2024-12-31",
                limit=1,
                offset=0,
                allow_read_through_cache=False,
            )
        self.assertEqual(transport.requests, [])

        v1_rows = client.v1_factor_query(
            scodes=("601089",),
            factors=("balance_sheet.ths_total_assets_stock",),
            report_period_end="2024-12-31",
            allow_read_through_cache=True,
        )
        page = client.v2_table_query(
            table_name="balance_sheet",
            primary_key_name="scode",
            primary_key_values=("601089",),
            columns=("ths_total_assets_stock",),
            filter_date="report_period_end",
            start_date="2024-12-31",
            end_date="2024-12-31",
            limit=1,
            offset=0,
            allow_read_through_cache=True,
        )

        self.assertEqual(v1_rows[0]["scode"], "601089")
        self.assertEqual(page["rows"][0]["scode"], "601089")  # type: ignore[index]
        self.assertEqual(transport.requests[0].json_body["scode"], ["601089"])
        self.assertEqual(transport.requests[1].json_body["limit"], 1)

    def test_count_and_query_require_primary_key_unless_metadata_allows_date_only(self) -> None:
        transport = StubTransport(
            response({"code": 20000, "message": "success", "data": {"count": 60}}),
            response({"code": 20000, "message": "success", "data": {"rows": []}}),
        )
        client = FactorServiceClient(
            base_url="https://factor.example.internal",
            bearer_token="secret",
            transport=transport,
        )
        with self.assertRaisesRegex(ValueError, "primary key"):
            client.v2_table_count(
                table_name="balance_sheet",
                primary_key_name=None,
                primary_key_values=(),
                filter_date="report_period_end",
                start_date="2024-01-01",
                end_date="2024-12-31",
                allow_date_only_query=False,
            )
        count = client.v2_table_count(
            table_name="ths_cn_money_supply_monthly",
            primary_key_name=None,
            primary_key_values=(),
            filter_date="period_end",
            start_date="2021-01-01",
            end_date="2026-06-30",
            allow_date_only_query=True,
        )
        self.assertEqual(count, 60)
        page = client.v2_table_query(
            table_name="ths_cn_money_supply_monthly",
            primary_key_name=None,
            primary_key_values=(),
            columns=("m2_end_value",),
            filter_date="period_end",
            start_date="2021-01-01",
            end_date="2026-06-30",
            limit=100,
            offset=0,
            allow_date_only_query=True,
            allow_read_through_cache=True,
        )
        self.assertEqual(page["rows"], [])
        self.assertNotIn("primary_key", transport.requests[0].json_body)

    def test_query_paginates_and_never_exceeds_5000_rows(self) -> None:
        transport = StubTransport(
            response({"code": 20000, "message": "success", "data": {"count": 3}}),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": {"rows": [{"scode": "600000"}, {"scode": "600001"}]},
                }
            ),
            response(
                {
                    "code": 20000,
                    "message": "success",
                    "data": {"rows": [{"scode": "600002"}]},
                }
            ),
        )
        client = FactorServiceClient(
            base_url="https://factor.example.internal",
            bearer_token="secret",
            transport=transport,
        )
        rows = tuple(
            client.iter_v2_table_rows(
                table_name="balance_sheet",
                primary_key_name="scode",
                primary_key_values=("600000", "600001", "600002"),
                columns=("ths_total_assets_stock",),
                filter_date="report_period_end",
                start_date="2024-01-01",
                end_date="2024-12-31",
                page_size=2,
                allow_date_only_query=False,
                allow_read_through_cache=True,
            )
        )
        self.assertEqual([row["scode"] for row in rows], ["600000", "600001", "600002"])
        self.assertEqual(
            [request.json_body.get("offset") for request in transport.requests[1:]],
            [0, 2],
        )
        with self.assertRaisesRegex(ValueError, "5000"):
            tuple(
                client.iter_v2_table_rows(
                    table_name="balance_sheet",
                    primary_key_name="scode",
                    primary_key_values=("600000",),
                    columns=(),
                    filter_date="report_period_end",
                    start_date="2024-01-01",
                    end_date="2024-12-31",
                    page_size=5001,
                    allow_date_only_query=False,
                    allow_read_through_cache=True,
                )
            )


if __name__ == "__main__":
    unittest.main()
