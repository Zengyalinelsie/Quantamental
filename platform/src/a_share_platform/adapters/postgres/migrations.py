"""Minimal transaction-aware PostgreSQL migration runner."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class MigrationResult(Protocol):
    def fetchone(self) -> object | None: ...


class MigrationConnection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> MigrationResult: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def discover_migrations(directory: Path) -> tuple[Path, ...]:
    """Return SQL migrations in deterministic lexical order."""

    return tuple(sorted(path for path in directory.glob("*.sql") if path.is_file()))


def apply_migrations(connection: MigrationConnection, directory: Path) -> tuple[str, ...]:
    """Apply each not-yet-recorded migration once, rolling back on failure."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied: list[str] = []
    try:
        for path in discover_migrations(directory):
            version = path.stem
            existing = connection.execute(
                "SELECT version FROM public.schema_migrations WHERE version = %s",
                (version,),
            )
            if existing.fetchone() is not None:
                continue
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO public.schema_migrations(version) VALUES (%s)",
                (version,),
            )
            applied.append(version)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return tuple(applied)
