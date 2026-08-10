"""Pure CNInfo/AkShare shape normalization for P2 market-structure staging.

This module deliberately performs no network access and no trust promotion.  The
AkShare endpoints expose date-only announcement fields, so the result must not be
treated as an exact ``available_at`` or as PIT-verified data.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from numbers import Real

from a_share_platform.domain.security_master import Exchange

from .backfill_payloads import (
    CorporateActionPayload,
    ShareCapitalPayload,
    StagedCorporateActionObservation,
    StagedShareCapitalObservation,
)

_PER_TEN_SHARES = Decimal(10)


class CninfoMarketStructureNormalizer:
    """Map recorded endpoint rows into provider-neutral staged observations."""

    def share_capital(
        self,
        *,
        code: str,
        records: Sequence[Mapping[str, object]],
    ) -> ShareCapitalPayload:
        exchange = _exchange(code)
        digits = code.split(".", 1)[1]
        rows: list[StagedShareCapitalObservation] = []
        for record in records:
            _require_record_code(record.get("证券代码"), digits)
            effective_on = _required_date(record.get("变动日期"), "变动日期")
            announced_on = _optional_date(record.get("公告日期"), "公告日期")
            total_shares = _required_decimal(record.get("总股本"), "总股本")
            circulating = _optional_non_negative_decimal(
                record.get("已流通股份"), "已流通股份"
            )
            restricted = _optional_non_negative_decimal(
                record.get("流通受限股份"), "流通受限股份"
            )
            normalized = (
                code,
                effective_on.isoformat(),
                None if announced_on is None else announced_on.isoformat(),
                str(total_shares),
                None if circulating is None else str(circulating),
                None if restricted is None else str(restricted),
                _optional_text(record.get("变动原因")),
            )
            rows.append(
                StagedShareCapitalObservation(
                    code=code,
                    exchange=exchange,
                    effective_on=effective_on,
                    announced_on=announced_on,
                    total_shares=total_shares,
                    circulating_shares=circulating,
                    restricted_shares=restricted,
                    free_float_shares=None,
                    provider_record_id=_record_id(
                        "cninfo:stock_share_change",
                        normalized,
                    ),
                    source_id="akshare.stock_share_change_cninfo",
                )
            )
        return ShareCapitalPayload(
            tuple(sorted(rows, key=lambda row: (row.effective_on, row.provider_record_id)))
        )

    def corporate_actions(
        self,
        *,
        code: str,
        records: Sequence[Mapping[str, object]],
    ) -> CorporateActionPayload:
        exchange = _exchange(code)
        rows: list[StagedCorporateActionObservation] = []
        for record in records:
            announced_on = _optional_date(
                record.get("实施方案公告日期"),
                "实施方案公告日期",
            )
            record_date = _optional_date(record.get("股权登记日"), "股权登记日")
            ex_date = _optional_date(record.get("除权日"), "除权日")
            cash = _per_share(record.get("派息比例"), "派息比例")
            bonus = _per_share(record.get("送股比例"), "送股比例")
            capitalization = _per_share(record.get("转增比例"), "转增比例")
            if cash is None and bonus is None and capitalization is None:
                continue
            normalized = (
                code,
                None if announced_on is None else announced_on.isoformat(),
                None if record_date is None else record_date.isoformat(),
                None if ex_date is None else ex_date.isoformat(),
                None if cash is None else str(cash),
                None if bonus is None else str(bonus),
                None if capitalization is None else str(capitalization),
                _optional_text(record.get("分红类型")),
                _optional_text(record.get("报告时间")),
            )
            rows.append(
                StagedCorporateActionObservation(
                    code=code,
                    exchange=exchange,
                    announced_on=announced_on,
                    record_date=record_date,
                    ex_date=ex_date,
                    cash_per_share=cash,
                    bonus_shares_per_share=bonus,
                    capitalization_shares_per_share=capitalization,
                    rights_shares_per_share=None,
                    rights_subscription_price=None,
                    currency="CNY",
                    provider_record_id=_record_id(
                        "cninfo:stock_dividend",
                        normalized,
                    ),
                    source_id="akshare.stock_dividend_cninfo",
                )
            )
        return CorporateActionPayload(
            tuple(
                sorted(
                    rows,
                    key=lambda row: (
                        row.announced_on or date.min,
                        row.provider_record_id,
                    ),
                )
            )
        )


def _exchange(code: str) -> Exchange:
    if not isinstance(code, str) or len(code) != 9 or code[2] != ".":
        raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000")
    try:
        return {"SH": Exchange.XSHG, "SZ": Exchange.XSHE, "BJ": Exchange.XBSE}[
            code[:2]
        ]
    except KeyError as error:
        raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000") from error


def _require_record_code(value: object, expected: str) -> None:
    if _is_missing(value):
        raise ValueError("CNInfo share-capital row is missing 证券代码")
    actual = str(value).strip().split(".")[-1].zfill(6)
    if actual != expected:
        raise ValueError(
            f"CNInfo share-capital code mismatch: expected={expected}, actual={actual}"
        )


def _required_date(value: object, field: str) -> date:
    selected = _optional_date(value, field)
    if selected is None:
        raise ValueError(f"{field} must not be missing")
    return selected


def _optional_date(value: object, field: str) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _required_decimal(value: object, field: str) -> Decimal:
    selected = _optional_decimal(value, field)
    if selected is None:
        raise ValueError(f"{field} must not be missing")
    if selected <= 0:
        raise ValueError(f"{field} must be positive")
    return selected


def _optional_non_negative_decimal(value: object, field: str) -> Decimal | None:
    selected = _optional_decimal(value, field)
    if selected is not None and selected < 0:
        raise ValueError(f"{field} must not be negative")
    return selected


def _per_share(value: object, field: str) -> Decimal | None:
    """CNInfo distribution ratios are expressed per ten A shares."""

    selected = _optional_non_negative_decimal(value, field)
    if selected in {None, Decimal(0)}:
        return None
    return selected / _PER_TEN_SHARES


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if _is_missing(value):
        return None
    try:
        selected = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not selected.is_finite():
        raise ValueError(f"{field} must be finite")
    return selected


def _optional_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    selected = str(value).strip()
    return selected or None


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if type(value).__name__ == "NaTType":
        return True
    if isinstance(value, Real):
        return math.isnan(float(value))
    return False


def _record_id(prefix: str, values: tuple[object, ...]) -> str:
    encoded = json.dumps(
        values,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"{prefix}:{digest}"
