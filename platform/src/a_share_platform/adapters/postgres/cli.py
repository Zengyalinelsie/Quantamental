"""CLI entrypoint for applying platform-owned PostgreSQL migrations."""

from __future__ import annotations

from pathlib import Path

import psycopg

from a_share_platform.application.settings import Settings

from .migrations import apply_migrations


def main() -> None:
    settings = Settings.from_environment()
    directory = Path(__file__).resolve().parents[4] / "migrations"
    with psycopg.connect(settings.database_url) as connection:
        applied = apply_migrations(connection, directory)
    for version in applied:
        print(version)


if __name__ == "__main__":
    main()
