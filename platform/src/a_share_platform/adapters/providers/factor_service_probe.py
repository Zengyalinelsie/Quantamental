"""Repeatable Factor Service qualification probe for the three A-share statements."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from functools import partial

from .factor_service import FactorServiceClient, FactorServiceError

_STATEMENT_TABLES = ("balance_sheet", "income_statement", "cash_flow")


class ProbeStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class FactorServiceProbeResult:
    operation: str
    status: ProbeStatus
    observed_items: int | None
    detail: str


def _observed_items(value: object) -> int | None:
    if isinstance(value, Mapping):
        rows = value.get("rows")
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            return len(rows)
        return len(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    if type(value) is int:
        return value
    return None


def _attempt(operation: str, call: Callable[[], object]) -> FactorServiceProbeResult:
    try:
        value = call()
    except (FactorServiceError, ValueError, TypeError) as error:
        return FactorServiceProbeResult(
            operation=operation,
            status=ProbeStatus.FAILED,
            observed_items=None,
            detail=str(error),
        )
    return FactorServiceProbeResult(
        operation=operation,
        status=ProbeStatus.PASSED,
        observed_items=_observed_items(value),
        detail="contract accepted",
    )


def _skipped(operation: str) -> FactorServiceProbeResult:
    return FactorServiceProbeResult(
        operation=operation,
        status=ProbeStatus.SKIPPED,
        observed_items=None,
        detail="read-through cache acknowledgement not provided",
    )


def run_financial_qualification_probe(
    client: FactorServiceClient,
    *,
    symbol: str,
    report_period_end: str,
    allow_read_through_cache: bool,
) -> tuple[FactorServiceProbeResult, ...]:
    """Exercise every documented endpoint and all three A-share statement tables.

    Raw provider values are deliberately not printed or persisted.  This probe
    records endpoint-contract status and counts; a later governed fixture run
    owns content-addressed storage and manual expected values.
    """

    if type(allow_read_through_cache) is not bool:
        raise TypeError("allow_read_through_cache must be a boolean")
    results = [
        _attempt("v1.health", client.v1_health),
        _attempt(
            "v1.factor.list",
            partial(client.v1_factor_list, table_name="balance_sheet"),
        ),
        _attempt("v1.table.list", client.v1_table_list),
        _attempt("v2.health", client.v2_health),
        _attempt("v2.meta.schema", client.v2_meta_schema),
        _attempt(
            "v2.metadata",
            partial(client.v2_metadata, filter_date="report_period_end"),
        ),
        _attempt(
            "v2.tables",
            partial(client.v2_tables, filter_date="report_period_end"),
        ),
    ]
    for table_name in _STATEMENT_TABLES:
        results.append(
            _attempt(
                f"v2.table.detail.{table_name}",
                partial(client.v2_table_detail, table_name),
            )
        )
        results.append(
            _attempt(
                f"v2.columns.search.{table_name}",
                partial(
                    client.v2_columns_search,
                    table_name=table_name,
                    enabled=True,
                ),
            )
        )
        results.append(
            _attempt(
                f"v2.table.count.{table_name}",
                partial(
                    client.v2_table_count,
                    table_name=table_name,
                    primary_key_name="scode",
                    primary_key_values=(symbol,),
                    filter_date="report_period_end",
                    start_date=report_period_end,
                    end_date=report_period_end,
                    allow_date_only_query=False,
                ),
            )
        )

    if allow_read_through_cache:
        results.append(
            _attempt(
                "v1.factor.query",
                partial(
                    client.v1_factor_query,
                    scodes=(symbol,),
                    tables=("balance_sheet",),
                    report_period_end=report_period_end,
                    allow_read_through_cache=True,
                ),
            )
        )
        for table_name in _STATEMENT_TABLES:
            results.append(
                _attempt(
                    f"v2.table.query.{table_name}",
                    partial(
                        client.v2_table_query,
                        table_name=table_name,
                        primary_key_name="scode",
                        primary_key_values=(symbol,),
                        columns=(),
                        filter_date="report_period_end",
                        start_date=report_period_end,
                        end_date=report_period_end,
                        limit=1,
                        offset=0,
                        allow_date_only_query=False,
                        allow_read_through_cache=True,
                    ),
                )
            )
    else:
        results.append(_skipped("v1.factor.query"))
        results.extend(
            _skipped(f"v2.table.query.{table_name}")
            for table_name in _STATEMENT_TABLES
        )
    return tuple(results)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Factor Service v1/v2 A-share financial contracts",
    )
    parser.add_argument("--symbol", default="601089")
    parser.add_argument("--report-period-end", default="2024-12-31")
    parser.add_argument("--allow-read-through-cache", action="store_true")
    parser.add_argument(
        "--allow-anonymous",
        action="store_true",
        help="allow a development probe without FACTOR_SERVICE_BEARER_TOKEN",
    )
    arguments = parser.parse_args(argv)
    client = FactorServiceClient.from_environment(require_token=not arguments.allow_anonymous)
    results = run_financial_qualification_probe(
        client,
        symbol=arguments.symbol,
        report_period_end=arguments.report_period_end,
        allow_read_through_cache=arguments.allow_read_through_cache,
    )
    document = {
        "provider_id": "factor_service_ths",
        "symbol": arguments.symbol,
        "report_period_end": arguments.report_period_end,
        "read_through_cache_acknowledged": arguments.allow_read_through_cache,
        "results": [
            {**asdict(result), "status": result.status.value}
            for result in results
        ],
    }
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    if any(result.status is ProbeStatus.FAILED for result in results):
        return 1
    if any(result.status is ProbeStatus.SKIPPED for result in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
