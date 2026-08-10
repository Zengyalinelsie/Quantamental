"""Explicit environment configuration with no production secret defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


@dataclass(frozen=True)
class Settings:
    environment: Environment
    database_url: str
    object_store_url: str
    object_store_bucket: str
    parquet_root: str
    read_only: bool = True

    @classmethod
    def for_environment(cls, environment: Environment) -> Settings:
        environment = Environment(environment)
        if environment is Environment.PRODUCTION:
            raise ValueError("production requires explicit environment configuration")
        suffix = "test" if environment is Environment.TEST else "dev"
        return cls(
            environment=environment,
            database_url=(
                f"postgresql://a_share_platform_{suffix}:local-only@localhost:55432/"
                f"a_share_platform_{suffix}"
            ),
            object_store_url="http://localhost:9000",
            object_store_bucket=f"a-share-platform-{suffix}",
            parquet_root=f"data/parquet/{suffix}",
        )

    @classmethod
    def from_environment(
        cls,
        environment: Environment | str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> Settings:
        values = os.environ if environ is None else environ
        selected = Environment(environment or values.get("ASP_ENVIRONMENT", "development"))
        if selected is not Environment.PRODUCTION:
            defaults = cls.for_environment(selected)
            return cls(
                environment=selected,
                database_url=values.get("ASP_DATABASE_URL", defaults.database_url),
                object_store_url=values.get("ASP_OBJECT_STORE_URL", defaults.object_store_url),
                object_store_bucket=values.get(
                    "ASP_OBJECT_STORE_BUCKET", defaults.object_store_bucket
                ),
                parquet_root=values.get("ASP_PARQUET_ROOT", defaults.parquet_root),
            )
        required = (
            "ASP_DATABASE_URL",
            "ASP_OBJECT_STORE_URL",
            "ASP_OBJECT_STORE_BUCKET",
            "ASP_PARQUET_ROOT",
        )
        missing = tuple(name for name in required if not values.get(name))
        if missing:
            raise ValueError(
                "production requires explicit configuration: " + ", ".join(missing)
            )
        return cls(
            environment=selected,
            database_url=values["ASP_DATABASE_URL"],
            object_store_url=values["ASP_OBJECT_STORE_URL"],
            object_store_bucket=values["ASP_OBJECT_STORE_BUCKET"],
            parquet_root=values["ASP_PARQUET_ROOT"],
        )
