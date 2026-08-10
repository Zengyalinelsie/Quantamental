import unittest

from a_share_platform.adapters.providers.factor_service_probe import (
    ProbeStatus,
    run_financial_qualification_probe,
)


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, name: str, value: object) -> object:
        self.calls.append(name)
        return value

    def v1_health(self) -> object:
        return self._record("v1_health", {"status": "ok"})

    def v1_factor_list(self, **kwargs: object) -> object:
        return self._record("v1_factor_list", ({"factor_name": "a"},))

    def v1_table_list(self) -> object:
        return self._record("v1_table_list", ({"table_name": "a"},))

    def v1_factor_query(self, **kwargs: object) -> object:
        return self._record("v1_factor_query", ({"scode": "601089"},))

    def v2_health(self) -> object:
        return self._record("v2_health", {"status": "ok"})

    def v2_meta_schema(self) -> object:
        return self._record("v2_meta_schema", {"table_name": "name"})

    def v2_metadata(self, **kwargs: object) -> object:
        return self._record("v2_metadata", {"prompt_version": "v1"})

    def v2_tables(self, **kwargs: object) -> object:
        return self._record("v2_tables", ({"table_name": "balance_sheet"},))

    def v2_table_detail(self, table_name: str) -> object:
        return self._record(f"v2_table_detail:{table_name}", {"table_name": table_name})

    def v2_columns_search(self, **kwargs: object) -> object:
        table_name = str(kwargs["table_name"])
        return self._record(f"v2_columns_search:{table_name}", ())

    def v2_table_count(self, **kwargs: object) -> object:
        table_name = str(kwargs["table_name"])
        return self._record(f"v2_table_count:{table_name}", 1)

    def v2_table_query(self, **kwargs: object) -> object:
        table_name = str(kwargs["table_name"])
        return self._record(f"v2_table_query:{table_name}", {"rows": [{"scode": "601089"}]})


class FactorServiceProbeTest(unittest.TestCase):
    def test_metadata_probe_covers_every_endpoint_and_skips_query_without_ack(self) -> None:
        client = RecordingClient()
        results = run_financial_qualification_probe(
            client,  # type: ignore[arg-type]
            symbol="601089",
            report_period_end="2024-12-31",
            allow_read_through_cache=False,
        )
        by_name = {result.operation: result for result in results}

        self.assertEqual(by_name["v1.factor.query"].status, ProbeStatus.SKIPPED)
        self.assertEqual(by_name["v2.table.query.balance_sheet"].status, ProbeStatus.SKIPPED)
        self.assertNotIn("v1_factor_query", client.calls)
        self.assertFalse(any(call.startswith("v2_table_query:") for call in client.calls))
        self.assertEqual(
            {call for call in client.calls if call.startswith("v2_table_detail:")},
            {
                "v2_table_detail:balance_sheet",
                "v2_table_detail:income_statement",
                "v2_table_detail:cash_flow",
            },
        )
        self.assertEqual(
            {call for call in client.calls if call.startswith("v2_table_count:")},
            {
                "v2_table_count:balance_sheet",
                "v2_table_count:income_statement",
                "v2_table_count:cash_flow",
            },
        )

    def test_explicit_ack_runs_minimal_queries_for_all_three_statements(self) -> None:
        client = RecordingClient()
        results = run_financial_qualification_probe(
            client,  # type: ignore[arg-type]
            symbol="601089",
            report_period_end="2024-12-31",
            allow_read_through_cache=True,
        )
        failed = [result for result in results if result.status is not ProbeStatus.PASSED]
        self.assertEqual(failed, [])
        self.assertIn("v1_factor_query", client.calls)
        self.assertEqual(
            {call for call in client.calls if call.startswith("v2_table_query:")},
            {
                "v2_table_query:balance_sheet",
                "v2_table_query:income_statement",
                "v2_table_query:cash_flow",
            },
        )


if __name__ == "__main__":
    unittest.main()
