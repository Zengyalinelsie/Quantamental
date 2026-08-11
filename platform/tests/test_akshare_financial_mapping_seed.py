import unittest

from a_share_platform.adapters.memory.metrics import InMemoryMetricRegistryRepository
from a_share_platform.application.akshare_financial_mapping_seed import (
    AKSHARE_CURRENT_MAPPING_VERSION_ID,
    akshare_current_mapping_package_v1,
    install_akshare_current_mapping_v1,
)
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.metrics import MappingUseScope


class AkShareFinancialMappingSeedTest(unittest.TestCase):
    def test_package_is_deterministic_and_current_research_only(self) -> None:
        first = akshare_current_mapping_package_v1()
        repeated = akshare_current_mapping_package_v1()

        self.assertEqual(first, repeated)
        self.assertEqual(first.version.mapping_version_id, AKSHARE_CURRENT_MAPPING_VERSION_ID)
        self.assertEqual(first.version.provider_id, "akshare")
        self.assertTrue(first.version.content_hash.startswith("sha256:"))
        self.assertEqual(len(first.metrics), 9)
        self.assertEqual(len(first.mappings), 9)
        self.assertEqual(len({item.metric_code for item in first.metrics}), 9)
        self.assertEqual(len({item.mapping_id for item in first.mappings}), 9)
        self.assertTrue(
            all(
                item.allowed_use_scopes == {MappingUseScope.CURRENT_RESEARCH}
                for item in first.mappings
            )
        )
        self.assertIn(
            "income.total_operating_revenue",
            {item.metric_code for item in first.metrics},
        )
        self.assertNotIn(
            "income.operating_revenue",
            {item.metric_code for item in first.mappings},
        )

    def test_install_is_idempotent_in_the_metric_registry(self) -> None:
        repository = InMemoryMetricRegistryRepository()
        service = MetricRegistryService(repository)

        first = install_akshare_current_mapping_v1(service)
        repeated = install_akshare_current_mapping_v1(service)

        self.assertEqual(first, repeated)
        self.assertEqual(
            repository.get_mapping_version(AKSHARE_CURRENT_MAPPING_VERSION_ID),
            first.version,
        )
        for mapping in first.mappings:
            self.assertEqual(
                repository.find_mappings(
                    provider_id="akshare",
                    statement_type=mapping.statement_type,
                    source_field=mapping.source_field,
                    mapping_version_id=AKSHARE_CURRENT_MAPPING_VERSION_ID,
                ),
                (mapping,),
            )


if __name__ == "__main__":
    unittest.main()
