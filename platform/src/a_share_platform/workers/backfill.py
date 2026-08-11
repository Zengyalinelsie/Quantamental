"""Dry-run-by-default CLI for bounded, auditable A-share research backfills."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import shlex
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from a_share_platform.adapters.memory.backfill import InMemoryBackfillRepository
from a_share_platform.adapters.parquet.market_data import ParquetMarketDataStore
from a_share_platform.adapters.postgres.backfill import PostgresBackfillRepository
from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.adapters.postgres.market_structure import (
    PostgresCurrentKnownListingResolver,
    PostgresMarketStructureObservationSink,
)
from a_share_platform.adapters.providers.akshare_market_structure_source import (
    AkshareMarketStructureSource,
)
from a_share_platform.adapters.providers.baostock_backfill import BaostockBackfillSource
from a_share_platform.adapters.providers.futu_backfill import FutuQuoteBackfillSource
from a_share_platform.adapters.providers.futu_quote import FutuQuoteDailyReader
from a_share_platform.adapters.providers.identity_universe_backfill import (
    IdentityUniverseBackfillSource,
)
from a_share_platform.adapters.sinks.canonical_backfill import CanonicalBackfillSink
from a_share_platform.adapters.sinks.routing import DomainRoutingBackfillSink
from a_share_platform.application.backfill import (
    BackfillService,
    build_csi_backfill_plan,
    build_private_local_backfill_plan,
)
from a_share_platform.application.provider_registry import build_p2_provider_registry
from a_share_platform.domain.backfill import (
    BackfillDataDomain,
    BackfillPlan,
    UniverseObservationMode,
)
from a_share_platform.ports.backfill import BackfillSink, BackfillSource

PRIVATE_LOCAL_STORAGE_ROOT = (
    Path(__file__).resolve().parents[3] / "var" / "private-research"
).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="a_share_mcp_baostock")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--plan-id")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--symbols", nargs="+", help="explicit SH./SZ. symbols")
    scope.add_argument(
        "--all-a-share",
        action="store_true",
        help="explicitly authorize full XSHG/XSHE identity and CSI 300/500 membership",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        choices=[item.value for item in BackfillDataDomain],
        help="explicit data domains; each executable provider enforces its own subset",
    )
    parser.add_argument(
        "--benchmarks",
        nargs="+",
        choices=("000300", "000905"),
        help="explicit CSI benchmark subset for an all-A-share universe backfill",
    )
    parser.add_argument(
        "--universe-observation-mode",
        choices=[item.value for item in UniverseObservationMode],
        default=UniverseObservationMode.CONTINUOUS_DAILY.value,
        help=(
            "continuous_daily queries every trading date; discrete_month_end "
            "persists only observed month-end snapshots and explicit gaps"
        ),
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        choices=("XSHG", "XSHE", "XBSE"),
        help="explicit market slice; required for provider-specific all-market jobs",
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
    private_request = bool(args.domains and (args.symbols or args.all_a_share))
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
        "all_a_share": plan.all_a_share,
        "markets": list(plan.markets),
        "universe_observation_mode": plan.universe_observation_mode.value,
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
            ",".join(args.symbols or ()),
            ",".join(args.domains),
            ",".join(args.benchmarks or ("000300", "000905")),
            ",".join(args.markets or ()),
            args.universe_observation_mode,
            "all_a_share" if args.all_a_share else "explicit_symbols",
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
            symbols=tuple(args.symbols or ()),
            all_a_share=args.all_a_share,
            domains=tuple(BackfillDataDomain(item) for item in args.domains),
            start_date=args.start,
            end_date=args.end,
            created_at=now,
            universe_benchmark_codes=(
                None if args.benchmarks is None else tuple(args.benchmarks)
            ),
            markets=(None if args.markets is None else tuple(args.markets)),
            universe_observation_mode=UniverseObservationMode(
                args.universe_observation_mode
            ),
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
    elif not _postgres_endpoint_is_private_local(args.database_url):
        blockers.append(
            "private-local PostgreSQL must use a loopback or Unix socket endpoint"
        )
    if args.parquet_root is None:
        blockers.append("an explicit local Parquet root is required for execution")
    elif not _parquet_root_is_private_local(args.parquet_root):
        blockers.append(
            "Parquet output must remain under the controlled private-local root "
            f"{PRIVATE_LOCAL_STORAGE_ROOT}"
        )
    if not args.symbols and not args.all_a_share:
        blockers.append("explicit symbols are required for execution")
    if not args.domains:
        blockers.append("explicit domains are required for execution")
    supported = {
        "baostock_sdk": {
            BackfillDataDomain.RAW_DAILY_BAR.value,
            BackfillDataDomain.TRADING_CALENDAR.value,
        },
        "futu_quote": {BackfillDataDomain.RAW_DAILY_BAR.value},
        "a_share_identity_universe": {
            BackfillDataDomain.SECURITY_MASTER.value,
            BackfillDataDomain.UNIVERSE.value,
        },
        "akshare": {
            BackfillDataDomain.SECURITY_MASTER.value,
            BackfillDataDomain.SHARE_CAPITAL.value,
            BackfillDataDomain.CORPORATE_ACTION.value,
        },
    }
    if args.provider not in supported:
        blockers.append(f"provider={args.provider} has no executable private-local source")
    elif args.domains and not set(args.domains).issubset(supported[args.provider]):
        blockers.append(
            f"provider={args.provider} does not execute every requested domain"
        )
    if args.provider == "a_share_identity_universe":
        requested_domains = set(args.domains or ())
        if not args.all_a_share and requested_domains != {
            BackfillDataDomain.SECURITY_MASTER.value
        }:
            blockers.append(
                "provider=a_share_identity_universe with explicit symbols supports "
                "only security_master; Universe requires --all-a-share"
            )
        if (
            BackfillDataDomain.UNIVERSE.value in requested_domains
            and (args.end - args.start).days > 31
            and args.universe_observation_mode
            != UniverseObservationMode.DISCRETE_MONTH_END.value
        ):
            blockers.append(
                "historical Universe execution longer than 31 days requires "
                "--universe-observation-mode discrete_month_end to cap provider "
                "requests and preserve unobserved gaps"
            )
    if args.all_a_share:
        if args.provider == "a_share_identity_universe":
            if args.markets is not None and set(args.markets).difference({"XSHG", "XSHE"}):
                blockers.append(
                    "provider=a_share_identity_universe supports only XSHG/XSHE"
                )
        elif args.provider == "akshare":
            if set(args.domains or ()) != {BackfillDataDomain.SECURITY_MASTER.value}:
                blockers.append(
                    "provider=akshare --all-a-share supports only security_master"
                )
            if args.markets != ["XBSE"]:
                blockers.append(
                    "provider=akshare --all-a-share requires --markets XBSE"
                )
        else:
            blockers.append(
                "--all-a-share requires provider=a_share_identity_universe or akshare"
            )
    return blockers


def _postgres_endpoint_is_private_local(dsn: str) -> bool:
    value = dsn.strip()
    if not value:
        return False
    if value.startswith(("postgresql://", "postgres://")):
        parsed = urlparse(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "service" in query or "servicefile" in query:
            return False
        endpoints: list[tuple[str, bool]] = []
        if parsed.hostname is not None:
            endpoints.append((parsed.hostname, False))
        endpoints.extend((unquote(item), True) for item in query.get("host", ()))
        endpoints.extend((unquote(item), False) for item in query.get("hostaddr", ()))
        return not endpoints or all(
            _postgres_host_is_private_local(host, allow_unix_socket=allow_socket)
            for host, allow_socket in endpoints
        )

    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    parameters: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            return False
        key, item = token.split("=", 1)
        parameters[key.casefold()] = item
    if "service" in parameters or "servicefile" in parameters:
        return False
    endpoints = []
    if "host" in parameters:
        endpoints.append((parameters["host"], True))
    if "hostaddr" in parameters:
        endpoints.append((parameters["hostaddr"], False))
    return not endpoints or all(
        _postgres_host_is_private_local(host, allow_unix_socket=allow_socket)
        for host, allow_socket in endpoints
    )


def _postgres_host_is_private_local(host: str, *, allow_unix_socket: bool) -> bool:
    values = tuple(item.strip() for item in host.split(","))
    if not values or any(not item for item in values):
        return False
    for item in values:
        if allow_unix_socket and Path(item).is_absolute():
            continue
        if item.casefold() == "localhost":
            continue
        try:
            if ipaddress.ip_address(item).is_loopback:
                continue
        except ValueError:
            pass
        return False
    return True


def _parquet_root_is_private_local(root: Path) -> bool:
    candidate = root.expanduser().resolve(strict=False)
    return candidate.is_relative_to(PRIVATE_LOCAL_STORAGE_ROOT)


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
        elif plan.provider_id == "a_share_identity_universe":
            source = IdentityUniverseBackfillSource(clock=lambda: datetime.now(UTC))
        elif plan.provider_id == "akshare":
            source = AkshareMarketStructureSource(clock=lambda: datetime.now(UTC))
        else:  # protected by the CLI gate and retained as defense in depth
            raise ValueError(f"unsupported executable provider: {plan.provider_id}")
        assert args.parquet_root is not None
        canonical_sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=ParquetMarketDataStore(args.parquet_root),
            clock=lambda: datetime.now(UTC),
        )
        sink: BackfillSink = canonical_sink
        if plan.provider_id == "akshare":
            observation_sink = PostgresMarketStructureObservationSink(
                connection=connection,
                listing_resolver=PostgresCurrentKnownListingResolver(connection),
            )
            sink = DomainRoutingBackfillSink(
                default_sink=canonical_sink,
                routes={
                    BackfillDataDomain.SHARE_CAPITAL: observation_sink,
                    BackfillDataDomain.CORPORATE_ACTION: observation_sink,
                },
            )
        job = service.start(plan, source=source, sink=sink)
        return {
            "execution_status": job.status.value,
            "dataset_version_id": job.dataset_version_id,
        }


if __name__ == "__main__":
    raise SystemExit(main())
