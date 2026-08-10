"""Current identity and historical CSI membership source for private local research."""

from __future__ import annotations

import hashlib
import importlib
import json
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, TypeVar, cast

from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillDataDomain,
    BackfillPlan,
    BackfillWorkUnit,
    DatasetQualityStatus,
    ProviderRetrievalMetadata,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import ProviderUse
from a_share_platform.domain.security_master import Board, Exchange, ListingState

from .backfill_payloads import (
    SecurityMasterPayload,
    StagedSecurityIdentity,
    StagedUniverseMembership,
    UniverseMembershipPayload,
)
from .baostock_backfill import ProviderBackfillUnavailable

_EXCHANGES = {"XSHG": Exchange.XSHG, "XSHE": Exchange.XSHE}
_SOURCE_METHODS = {
    "000300": "query_hs300_stocks",
    "000905": "query_zz500_stocks",
}
_DEFAULT_MEMBERSHIP_CARDINALITY_BOUNDS = {
    "000300": (280, 320),
    "000905": (450, 550),
}
_T = TypeVar("_T")


class IdentityUniverseBackfillSource:
    """Combine BaoStock structure with CNInfo legal names without claiming PIT identity."""

    provider_id = "a_share_identity_universe"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        baostock_module_loader: Callable[[str], object] = importlib.import_module,
        akshare_module_loader: Callable[[str], object] = importlib.import_module,
        sleeper: Callable[[float], None] = time.sleep,
        profile_attempts: int = 3,
        profile_retry_delay_seconds: float = 0.25,
        minimum_security_rows: int = 1_000,
        minimum_security_coverage_ratio: float = 0.95,
        membership_cardinality_bounds: Mapping[str, tuple[int, int]] | None = None,
        maximum_membership_change_ratio: float = 0.20,
        membership_update_max_age_days: int = 370,
        request_interval_seconds: float = 0.05,
        call_timeout_seconds: float = 30.0,
    ) -> None:
        if type(profile_attempts) is not int or profile_attempts < 1:
            raise ValueError("profile_attempts must be a positive integer")
        if profile_retry_delay_seconds < 0:
            raise ValueError("profile_retry_delay_seconds cannot be negative")
        if type(minimum_security_rows) is not int or minimum_security_rows < 1:
            raise ValueError("minimum_security_rows must be a positive integer")
        if not 0 < minimum_security_coverage_ratio <= 1:
            raise ValueError("minimum_security_coverage_ratio must be in (0, 1]")
        bounds = dict(
            _DEFAULT_MEMBERSHIP_CARDINALITY_BOUNDS
            if membership_cardinality_bounds is None
            else membership_cardinality_bounds
        )
        if set(bounds) != set(_SOURCE_METHODS):
            raise ValueError("membership cardinality bounds must cover CSI300 and CSI500")
        for lower, upper in bounds.values():
            if type(lower) is not int or type(upper) is not int or not 0 < lower <= upper:
                raise ValueError("membership cardinality bounds must be positive intervals")
        if not 0 <= maximum_membership_change_ratio <= 2:
            raise ValueError("maximum_membership_change_ratio must be in [0, 2]")
        if (
            type(membership_update_max_age_days) is not int
            or membership_update_max_age_days < 1
        ):
            raise ValueError("membership_update_max_age_days must be a positive integer")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        if call_timeout_seconds <= 0:
            raise ValueError("call_timeout_seconds must be positive")
        self._clock = clock
        self._baostock_module_loader = baostock_module_loader
        self._akshare_module_loader = akshare_module_loader
        self._sleeper = sleeper
        self._profile_attempts = profile_attempts
        self._profile_retry_delay_seconds = profile_retry_delay_seconds
        self._minimum_security_rows = minimum_security_rows
        self._minimum_security_coverage_ratio = minimum_security_coverage_ratio
        self._membership_cardinality_bounds = bounds
        self._maximum_membership_change_ratio = maximum_membership_change_ratio
        self._membership_update_max_age_days = membership_update_max_age_days
        self._request_interval_seconds = request_interval_seconds
        self._call_timeout_seconds = call_timeout_seconds

    def fetch(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> BackfillBatch:
        self._validate_request(unit, plan)
        retrieved_at = self._clock()
        baostock = cast(Any, self._baostock_module_loader("baostock"))
        login = self._provider_call("login", baostock.login)
        self._require_success(login, "login")
        rejected_rows = 0
        issues: Counter[str] = Counter()
        expected_rows: int | None = None
        payload: SecurityMasterPayload | UniverseMembershipPayload
        cutoff_date: date | None
        try:
            if unit.domain is BackfillDataDomain.SECURITY_MASTER:
                akshare = cast(Any, self._akshare_module_loader("akshare"))
                payload, rejected_rows, issues, expected_rows = self._security_master_payload(
                    baostock,
                    akshare,
                    unit,
                    retrieved_at.date(),
                    requested_symbols=plan.symbols,
                )
                units = (("identity", "record"),)
                cutoff_date = retrieved_at.date()
            else:
                payload = self._universe_payload(baostock, unit, plan)
                units = (("benchmark_membership", "boolean"),)
                cutoff_date = unit.end_date
                expected_rows = None
        finally:
            self._provider_call("logout", baostock.logout)

        warnings = [
            "private local research only; external redistribution is prohibited",
            "current identity and retrieved historical membership remain normalized_current",
            "retrieval time does not establish historical PIT availability",
        ]
        if issues:
            warnings.append("provider rows with unavailable required identity fields were rejected")
        if not payload.rows:
            issues["empty_provider_result"] += 1
            warnings.append("provider returned no accepted rows for the requested work unit")
        quality = DatasetQualityStatus.PASSED if not issues else DatasetQualityStatus.WARNED
        return BackfillBatch(
            work_unit=unit,
            metadata=ProviderRetrievalMetadata(
                provider_id=self.provider_id,
                retrieved_at=retrieved_at,
                cutoff_date=cutoff_date,
                adjustment_mode="not_applicable",
                units=units,
                warnings=tuple(warnings),
            ),
            row_count=len(payload.rows),
            rejected_rows=rejected_rows,
            content_hash=self._content_hash(unit, payload),
            expected_rows=expected_rows,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            quality_status=quality,
            issue_counts=tuple(sorted(issues.items())),
            warnings=tuple(warnings[3:]),
            payload=payload,
        )

    def _validate_request(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> None:
        if plan.provider_id != self.provider_id:
            raise ValueError("plan provider does not match identity/universe source")
        if plan.provider_use is not ProviderUse.PRIVATE_LOCAL_RESEARCH:
            raise ValueError("identity/universe source requires private_local_research use")
        if plan.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("identity/universe source can emit only normalized_current")
        if plan.symbols and not plan.all_a_share:
            if unit.domain is not BackfillDataDomain.SECURITY_MASTER:
                raise ValueError(
                    "explicit-symbol identity source supports only security_master"
                )
        elif not plan.all_a_share or plan.symbols:
            raise ValueError(
                "identity/universe source requires all_a_share or explicit symbols"
            )
        if unit.domain not in {
            BackfillDataDomain.SECURITY_MASTER,
            BackfillDataDomain.UNIVERSE,
        }:
            raise ProviderBackfillUnavailable(
                f"identity/universe source does not implement domain={unit.domain.value}"
            )

    def _security_master_payload(
        self,
        baostock: Any,
        akshare: Any,
        unit: BackfillWorkUnit,
        observed_on: date,
        *,
        requested_symbols: tuple[str, ...],
    ) -> tuple[SecurityMasterPayload, int, Counter[str], int]:
        if unit.market not in _EXCHANGES:
            raise ProviderBackfillUnavailable(
                f"identity source does not support market={unit.market}"
            )
        basic_result = self._provider_call(
            "security master",
            baostock.query_stock_basic,
        )
        self._require_success(basic_result, "security master")
        market_basic_rows = tuple(
            row
            for row in self._result_rows(basic_result)
            if self._security_market(row) == unit.market
        )
        requested = {
            symbol
            for symbol in requested_symbols
            if self._symbol_market(symbol) == unit.market
        }
        basic_rows = tuple(
            row
            for row in market_basic_rows
            if not requested
            or self._canonical_code(self._text(row, "code")) in requested
        )
        if not requested and len(basic_rows) < self._minimum_security_rows:
            raise ProviderBackfillUnavailable(
                "security master row count is below the configured minimum"
            )
        basic_codes = tuple(
            self._canonical_code(self._text(row, "code")) for row in basic_rows
        )
        if len(basic_codes) != len(set(basic_codes)):
            raise ProviderBackfillUnavailable("security master contains duplicate codes")
        missing_symbols = tuple(sorted(requested.difference(basic_codes)))
        if missing_symbols:
            raise ProviderBackfillUnavailable(
                "security master provider omitted requested symbols: "
                f"missing_count={len(missing_symbols)}; "
                f"missing_symbols={','.join(missing_symbols)}"
            )
        industry_result = self._provider_call(
            "industry membership",
            lambda: baostock.query_stock_industry(date=observed_on.isoformat()),
        )
        self._require_success(industry_result, "industry membership")
        industry_rows = tuple(
            row
            for row in self._result_rows(industry_result)
            if self._is_a_share_code(self._text(row, "code"))
        )
        industry_codes = tuple(
            self._canonical_code(self._text(row, "code")) for row in industry_rows
        )
        if len(industry_codes) != len(set(industry_codes)):
            raise ProviderBackfillUnavailable("industry membership contains duplicate codes")
        industries = dict(zip(industry_codes, industry_rows, strict=True))
        accepted: list[StagedSecurityIdentity] = []
        rejected = 0
        issues: Counter[str] = Counter()
        for raw in basic_rows:
            code = self._canonical_code(self._text(raw, "code"))
            listed_on = self._date(raw, "ipoDate")
            legal_name = self._legal_name(akshare, code, listed_on)
            if legal_name is None:
                rejected += 1
                issues["legal_name_unavailable"] += 1
                continue
            delisted_on = self._optional_date(raw, "outDate")
            status = self._text(raw, "status")
            if status not in {"0", "1"}:
                raise ProviderBackfillUnavailable("security status must be 0 or 1")
            industry = industries.get(code)
            taxonomy = None
            industry_name = None
            if industry is not None:
                taxonomy = self._optional_text(industry, "industryClassification")
                industry_name = self._optional_text(industry, "industry")
                if bool(taxonomy) != bool(industry_name):
                    issues["partial_industry_classification"] += 1
                    taxonomy = None
                    industry_name = None
            accepted.append(
                StagedSecurityIdentity(
                    code=code,
                    company_legal_name=legal_name,
                    security_name=self._text(raw, "code_name"),
                    exchange=_EXCHANGES[unit.market],
                    board=self._board(code),
                    listed_on=listed_on,
                    delisted_on=delisted_on,
                    listing_state=(
                        ListingState.ACTIVE if status == "1" else ListingState.TERMINATED
                    ),
                    observed_on=observed_on,
                    industry_taxonomy=taxonomy,
                    industry_code=None,
                    industry_name=industry_name,
                    identity_source_id="baostock_sdk.query_stock_basic",
                    legal_name_source_id="akshare.stock_profile_cninfo",
                    industry_source_id=(
                        None
                        if taxonomy is None
                        else "baostock_sdk.query_stock_industry"
                    ),
                )
            )
        coverage_ratio = len(accepted) / len(basic_rows)
        required_coverage = 1.0 if requested else self._minimum_security_coverage_ratio
        if coverage_ratio < required_coverage:
            raise ProviderBackfillUnavailable(
                "security master accepted-row coverage is below the configured minimum"
            )
        return SecurityMasterPayload(tuple(accepted)), rejected, issues, len(basic_rows)

    def _universe_payload(
        self,
        baostock: Any,
        unit: BackfillWorkUnit,
        plan: BackfillPlan,
    ) -> UniverseMembershipPayload:
        benchmark_code = unit.scope_id.removeprefix("index:")
        try:
            method_name = _SOURCE_METHODS[benchmark_code]
        except KeyError as error:
            raise ProviderBackfillUnavailable(
                f"unsupported benchmark scope={unit.scope_id}"
            ) from error
        query_end = min(plan.end_date, unit.end_date + timedelta(days=14))
        calendar = self._provider_call(
            "universe trading calendar",
            lambda: baostock.query_trade_dates(
                start_date=unit.start_date.isoformat(),
                end_date=query_end.isoformat(),
            ),
        )
        self._require_success(calendar, "universe trading calendar")
        raw_trading_dates = tuple(
            self._date(row, "calendar_date")
            for row in self._result_rows(calendar)
            if self._text(row, "is_trading_day") == "1"
        )
        if len(raw_trading_dates) != len(set(raw_trading_dates)):
            raise ProviderBackfillUnavailable("universe trading calendar contains duplicates")
        if any(
            item < unit.start_date or item > query_end for item in raw_trading_dates
        ):
            raise ProviderBackfillUnavailable("universe trading calendar escaped request bounds")
        trading_dates = tuple(sorted(raw_trading_dates))
        checkpoint_dates = tuple(item for item in trading_dates if item <= unit.end_date)
        if not checkpoint_dates:
            raise ProviderBackfillUnavailable(
                "universe trading calendar contains no checkpoint trading day"
            )
        boundary_date = next((item for item in trading_dates if item > unit.end_date), None)
        if unit.end_date < plan.end_date and boundary_date is None:
            raise ProviderBackfillUnavailable(
                "next annual checkpoint boundary trading day is unavailable"
            )
        active: dict[str, date] = {}
        intervals: list[StagedUniverseMembership] = []
        source_id = f"baostock_sdk.{method_name}"
        query_members = getattr(baostock, method_name)
        previous_members: set[str] | None = None
        for trading_date in checkpoint_dates:
            result = self._provider_call(
                f"{benchmark_code} membership",
                partial(query_members, date=trading_date.isoformat()),
                paced=True,
            )
            self._require_success(result, f"{benchmark_code} membership")
            member_rows = self._result_rows(result)
            if not member_rows:
                raise ProviderBackfillUnavailable(
                    f"{benchmark_code} membership returned an empty snapshot"
                )
            update_dates = tuple(self._date(row, "updateDate") for row in member_rows)
            if any(item > trading_date for item in update_dates):
                raise ProviderBackfillUnavailable(
                    f"{benchmark_code} membership contains a future updateDate"
                )
            if any(
                (trading_date - item).days > self._membership_update_max_age_days
                for item in update_dates
            ):
                raise ProviderBackfillUnavailable(
                    f"{benchmark_code} membership updateDate is implausibly stale"
                )
            member_codes = tuple(self._text(row, "code") for row in member_rows)
            if any(not self._is_a_share_code(code) for code in member_codes):
                raise ProviderBackfillUnavailable(
                    f"{benchmark_code} membership contains a non-A-share code"
                )
            members = {self._canonical_code(code) for code in member_codes}
            if len(members) != len(member_codes):
                raise ProviderBackfillUnavailable(
                    f"{benchmark_code} membership contains duplicate codes"
                )
            lower, upper = self._membership_cardinality_bounds[benchmark_code]
            if not lower <= len(members) <= upper:
                raise ProviderBackfillUnavailable(
                    f"{benchmark_code} membership cardinality escaped configured bounds"
                )
            if previous_members is not None:
                change_ratio = len(previous_members ^ members) / max(
                    len(previous_members),
                    len(members),
                    1,
                )
                if change_ratio > self._maximum_membership_change_ratio:
                    raise ProviderBackfillUnavailable(
                        f"{benchmark_code} membership change ratio exceeded the quality gate"
                    )
            for code in sorted(active.keys() - members):
                intervals.append(
                    StagedUniverseMembership(code, active.pop(code), trading_date, source_id)
                )
            for code in sorted(members - active.keys()):
                active[code] = trading_date
            previous_members = members
        close_on = boundary_date or (unit.end_date + timedelta(days=1))
        for code, valid_from in sorted(active.items()):
            intervals.append(
                StagedUniverseMembership(code, valid_from, close_on, source_id)
            )
        return UniverseMembershipPayload(benchmark_code, tuple(intervals))

    def _legal_name(self, akshare: Any, code: str, listed_on: date) -> str | None:
        symbol = code.split(".", 1)[1]
        for attempt in range(self._profile_attempts):
            try:
                frame = self._provider_call(
                    "CNInfo company profile",
                    lambda: akshare.stock_profile_cninfo(symbol=symbol),
                    paced=True,
                )
                records = frame.to_dict("records")
            except Exception:  # noqa: BLE001 - provider boundary retries, then rejects visibly
                records = ()
            for raw in records:
                row = cast(Mapping[str, object], raw)
                self._validate_cninfo_identity(row, code, symbol, listed_on)
                value = self._optional_text(row, "公司名称")
                if value:
                    return value
            if attempt + 1 < self._profile_attempts:
                self._sleeper(self._profile_retry_delay_seconds * (2**attempt))
        return None

    @classmethod
    def _validate_cninfo_identity(
        cls,
        row: Mapping[str, object],
        code: str,
        symbol: str,
        listed_on: date,
    ) -> None:
        returned_code = cls._optional_text(row, "A股代码")
        if returned_code is not None:
            if cls._cninfo_code(row) != symbol:
                raise ProviderBackfillUnavailable(
                    "CNInfo company profile code mismatch"
                )
            return
        if not code.startswith("SH.689"):
            raise ProviderBackfillUnavailable(
                "A股代码 is missing from provider payload"
            )
        if cls._optional_text(row, "所属市场") != "上交所科创板":
            raise ProviderBackfillUnavailable(
                "CNInfo CDR company profile market mismatch"
            )
        if cls._date(row, "上市日期") != listed_on:
            raise ProviderBackfillUnavailable(
                "CNInfo CDR company profile listing date mismatch"
            )

    @classmethod
    def _cninfo_code(cls, row: Mapping[str, object]) -> str:
        raw = cls._text(row, "A股代码").rsplit(".", 1)[-1]
        if not raw.isdigit() or len(raw) > 6:
            raise ProviderBackfillUnavailable("CNInfo A-share code is invalid")
        return raw.zfill(6)

    def _provider_call(
        self,
        operation: str,
        action: Callable[[], _T],
        *,
        paced: bool = False,
    ) -> _T:
        if paced and self._request_interval_seconds:
            self._sleeper(self._request_interval_seconds)
        outcome: list[tuple[bool, object]] = []

        def invoke() -> None:
            try:
                outcome.append((True, action()))
            except BaseException as error:  # noqa: BLE001 - crosses thread boundary
                outcome.append((False, error))

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        worker.join(self._call_timeout_seconds)
        if worker.is_alive():
            raise ProviderBackfillUnavailable(
                f"{operation} timed out after {self._call_timeout_seconds:g} seconds"
            )
        succeeded, value = outcome[0]
        if not succeeded:
            assert isinstance(value, BaseException)
            raise ProviderBackfillUnavailable(f"{operation} failed: {value}") from value
        return cast(_T, value)

    @staticmethod
    def _security_market(row: Mapping[str, object]) -> str | None:
        code = IdentityUniverseBackfillSource._optional_text(row, "code")
        if code is None or not IdentityUniverseBackfillSource._is_a_share_code(code):
            return None
        return "XSHG" if code.lower().startswith("sh.") else "XSHE"

    @staticmethod
    def _symbol_market(code: str) -> str | None:
        return {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}.get(code[:2])

    @staticmethod
    def _is_a_share_code(value: str) -> bool:
        code = value.lower()
        if code.startswith("sh."):
            return code[3:6] in {"600", "601", "603", "605", "688", "689"}
        if code.startswith("sz."):
            return code[3:6] in {"000", "001", "002", "003", "300", "301"}
        return False

    @staticmethod
    def _canonical_code(value: str) -> str:
        market, digits = value.strip().split(".", 1)
        prefix = {"sh": "SH", "sz": "SZ"}.get(market.lower())
        if prefix is None or len(digits) != 6 or not digits.isdigit():
            raise ProviderBackfillUnavailable(f"unsupported A-share code={value!r}")
        return f"{prefix}.{digits}"

    @staticmethod
    def _board(code: str) -> Board:
        digits = code.split(".", 1)[1]
        if code.startswith("SH.") and digits.startswith(("688", "689")):
            return Board.STAR
        if code.startswith("SZ.") and digits.startswith(("300", "301")):
            return Board.CHINEXT
        return Board.MAIN

    @staticmethod
    def _result_rows(result: Any) -> tuple[Mapping[str, object], ...]:
        fields = tuple(str(item) for item in result.fields)
        rows: list[Mapping[str, object]] = []
        while result.next():
            values = result.get_row_data()
            if len(values) != len(fields):
                raise ProviderBackfillUnavailable("provider row and field counts disagree")
            rows.append(dict(zip(fields, values, strict=True)))
        return tuple(rows)

    @staticmethod
    def _require_success(result: Any, operation: str) -> None:
        if str(getattr(result, "error_code", "")) != "0":
            message = str(getattr(result, "error_msg", "unknown provider error"))
            raise ProviderBackfillUnavailable(f"{operation} failed: {message}")

    @staticmethod
    def _optional_text(row: Mapping[str, object], field: str) -> str | None:
        value = row.get(field)
        text = "" if value is None else str(value).strip()
        return text or None

    @classmethod
    def _text(cls, row: Mapping[str, object], field: str) -> str:
        value = cls._optional_text(row, field)
        if value is None:
            raise ProviderBackfillUnavailable(f"{field} is missing from provider payload")
        return value

    @classmethod
    def _date(cls, row: Mapping[str, object], field: str) -> date:
        try:
            return date.fromisoformat(cls._text(row, field))
        except ValueError as error:
            raise ProviderBackfillUnavailable(f"{field} is not an ISO date") from error

    @classmethod
    def _optional_date(cls, row: Mapping[str, object], field: str) -> date | None:
        value = cls._optional_text(row, field)
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ProviderBackfillUnavailable(f"{field} is not an ISO date") from error

    @staticmethod
    def _content_hash(unit: BackfillWorkUnit, payload: object) -> str:
        document = json.dumps(
            {"checkpoint_key": unit.checkpoint_key, "payload": payload},
            default=str,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(document).hexdigest()}"
