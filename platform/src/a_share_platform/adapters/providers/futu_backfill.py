"""Futu quote-only source for bounded private local raw-bar staging."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

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
from a_share_platform.domain.security_master import Exchange

from .backfill_payloads import DailyObservationPayload, StagedDailyObservation
from .futu_quote import FutuQuoteDailyReader

_MARKET_PREFIX = {"XSHG": "SH", "XSHE": "SZ"}
_EXCHANGES = {"XSHG": Exchange.XSHG, "XSHE": Exchange.XSHE}


class FutuQuoteBackfillSource:
    provider_id = "futu_quote"

    def __init__(self, *, reader: FutuQuoteDailyReader) -> None:
        self._reader = reader

    def fetch(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> BackfillBatch:
        if plan.provider_id != self.provider_id:
            raise ValueError("plan provider does not match Futu quote source")
        if plan.provider_use is not ProviderUse.PRIVATE_LOCAL_RESEARCH:
            raise ValueError("Futu executable source requires private_local_research use")
        if plan.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("Futu quote source can emit only normalized_current")
        if unit.domain is not BackfillDataDomain.RAW_DAILY_BAR:
            raise ValueError(f"futu_quote does not implement domain={unit.domain.value}")
        if unit.market not in _MARKET_PREFIX:
            raise ValueError(f"futu_quote does not support market={unit.market}")
        prefix = _MARKET_PREFIX[unit.market]
        staged: list[StagedDailyObservation] = []
        metadata: list[ProviderRetrievalMetadata] = []
        for symbol in (item for item in plan.symbols if item.startswith(prefix + ".")):
            result = self._reader.fetch_raw_daily_rows(
                code=symbol,
                start_date=unit.start_date,
                end_date=unit.end_date,
            )
            metadata.append(result.metadata)
            staged.extend(self._normalize(row, unit.market) for row in result.rows)
        payload = DailyObservationPayload(tuple(staged))
        warnings = {
            warning
            for item in metadata
            for warning in item.warnings
        }
        warnings.add("private local research only; external redistribution is prohibited")
        if not staged:
            warnings.add("provider returned no rows for the requested work unit")
        retrieved_at = max(item.retrieved_at for item in metadata) if metadata else plan.created_at
        cutoffs = [item.cutoff_date for item in metadata if item.cutoff_date is not None]
        return BackfillBatch(
            work_unit=unit,
            metadata=ProviderRetrievalMetadata(
                provider_id=self.provider_id,
                retrieved_at=retrieved_at,
                cutoff_date=max(cutoffs) if cutoffs else None,
                adjustment_mode="unadjusted",
                units=(
                    ("open", "CNY/share"),
                    ("high", "CNY/share"),
                    ("low", "CNY/share"),
                    ("close", "CNY/share"),
                    ("last_close", "CNY/share"),
                    ("volume", "shares"),
                    ("turnover", "CNY"),
                ),
                warnings=tuple(sorted(warnings)),
            ),
            row_count=len(staged),
            rejected_rows=0,
            content_hash=self._content_hash(unit, payload),
            expected_rows=None,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            quality_status=(
                DatasetQualityStatus.PASSED if staged else DatasetQualityStatus.WARNED
            ),
            issue_counts=(() if staged else (("empty_provider_result", 1),)),
            warnings=(() if staged else ("empty provider result",)),
            payload=payload,
        )

    def _normalize(
        self,
        row: Mapping[str, object],
        market: str,
    ) -> StagedDailyObservation:
        code = self._text(row, "code")
        session_date = self._date(row, "time_key")
        return StagedDailyObservation(
            code=code,
            exchange=_EXCHANGES[market],
            session_date=session_date,
            currency="CNY",
            open=self._decimal(row, "open"),
            high=self._decimal(row, "high"),
            low=self._decimal(row, "low"),
            close=self._decimal(row, "close"),
            previous_close=self._decimal(row, "last_close"),
            volume_shares=self._integer(row, "volume"),
            amount=self._decimal(row, "turnover", allow_zero=True),
            is_trading=True,
            special_treatment=None,
            source_id=self.provider_id,
        )

    @staticmethod
    def _text(row: Mapping[str, object], field: str) -> str:
        value = row.get(field)
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError(f"{field} is missing from Futu quote row")
        return text

    @classmethod
    def _date(cls, row: Mapping[str, object], field: str) -> date:
        try:
            return date.fromisoformat(cls._text(row, field)[:10])
        except ValueError as error:
            raise ValueError(f"{field} is not an ISO-compatible date") from error

    @classmethod
    def _decimal(
        cls,
        row: Mapping[str, object],
        field: str,
        *,
        allow_zero: bool = False,
    ) -> Decimal:
        try:
            value = Decimal(cls._text(row, field))
        except InvalidOperation as error:
            raise ValueError(f"{field} is not a decimal") from error
        if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
            raise ValueError(f"{field} is outside the normalized range")
        return value

    @classmethod
    def _integer(cls, row: Mapping[str, object], field: str) -> int:
        try:
            value = int(cls._text(row, field))
        except ValueError as error:
            raise ValueError(f"{field} is not an integer") from error
        if value < 0:
            raise ValueError(f"{field} cannot be negative")
        return value

    @staticmethod
    def _content_hash(unit: BackfillWorkUnit, payload: DailyObservationPayload) -> str:
        document = json.dumps(
            {"checkpoint_key": unit.checkpoint_key, "payload": payload},
            default=str,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(document).hexdigest()}"
