import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from a_share_platform.adapters.memory.valuation_inputs import (
    MemoryValuationImprovementInputSource,
)
from a_share_platform.adapters.postgres.valuation_input_qualification import (
    FrozenPriceObservation,
    PostgresValuationInputQualificationSource,
    ValuationInputQualificationUnavailable,
)
from a_share_platform.application.valuation_improvement import (
    ValuationImprovementOrchestrationService,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import ValuationMetric
from a_share_platform.domain.valuation_input_qualification import (
    ValuationInputDomain,
    ValuationInputQualificationRequest,
)
from a_share_platform.domain.valuation_models import (
    UnavailableAnalystRevisionInput,
    UnavailableFundamentalAnchorInput,
    ValuationModelStatus,
)
from a_share_platform.domain.valuation_scenarios import ValuationScenarioStatus
from a_share_platform.ports.valuation_inputs import (
    VALUATION_INPUT_BUNDLE_V2,
    ValuationImprovementInputRequest,
)
from tests.test_valuation_improvement_service import DECISION_TIME, scenario_definition

HASH = "sha256:" + "a" * 64
FINANCIAL_DATASET = "dataset:financial:qualified:v1"
PRICE_DATASET = "dataset:price:qualified:v1"
COMPARABLE_DATASET = "dataset:industry:qualified:v1"
CAPITAL_DATASET = "dataset:share-capital:qualified:v1"


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def financial_rows(trust: DataTrustState) -> list[tuple[object, ...]]:
    periods = (date(2023, 12, 31), date(2024, 3, 31), date(2024, 12, 31), date(2025, 3, 31))
    metrics = (
        "income.total_operating_revenue",
        "income.net_profit",
        "cash_flow.net_operating_cash_flow",
        "balance.total_equity",
    )
    values = {
        "income.total_operating_revenue": ("80", "20", "100", "30"),
        "income.net_profit": ("8", "2", "12", "3"),
        "cash_flow.net_operating_cash_flow": ("7", "1", "11", "2"),
        "balance.total_equity": ("150", "155", "180", "200"),
    }
    return [
        (
            f"financial:{metric}:{period.isoformat()}",
            metric,
            period,
            FINANCIAL_DATASET,
            "provider:financial:v1",
            DECISION_TIME - timedelta(days=1),
            HASH,
            trust.value,
            values[metric][period_index],
            "currency",
            "CNY",
            ("point_in_time" if metric == "balance.total_equity" else "ttm"),
            "mapping:financial:v1",
            f"raw:{metric}:{period.isoformat()}",
        )
        for metric in metrics
        for period_index, period in enumerate(periods)
    ]


def comparable_rows(trust: DataTrustState) -> list[tuple[object, ...]]:
    return [
        (
            f"industry:{index}",
            security_id,
            "taxonomy:csic",
            "C30",
            COMPARABLE_DATASET,
            "provider:industry:v1",
            trust.value,
            DECISION_TIME - timedelta(days=2),
            HASH,
        )
        for index, security_id in enumerate(
            ("security:000001.XSHE", "security:000002.XSHE", "security:000003.XSHE"),
            start=1,
        )
    ]


class FakeConnection:
    def __init__(
        self,
        *,
        financial: list[tuple[object, ...]],
        price_catalog: list[tuple[object, ...]],
        comparables: list[tuple[object, ...]],
    ) -> None:
        self.financial = financial
        self.price_catalog = price_catalog
        self.comparables = comparables
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.operational_error = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if self.operational_error:
            raise psycopg.OperationalError("database unavailable")
        normalized = " ".join(query.split())
        if "financial input rows" in normalized:
            return FakeResult(self.financial)
        if "price input partitions" in normalized:
            return FakeResult(self.price_catalog)
        if "comparable input rows" in normalized:
            return FakeResult(self.comparables)
        if "subject industry code" in normalized:
            return FakeResult([("C30",)])
        return FakeResult()


def price_catalog(trust: DataTrustState) -> list[tuple[object, ...]]:
    return [
        (
            "listing:XSHE:000001",
            "XSHE",
            "partition:price:v1",
            PRICE_DATASET,
            "file:///private/tmp/qualified-price.parquet",
            trust.value,
            DECISION_TIME - timedelta(hours=1),
            "provider:price:v1",
            HASH,
            "share-capital:000001:2025-04-30",
            Decimal(100),
            CAPITAL_DATASET,
            "provider:share-capital:v1",
            DECISION_TIME - timedelta(hours=2),
            trust.value,
            HASH,
        )
    ]


def request(
    *,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
) -> ValuationInputQualificationRequest:
    return ValuationInputQualificationRequest(
        security_id="security:000001.XSHE",
        decision_time=DECISION_TIME,
        data_mode=data_mode,
        requested_trust_state=trust_state,
        max_price_age_days=7,
    )


class PostgresValuationInputQualificationSourceTest(unittest.TestCase):
    def source(
        self,
        *,
        trust: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
        comparables: list[tuple[object, ...]] | None = None,
        price_date: date | None = None,
    ) -> tuple[PostgresValuationInputQualificationSource, FakeConnection]:
        connection = FakeConnection(
            financial=financial_rows(trust),
            price_catalog=price_catalog(trust),
            comparables=comparable_rows(trust) if comparables is None else comparables,
        )

        @contextmanager
        def factory() -> Iterator[FakeConnection]:
            yield connection

        def reader(
            storage_uri: str,
            listing_id: str,
            decision_date: date,
            dataset_version_id: str,
            available_at,
            content_hash: str,
        ) -> FrozenPriceObservation | None:
            self.assertEqual(storage_uri, "file:///private/tmp/qualified-price.parquet")
            self.assertEqual(listing_id, "listing:XSHE:000001")
            self.assertEqual(dataset_version_id, PRICE_DATASET)
            return FrozenPriceObservation(
                observation_id="price:000001:2025-04-30",
                listing_id=listing_id,
                session_date=price_date or DECISION_TIME.date(),
                close=Decimal(10),
                currency="CNY",
                dataset_version_id=dataset_version_id,
                source_id="provider:price:v1",
                trust_state=trust,
                available_at=available_at,
                content_hash=content_hash,
            )

        return PostgresValuationInputQualificationSource(factory, price_reader=reader), connection

    def test_current_three_domain_evidence_is_read_only_complete_and_qualified(self) -> None:
        source, connection = self.source()
        result = source.inspect(request())

        self.assertTrue(result.is_qualified)
        self.assertEqual(result.blockers, ())
        self.assertEqual(
            result.dataset_version_ids,
            tuple(
                sorted(
                    (
                        CAPITAL_DATASET,
                        COMPARABLE_DATASET,
                        FINANCIAL_DATASET,
                        PRICE_DATASET,
                    )
                )
            ),
        )
        self.assertEqual(
            {item.domain for item in result.domain_evidence},
            set(ValuationInputDomain),
        )
        sql = "\n".join(query for query, _ in connection.calls)
        self.assertIn("observation.normalized_current_financial_observations", sql)
        self.assertNotIn("canonical.financial_fact_observations", sql)
        self.assertIn("SET TRANSACTION READ ONLY", sql)

    def test_strict_path_uses_only_pit_bitemporal_facts_and_exact_trust(self) -> None:
        source, connection = self.source(trust=DataTrustState.PIT_VERIFIED)
        strict_request = request(
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
        )
        result = source.inspect(strict_request)
        compiled = source.compile(strict_request)

        self.assertTrue(result.is_qualified)
        self.assertIsNotNone(compiled.bundle)
        sql = "\n".join(query for query, _ in connection.calls)
        self.assertIn("canonical.financial_fact_observations", sql)
        self.assertIn("trust_state = 'pit_verified'", sql)
        self.assertIn("known_from <=", sql)
        self.assertIn("available_at <=", sql)
        self.assertNotIn("observation.normalized_current_financial_observations", sql)
        self.assertIn("industry.available_at <=", sql)

    def test_qualified_real_rows_compile_a_deterministic_partial_bundle_without_fake_inputs(
        self,
    ) -> None:
        source, _ = self.source()
        compiled = source.compile(request())

        self.assertTrue(compiled.qualification.is_qualified)
        self.assertIsNotNone(compiled.bundle)
        frozen = compiled.bundle
        assert frozen is not None
        self.assertEqual(frozen.document_schema_version, VALUATION_INPUT_BUNDLE_V2)
        self.assertIsNone(frozen.market_implied)
        self.assertIsNone(frozen.fundamental_anchor)
        suite = frozen.valuation_model_suite_inputs
        assert suite is not None
        self.assertTrue(all(item.median_value is None for item in suite.relative_references))
        self.assertTrue(all(item.unavailable_reasons for item in suite.relative_references))
        self.assertIsInstance(
            suite.fundamental_anchor_input,
            UnavailableFundamentalAnchorInput,
        )
        self.assertIsInstance(
            suite.analyst_revision_input,
            UnavailableAnalystRevisionInput,
        )
        self.assertNotIn("provider:analyst:unavailable", repr(suite.analyst_revision_input))
        self.assertIn(":v2", frozen.bundle_version_id)
        self.assertEqual(
            frozen.dataset_version_ids,
            tuple(
                sorted(
                    (
                        CAPITAL_DATASET,
                        COMPARABLE_DATASET,
                        FINANCIAL_DATASET,
                        PRICE_DATASET,
                    )
                )
            ),
        )
        metrics = {item.metric: item for item in frozen.valuation_metric_inputs}
        self.assertEqual(metrics[ValuationMetric.EARNINGS_TO_PRICE].numerator, Decimal("0.03"))
        self.assertEqual(metrics[ValuationMetric.EARNINGS_TO_PRICE].denominator, Decimal(10))
        self.assertEqual(metrics[ValuationMetric.BOOK_TO_PRICE].numerator, Decimal(2))
        self.assertIsNone(metrics[ValuationMetric.FREE_CASH_FLOW_YIELD].numerator)
        self.assertTrue(all(item.level is None for item in frozen.improvement_inputs))
        self.assertTrue(all(item.unavailable_reasons for item in frozen.improvement_inputs))
        self.assertTrue(all(item.driver_lower is None for item in frozen.scenario_inputs))
        analysis = ValuationImprovementOrchestrationService(
            MemoryValuationImprovementInputSource((frozen,)),
            scenario_definition(),
        ).evaluate(
            ValuationImprovementInputRequest(
                security_id=frozen.security_id,
                decision_time=frozen.decision_time,
                data_mode=frozen.data_mode,
                trust_state=frozen.trust_state,
                bundle_version_id=frozen.bundle_version_id,
            )
        )
        self.assertIs(
            analysis.fundamental_anchor_model_result.status,
            ValuationModelStatus.UNAVAILABLE,
        )
        self.assertIs(
            analysis.implied_expectation_result.status,
            ValuationModelStatus.UNAVAILABLE,
        )
        self.assertEqual(
            {
                item.status
                for item in analysis.scenario_result.scenario_results
            },
            {ValuationScenarioStatus.UNAVAILABLE},
        )

    def test_stale_price_or_unversioned_comparables_fail_closed_without_zero_fill(self) -> None:
        stale_source, _ = self.source(price_date=DECISION_TIME.date() - timedelta(days=8))
        stale = stale_source.inspect(request())
        self.assertFalse(stale.is_qualified)
        self.assertTrue(any("stale" in blocker for blocker in stale.blockers))

        missing_source, _ = self.source(comparables=[])
        missing = missing_source.inspect(request())
        self.assertFalse(missing.is_qualified)
        comparable = next(
            item
            for item in missing.domain_evidence
            if item.domain is ValuationInputDomain.COMPARABLE
        )
        self.assertEqual(comparable.observation_count, 0)
        self.assertTrue(comparable.blockers)

    def test_operational_failure_is_explicit_and_has_no_runtime_fixture_fallback(self) -> None:
        source, connection = self.source()
        connection.operational_error = True
        with self.assertRaisesRegex(ValuationInputQualificationUnavailable, "PostgreSQL"):
            source.inspect(request())


if __name__ == "__main__":
    unittest.main()
