"""Dry-run-by-default CLI for the canonical CSI 300/500 backfill plan."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime

from a_share_platform.adapters.memory.backfill import InMemoryBackfillRepository
from a_share_platform.application.backfill import BackfillService, build_csi_backfill_plan
from a_share_platform.application.provider_registry import build_p2_provider_registry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="a_share_mcp_baostock")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--plan-id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="request execution; still fails closed unless every field has bulk-storage approval",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = datetime.now(UTC)
    plan_id = args.plan_id or (
        f"csi300-csi500:{args.provider}:{args.start.isoformat()}:{args.end.isoformat()}"
    )
    plan = build_csi_backfill_plan(
        plan_id=plan_id,
        provider_id=args.provider,
        start_date=args.start,
        end_date=args.end,
        created_at=now,
    )
    repository = InMemoryBackfillRepository()
    service = BackfillService(
        registry=build_p2_provider_registry(),
        repository=repository,
        clock=lambda: now,
    )
    preview = service.preview(plan)
    blockers = list(preview.qualification.blockers)
    if args.execute:
        blockers.append(
            "CLI has no approved bulk source/sink configured; no network or database write attempted"
        )
    output = {
        "mode": "execute_requested" if args.execute else "dry_run",
        "writes_performed": False,
        "plan_id": plan.plan_id,
        "provider_id": plan.provider_id,
        "start_date": plan.start_date.isoformat(),
        "end_date": plan.end_date.isoformat(),
        "scopes": [scope.scope_id for scope in plan.scopes],
        "domains": [domain.value for domain in plan.domains],
        "work_unit_count": len(preview.work_units),
        "qualified_for_bulk_persistence": preview.qualification.permitted,
        "blockers": blockers,
        "warnings": list(preview.qualification.warnings),
    }
    if args.execute:
        output["execution_status"] = "blocked"
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if args.execute else 0


if __name__ == "__main__":
    raise SystemExit(main())
