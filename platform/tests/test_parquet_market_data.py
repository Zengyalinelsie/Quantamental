import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from a_share_platform.adapters.parquet.market_data import ParquetMarketDataStore
from tests.market_data_fixtures import build_market_data_fixture


class ParquetMarketDataStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_market_data_fixture()

    def test_writes_real_partitioned_parquet_and_queries_raw_bars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ParquetMarketDataStore(Path(directory))
            written = store.write_bars(self.catalog.bars)

            self.assertEqual(len(written), 2)
            expected = (
                Path(directory)
                / "daily_bars"
                / "dataset_version_id=dataset%3Ap2-contract-fixture%3Av1"
                / "exchange=XSHE"
                / "year=2018"
                / "part-00000.parquet"
            )
            self.assertIn(expected, written)
            payload = expected.read_bytes()
            self.assertEqual(payload[:4], b"PAR1")
            self.assertEqual(payload[-4:], b"PAR1")

            rows = store.query_bars(
                "listing:cmre:xshe",
                start=date(2018, 1, 1),
                end=date(2018, 1, 3),
                dataset_version_id="dataset:p2-contract-fixture:v1",
            )
            self.assertEqual(rows, (self.catalog.bars[0],))

    def test_adjustment_factors_are_independent_parquet_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ParquetMarketDataStore(Path(directory))
            store.write_bars(self.catalog.bars)
            written = store.write_adjustment_factors(self.catalog.factors)
            self.assertEqual(len(written), 1)
            factors = store.query_adjustment_factors(
                "listing:cmre:xshe",
                start=date(2018, 1, 2),
                end=date(2018, 1, 2),
                dataset_version_id="dataset:p2-contract-fixture:v1",
            )
            self.assertEqual(factors, self.catalog.factors)
            self.assertEqual(
                store.adjusted_close(
                    "listing:cmre:xshe",
                    date(2018, 1, 2),
                    dataset_version_id="dataset:p2-contract-fixture:v1",
                ),
                self.catalog.adjusted_close("listing:cmre:xshe", date(2018, 1, 2)),
            )

    def test_existing_partition_is_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ParquetMarketDataStore(Path(directory))
            store.write_bars((self.catalog.bars[0],))
            with self.assertRaisesRegex(FileExistsError, "partition already exists"):
                store.write_bars((self.catalog.bars[0],))

    def test_ensure_bars_resumes_identical_partition_but_rejects_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ParquetMarketDataStore(Path(directory))
            first = store.ensure_bars((self.catalog.bars[0],))
            resumed = store.ensure_bars((self.catalog.bars[0],))
            self.assertEqual(resumed, first)

            conflicting = replace(self.catalog.bars[0], amount=Decimal(1))
            with self.assertRaisesRegex(FileExistsError, "content differs"):
                store.ensure_bars((conflicting,))

    def test_empty_store_query_is_explicitly_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ParquetMarketDataStore(Path(directory))
            self.assertEqual(
                store.query_bars(
                    "listing:missing",
                    start=date(2018, 1, 1),
                    end=date(2018, 1, 2),
                    dataset_version_id="dataset:missing:v1",
                ),
                (),
            )


if __name__ == "__main__":
    unittest.main()
