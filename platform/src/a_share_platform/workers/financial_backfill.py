"""Dry-run-by-default entry point for private-local P3.5 financial backfills."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from a_share_platform.application.financial_backfill import (
    FinancialBackfillPlanner,
)
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillCohort,
    FinancialBackfillPlan,
    FinancialStatementSelection,
)
from a_share_platform.domain.financial_sources import (
    FinancialSourceAccessMode,
    FinancialSourceProfile,
    FinancialSourceQualification,
    FinancialSourceRole,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.workers.backfill import _postgres_endpoint_is_private_local


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="immutable financial plan JSON")
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="versioned provider qualification JSON",
    )
    parser.add_argument("--database-url", help="explicit private-local PostgreSQL DSN")
    parser.add_argument(
        "--private-local-research-ack",
        action="store_true",
        help="acknowledge private-local normalized_current-only use and no redistribution",
    )
    parser.add_argument(
        "--bulk-persistence-ack",
        action="store_true",
        help="acknowledge provider retention and bulk-persistence permission",
    )
    parser.add_argument(
        "--mapping-approved-ack",
        action="store_true",
        help="acknowledge that the exact mapping version has been reviewed and approved",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="request execution only after every local, source, and mapping gate passes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    plan = _load_plan(args.plan)
    profile = _load_profile(args.profile)
    preview = FinancialBackfillPlanner().preview(plan, profile)
    credentials_configured = bool(
        os.environ.get("FACTOR_SERVICE_BASE_URL", "").strip()
        and os.environ.get("FACTOR_SERVICE_BEARER_TOKEN", "").strip()
    )
    blockers = list(preview.qualification.blockers)
    if args.execute:
        blockers.extend(_execution_gate_blockers(args, plan))
    blockers = list(dict.fromkeys(blockers))
    output: dict[str, Any] = {
        "mode": "execute_requested" if args.execute else "dry_run",
        "writes_performed": False,
        "plan_id": plan.plan_id,
        "provider_id": plan.provider_id,
        "provider_profile_version": plan.provider_profile_version,
        "cohort": plan.cohort.value,
        "universe_version_id": plan.universe_version_id,
        "mapping_version_id": plan.mapping_version_id,
        "data_mode": plan.data_mode.value,
        "output_trust_state": plan.output_trust_state.value,
        "qualified": preview.qualification.permitted,
        "work_unit_count": len(preview.work_units),
        "credentials_configured": credentials_configured,
        "blockers": blockers,
        "warnings": list(preview.qualification.warnings),
    }
    if args.execute and blockers:
        output["execution_status"] = "blocked"
        _print(output)
        return 2
    if args.execute:
        try:
            execution = _execute_financial_backfill(args, plan, profile)
        except Exception as error:  # noqa: BLE001 - CLI boundary reports safe type/message only
            output.update(
                {
                    "execution_status": "failed",
                    "execution_error": f"{type(error).__name__}: {_safe_error_text(error)}",
                }
            )
            _print(output)
            return 1
        output.update(execution)
        output["writes_performed"] = execution.get("execution_status") == "succeeded"
    _print(output)
    return 0


def _print(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _execution_gate_blockers(
    args: argparse.Namespace,
    plan: FinancialBackfillPlan,
) -> list[str]:
    blockers: list[str] = []
    if not args.private_local_research_ack:
        blockers.append("private-local-research ack is required for execution")
    if not args.bulk_persistence_ack:
        blockers.append("bulk-persistence ack is required for execution")
    if not args.mapping_approved_ack:
        blockers.append("mapping approval ack is required for execution")
    if not args.database_url:
        blockers.append("an explicit local database URL is required for execution")
    elif not _postgres_endpoint_is_private_local(args.database_url):
        blockers.append("private-local PostgreSQL must use a loopback or Unix socket endpoint")
    if not os.environ.get("FACTOR_SERVICE_BASE_URL", "").strip():
        blockers.append("FACTOR_SERVICE_BASE_URL is required for execution")
    if not os.environ.get("FACTOR_SERVICE_BEARER_TOKEN", "").strip():
        blockers.append("FACTOR_SERVICE_BEARER_TOKEN is required for execution")
    if plan.provider_id != "factor_service_ths":
        blockers.append(
            f"provider={plan.provider_id} has no executable financial source; "
            "AkShare/Eastmoney requires source-aware retrieval grouping and immutable cache"
        )
    return blockers


def _read_object(path: Path, label: str) -> Mapping[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate JSON key: {key}")
            result[key] = item
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _required_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty JSON array")
    return value


def _required_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a JSON boolean")
    return cast(bool, value)


def _required_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be a JSON integer")
    return cast(int, value)


def _safe_error_text(error: Exception) -> str:
    detail = str(error)
    token = os.environ.get("FACTOR_SERVICE_BEARER_TOKEN", "")
    if token:
        detail = detail.replace(token, "<redacted>")
    return detail


def _load_plan(path: Path) -> FinancialBackfillPlan:
    value = _read_object(path, "financial plan")
    statements = _required_list(value.get("statements"), "statements")
    periods = _required_list(value.get("report_period_ends"), "report_period_ends")
    symbols = _required_list(value.get("symbols"), "symbols")
    return FinancialBackfillPlan(
        plan_id=str(value["plan_id"]),
        provider_id=str(value["provider_id"]),
        provider_profile_version=str(value["provider_profile_version"]),
        cohort=FinancialBackfillCohort(str(value["cohort"])),
        universe_version_id=str(value["universe_version_id"]),
        mapping_version_id=str(value["mapping_version_id"]),
        statements=tuple(
            FinancialStatementSelection(
                statement_type=StatementType(str(cast(Mapping[str, object], item)["statement_type"])),
                provider_table=str(cast(Mapping[str, object], item)["provider_table"]),
            )
            for item in statements
        ),
        report_period_ends=tuple(date.fromisoformat(str(item)) for item in periods),
        symbols=tuple(str(item) for item in symbols),
        symbol_bucket_size=_required_int(value["symbol_bucket_size"], "symbol_bucket_size"),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        data_mode=DataMode(str(value["data_mode"])),
        output_trust_state=DataTrustState(str(value["output_trust_state"])),
        allow_read_through_cache=_required_bool(
            value["allow_read_through_cache"],
            "allow_read_through_cache",
        ),
        bulk_persistence_acknowledged=_required_bool(
            value["bulk_persistence_acknowledged"],
            "bulk_persistence_acknowledged",
        ),
        predecessor_coverage_report_id=(
            None
            if value.get("predecessor_coverage_report_id") is None
            else str(value["predecessor_coverage_report_id"])
        ),
    )


def _load_profile(path: Path) -> FinancialSourceProfile:
    value = _read_object(path, "financial source profile")
    markets = _required_list(value.get("markets"), "markets")
    statements = _required_list(value.get("statements"), "statements")
    warnings = value.get("warnings", [])
    if not isinstance(warnings, list):
        raise TypeError("warnings must be a JSON array")
    return FinancialSourceProfile(
        profile_version=str(value["profile_version"]),
        provider_id=str(value["provider_id"]),
        role=FinancialSourceRole(str(value["role"])),
        markets=frozenset(str(item) for item in markets),
        statements=frozenset(StatementType(str(item)) for item in statements),
        access_mode=FinancialSourceAccessMode(str(value["access_mode"])),
        qualification=FinancialSourceQualification(str(value["qualification"])),
        trust_ceiling=DataTrustState(str(value["trust_ceiling"])),
        retention_allowed=_required_bool(value["retention_allowed"], "retention_allowed"),
        bulk_persistence_allowed=_required_bool(
            value["bulk_persistence_allowed"],
            "bulk_persistence_allowed",
        ),
        supplies_revision_history=_required_bool(
            value["supplies_revision_history"],
            "supplies_revision_history",
        ),
        supplies_exact_available_at=_required_bool(
            value["supplies_exact_available_at"],
            "supplies_exact_available_at",
        ),
        max_rows_per_request=_required_int(
            value["max_rows_per_request"],
            "max_rows_per_request",
        ),
        warnings=tuple(str(item) for item in warnings),
    )


def _execute_financial_backfill(
    args: argparse.Namespace,
    plan: FinancialBackfillPlan,
    profile: FinancialSourceProfile,
) -> dict[str, object]:
    """Fail closed until the byte-exact live source composition is installed.

    The PostgreSQL unit of work is executable independently and this CLI owns all
    external side-effect gates. The source composition remains blocked because the
    current provider adapter exposes decoded records, not byte-exact HTTP response
    bodies. Treating those decoded records as raw evidence would be dishonest.
    """

    del args, plan, profile
    raise RuntimeError(
        "byte-exact Factor Service evidence recorder is not configured; "
        "financial execution remains blocked"
    )


if __name__ == "__main__":
    raise SystemExit(main())
