"""Dry-run-by-default CLI for bounded, auditable A-share research backfills."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from a_share_platform.adapters.memory.backfill import InMemoryBackfillRepository
from a_share_platform.adapters.parquet.market_data import ParquetMarketDataStore
from a_share_platform.adapters.postgres.backfill import PostgresBackfillRepository
from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.adapters.providers.baostock_backfill import BaostockBackfillSource
from a_share_platform.adapters.providers.futu_backfill import FutuQuoteBackfillSource
from a_share_platform.adapters.providers.futu_quote import FutuQuoteDailyReader
from a_share_platform.adapters.sinks.canonical_backfill import CanonicalBackfillSink
from a_share_platform.application.backfill import (
    BackfillService,
    build_csi_backfill_plan,
    build_private_local_backfill_plan,
)
from a_share_platform.application.provider_registry import build_p2_provider_registry
from a_share_platform.domain.backfill import BackfillDataDomain, BackfillPlan
from a_share_platform.ports.backfill import BackfillSource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="a_share_mcp_baostock")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--plan-id")
    parser.add_argument("--symbols", nargs="+", help="explicit SH./SZ. symbols")
    parser.add_argument(
        "--domains",
        nargs="+",
        choices=[item.value for item in BackfillDataDomain],
        help="explicit data domains; executable sources currently cover raw bars/calendar",
    )
    parser.add_argument("--database-url", help="explicit local PostgreSQL DSN")
    parser.add_argument("--parquet-root", type=Path, help="explicit local Parquet root")
    parser.add_argument(
        "--private-local-research-ack",
        action="store_true",
        help=(
            "acknowledge normalized_current-only private local storage with no "
            "redistribution, strict historical, or production use"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute only after all private-local gates and provider capabilities pass",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = datetime.now(UTC)
    private_request = bool(args.symbols and args.domains)
    plan_id = args.plan_id or _default_plan_id(args, private_request)
    plan = _build_plan(args, plan_id, now, private_request)
    repository = InMemoryBackfillRepository()
    service = BackfillService(
        registry=build_p2_provider_registry(),
        repository=repository,
        clock=lambda: now,
    )
    preview = service.preview(plan)
    blockers = list(preview.qualification.blockers)
    if args.execute:
        blockers.extend(_execution_gate_blockers(args))
    output = {
        "mode": "execute_requested" if args.execute else "dry_run",
        "writes_performed": False,
        "plan_id": plan.plan_id,
        "provider_id": plan.provider_id,
        "start_date": plan.start_date.isoformat(),
        "end_date": plan.end_date.isoformat(),
        "scopes": [scope.scope_id for scope in plan.scopes],
        "domains": [domain.value for domain in plan.domains],
        "symbols": list(plan.symbols),
        "markets": list(plan.markets),
        "work_unit_count": len(preview.work_units),
        "provider_use": plan.provider_use.value,
        "output_trust_state": plan.output_trust_state.value,
        "qualified_for_bulk_persistence": (
            preview.qualification.permitted
            if plan.provider_use.value == "raw_bulk_persistence"
            else False
        ),
        "qualified_for_private_local_research": (
            preview.qualification.permitted
            if plan.provider_use.value == "private_local_research"
            else False
        ),
        "blockers": blockers,
        "warnings": list(preview.qualification.warnings),
    }
    if args.execute and blockers:
        output["execution_status"] = "blocked"
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    if args.execute:
        try:
            execution = _execute_backfill(args, plan, now)
        except Exception as error:  # noqa: BLE001 - CLI boundary must report SDK/DB failures
            output.update(
                {
                    "execution_status": "failed",
                    "execution_error": f"{type(error).__name__}: {error}",
                }
            )
            print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        output.update(execution)
        output["writes_performed"] = execution.get("execution_status") == "succeeded"
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _default_plan_id(args: argparse.Namespace, private_request: bool) -> str:
    if not private_request:
        return f"csi300-csi500:{args.provider}:{args.start.isoformat()}:{args.end.isoformat()}"
    identity = "|".join(
        (
            args.provider,
            args.start.isoformat(),
            args.end.isoformat(),
            ",".join(args.symbols),
            ",".join(args.domains),
        )
    ).encode("utf-8")
    return f"private-local:{args.provider}:{hashlib.sha256(identity).hexdigest()[:20]}"


def _build_plan(
    args: argparse.Namespace,
    plan_id: str,
    now: datetime,
    private_request: bool,
) -> BackfillPlan:
    if private_request:
        return build_private_local_backfill_plan(
            plan_id=plan_id,
            provider_id=args.provider,
            symbols=tuple(args.symbols),
            domains=tuple(BackfillDataDomain(item) for item in args.domains),
            start_date=args.start,
            end_date=args.end,
            created_at=now,
        )
    return build_csi_backfill_plan(
        plan_id=plan_id,
        provider_id=args.provider,
        start_date=args.start,
        end_date=args.end,
        created_at=now,
    )


def _execution_gate_blockers(args: argparse.Namespace) -> list[str]:
    blockers: list[str] = []
    if not args.private_local_research_ack:
        blockers.append("private-local-research ack is required for execution")
    if not args.database_url:
        blockers.append("an explicit local database URL is required for execution")
    if args.parquet_root is None:
        blockers.append("an explicit local Parquet root is required for execution")
    if not args.symbols:
        blockers.append("explicit symbols are required for execution")
    if not args.domains:
        blockers.append("explicit domains are required for execution")
    supported = {
        "baostock_sdk": {
            BackfillDataDomain.RAW_DAILY_BAR.value,
            BackfillDataDomain.TRADING_CALENDAR.value,
        },
        "futu_quote": {BackfillDataDomain.RAW_DAILY_BAR.value},
    }
    if args.provider not in supported:
        blockers.append(f"provider={args.provider} has no executable private-local source")
    elif args.domains and not set(args.domains).issubset(supported[args.provider]):
        blockers.append(
            f"provider={args.provider} does not execute every requested domain"
        )
    return blockers


def _execute_backfill(
    args: argparse.Namespace,
    plan: BackfillPlan,
    now: datetime,
) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(args.database_url) as connection:
        repository = PostgresBackfillRepository(connection)
        governance = PostgresDatasetVersionRepository(connection)
        service = BackfillService(
            registry=build_p2_provider_registry(),
            repository=repository,
            governance_repository=governance,
            clock=lambda: now,
        )
        source: BackfillSource
        if plan.provider_id == "baostock_sdk":
            source = BaostockBackfillSource(clock=lambda: datetime.now(UTC))
        elif plan.provider_id == "futu_quote":
            source = FutuQuoteBackfillSource(
                reader=FutuQuoteDailyReader(clock=lambda: datetime.now(UTC))
            )
        else:  # protected by the CLI gate and retained as defense in depth
            raise ValueError(f"unsupported executable provider: {plan.provider_id}")
        assert args.parquet_root is not None
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=ParquetMarketDataStore(args.parquet_root),
            clock=lambda: datetime.now(UTC),
        )
        job = service.start(plan, source=source, sink=sink)
        return {
            "execution_status": job.status.value,
            "dataset_version_id": job.dataset_version_id,
        }


if __name__ == "__main__":
    raise SystemExit(main())
