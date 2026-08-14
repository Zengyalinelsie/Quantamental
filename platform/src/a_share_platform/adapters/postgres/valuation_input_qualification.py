"""Read-only qualification of real financial, price, and comparable inputs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import unquote, urlparse

import duckdb
import psycopg

from a_share_platform.domain.features import FeaturePeriod
from a_share_platform.domain.fundamental_improvement import (
    BaseEffectTreatment,
    FundamentalImprovementExposures,
    FundamentalImprovementInput,
    FundamentalImprovementMetric,
    ImprovementComparison,
    ImprovementInputProvenance,
    ImprovementWindow,
    OneOffTreatment,
    SeasonalityTreatment,
)
from a_share_platform.domain.industry_templates import IndustryTemplateId
from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import (
    ValuationExpectationMetric,
    ValuationExpectationRangeInput,
    ValuationExpectationSource,
    ValuationExposures,
    ValuationInputProvenance,
    ValuationMetric,
    ValuationMetricInput,
)
from a_share_platform.domain.valuation_input_qualification import (
    ValuationInputDomain,
    ValuationInputDomainEvidence,
    ValuationInputQualification,
    ValuationInputQualificationRequest,
)
from a_share_platform.domain.valuation_scenarios import (
    ValuationScenario,
    ValuationScenarioInput,
    ValuationScenarioProvenance,
)
from a_share_platform.ports.valuation_inputs import ValuationImprovementInputBundle

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_FINANCIAL_METRICS = frozenset(
    {
        "income.total_operating_revenue",
        "income.net_profit",
        "cash_flow.net_operating_cash_flow",
        "balance.total_equity",
    }
)
_IMPROVEMENT_METRICS = frozenset(
    {
        "income.total_operating_revenue",
        "income.net_profit",
        "cash_flow.net_operating_cash_flow",
    }
)
_QUARTER_INDEX = {(3, 31): 0, (6, 30): 1, (9, 30): 2, (12, 31): 3}


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _quarter_ordinal(value: date) -> int | None:
    index = _QUARTER_INDEX.get((value.month, value.day))
    return None if index is None else value.year * 4 + index


@dataclass(frozen=True)
class FrozenPriceObservation:
    observation_id: str
    listing_id: str
    session_date: date
    close: Decimal
    currency: str
    dataset_version_id: str
    source_id: str
    trust_state: DataTrustState
    available_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "listing_id",
            "dataset_version_id",
            "source_id",
        ):
            _text(getattr(self, field_name), field_name)
        if not isinstance(self.session_date, date) or isinstance(self.session_date, datetime):
            raise TypeError("session_date must be a date")
        if not isinstance(self.close, Decimal) or not self.close.is_finite() or self.close <= 0:
            raise ValueError("close must be a positive finite Decimal")
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ValueError("currency must be a three-letter uppercase code")
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        _aware(self.available_at, "available_at")
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")


class QueryResult(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]
PriceReader = Callable[
    [str, str, date, str, datetime, str],
    FrozenPriceObservation | None,
]


class ValuationInputQualificationUnavailable(RuntimeError):
    """The real PostgreSQL input catalog cannot be inspected."""


@dataclass(frozen=True)
class PostgresValuationInputCompilation:
    qualification: ValuationInputQualification
    bundle: ValuationImprovementInputBundle | None

    def __post_init__(self) -> None:
        if not isinstance(self.qualification, ValuationInputQualification):
            raise TypeError("qualification must be a ValuationInputQualification")
        if self.bundle is not None and not isinstance(
            self.bundle, ValuationImprovementInputBundle
        ):
            raise TypeError("bundle must be a ValuationImprovementInputBundle")
        if self.qualification.is_qualified != (self.bundle is not None):
            raise ValueError("qualified compilation must contain exactly one frozen bundle")


class DuckDbFrozenPriceReader:
    """Read one exact listing from a PostgreSQL-catalogued immutable Parquet file."""

    def __call__(
        self,
        storage_uri: str,
        listing_id: str,
        decision_date: date,
        dataset_version_id: str,
        available_at: datetime,
        content_hash: str,
    ) -> FrozenPriceObservation | None:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "file":
            return None
        path = Path(unquote(parsed.path))
        if not path.is_file():
            return None
        connection = duckdb.connect(":memory:")
        try:
            row = connection.execute(
                """
                SELECT listing_id, session_date, close, currency, source_id,
                       dataset_version_id, trust_state
                FROM read_parquet(?)
                WHERE listing_id = %s AND session_date <= %s
                  AND dataset_version_id = %s
                ORDER BY session_date DESC, source_id
                LIMIT 1
                """.replace("%s", "?"),
                (str(path), listing_id, decision_date, dataset_version_id),
            ).fetchone()
        except duckdb.Error:
            return None
        finally:
            connection.close()
        if row is None:
            return None
        return FrozenPriceObservation(
            observation_id=(
                f"price:{row[0]}:{row[1].isoformat()}:{row[4]}:{row[5]}"
            ),
            listing_id=str(row[0]),
            session_date=cast(date, row[1]),
            close=cast(Decimal, row[2]),
            currency=str(row[3]),
            source_id=str(row[4]),
            dataset_version_id=str(row[5]),
            trust_state=DataTrustState(str(row[6])),
            available_at=available_at,
            content_hash=content_hash,
        )


class PostgresValuationInputQualificationSource:
    """Inspect all three source domains without computing or persisting a bundle."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        price_reader: PriceReader | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._price_reader = price_reader or DuckDbFrozenPriceReader()

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresValuationInputQualificationSource:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def inspect(
        self,
        request: ValuationInputQualificationRequest,
    ) -> ValuationInputQualification:
        if not isinstance(request, ValuationInputQualificationRequest):
            raise TypeError("request must be a ValuationInputQualificationRequest")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                financial = self._financial(connection, request)
                price = self._price(connection, request)
                comparable = self._comparable(connection, request)
        except psycopg.OperationalError as error:
            raise ValuationInputQualificationUnavailable(
                "PostgreSQL valuation input qualification is unavailable"
            ) from error
        return ValuationInputQualification(
            security_id=request.security_id,
            decision_time=request.decision_time,
            data_mode=request.data_mode,
            requested_trust_state=request.requested_trust_state,
            domain_evidence=(financial, price, comparable),
        )

    def compile(
        self,
        request: ValuationInputQualificationRequest,
    ) -> PostgresValuationInputCompilation:
        """Compile one deterministic bundle or return the exact failed qualification."""

        if not isinstance(request, ValuationInputQualificationRequest):
            raise TypeError("request must be a ValuationInputQualificationRequest")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                financial = self._financial(connection, request)
                price = self._price(connection, request)
                comparable = self._comparable(connection, request)
                qualification = ValuationInputQualification(
                    security_id=request.security_id,
                    decision_time=request.decision_time,
                    data_mode=request.data_mode,
                    requested_trust_state=request.requested_trust_state,
                    domain_evidence=(financial, price, comparable),
                )
                if not qualification.is_qualified:
                    return PostgresValuationInputCompilation(qualification, None)
                financial_rows = self._financial_rows(connection, request)
                price_rows = self._price_catalog_rows(connection, request)
                selected_price, selected_price_row = self._select_price(
                    price_rows,
                    request,
                )
                industry_rows = connection.execute(
                    """
                    /* subject industry code */
                    SELECT industry_code
                    FROM canonical.industry_memberships
                    WHERE security_id = %s
                      AND valid_from <= %s
                      AND (valid_to IS NULL OR %s < valid_to)
                      AND trust_state = %s
                      AND dataset_version_id IS NOT NULL
                      AND observed_at <= %s
                      AND industry_code IS NOT NULL
                    ORDER BY observed_at DESC, industry_membership_id DESC
                    LIMIT 1
                    """,
                    (
                        request.security_id,
                        request.decision_time.date(),
                        request.decision_time.date(),
                        request.requested_trust_state.value,
                        request.decision_time,
                    ),
                ).fetchall()
                if (
                    selected_price is None
                    or selected_price_row is None
                    or len(industry_rows) != 1
                ):
                    raise RuntimeError(
                        "qualified valuation input rows changed inside repeatable-read compilation"
                    )
                frozen = self._build_bundle(
                    request=request,
                    qualification=qualification,
                    financial_rows=financial_rows,
                    price=selected_price,
                    price_catalog_row=selected_price_row,
                    industry_code=str(industry_rows[0][0]),
                )
                return PostgresValuationInputCompilation(qualification, frozen)
        except psycopg.OperationalError as error:
            raise ValuationInputQualificationUnavailable(
                "PostgreSQL valuation input compilation is unavailable"
            ) from error

    @classmethod
    def _build_bundle(
        cls,
        *,
        request: ValuationInputQualificationRequest,
        qualification: ValuationInputQualification,
        financial_rows: Sequence[Sequence[object]],
        price: FrozenPriceObservation,
        price_catalog_row: Sequence[object],
        industry_code: str,
    ) -> ValuationImprovementInputBundle:
        window = cls._improvement_window(financial_rows)
        if window is None:
            raise RuntimeError("qualified financial rows lost their improvement window")
        current, prior, current_comparison, prior_comparison = window
        indexed = {(str(row[1]), cast(date, row[2])): row for row in financial_rows}

        def point(metric: str, period: date) -> Sequence[object]:
            try:
                return indexed[(metric, period)]
            except KeyError as error:
                raise RuntimeError(f"qualified financial point disappeared: {metric}/{period}") from error

        def number(row: Sequence[object]) -> Decimal:
            value = Decimal(str(row[8]))
            if not value.is_finite():
                raise ValueError("financial input must be finite")
            return value

        evidence_by_domain = {
            evidence.domain: evidence for evidence in qualification.domain_evidence
        }
        financial_evidence = evidence_by_domain[ValuationInputDomain.FINANCIAL]
        price_evidence = evidence_by_domain[ValuationInputDomain.PRICE]
        comparable_evidence = evidence_by_domain[ValuationInputDomain.COMPARABLE]

        def valuation_provenance(
            *,
            method_id: str,
            evidence: tuple[ValuationInputDomainEvidence, ...],
            observations: tuple[str, ...] = (),
            hashes: tuple[str, ...] = (),
        ) -> ValuationInputProvenance:
            datasets = tuple(
                sorted(
                    {
                        dataset_id
                        for item in evidence
                        for dataset_id in item.dataset_version_ids
                    }
                )
            )
            source_observations = tuple(
                sorted(
                    set(observations).union(
                        observation_id
                        for item in evidence
                        for observation_id in item.observation_ids
                    )
                )
            )
            content_hashes = tuple(
                sorted(
                    set(hashes).union(
                        content_hash
                        for item in evidence
                        for content_hash in item.content_hashes
                    )
                )
            )
            return ValuationInputProvenance(
                dataset_version_id=datasets[0],
                additional_dataset_version_ids=datasets[1:],
                method_id=method_id,
                method_version="v1",
                source_observation_ids=source_observations,
                content_hashes=content_hashes,
            )

        financial_price_provenance = valuation_provenance(
            method_id="valuation:per-share-price-ratio:v1",
            evidence=(financial_evidence, price_evidence),
        )
        financial_only_provenance = valuation_provenance(
            method_id="valuation:fundamental-anchor-unavailable:v1",
            evidence=(financial_evidence,),
        )
        price_only_provenance = valuation_provenance(
            method_id="valuation:market-implied-unavailable:v1",
            evidence=(price_evidence,),
        )
        financial_available = cast(datetime, financial_evidence.latest_source_available_at)
        price_available = cast(datetime, price_evidence.latest_source_available_at)
        comparable_available = cast(
            datetime,
            comparable_evidence.latest_source_available_at,
        )
        financial_price_available = max(financial_available, price_available)

        profit_row = point("income.net_profit", current)
        equity_row = point("balance.total_equity", current)
        if str(profit_row[9]) != "currency" or str(equity_row[9]) != "currency":
            raise ValueError("valuation financial inputs must use canonical currency units")
        currency = str(profit_row[10])
        if currency != str(equity_row[10]) or currency != price.currency:
            raise ValueError("valuation financial and price currencies must match")
        shares = Decimal(str(price_catalog_row[10]))
        if not shares.is_finite() or shares <= 0:
            raise ValueError("share capital must be a positive finite Decimal")

        def valuation_metric(
            metric: ValuationMetric,
            numerator: Decimal | None,
            denominator: Decimal | None,
            numerator_unit: MetricUnit,
            numerator_period: FeaturePeriod,
            denominator_unit: MetricUnit,
            denominator_period: FeaturePeriod,
            *,
            unavailable_reason: str | None = None,
        ) -> ValuationMetricInput:
            return ValuationMetricInput(
                metric=metric,
                numerator=numerator,
                denominator=denominator,
                numerator_unit=numerator_unit,
                numerator_period=numerator_period,
                denominator_unit=denominator_unit,
                denominator_period=denominator_period,
                currency=currency,
                provenance=financial_price_provenance,
                data_mode=request.data_mode,
                trust_state=request.requested_trust_state,
                unavailable_reasons=(
                    () if unavailable_reason is None else (unavailable_reason,)
                ),
                decision_time=request.decision_time,
                latest_source_available_at=financial_price_available,
            )

        valuation_metrics = (
            valuation_metric(
                ValuationMetric.EARNINGS_TO_PRICE,
                number(profit_row) / shares,
                price.close,
                MetricUnit.CURRENCY_PER_SHARE,
                FeaturePeriod.TTM,
                MetricUnit.CURRENCY_PER_SHARE,
                FeaturePeriod.INSTANT,
            ),
            valuation_metric(
                ValuationMetric.BOOK_TO_PRICE,
                number(equity_row) / shares,
                price.close,
                MetricUnit.CURRENCY_PER_SHARE,
                FeaturePeriod.INSTANT,
                MetricUnit.CURRENCY_PER_SHARE,
                FeaturePeriod.INSTANT,
            ),
            valuation_metric(
                ValuationMetric.FREE_CASH_FLOW_YIELD,
                None,
                None,
                MetricUnit.CURRENCY_PER_SHARE,
                FeaturePeriod.TTM,
                MetricUnit.CURRENCY_PER_SHARE,
                FeaturePeriod.INSTANT,
                unavailable_reason="capital expenditure is unavailable; free cash flow was not inferred",
            ),
            valuation_metric(
                ValuationMetric.ENTERPRISE_VALUE_TO_EBIT,
                None,
                None,
                MetricUnit.CURRENCY,
                FeaturePeriod.INSTANT,
                MetricUnit.CURRENCY,
                FeaturePeriod.TTM,
                unavailable_reason="debt, cash, and EBIT inputs are incomplete; enterprise value was not inferred",
            ),
        )

        market_implied = ValuationExpectationRangeInput(
            source=ValuationExpectationSource.MARKET_IMPLIED,
            expectation_metric=ValuationExpectationMetric.GROWTH,
            lower=None,
            upper=None,
            unit=MetricUnit.RATIO,
            assumptions=("No approved market-implied expectation model is bound to this bundle.",),
            invalidation_conditions=("Compile a new bundle after an approved model is available.",),
            provenance=price_only_provenance,
            data_mode=request.data_mode,
            trust_state=request.requested_trust_state,
            unavailable_reasons=("market-implied expectation interval is unavailable",),
            decision_time=request.decision_time,
            latest_source_available_at=price_available,
        )
        fundamental_anchor = ValuationExpectationRangeInput(
            source=ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
            expectation_metric=ValuationExpectationMetric.GROWTH,
            lower=None,
            upper=None,
            unit=MetricUnit.RATIO,
            assumptions=("No approved fundamental-anchor model is bound to this bundle.",),
            invalidation_conditions=("Compile a new bundle after an approved model is available.",),
            provenance=financial_only_provenance,
            data_mode=request.data_mode,
            trust_state=request.requested_trust_state,
            unavailable_reasons=("fundamental-anchor expectation interval is unavailable",),
            decision_time=request.decision_time,
            latest_source_available_at=financial_available,
        )

        def change(metric: str, value_date: date, comparison_date: date) -> Decimal:
            comparison = number(point(metric, comparison_date))
            if comparison == 0:
                raise ValueError(f"{metric} comparison value is zero")
            return number(point(metric, value_date)) / comparison - Decimal(1)

        def improvement_provenance(
            metric: FundamentalImprovementMetric,
            rows: tuple[Sequence[object], ...],
        ) -> ImprovementInputProvenance:
            datasets = tuple(sorted({str(row[3]) for row in rows}))
            sources = tuple(sorted({str(row[4]) for row in rows}))
            mappings = tuple(sorted({str(row[12]) for row in rows}))
            mapping_id = (
                mappings[0]
                if len(mappings) == 1
                else "mapping-set:"
                + hashlib.sha256("|".join(mappings).encode()).hexdigest()
            )
            return ImprovementInputProvenance(
                dataset_version_id=datasets[0],
                additional_dataset_version_ids=datasets[1:],
                source_version_id="source-set:" + hashlib.sha256("|".join(sources).encode()).hexdigest(),
                mapping_version_id=mapping_id,
                metric_definition_id=f"metric:{metric.value}",
                metric_definition_version="v1",
                source_fact_ids=tuple(sorted(str(row[0]) for row in rows)),
                content_hashes=tuple(sorted({str(row[6]) for row in rows})),
            )

        improvement_inputs: list[FundamentalImprovementInput] = []
        metric_bindings = {
            FundamentalImprovementMetric.REVENUE: "income.total_operating_revenue",
            FundamentalImprovementMetric.PROFIT: "income.net_profit",
            FundamentalImprovementMetric.CASH_FLOW: "cash_flow.net_operating_cash_flow",
        }
        for metric, financial_metric in metric_bindings.items():
            rows = tuple(
                point(financial_metric, period)
                for period in (current, current_comparison, prior, prior_comparison)
            )
            improvement_inputs.append(
                FundamentalImprovementInput(
                    metric=metric,
                    level=number(rows[0]),
                    current_change=change(financial_metric, current, current_comparison),
                    prior_change=change(financial_metric, prior, prior_comparison),
                    level_unit=MetricUnit.CURRENCY,
                    change_unit=MetricUnit.RATIO,
                    currency=currency,
                    comparison=ImprovementComparison.YOY,
                    window=ImprovementWindow.TTM,
                    current_period_end=current,
                    current_comparison_period_end=current_comparison,
                    prior_period_end=prior,
                    prior_comparison_period_end=prior_comparison,
                    seasonality_treatment=SeasonalityTreatment.YOY_COMPARABLE,
                    base_effect_treatment=BaseEffectTreatment.UNKNOWN,
                    one_off_treatment=OneOffTreatment.UNKNOWN,
                    provenance=improvement_provenance(metric, rows),
                    data_mode=request.data_mode,
                    trust_state=request.requested_trust_state,
                    decision_time=request.decision_time,
                    latest_source_available_at=financial_available,
                )
            )

        margin_rows = tuple(
            row
            for period in (current, current_comparison, prior, prior_comparison)
            for row in (
                point("income.net_profit", period),
                point("income.total_operating_revenue", period),
            )
        )

        def margin(period: date) -> Decimal:
            revenue = number(point("income.total_operating_revenue", period))
            if revenue == 0:
                raise ValueError("margin denominator revenue is zero")
            return number(point("income.net_profit", period)) / revenue

        improvement_inputs.append(
            FundamentalImprovementInput(
                metric=FundamentalImprovementMetric.MARGIN,
                level=margin(current),
                current_change=margin(current) - margin(current_comparison),
                prior_change=margin(prior) - margin(prior_comparison),
                level_unit=MetricUnit.RATIO,
                change_unit=MetricUnit.RATIO,
                currency=None,
                comparison=ImprovementComparison.YOY,
                window=ImprovementWindow.TTM,
                current_period_end=current,
                current_comparison_period_end=current_comparison,
                prior_period_end=prior,
                prior_comparison_period_end=prior_comparison,
                seasonality_treatment=SeasonalityTreatment.YOY_COMPARABLE,
                base_effect_treatment=BaseEffectTreatment.UNKNOWN,
                one_off_treatment=OneOffTreatment.UNKNOWN,
                provenance=improvement_provenance(
                    FundamentalImprovementMetric.MARGIN,
                    margin_rows,
                ),
                data_mode=request.data_mode,
                trust_state=request.requested_trust_state,
                decision_time=request.decision_time,
                latest_source_available_at=financial_available,
            )
        )

        comparable_datasets = comparable_evidence.dataset_version_ids
        scenario_provenance = ValuationScenarioProvenance(
            dataset_version_id=comparable_datasets[0],
            additional_dataset_version_ids=comparable_datasets[1:],
            source_observation_ids=comparable_evidence.observation_ids,
            content_hashes=comparable_evidence.content_hashes,
        )
        scenario_inputs = tuple(
            ValuationScenarioInput(
                scenario=scenario,
                driver_lower=None,
                driver_upper=None,
                driver_unit=MetricUnit.RATIO,
                assumptions=("No approved scenario interval is bound to this frozen bundle.",),
                provenance=scenario_provenance,
                data_mode=request.data_mode,
                trust_state=request.requested_trust_state,
                unavailable_reasons=(
                    f"{scenario.value} scenario interval is unavailable",
                ),
                decision_time=request.decision_time,
                latest_source_available_at=comparable_available,
            )
            for scenario in ValuationScenario
        )

        comparable_payload = {
            "datasets": comparable_evidence.dataset_version_ids,
            "observations": comparable_evidence.observation_ids,
            "hashes": comparable_evidence.content_hashes,
        }
        comparable_hash = hashlib.sha256(
            json.dumps(comparable_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        bundle_payload = {
            "security_id": request.security_id,
            "decision_time": request.decision_time.isoformat(),
            "data_mode": request.data_mode.value,
            "trust_state": request.requested_trust_state.value,
            "datasets": qualification.dataset_version_ids,
            "observations": tuple(
                observation_id
                for evidence in qualification.domain_evidence
                for observation_id in evidence.observation_ids
            ),
            "hashes": tuple(
                content_hash
                for evidence in qualification.domain_evidence
                for content_hash in evidence.content_hashes
            ),
        }
        bundle_hash = hashlib.sha256(
            json.dumps(bundle_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        market_cap = price.close * shares
        template = (
            IndustryTemplateId.BANK
            if industry_code.startswith("J66")
            else IndustryTemplateId.MANUFACTURING_CONSUMER
            if industry_code.startswith("C")
            else IndustryTemplateId.NON_FINANCIAL_GENERAL
        )
        exposures = ValuationExposures(
            industry_code=industry_code,
            log_market_cap=market_cap.ln(),
            beta=None,
        )
        improvement_exposures = FundamentalImprovementExposures(
            industry_code=industry_code,
            log_market_cap=market_cap.ln(),
            beta=None,
        )
        return ValuationImprovementInputBundle(
            bundle_version_id=(
                f"bundle:{request.security_id}:{request.decision_time.date().isoformat()}:"
                f"{bundle_hash[:24]}:v1"
            ),
            security_id=request.security_id,
            decision_time=request.decision_time,
            latest_source_available_at=max(
                financial_available,
                price_available,
                comparable_available,
            ),
            data_mode=request.data_mode,
            trust_state=request.requested_trust_state,
            dataset_version_ids=qualification.dataset_version_ids,
            industry_template_id=template,
            valuation_formula_version="v0",
            improvement_formula_version="v0",
            scenario_method_id="valuation-sensitivity:affine-expectation:v1",
            scenario_method_version="v1",
            valuation_metric_inputs=valuation_metrics,
            market_implied=market_implied,
            fundamental_anchor=fundamental_anchor,
            valuation_exposures=exposures,
            currency=currency,
            comparable_set_version_id=f"comparable-set:{comparable_hash[:24]}:v1",
            improvement_inputs=tuple(improvement_inputs),
            improvement_exposures=improvement_exposures,
            scenario_inputs=scenario_inputs,
        )

    @staticmethod
    def _improvement_window(
        rows: Sequence[Sequence[object]],
    ) -> tuple[date, date, date, date] | None:
        by_metric: dict[str, dict[int, date]] = {
            metric: {} for metric in _IMPROVEMENT_METRICS
        }
        for row in rows:
            metric = str(row[1])
            period = cast(date, row[2])
            ordinal = _quarter_ordinal(period)
            value_basis = str(row[11]) if len(row) > 11 else "ttm"
            if metric in by_metric and ordinal is not None and value_basis == "ttm":
                by_metric[metric][ordinal] = period
        common = set.intersection(*(set(values) for values in by_metric.values()))
        candidates = sorted(
            (
                current
                for current in common
                if {current, current - 1, current - 4, current - 5} <= common
            ),
            reverse=True,
        )
        if not candidates:
            return None
        current = candidates[0]
        reference = next(iter(by_metric.values()))
        return (
            reference[current],
            reference[current - 1],
            reference[current - 4],
            reference[current - 5],
        )

    def _financial(
        self,
        connection: Connection,
        request: ValuationInputQualificationRequest,
    ) -> ValuationInputDomainEvidence:
        rows = self._financial_rows(connection, request)
        blockers: list[str] = []
        observed_metrics = {str(row[1]) for row in rows}
        missing_metrics = sorted(_REQUIRED_FINANCIAL_METRICS - observed_metrics)
        if missing_metrics:
            blockers.append("required financial metrics are unavailable: " + ", ".join(missing_metrics))
        if rows and not self._has_improvement_window(rows):
            blockers.append(
                "financial periods do not contain an adjacent-quarter YoY improvement window"
            )
        financial_keys = [(str(row[1]), cast(date, row[2])) for row in rows]
        if len(financial_keys) != len(set(financial_keys)):
            blockers.append(
                "multiple financial observations share a metric and period without an authority selection"
            )
        if not rows:
            blockers.append("qualified financial observations are unavailable")
        return self._evidence_from_rows(
            ValuationInputDomain.FINANCIAL,
            rows,
            blockers=tuple(blockers),
            observation_index=0,
            dataset_index=3,
            source_index=4,
            available_index=5,
            trust_index=7,
            hash_index=6,
        )

    @staticmethod
    def _financial_rows(
        connection: Connection,
        request: ValuationInputQualificationRequest,
    ) -> list[tuple[object, ...]]:
        if request.data_mode is DataMode.STRICT_HISTORICAL:
            query = """
                /* financial input rows */
                SELECT fact_id, metric_code, report_period_end, dataset_version_id,
                       provider_id, available_at, raw_object_hash, trust_state,
                       fact_value #>> '{}', unit, currency, period_type,
                       mapping_version_id, source_object_id
                FROM canonical.financial_fact_observations
                WHERE security_id = %s
                  AND trust_state = 'pit_verified'
                  AND quality_state = 'passed'
                  AND available_at <= %s
                  AND known_from <= %s
                  AND (known_to IS NULL OR %s < known_to)
                ORDER BY metric_code, report_period_end, fact_id
            """
            params: tuple[object, ...] = (
                request.security_id,
                request.decision_time,
                request.decision_time,
                request.decision_time,
            )
        else:
            query = """
                /* financial input rows */
                SELECT observation_id, metric_code, report_period_end,
                       dataset_version_id, provider_id,
                       COALESCE(available_at, retrieved_at), raw_object_hash, trust_state,
                       canonical_value, canonical_unit, currency, value_basis,
                       mapping_version_id, raw_object_id
                FROM observation.normalized_current_financial_observations
                WHERE security_id = %s
                  AND trust_state = 'normalized_current'
                  AND COALESCE(available_at, retrieved_at) <= %s
                ORDER BY metric_code, report_period_end, observation_id
            """
            params = (request.security_id, request.decision_time)
        return connection.execute(query, params).fetchall()

    @staticmethod
    def _has_improvement_window(rows: Sequence[Sequence[object]]) -> bool:
        by_metric: dict[str, set[int]] = {metric: set() for metric in _IMPROVEMENT_METRICS}
        for row in rows:
            metric = str(row[1])
            period = cast(date, row[2])
            ordinal = _quarter_ordinal(period)
            value_basis = str(row[11]) if len(row) > 11 else "ttm"
            if metric in by_metric and ordinal is not None and value_basis == "ttm":
                by_metric[metric].add(ordinal)
        common = set.intersection(*by_metric.values()) if by_metric else set()
        return any({current, current - 1, current - 4, current - 5} <= common for current in common)

    def _price(
        self,
        connection: Connection,
        request: ValuationInputQualificationRequest,
    ) -> ValuationInputDomainEvidence:
        rows = self._price_catalog_rows(connection, request)
        selected, selected_row = self._select_price(rows, request)
        blockers: list[str] = []
        if selected is None or selected_row is None:
            blockers.append("qualified price observation is unavailable")
            return ValuationInputDomainEvidence(
                domain=ValuationInputDomain.PRICE,
                trust_state=None,
                dataset_version_ids=(),
                source_ids=(),
                observation_ids=(),
                content_hashes=(),
                observation_count=0,
                latest_source_available_at=None,
                blockers=tuple(blockers),
            )
        age = (request.decision_time.date() - selected.session_date).days
        if age > request.max_price_age_days:
            blockers.append(
                f"price is stale by {age} days; maximum is {request.max_price_age_days}"
            )
        if selected.trust_state is not request.requested_trust_state:
            blockers.append("price observation trust does not match the requested trust")
        capital_trust = DataTrustState(str(selected_row[14]))
        if capital_trust is not request.requested_trust_state:
            blockers.append("share-capital trust does not match the requested trust")
        return ValuationInputDomainEvidence(
            domain=ValuationInputDomain.PRICE,
            trust_state=(
                selected.trust_state if selected.trust_state is capital_trust else None
            ),
            dataset_version_ids=tuple(
                sorted({selected.dataset_version_id, str(selected_row[11])})
            ),
            source_ids=tuple(sorted({selected.source_id, str(selected_row[12])})),
            observation_ids=tuple(
                sorted({selected.observation_id, str(selected_row[9])})
            ),
            content_hashes=tuple(
                sorted({selected.content_hash, str(selected_row[15])})
            ),
            observation_count=2,
            latest_source_available_at=max(
                selected.available_at,
                cast(datetime, selected_row[13]),
            ),
            blockers=tuple(blockers),
        )

    @staticmethod
    def _price_catalog_rows(
        connection: Connection,
        request: ValuationInputQualificationRequest,
    ) -> list[tuple[object, ...]]:
        oldest = request.decision_time.date() - timedelta(days=request.max_price_age_days)
        return connection.execute(
            """
            /* price input partitions */
            SELECT listings.listing_id, listings.exchange, partitions.partition_id,
                   partitions.dataset_version_id, partitions.storage_uri,
                   jobs.output_trust_state, checkpoints.retrieved_at,
                   jobs.provider_id, datasets.content_hash,
                   capital.observation_id, capital.total_shares,
                   capital.dataset_version_id, capital.source_id,
                   capital.retrieved_at, capital.trust_state,
                   capital.batch_content_hash
            FROM canonical.listings AS listings
            JOIN observation.market_data_partitions AS partitions
              ON partitions.exchange = listings.exchange
             AND partitions.data_type = 'daily_bar'
            JOIN governance.dataset_versions AS datasets
              ON datasets.dataset_version_id = partitions.dataset_version_id
            JOIN governance.ingestion_jobs AS jobs
              ON jobs.dataset_version_id = partitions.dataset_version_id
             AND jobs.status = 'succeeded'
            JOIN governance.ingestion_checkpoints AS checkpoints
              ON checkpoints.job_id = jobs.job_id
             AND checkpoints.data_domain = 'raw_daily_bar'
             AND checkpoints.status = 'succeeded'
            JOIN LATERAL (
                SELECT observation_id, total_shares, dataset_version_id,
                       source_id, retrieved_at, trust_state, batch_content_hash
                FROM observation.share_capital_observations
                WHERE listing_id = listings.listing_id
                  AND effective_on <= %s
                  AND retrieved_at <= %s
                  AND trust_state = %s
                ORDER BY effective_on DESC, retrieved_at DESC, observation_id
                LIMIT 1
            ) AS capital ON TRUE
            WHERE listings.security_id = %s
              AND partitions.start_date <= %s
              AND partitions.end_date >= %s
              AND jobs.output_trust_state = %s
            ORDER BY partitions.end_date DESC, partitions.partition_id
            """,
            (
                request.decision_time.date(),
                request.decision_time,
                request.requested_trust_state.value,
                request.security_id,
                request.decision_time.date(),
                oldest,
                request.requested_trust_state.value,
            ),
        ).fetchall()

    def _select_price(
        self,
        rows: Sequence[Sequence[object]],
        request: ValuationInputQualificationRequest,
    ) -> tuple[FrozenPriceObservation | None, Sequence[object] | None]:
        for row in rows:
            retrieved_at = cast(datetime, row[6])
            if retrieved_at > request.decision_time:
                continue
            candidate = self._price_reader(
                str(row[4]),
                str(row[0]),
                request.decision_time.date(),
                str(row[3]),
                retrieved_at,
                str(row[8]),
            )
            if candidate is None:
                continue
            return candidate, row
        return None, None

    def _comparable(
        self,
        connection: Connection,
        request: ValuationInputQualificationRequest,
    ) -> ValuationInputDomainEvidence:
        rows = connection.execute(
            """
            /* comparable input rows */
            WITH subject AS (
                SELECT taxonomy, industry_code
                FROM canonical.industry_memberships
                WHERE security_id = %s
                  AND valid_from <= %s
                  AND (valid_to IS NULL OR %s < valid_to)
                  AND industry_code IS NOT NULL
                  AND trust_state = %s
                  AND observed_at <= %s
                  AND (
                      %s <> 'pit_verified'
                      OR (available_at IS NOT NULL AND available_at <= %s)
                  )
                ORDER BY observed_at DESC, industry_membership_id DESC
                LIMIT 1
            )
            SELECT peers.industry_membership_id, peers.security_id,
                   peers.taxonomy, peers.industry_code,
                   peers.dataset_version_id, peers.source_id,
                   peers.trust_state,
                   COALESCE(peers.available_at, peers.observed_at),
                   datasets.content_hash
            FROM subject
            JOIN canonical.industry_memberships AS peers
              ON peers.taxonomy = subject.taxonomy
             AND peers.industry_code = subject.industry_code
            JOIN governance.dataset_versions AS datasets
              ON datasets.dataset_version_id = peers.dataset_version_id
            WHERE peers.valid_from <= %s
              AND (peers.valid_to IS NULL OR %s < peers.valid_to)
              AND peers.trust_state = %s
              AND peers.dataset_version_id IS NOT NULL
              AND peers.observed_at <= %s
              AND (
                  %s <> 'pit_verified'
                  OR (peers.available_at IS NOT NULL AND peers.available_at <= %s)
              )
            ORDER BY peers.security_id, peers.industry_membership_id
            """,
            (
                request.security_id,
                request.decision_time.date(),
                request.decision_time.date(),
                request.requested_trust_state.value,
                request.decision_time,
                request.requested_trust_state.value,
                request.decision_time,
                request.decision_time.date(),
                request.decision_time.date(),
                request.requested_trust_state.value,
                request.decision_time,
                request.requested_trust_state.value,
                request.decision_time,
            ),
        ).fetchall()
        blockers: list[str] = []
        member_count = len({str(row[1]) for row in rows})
        if member_count < 3:
            blockers.append(
                "versioned comparable set requires the subject and at least two peers"
            )
        if not rows:
            blockers.append("qualified comparable observations are unavailable")
        return self._evidence_from_rows(
            ValuationInputDomain.COMPARABLE,
            rows,
            blockers=tuple(blockers),
            observation_index=0,
            dataset_index=4,
            source_index=5,
            available_index=7,
            trust_index=6,
            hash_index=8,
        )

    @staticmethod
    def _evidence_from_rows(
        domain: ValuationInputDomain,
        rows: Sequence[Sequence[object]],
        *,
        blockers: tuple[str, ...],
        observation_index: int,
        dataset_index: int,
        source_index: int,
        available_index: int,
        trust_index: int,
        hash_index: int,
    ) -> ValuationInputDomainEvidence:
        trusts = {DataTrustState(str(row[trust_index])) for row in rows}
        trust = next(iter(trusts)) if len(trusts) == 1 else None
        normalized_blockers = list(blockers)
        if len(trusts) > 1:
            normalized_blockers.append("source observations contain mixed trust states")
        return ValuationInputDomainEvidence(
            domain=domain,
            trust_state=trust,
            dataset_version_ids=tuple(sorted({str(row[dataset_index]) for row in rows})),
            source_ids=tuple(sorted({str(row[source_index]) for row in rows})),
            observation_ids=tuple(sorted({str(row[observation_index]) for row in rows})),
            content_hashes=tuple(sorted({str(row[hash_index]) for row in rows})),
            observation_count=len(rows),
            latest_source_available_at=(
                None
                if not rows
                else max(cast(datetime, row[available_index]) for row in rows)
            ),
            blockers=tuple(normalized_blockers),
        )


__all__ = [
    "DuckDbFrozenPriceReader",
    "FrozenPriceObservation",
    "PostgresValuationInputCompilation",
    "PostgresValuationInputQualificationSource",
    "ValuationInputQualificationUnavailable",
]
