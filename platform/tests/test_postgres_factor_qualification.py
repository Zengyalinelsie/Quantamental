import unittest
from contextlib import AbstractContextManager
from datetime import date
from typing import Self

from a_share_platform.adapters.postgres.factor_qualification import (
    PostgresFactorQualificationRepository,
    PostgresFactorQualificationSource,
)
from a_share_platform.application.factor_qualification import FactorQualificationService
from a_share_platform.domain.factor_readiness import FactorDataRole
from a_share_platform.domain.pit import DataTrustState
from tests.test_factor_qualification_audit import (
    END,
    START,
    environment,
    request,
    snapshot,
    targets,
)


def _json_value(value: object) -> object:
    return value.obj if hasattr(value, "obj") else value


class Result:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class Transaction:
    def __init__(self, connection: "SourceConnection | RepositoryConnection") -> None:
        self.connection = connection

    def __enter__(self) -> Self:
        self.connection.transactions += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class SourceConnection(AbstractContextManager["SourceConnection"]):
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.transactions = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def transaction(self) -> Transaction:
        return Transaction(self)

    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result:
        self.calls.append((query, params))
        sql = " ".join(query.split())
        observed = (
            10,
            10,
            START,
            END,
            ["dataset:real:v1"],
            ["source:real:v1"],
        )
        unavailable = (0, 0, None, None, None, None)
        if sql == "SET TRANSACTION READ ONLY":
            return Result()
        if "COUNT(memberships.listing_id) AS member_count" in sql:
            return Result(
                [
                    ("universe:csi500:current:v1", "dataset:csi500:v1", 500),
                    ("universe:csi300:current:v1", "dataset:csi300:v1", 300),
                ]
            )
        if "JOIN financial_fact_observations AS facts" in sql:
            return Result(
                [
                    (
                        12,
                        2,
                        date(2025, 3, 31),
                        date(2025, 3, 31),
                        ["dataset:p3-pit-fixture-pack-v1"],
                        ["provider:fixture"],
                    )
                ]
            )
        if "FROM universe_versions AS versions" in sql:
            return Result([(29600, 800, START, END, ["dataset:universe:v1"], ["csi"])])
        if "JOIN industry_memberships AS observed" in sql:
            return Result([unavailable])
        if "FROM industry_memberships" in sql:
            return Result(
                [(1258, date(2026, 8, 10), date(2026, 8, 11))]
            )
        if "JOIN daily_market_states AS observed" in sql:
            return Result([(7177, 30, START, date(2018, 12, 31), *observed[4:])])
        if "JOIN share_capital_observations AS observed" in sql:
            return Result([(24951, 800, START, END, *observed[4:])])
        if "FROM covered_action_universe" in sql:
            return Result([(8059, 800, START, END, *observed[4:])])
        if "FROM timing_benchmark_bars" in sql:
            return Result([unavailable])
        if "JOIN research_labels AS labels" in sql:
            return Result([unavailable])
        if "SELECT DISTINCT metric_code" in sql:
            return Result(
                [
                    ("income.net_profit_parent",),
                    ("income.operating_revenue",),
                ]
            )
        if "FROM UNNEST" in sql:
            return Result([(feature_id, 0) for feature_id in sorted(params[0])])
        raise AssertionError(f"unexpected qualification query: {sql}")


class SourceFactory:
    def __init__(self, connection: SourceConnection) -> None:
        self.connection = connection

    def __call__(self) -> AbstractContextManager[SourceConnection]:
        return self.connection


class RepositoryConnection(AbstractContextManager["RepositoryConnection"]):
    def __init__(self) -> None:
        self.transactions = 0
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.datasets: dict[str, tuple[object, ...]] = {}
        self.reports: dict[str, tuple[object, ...]] = {}
        self.audits: dict[str, tuple[object, ...]] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def transaction(self) -> Transaction:
        return Transaction(self)

    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result:
        self.calls.append((query, params))
        sql = " ".join(query.split())
        if sql.startswith("INSERT INTO dataset_versions"):
            self.datasets.setdefault(
                str(params[0]),
                (*params[:4], _json_value(params[4])),
            )
            return Result()
        if "FROM dataset_versions WHERE dataset_version_id" in sql:
            row = self.datasets.get(str(params[0]))
            return Result([] if row is None else [row])
        if sql.startswith("INSERT INTO factor_validation_reports"):
            self.reports.setdefault(
                str(params[0]),
                (params[1], params[3], False),
            )
            return Result()
        if "FROM factor_validation_reports WHERE report_id" in sql:
            row = self.reports.get(str(params[0]))
            return Result([] if row is None else [row])
        if sql.startswith("INSERT INTO factor_qualification_audits"):
            self.audits.setdefault(
                str(params[0]),
                (params[1], params[8], params[9], params[11]),
            )
            return Result()
        if "FROM factor_qualification_audits WHERE audit_id" in sql:
            row = self.audits.get(str(params[0]))
            return Result([] if row is None else [row])
        if sql.startswith("INSERT INTO lineage_edges"):
            return Result()
        raise AssertionError(f"unexpected qualification persistence query: {sql}")


