import os
import unittest
from unittest.mock import patch

from a_share_platform.application.settings import Environment, Settings


class SettingsTest(unittest.TestCase):
    def test_environment_values_are_explicit(self) -> None:
        self.assertEqual(
            {item.value for item in Environment},
            {"development", "test", "production"},
        )

    def test_test_environment_is_read_only_and_uses_distinct_database(self) -> None:
        settings = Settings.for_environment(Environment.TEST)
        self.assertTrue(settings.read_only)
        self.assertIn("_test", settings.database_url)
        self.assertIn(":55432/", settings.database_url)
        self.assertEqual(settings.object_store_bucket, "a-share-platform-test")
        self.assertEqual(settings.parquet_root, "data/parquet/test")

    def test_development_uses_the_compose_host_port(self) -> None:
        settings = Settings.for_environment(Environment.DEVELOPMENT)
        self.assertEqual(
            settings.database_url,
            "postgresql://a_share_platform_dev:local-only@localhost:55432/"
            "a_share_platform_dev",
        )

    def test_production_requires_explicit_database_and_object_store(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            ValueError, "production requires"
        ):
            Settings.from_environment(Environment.PRODUCTION)

    def test_secrets_are_loaded_from_environment_not_defaults(self) -> None:
        environment = {
            "ASP_DATABASE_URL": "postgresql://db.example/research",
            "ASP_OBJECT_STORE_URL": "https://objects.example",
            "ASP_OBJECT_STORE_BUCKET": "production-artifacts",
            "ASP_PARQUET_ROOT": "/srv/a-share-platform/parquet",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_environment(Environment.PRODUCTION)
        self.assertEqual(settings.database_url, environment["ASP_DATABASE_URL"])
        self.assertEqual(settings.object_store_url, environment["ASP_OBJECT_STORE_URL"])
        self.assertEqual(settings.object_store_bucket, environment["ASP_OBJECT_STORE_BUCKET"])
        self.assertEqual(settings.parquet_root, environment["ASP_PARQUET_ROOT"])


if __name__ == "__main__":
    unittest.main()
