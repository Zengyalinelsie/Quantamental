import unittest

from a_share_platform.adapters.providers.akshare_financial_profile import (
    AKSHARE_FINANCIAL_FIELD_BINDINGS_V1,
    akshare_financial_normalizers_v1,
)
from a_share_platform.domain.financial_sources import FinancialValueBasis
from a_share_platform.domain.metrics import StatementType


class AkShareFinancialProfileTest(unittest.TestCase):
    def test_v1_field_set_keeps_three_statements_and_metric_definitions_distinct(self) -> None:
        by_statement = {
            statement_type: tuple(
                binding
                for binding in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1
                if binding.statement_type is statement_type
            )
            for statement_type in StatementType
        }

        self.assertEqual({key: len(value) for key, value in by_statement.items()}, {
            StatementType.BALANCE_SHEET: 3,
            StatementType.INCOME_STATEMENT: 3,
            StatementType.CASH_FLOW_STATEMENT: 3,
        })
        self.assertEqual(
            tuple(binding.provider_field for binding in by_statement[StatementType.BALANCE_SHEET]),
            ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"),
        )
        self.assertEqual(
            tuple(binding.provider_field for binding in by_statement[StatementType.INCOME_STATEMENT]),
            ("TOTAL_OPERATE_INCOME", "OPERATE_PROFIT", "NETPROFIT"),
        )
        self.assertEqual(
            tuple(binding.provider_field for binding in by_statement[StatementType.CASH_FLOW_STATEMENT]),
            ("NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE"),
        )
        self.assertTrue(
            all(
                binding.value_basis is FinancialValueBasis.POINT_IN_TIME
                for binding in by_statement[StatementType.BALANCE_SHEET]
            )
        )
        self.assertTrue(
            all(
                binding.value_basis is FinancialValueBasis.CUMULATIVE_YTD
                for statement_type in (
                    StatementType.INCOME_STATEMENT,
                    StatementType.CASH_FLOW_STATEMENT,
                )
                for binding in by_statement[statement_type]
            )
        )
        self.assertEqual(len({item.metric_code for item in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1}), 9)
        self.assertIn(
            "income.total_operating_revenue",
            {item.metric_code for item in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1},
        )
        self.assertNotIn(
            "income.operating_revenue",
            {item.metric_code for item in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1},
        )

    def test_normalizer_registry_has_only_fields_for_each_statement(self) -> None:
        normalizers = akshare_financial_normalizers_v1()

        self.assertEqual(set(normalizers), set(StatementType))
        self.assertEqual(
            normalizers[StatementType.BALANCE_SHEET].provider_fields,
            ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"),
        )
        self.assertEqual(
            normalizers[StatementType.INCOME_STATEMENT].provider_fields,
            ("TOTAL_OPERATE_INCOME", "OPERATE_PROFIT", "NETPROFIT"),
        )
        self.assertEqual(
            normalizers[StatementType.CASH_FLOW_STATEMENT].provider_fields,
            ("NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE"),
        )


if __name__ == "__main__":
    unittest.main()