class RepositoryFactory:
    def __init__(self, connection: RepositoryConnection) -> None:
        self.connection = connection

    def __call__(self) -> AbstractContextManager[RepositoryConnection]:
        return self.connection


class ExperimentRepository:
    def __init__(self) -> None:
        self.runs: dict[str, object] = {}

    def save_run(self, value):  # type: ignore[no-untyped-def]
        existing = self.runs.get(value.run_id)
        if existing is not None and existing != value:
            raise RuntimeError("immutable experiment conflict")
        self.runs[value.run_id] = value
        return value


class PostgresFactorQualificationTest(unittest.TestCase):
    def test_source_uses_read_only_transaction_and_parses_all_eight_roles(self) -> None:
        connection = SourceConnection()
        source = PostgresFactorQualificationSource(SourceFactory(connection))

        value = source.inspect(request(), targets())

        self.assertEqual(connection.transactions, 1)
        self.assertEqual(connection.calls[0][0].strip(), "SET TRANSACTION READ ONLY")
        self.assertEqual({item.role for item in value.role_evidence}, set(FactorDataRole))
        financial = next(
            item
            for item in value.role_evidence
            if item.role is FactorDataRole.FINANCIAL_FACT
        )
        self.assertIs(financial.trust_state, DataTrustState.PIT_VERIFIED)
        self.assertEqual(financial.observed_entity_count, 2)
        self.assertEqual(
            [item.role for item in value.role_evidence if item.row_count == 0],
            [
                FactorDataRole.BENCHMARK_BAR,
                FactorDataRole.FORWARD_RETURN_LABEL,
                FactorDataRole.INDUSTRY_CLASSIFICATION,
            ],
        )
        self.assertFalse(
            any("UPDATE" in query or "INSERT" in query for query, _ in connection.calls)
        )
        industry = next(
            item
            for item in value.role_evidence
            if item.role is FactorDataRole.INDUSTRY_CLASSIFICATION
        )
        self.assertTrue(
            any(
                "current-only rows=1258" in warning
                and "2026-08-10..2026-08-11" in warning
                for warning in industry.warnings
            )
        )

    def test_corporate_action_coverage_includes_successful_explicit_zero_evidence(self) -> None:
        query, parameters = PostgresFactorQualificationSource._role_query(
            request(),
            FactorDataRole.CORPORATE_ACTION,
        )

        self.assertIn("covered_action_universe", query)
        self.assertIn("ingestion_checkpoints", query)
        self.assertIn("checkpoints.status = 'succeeded'", query)
        self.assertIn("WHERE checkpoints.processed_rows = 0", query)
        self.assertIn("COUNT(*) FROM covered_action_universe", query)
        self.assertNotIn("COUNT(DISTINCT target.listing_id)", query)
        self.assertEqual(parameters[:2], (request().evaluated_at.date(),) * 2)

    def test_benchmark_query_does_not_assume_a_nonexistent_surrogate_key(self) -> None:
        query, _ = PostgresFactorQualificationSource._role_query(
            request(),
            FactorDataRole.BENCHMARK_BAR,
        )

        self.assertIn("COUNT(*)", query)
        self.assertNotIn("bar_id", query)
        self.assertIn("provider_id", query)
        self.assertNotIn("source_id", query)

    def test_repository_save_is_append_only_idempotent_and_binds_lineage(self) -> None:
        audit = FactorQualificationService(
            source=type("Source", (), {"inspect": lambda _self, *_args: snapshot()})(),
            repository=type("Unused", (), {})(),
        ).evaluate(
            request=request(),
            targets=targets(),
            code_sha="1" * 40,
            environment=environment(),
        ).audits[0]
        connection = RepositoryConnection()
        experiments = ExperimentRepository()
        repository = PostgresFactorQualificationRepository(
            RepositoryFactory(connection),
            experiments,  # type: ignore[arg-type]
        )

        self.assertTrue(repository.save(audit))
        self.assertFalse(repository.save(audit))

        self.assertEqual(len(connection.datasets), len(FactorDataRole))
        self.assertEqual(len(connection.reports), 1)
        self.assertEqual(len(connection.audits), 1)
        self.assertEqual(len(experiments.runs), 1)
        self.assertTrue(any("INSERT INTO lineage_edges" in query for query, _ in connection.calls))
        self.assertFalse(any("UPDATE" in query or "DELETE" in query for query, _ in connection.calls))


if __name__ == "__main__":
    unittest.main()
