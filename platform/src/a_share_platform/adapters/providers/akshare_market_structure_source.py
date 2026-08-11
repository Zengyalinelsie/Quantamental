"""Rate-limited AkShare/CNInfo market-structure source for private local research."""

from __future__ import annotations

import hashlib
import importlib
import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any, cast

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

from .akshare_market_structure import CninfoMarketStructureNormalizer
from .backfill_payloads import (
    CorporateActionPayload,
    SecurityMasterPayload,
    ShareCapitalPayload,
    StagedCorporateActionObservation,
    StagedSecurityIdentity,
    StagedShareCapitalObservation,
)
from .baostock_backfill import ProviderBackfillUnavailable

_SUPPORTED_DOMAINS = {
    BackfillDataDomain.SECURITY_MASTER,
    BackfillDataDomain.SHARE_CAPITAL,
    BackfillDataDomain.CORPORATE_ACTION,
}
_MARKET_PREFIX = {"XSHG": "SH", "XSHE": "SZ", "XBSE": "BJ"}


class AkshareMarketStructureSource:
    """Fetch approved current observations without promoting them to PIT history.

    AkShare wraps public CNInfo/BSE endpoints. Calls are sequential, paced, bounded,
    and cached for the lifetime of one worker so annual checkpoints do not download
    the same full-history response repeatedly.
    """

    provider_id = "akshare"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        akshare_module_loader: Callable[[str], object] = importlib.import_module,
        normalizer: CninfoMarketStructureNormalizer | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        minimum_interval_seconds: float = 0.5,
        maximum_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if type(maximum_attempts) is not int or maximum_attempts < 1:
            raise ValueError("maximum_attempts must be a positive integer")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        self._clock = clock
        self._akshare_module_loader = akshare_module_loader
        self._normalizer = normalizer or CninfoMarketStructureNormalizer()
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._minimum_interval_seconds = float(minimum_interval_seconds)
        self._maximum_attempts = maximum_attempts
        self._retry_delay_seconds = float(retry_delay_seconds)
        self._call_lock = threading.Lock()
        self._last_started_at: float | None = None
        self._share_cache: dict[
            tuple[str, date, date],
            tuple[datetime, tuple[StagedShareCapitalObservation, ...]],
        ] = {}
        self._action_cache: dict[
            str,
            tuple[datetime, tuple[StagedCorporateActionObservation, ...]],
        ] = {}
        self._bse_rows: tuple[datetime, tuple[Mapping[str, object], ...]] | None = None
        self._profile_cache: dict[str, tuple[datetime, str]] = {}

    def fetch(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> BackfillBatch:
        self._validate(unit, plan)
        akshare = cast(Any, self._akshare_module_loader("akshare"))
        expected_rows: int | None = None
        issue_counts: tuple[tuple[str, int], ...] = ()
        warnings: list[str] = []
        payload: ShareCapitalPayload | CorporateActionPayload | SecurityMasterPayload
        retrieved_at: datetime
        units: tuple[tuple[str, str], ...]

        if unit.domain is BackfillDataDomain.SHARE_CAPITAL:
            payload, retrieved_at = self._share_capital(akshare, unit, plan)
            units = (
                ("total_shares", "shares"),
                ("circulating_shares", "shares"),
                ("free_float_shares", "shares"),
            )
            if not payload.rows:
                issue_counts = (("empty_provider_interval", 1),)
                warnings.append("no share-capital observation was returned for this interval")
        elif unit.domain is BackfillDataDomain.CORPORATE_ACTION:
            payload, retrieved_at = self._corporate_actions(akshare, unit, plan)
            units = (
                ("cash_per_share", "CNY/share"),
                ("share_ratio", "shares/share"),
            )
            if not payload.rows:
                warnings.append("no corporate action was returned for this interval")
        else:
            payload, expected_rows, retrieved_at = self._xbse_security_master(
                akshare,
                unit,
                plan,
            )
            units = (("identity", "record"),)

        metadata_warnings = (
            "private local research only; external redistribution is prohibited",
            "AkShare/CNInfo/BSE observations remain normalized_current",
            "retrieval time and date-only fields do not establish PIT availability",
        )
        return BackfillBatch(
            work_unit=unit,
            metadata=ProviderRetrievalMetadata(
                provider_id=self.provider_id,
                retrieved_at=retrieved_at,
                cutoff_date=(
                    retrieved_at.date()
                    if unit.domain is BackfillDataDomain.SECURITY_MASTER
                    else unit.end_date
                ),
                adjustment_mode="not_applicable",
                units=units,
                warnings=metadata_warnings,
            ),
            row_count=len(payload.rows),
            rejected_rows=0,
            content_hash=self._content_hash(unit, payload),
            expected_rows=expected_rows,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            quality_status=(
                DatasetQualityStatus.WARNED
                if issue_counts
                else DatasetQualityStatus.PASSED
            ),
            issue_counts=issue_counts,
            warnings=tuple(warnings),
            payload=payload,
        )

    def _validate(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> None:
        if plan.provider_id != self.provider_id:
            raise ValueError("plan provider does not match AkShare market-structure source")
        if plan.provider_use is not ProviderUse.PRIVATE_LOCAL_RESEARCH:
            raise ValueError("AkShare persistence requires private_local_research use")
        if plan.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("AkShare source can emit only normalized_current")
        if unit.domain not in _SUPPORTED_DOMAINS:
            raise ProviderBackfillUnavailable(
                f"AkShare market-structure source does not implement domain={unit.domain.value}"
            )
        if unit.market not in _MARKET_PREFIX:
            raise ProviderBackfillUnavailable("market-structure work unit requires a market")
        if unit.domain is BackfillDataDomain.SECURITY_MASTER and unit.market != "XBSE":
            raise ProviderBackfillUnavailable(
                "AkShare market-structure security master implements only XBSE"
            )
        if not plan.symbols and not plan.all_a_share:
            raise ValueError("AkShare market-structure source requires explicit scope")

    def _share_capital(
        self,
        akshare: Any,
        unit: BackfillWorkUnit,
        plan: BackfillPlan,
    ) -> tuple[ShareCapitalPayload, datetime]:
        accepted: list[StagedShareCapitalObservation] = []
        retrieved_times: list[datetime] = []
        for code in self._unit_symbols(unit, plan):
            key = (code, plan.start_date, plan.end_date)
            cached = self._share_cache.get(key)
            if cached is None:
                def fetch_share(current_code: str = code) -> object:
                    return akshare.stock_share_change_cninfo(
                        symbol=current_code.split(".", 1)[1],
                        start_date=plan.start_date.strftime("%Y%m%d"),
                        end_date=plan.end_date.strftime("%Y%m%d"),
                    )

                response = self._call(
                    "stock_share_change_cninfo",
                    fetch_share,
                )
                retrieved_at = self._clock()
                records = self._records(response)
                rows = self._normalizer.share_capital(code=code, records=records).rows
                cached = (retrieved_at, rows)
                self._share_cache[key] = cached
            retrieved_at, rows = cached
            retrieved_times.append(retrieved_at)
            accepted.extend(
                row for row in rows if unit.start_date <= row.effective_on <= unit.end_date
            )
        return (
            ShareCapitalPayload(
                tuple(sorted(accepted, key=lambda row: (row.code, row.effective_on)))
            ),
            max(retrieved_times),
        )

    def _corporate_actions(
        self,
        akshare: Any,
        unit: BackfillWorkUnit,
        plan: BackfillPlan,
    ) -> tuple[CorporateActionPayload, datetime]:
        accepted: list[StagedCorporateActionObservation] = []
        retrieved_times: list[datetime] = []
        for code in self._unit_symbols(unit, plan):
            cached = self._action_cache.get(code)
            if cached is None:
                def fetch_actions(current_code: str = code) -> object:
                    return akshare.stock_dividend_cninfo(
                        symbol=current_code.split(".", 1)[1]
                    )

                response = self._call(
                    "stock_dividend_cninfo",
                    fetch_actions,
                )
                retrieved_at = self._clock()
                records = self._records(response)
                rows = self._normalizer.corporate_actions(code=code, records=records).rows
                cached = (retrieved_at, rows)
                self._action_cache[code] = cached
            retrieved_at, rows = cached
            retrieved_times.append(retrieved_at)
            for row in rows:
                event_date = row.ex_date or row.record_date or row.announced_on
                if event_date is None:
                    raise ProviderBackfillUnavailable(
                        f"corporate action has no checkpoint date: {row.provider_record_id}"
                    )
                if unit.start_date <= event_date <= unit.end_date:
                    accepted.append(row)
        return (
            CorporateActionPayload(
                tuple(
                    sorted(
                        accepted,
                        key=lambda row: (
                            row.code,
                            row.ex_date or row.record_date or row.announced_on or date.min,
                            row.provider_record_id,
                        ),
                    ),
                )
            ),
            max(retrieved_times),
        )

    def _xbse_security_master(
        self,
        akshare: Any,
        unit: BackfillWorkUnit,
        plan: BackfillPlan,
    ) -> tuple[SecurityMasterPayload, int, datetime]:
        if self._bse_rows is None:
            response = self._call(
                "stock_info_bj_name_code",
                akshare.stock_info_bj_name_code,
            )
            self._bse_rows = (self._clock(), self._records(response))
        bse_retrieved_at, bse_rows = self._bse_rows
        keyed: dict[str, Mapping[str, object]] = {}
        for raw in bse_rows:
            digits = self._digits(raw.get("证券代码"), "证券代码")
            code = f"BJ.{digits}"
            if code in keyed:
                raise ProviderBackfillUnavailable("XBSE security master contains duplicate codes")
            keyed[code] = raw
        requested = set(self._unit_symbols(unit, plan))
        selected_codes = tuple(sorted(keyed if plan.all_a_share else requested))
        missing = tuple(sorted(requested.difference(keyed)))
        if missing:
            raise ProviderBackfillUnavailable(
                "XBSE security master omitted requested symbols: " + ",".join(missing)
            )
        accepted: list[StagedSecurityIdentity] = []
        retrieved_times = [bse_retrieved_at]
        for code in selected_codes:
            raw = keyed[code]
            digits = code.split(".", 1)[1]
            listed_on = self._required_date(raw.get("上市日期"), "上市日期")
            if listed_on > bse_retrieved_at.date():
                raise ProviderBackfillUnavailable("XBSE listing date cannot be in the future")
            legal_name, profile_retrieved_at = self._legal_name(akshare, digits)
            retrieved_times.append(profile_retrieved_at)
            observed_on = max(bse_retrieved_at, profile_retrieved_at).date()
            industry = self._optional_text(raw.get("所属行业"))
            accepted.append(
                StagedSecurityIdentity(
                    code=code,
                    company_legal_name=legal_name,
                    security_name=self._required_text(raw.get("证券简称"), "证券简称"),
                    exchange=Exchange.XBSE,
                    board=Board.BSE,
                    listed_on=listed_on,
                    delisted_on=None,
                    listing_state=ListingState.ACTIVE,
                    observed_on=observed_on,
                    industry_taxonomy=("BSE current industry" if industry else None),
                    industry_code=None,
                    industry_name=industry,
                    identity_source_id="akshare.stock_info_bj_name_code",
                    legal_name_source_id="akshare.stock_profile_cninfo",
                    industry_source_id=(
                        "akshare.stock_info_bj_name_code" if industry else None
                    ),
                )
            )
        return SecurityMasterPayload(tuple(accepted)), len(selected_codes), max(retrieved_times)

    def _legal_name(self, akshare: Any, digits: str) -> tuple[str, datetime]:
        cached = self._profile_cache.get(digits)
        if cached is not None:
            retrieved_at, legal_name = cached
            return legal_name, retrieved_at
        response = self._call(
            "stock_profile_cninfo",
            lambda: akshare.stock_profile_cninfo(symbol=digits),
        )
        retrieved_at = self._clock()
        records = self._records(response)
        if len(records) != 1:
            raise ProviderBackfillUnavailable(
                f"XBSE legal company profile must contain one row: code={digits}"
            )
        profile = records[0]
        profile_code = self._digits(profile.get("A股代码"), "A股代码")
        if profile_code != digits:
            raise ProviderBackfillUnavailable(
                f"XBSE profile code mismatch: expected={digits}, actual={profile_code}"
            )
        legal_name = self._required_text(profile.get("公司名称"), "公司名称")
        self._profile_cache[digits] = (retrieved_at, legal_name)
        return legal_name, retrieved_at

    def _unit_symbols(
        self,
        unit: BackfillWorkUnit,
        plan: BackfillPlan,
    ) -> tuple[str, ...]:
        prefix = _MARKET_PREFIX[cast(str, unit.market)] + "."
        selected = tuple(sorted(symbol for symbol in plan.symbols if symbol.startswith(prefix)))
        if not selected and not plan.all_a_share:
            raise ProviderBackfillUnavailable(
                f"no explicit symbols belong to market={unit.market}"
            )
        return selected

    def _call(self, operation: str, action: Callable[[], object]) -> object:
        with self._call_lock:
            for attempt in range(1, self._maximum_attempts + 1):
                self._pace()
                try:
                    return action()
                except Exception as error:
                    if attempt == self._maximum_attempts:
                        raise ProviderBackfillUnavailable(
                            f"AkShare {operation} failed after {attempt} attempts: "
                            f"{type(error).__name__}: {error}"
                        ) from error
                    self._sleeper(self._retry_delay_seconds * attempt)
        raise AssertionError("unreachable")

    def _pace(self) -> None:
        now = self._monotonic()
        if self._last_started_at is not None:
            remaining = self._minimum_interval_seconds - (now - self._last_started_at)
            if remaining > 0:
                self._sleeper(remaining)
                now = self._monotonic()
        self._last_started_at = now

    @staticmethod
    def _records(value: object) -> tuple[Mapping[str, object], ...]:
        converter = getattr(value, "to_dict", None)
        if not callable(converter):
            raise ProviderBackfillUnavailable("AkShare response is not a DataFrame-like table")
        raw = converter("records")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise ProviderBackfillUnavailable("AkShare records response must be a sequence")
        records: list[Mapping[str, object]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise ProviderBackfillUnavailable("AkShare records must be mappings")
            records.append(cast(Mapping[str, object], item))
        return tuple(records)

    @staticmethod
    def _digits(value: object, field: str) -> str:
        text = AkshareMarketStructureSource._required_text(value, field)
        digits = text.split(".")[-1].zfill(6)
        if len(digits) != 6 or not digits.isdigit():
            raise ProviderBackfillUnavailable(f"{field} must be a six-digit A-share code")
        return digits

    @staticmethod
    def _required_text(value: object, field: str) -> str:
        text = "" if value is None else str(value).strip()
        if not text:
            raise ProviderBackfillUnavailable(f"{field} is missing from provider payload")
        return text

    @staticmethod
    def _optional_text(value: object) -> str | None:
        text = "" if value is None else str(value).strip()
        return text or None

    @classmethod
    def _required_date(cls, value: object, field: str) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(cls._required_text(value, field)[:10])
        except ValueError as error:
            raise ProviderBackfillUnavailable(f"{field} must be an ISO date") from error

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
