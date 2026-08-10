import unittest
from datetime import UTC, date, datetime, timedelta

from a_share_platform.adapters.postgres.financial_facts import (
    PostgresFinancialFactRepository,
)
from a_share_platform.domain.metrics import MetricUnit, StatementType
from a_share_platform.domain.pit import (
    DataQualityState,
    DataTrustState,
    FactObservation,
    FinancialPeriodType,
)

KNOWN = datetime(2024, 3, 28, 10, 5, tzinfo=UTC)


def observation(*, known_to: datetime | None = None) -> FactObservation:
    return FactObservation(
        fact_id="fact:cninfo:revenue:2023:r0:system1",
        company_id="company:000001",
        security_id="security:000001-szse",
        metric_code="revenue",
        value=100.0,
        unit=MetricUnit.CURRENCY,
        currency="CNY",
        report_period_end=date(2023, 12, 31),
        period_type=FinancialPeriodType.ANNUAL,
        statement_type=StatementType.INCOME_STATEMENT,
        announced_at=datetime(2024, 3, 28, 10, tzinfo=UTC),
        available_at=datetime(2024, 3, 28, 10, 1, tzinfo=UTC),
        known_from=KNOWN,
        known_to=known_to,
        revision_sequence=0,
        provider_id="provider:cninfo",
        source_field="revenue",
        raw_object_hash="sha256:" + "a" * 64,
        trust_state=DataTrustState.PIT_VERIFIED,
        quality_state=DataQualityState.PASSED,
        mapping_version_id="metric-mapping:cninfo:v1",
        source_object_id="raw:cninfo:report:v1",
        dataset_version_id="dataset:financials:v1",
        quality_issue_ids=(),
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if query.lstrip().startswith("UPDATE") and self.rows:
            updated = list(self.rows[0])
            updated[13] = params[0]
            return FakeResult([tuple(updated)])
        return FakeResult(self.rows if query.lstrip().startswith("SELECT") else [])


class PostgresFinancialFactRepositoryTest(unittest.TestCase):
    def test_insert_preserves_all_fact_dimensions_and_is_immutable(self) -> None:
        connection = FakeConnection()
        repository = PostgresFinancialFactRepository(connection)
        value = observation()
        repository.save(value)
        query, params = connection.calls[-1]
        self.assertIn("INSERT INTO financial_fact_observations", query)
        self.assertIn("ON CONFLICT (fact_id) DO NOTHING", query)
        self.assertEqual(params[0], value.fact_id)
        self.assertEqual(params[1], value.company_id)
        self.assertEqual(params[17], value.raw_object_hash)
        self.assertEqual(params[18], DataTrustState.PIT_VERIFIED.value)
        self.assertEqual(params[19], DataQualityState.PASSED.value)

    def test_round_trip_and_system_interval_close_are_explicit(self) -> None:
        value = observation()
        row = (
            value.fact_id,
            value.company_id,
            value.security_id,
            value.metric_code,
            value.value,
            value.unit.value,
            value.currency,
            value.report_period_end,
            value.period_type.value,
            value.statement_type.value,
            value.announced_at,
            value.available_at,
            value.known_from,
            value.known_to,
            value.revision_sequence,
            value.provider_id,
            value.source_field,
            value.raw_object_hash,
            value.trust_state.value,
            value.quality_state.value,
            value.mapping_version_id,
            value.source_object_id,
            value.dataset_version_id,
            list(value.quality_issue_ids),
        )
        connection = FakeConnection([row])
        repository = PostgresFinancialFactRepository(connection)
        restored = repository.get(value.fact_id)
        self.assertEqual(restored, value)

        closed_at = KNOWN + timedelta(days=1)
        repository.close_system_interval(value.fact_id, closed_at)
        query, params = connection.calls[-1]
        self.assertIn("UPDATE financial_fact_observations", query)
        self.assertIn("known_to IS NULL", query)
        self.assertEqual(params, (closed_at, value.fact_id, closed_at))

    def test_find_uses_complete_economic_identity(self) -> None:
        value = observation()
        connection = FakeConnection()
        repository = PostgresFinancialFactRepository(connection)
        repository.find(
            company_id=value.company_id,
            security_id=value.security_id,
            metric_code=value.metric_code,
            report_period_end=value.report_period_end,
            period_type=value.period_type,
            statement_type=value.statement_type,
        )
        query, params = connection.calls[-1]
        self.assertIn("company_id = %s", query)
        self.assertIn("period_type = %s", query)
        self.assertIn("statement_type = %s", query)
        self.assertEqual(params[-2:], (value.period_type.value, value.statement_type.value))


if __name__ == "__main__":
    unittest.main()
