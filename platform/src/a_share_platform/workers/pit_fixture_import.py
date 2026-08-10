"""Dry-run-by-default CLI for the private-local real P3 PIT fixture pack."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import psycopg

from a_share_platform.adapters.postgres.pit_fixture_import import (
    PostgresPITFixtureImporter,
)
from a_share_platform.domain.pit_fixtures import PITFixturePack
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local

PLATFORM_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = PLATFORM_ROOT / "fixtures" / "p3" / "pit_fixture_pack.v1.json"
DEFAULT_EVIDENCE_ROOT = (
    PLATFORM_ROOT / "var" / "private-research" / "p3-fixtures" / "raw"
)
DEFAULT_IDENTITY_SNAPSHOT = (
    PLATFORM_ROOT
    / "var"
    / "private-research"
    / "p3-fixtures"
    / "baostock-security-basic.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument(
        "--identity-snapshot",
        type=Path,
        default=DEFAULT_IDENTITY_SNAPSHOT,
        help="private-local BaoStock identity snapshot used only for missing master FKs",
    )
    parser.add_argument("--database-url")
    parser.add_argument(
        "--private-local-research-ack",
        action="store_true",
        help="acknowledge private-local persistence with no redistribution or trading use",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="persist only after the local database and private-use gates pass",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pack = PITFixturePack.load(args.manifest)
    importer = PostgresPITFixtureImporter(
        pack,
        args.evidence_root,
        identity_snapshot_path=args.identity_snapshot,
    )
    output = asdict(importer.preview())
    output["mode"] = "execute_requested" if args.execute else "dry_run"
    output["blockers"] = []
    if not args.execute:
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    blockers: list[str] = []
    if not args.private_local_research_ack:
        blockers.append("private-local research acknowledgement is required")
    if not args.database_url:
        blockers.append("an explicit private-local database URL is required")
    elif not _postgres_endpoint_is_private_local(args.database_url):
        blockers.append("database must use a loopback or Unix socket endpoint")
    output["blockers"] = blockers
    if blockers:
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    try:
        with psycopg.connect(args.database_url) as connection:
            result = importer.execute(
                connection,
                private_local_research_ack=True,
            )
        output.update(asdict(result))
        output["execution_status"] = "succeeded"
    except Exception as error:  # noqa: BLE001 - CLI boundary reports a safe class/message
        output["execution_status"] = "failed"
        output["execution_error"] = f"{type(error).__name__}: {error}"
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
