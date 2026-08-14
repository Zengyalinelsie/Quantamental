"""PostgreSQL adapter for immutable frozen valuation/improvement input bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

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
from a_share_platform.domain.valuation_scenarios import (
    ValuationScenario,
    ValuationScenarioInput,
    ValuationScenarioProvenance,
)
from a_share_platform.ports.valuation_inputs import (
    ValuationImprovementInputBundle,
    ValuationImprovementInputConflict,
    ValuationImprovementInputRequest,
    ValuationImprovementInputUnavailable,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return getattr(value, "obj", value)


def _mapping(value: object, field_name: str) -> Mapping[object, object]:
    parsed = _json_value(value)
    if not isinstance(parsed, Mapping):
        raise TypeError(f"stored {field_name} must be an object")
    return parsed


def _array(value: object, field_name: str) -> Sequence[object]:
    parsed = _json_value(value)
    if not isinstance(parsed, (list, tuple)):
        raise TypeError(f"stored {field_name} must be an array")
    return parsed


def _required(document: Mapping[object, object], name: str) -> object:
    if name not in document:
        raise ValueError(f"stored valuation input bundle is missing {name}")
    return document[name]


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception as error:
        raise ValueError(f"stored {field_name} is not a Decimal") from error


def _datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    encoded = str(value)
    if encoded.endswith("Z"):
        encoded = encoded[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(encoded)
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO datetime") from error


def _date(value: object, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO date") from error


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    values = _array(value, field_name)
    if any(not isinstance(item, str) for item in values):
        raise TypeError(f"stored {field_name} must contain strings")
    return tuple(cast(str, item) for item in values)


def _valuation_provenance(value: object) -> ValuationInputProvenance:
    document = _mapping(value, "valuation provenance")
    return ValuationInputProvenance(
        dataset_version_id=str(_required(document, "dataset_version_id")),
        method_id=str(_required(document, "method_id")),
        method_version=str(_required(document, "method_version")),
        source_observation_ids=_strings(
            _required(document, "source_observation_ids"),
            "source_observation_ids",
        ),
        content_hashes=_strings(_required(document, "content_hashes"), "content_hashes"),
        additional_dataset_version_ids=_strings(
            document.get("additional_dataset_version_ids", []),
            "additional_dataset_version_ids",
        ),
    )


def _valuation_metric(value: object) -> ValuationMetricInput:
    document = _mapping(value, "valuation metric input")
    return ValuationMetricInput(
        metric=ValuationMetric(str(_required(document, "metric"))),
        numerator=_optional_decimal(document.get("numerator"), "numerator"),
        denominator=_optional_decimal(document.get("denominator"), "denominator"),
        numerator_unit=MetricUnit(str(_required(document, "numerator_unit"))),
        numerator_period=FeaturePeriod(str(_required(document, "numerator_period"))),
        denominator_unit=MetricUnit(str(_required(document, "denominator_unit"))),
        denominator_period=FeaturePeriod(str(_required(document, "denominator_period"))),
        currency=str(_required(document, "currency")),
        provenance=_valuation_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"),
            "unavailable_reasons",
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _expectation(value: object) -> ValuationExpectationRangeInput:
    document = _mapping(value, "valuation expectation input")
    return ValuationExpectationRangeInput(
        source=ValuationExpectationSource(str(_required(document, "source"))),
        expectation_metric=ValuationExpectationMetric(
            str(_required(document, "expectation_metric"))
        ),
        lower=_optional_decimal(document.get("lower"), "lower"),
        upper=_optional_decimal(document.get("upper"), "upper"),
        unit=MetricUnit(str(_required(document, "unit"))),
        assumptions=_strings(_required(document, "assumptions"), "assumptions"),
        invalidation_conditions=_strings(
            _required(document, "invalidation_conditions"),
            "invalidation_conditions",
        ),
        provenance=_valuation_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"),
            "unavailable_reasons",
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _improvement_provenance(value: object) -> ImprovementInputProvenance:
    document = _mapping(value, "improvement provenance")
    return ImprovementInputProvenance(
        dataset_version_id=str(_required(document, "dataset_version_id")),
        source_version_id=str(_required(document, "source_version_id")),
        mapping_version_id=str(_required(document, "mapping_version_id")),
        metric_definition_id=str(_required(document, "metric_definition_id")),
        metric_definition_version=str(_required(document, "metric_definition_version")),
        source_fact_ids=_strings(_required(document, "source_fact_ids"), "source_fact_ids"),
        content_hashes=_strings(_required(document, "content_hashes"), "content_hashes"),
        additional_dataset_version_ids=_strings(
            document.get("additional_dataset_version_ids", []),
            "additional_dataset_version_ids",
        ),
    )


def _improvement(value: object) -> FundamentalImprovementInput:
    document = _mapping(value, "improvement input")
    return FundamentalImprovementInput(
        metric=FundamentalImprovementMetric(str(_required(document, "metric"))),
        level=_optional_decimal(document.get("level"), "level"),
        current_change=_optional_decimal(document.get("current_change"), "current_change"),
        prior_change=_optional_decimal(document.get("prior_change"), "prior_change"),
        level_unit=MetricUnit(str(_required(document, "level_unit"))),
        change_unit=MetricUnit(str(_required(document, "change_unit"))),
        currency=None if document.get("currency") is None else str(document["currency"]),
        comparison=ImprovementComparison(str(_required(document, "comparison"))),
        window=ImprovementWindow(str(_required(document, "window"))),
        current_period_end=_date(
            _required(document, "current_period_end"), "current_period_end"
        ),
        current_comparison_period_end=_date(
            _required(document, "current_comparison_period_end"),
            "current_comparison_period_end",
        ),
        prior_period_end=_date(_required(document, "prior_period_end"), "prior_period_end"),
        prior_comparison_period_end=_date(
            _required(document, "prior_comparison_period_end"),
            "prior_comparison_period_end",
        ),
        seasonality_treatment=SeasonalityTreatment(
            str(_required(document, "seasonality_treatment"))
        ),
        base_effect_treatment=BaseEffectTreatment(
            str(_required(document, "base_effect_treatment"))
        ),
        one_off_treatment=OneOffTreatment(str(_required(document, "one_off_treatment"))),
        provenance=_improvement_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"), "unavailable_reasons"
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _scenario_provenance(value: object) -> ValuationScenarioProvenance:
    document = _mapping(value, "scenario provenance")
    return ValuationScenarioProvenance(
        dataset_version_id=str(_required(document, "dataset_version_id")),
        source_observation_ids=_strings(
            _required(document, "source_observation_ids"), "source_observation_ids"
        ),
        content_hashes=_strings(_required(document, "content_hashes"), "content_hashes"),
        additional_dataset_version_ids=_strings(
            document.get("additional_dataset_version_ids", []),
            "additional_dataset_version_ids",
        ),
    )


def _scenario(value: object) -> ValuationScenarioInput:
    document = _mapping(value, "scenario input")
    return ValuationScenarioInput(
        scenario=ValuationScenario(str(_required(document, "scenario"))),
        driver_lower=_optional_decimal(document.get("driver_lower"), "driver_lower"),
        driver_upper=_optional_decimal(document.get("driver_upper"), "driver_upper"),
        driver_unit=MetricUnit(str(_required(document, "driver_unit"))),
        assumptions=_strings(_required(document, "assumptions"), "assumptions"),
        provenance=_scenario_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"), "unavailable_reasons"
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _provenance_document(value: object) -> dict[str, object]:
    if isinstance(value, ValuationInputProvenance):
        return {
            "dataset_version_id": value.dataset_version_id,
            "method_id": value.method_id,
            "method_version": value.method_version,
            "source_observation_ids": list(value.source_observation_ids),
            "content_hashes": list(value.content_hashes),
            "additional_dataset_version_ids": list(value.additional_dataset_version_ids),
        }
    if isinstance(value, ImprovementInputProvenance):
        return {
            "dataset_version_id": value.dataset_version_id,
            "source_version_id": value.source_version_id,
            "mapping_version_id": value.mapping_version_id,
            "metric_definition_id": value.metric_definition_id,
            "metric_definition_version": value.metric_definition_version,
            "source_fact_ids": list(value.source_fact_ids),
            "content_hashes": list(value.content_hashes),
            "additional_dataset_version_ids": list(value.additional_dataset_version_ids),
        }
    if isinstance(value, ValuationScenarioProvenance):
        return {
            "dataset_version_id": value.dataset_version_id,
            "source_observation_ids": list(value.source_observation_ids),
            "content_hashes": list(value.content_hashes),
            "additional_dataset_version_ids": list(value.additional_dataset_version_ids),
        }
    raise TypeError("unsupported valuation bundle provenance")


def _valuation_metric_document(value: ValuationMetricInput) -> dict[str, object]:
    return {
        "metric": value.metric.value,
        "numerator": None if value.numerator is None else str(value.numerator),
        "denominator": None if value.denominator is None else str(value.denominator),
        "numerator_unit": value.numerator_unit.value,
        "numerator_period": value.numerator_period.value,
        "denominator_unit": value.denominator_unit.value,
        "denominator_period": value.denominator_period.value,
        "currency": value.currency,
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _expectation_document(value: ValuationExpectationRangeInput) -> dict[str, object]:
    return {
        "source": value.source.value,
        "expectation_metric": value.expectation_metric.value,
        "lower": None if value.lower is None else str(value.lower),
        "upper": None if value.upper is None else str(value.upper),
        "unit": value.unit.value,
        "assumptions": list(value.assumptions),
        "invalidation_conditions": list(value.invalidation_conditions),
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _improvement_document(value: FundamentalImprovementInput) -> dict[str, object]:
    return {
        "metric": value.metric.value,
        "level": None if value.level is None else str(value.level),
        "current_change": None if value.current_change is None else str(value.current_change),
        "prior_change": None if value.prior_change is None else str(value.prior_change),
        "level_unit": value.level_unit.value,
        "change_unit": value.change_unit.value,
        "currency": value.currency,
        "comparison": value.comparison.value,
        "window": value.window.value,
        "current_period_end": value.current_period_end.isoformat(),
        "current_comparison_period_end": value.current_comparison_period_end.isoformat(),
        "prior_period_end": value.prior_period_end.isoformat(),
        "prior_comparison_period_end": value.prior_comparison_period_end.isoformat(),
        "seasonality_treatment": value.seasonality_treatment.value,
        "base_effect_treatment": value.base_effect_treatment.value,
        "one_off_treatment": value.one_off_treatment.value,
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _scenario_document(value: ValuationScenarioInput) -> dict[str, object]:
    return {
        "scenario": value.scenario.value,
        "driver_lower": None if value.driver_lower is None else str(value.driver_lower),
        "driver_upper": None if value.driver_upper is None else str(value.driver_upper),
        "driver_unit": value.driver_unit.value,
        "assumptions": list(value.assumptions),
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def bundle_document(value: ValuationImprovementInputBundle) -> dict[str, object]:
    """Return a complete canonical JSON-compatible frozen bundle document."""

    if not isinstance(value, ValuationImprovementInputBundle):
        raise TypeError("value must be a ValuationImprovementInputBundle")
    return {
        "bundle_version_id": value.bundle_version_id,
        "security_id": value.security_id,
        "decision_time": value.decision_time.isoformat(),
        "latest_source_available_at": value.latest_source_available_at.isoformat(),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "dataset_version_ids": list(value.dataset_version_ids),
        "industry_template_id": value.industry_template_id.value,
        "valuation_formula_version": value.valuation_formula_version,
        "improvement_formula_version": value.improvement_formula_version,
        "scenario_method_id": value.scenario_method_id,
        "scenario_method_version": value.scenario_method_version,
        "valuation_metric_inputs": [
            _valuation_metric_document(item) for item in value.valuation_metric_inputs
        ],
        "market_implied": _expectation_document(value.market_implied),
        "fundamental_anchor": _expectation_document(value.fundamental_anchor),
        "valuation_exposures": {
            "industry_code": value.valuation_exposures.industry_code,
            "log_market_cap": (
                None
                if value.valuation_exposures.log_market_cap is None
                else str(value.valuation_exposures.log_market_cap)
            ),
            "beta": (
                None
                if value.valuation_exposures.beta is None
                else str(value.valuation_exposures.beta)
            ),
        },
        "currency": value.currency,
        "comparable_set_version_id": value.comparable_set_version_id,
        "improvement_inputs": [
            _improvement_document(item) for item in value.improvement_inputs
        ],
        "improvement_exposures": {
            "industry_code": value.improvement_exposures.industry_code,
            "log_market_cap": (
                None
                if value.improvement_exposures.log_market_cap is None
                else str(value.improvement_exposures.log_market_cap)
            ),
            "beta": (
                None
                if value.improvement_exposures.beta is None
                else str(value.improvement_exposures.beta)
            ),
        },
        "scenario_inputs": [_scenario_document(item) for item in value.scenario_inputs],
    }


def bundle_from_document(value: object) -> ValuationImprovementInputBundle:
    """Reconstruct domain values so every invariant is revalidated on read."""

    document = _mapping(value, "valuation input bundle")
    valuation_exposures = _mapping(
        _required(document, "valuation_exposures"), "valuation_exposures"
    )
    improvement_exposures = _mapping(
        _required(document, "improvement_exposures"), "improvement_exposures"
    )
    return ValuationImprovementInputBundle(
        bundle_version_id=str(_required(document, "bundle_version_id")),
        security_id=str(_required(document, "security_id")),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        dataset_version_ids=_strings(
            _required(document, "dataset_version_ids"), "dataset_version_ids"
        ),
        industry_template_id=IndustryTemplateId(
            str(_required(document, "industry_template_id"))
        ),
        valuation_formula_version=str(_required(document, "valuation_formula_version")),
        improvement_formula_version=str(_required(document, "improvement_formula_version")),
        scenario_method_id=str(_required(document, "scenario_method_id")),
        scenario_method_version=str(_required(document, "scenario_method_version")),
        valuation_metric_inputs=tuple(
            _valuation_metric(item)
            for item in _array(
                _required(document, "valuation_metric_inputs"),
                "valuation_metric_inputs",
            )
        ),
        market_implied=_expectation(_required(document, "market_implied")),
        fundamental_anchor=_expectation(_required(document, "fundamental_anchor")),
        valuation_exposures=ValuationExposures(
            industry_code=(
                None
                if valuation_exposures.get("industry_code") is None
                else str(valuation_exposures["industry_code"])
            ),
            log_market_cap=_optional_decimal(
                valuation_exposures.get("log_market_cap"), "log_market_cap"
            ),
            beta=_optional_decimal(valuation_exposures.get("beta"), "beta"),
        ),
        currency=str(_required(document, "currency")),
        comparable_set_version_id=str(_required(document, "comparable_set_version_id")),
        improvement_inputs=tuple(
            _improvement(item)
            for item in _array(_required(document, "improvement_inputs"), "improvement_inputs")
        ),
        improvement_exposures=FundamentalImprovementExposures(
            industry_code=(
                None
                if improvement_exposures.get("industry_code") is None
                else str(improvement_exposures["industry_code"])
            ),
            log_market_cap=_optional_decimal(
                improvement_exposures.get("log_market_cap"), "log_market_cap"
            ),
            beta=_optional_decimal(improvement_exposures.get("beta"), "beta"),
        ),
        scenario_inputs=tuple(
            _scenario(item)
            for item in _array(_required(document, "scenario_inputs"), "scenario_inputs")
        ),
    )


def bundle_content_hash(value: ValuationImprovementInputBundle) -> str:
    encoded = json.dumps(
        bundle_document(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


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


class PostgresValuationImprovementInputRepository:
    """Append and exact-key load complete frozen input bundles; never synthesise one."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresValuationImprovementInputRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def append(
        self,
        value: ValuationImprovementInputBundle,
    ) -> ValuationImprovementInputBundle:
        if not isinstance(value, ValuationImprovementInputBundle):
            raise TypeError("value must be a ValuationImprovementInputBundle")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._load(connection, self._request_for(value))
                if existing is not None:
                    if bundle_content_hash(existing) != bundle_content_hash(value):
                        raise ValuationImprovementInputConflict(
                            f"immutable valuation input bundle conflict: {value.bundle_version_id}"
                        )
                    return existing
                row = self.to_row(value)
                connection.execute(
                    """
                    INSERT INTO research.valuation_input_bundles (
                        bundle_version_id, security_id, decision_time, content_hash,
                        data_mode, trust_state, latest_source_available_at,
                        dataset_version_ids, bundle_document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (bundle_version_id) DO NOTHING
                    """,
                    (*row[:7], _json_parameter(row[7]), _json_parameter(row[8])),
                )
                stored = self._load(connection, self._request_for(value))
                if stored is None:
                    raise RuntimeError("valuation input bundle insert was not observable")
                if bundle_content_hash(stored) != bundle_content_hash(value):
                    raise ValuationImprovementInputConflict(
                        f"immutable valuation input bundle conflict: {value.bundle_version_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise ValuationImprovementInputConflict(
                f"immutable valuation input bundle conflict: {value.bundle_version_id}"
            ) from error

    def load(
        self,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        if not isinstance(query, ValuationImprovementInputRequest):
            raise TypeError("query must be a ValuationImprovementInputRequest")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._load(connection, query)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    @staticmethod
    def _request_for(
        value: ValuationImprovementInputBundle,
    ) -> ValuationImprovementInputRequest:
        return ValuationImprovementInputRequest(
            security_id=value.security_id,
            decision_time=value.decision_time,
            data_mode=value.data_mode,
            trust_state=value.trust_state,
            bundle_version_id=value.bundle_version_id,
        )

    @staticmethod
    def _select() -> str:
        return """
            SELECT bundle_version_id, security_id, decision_time, content_hash,
                   data_mode, trust_state, latest_source_available_at,
                   dataset_version_ids, bundle_document
            FROM research.valuation_input_bundles
        """

    def _load(
        self,
        connection: Connection,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        row = connection.execute(
            self._select()
            + """
            WHERE security_id = %s AND decision_time = %s
              AND data_mode = %s AND trust_state = %s
              AND bundle_version_id = %s
            """,
            (
                query.security_id,
                query.decision_time,
                query.data_mode.value,
                query.trust_state.value,
                query.bundle_version_id,
            ),
        ).fetchone()
        return None if row is None else self.from_row(row)

    @staticmethod
    def to_row(value: ValuationImprovementInputBundle) -> tuple[object, ...]:
        return (
            value.bundle_version_id,
            value.security_id,
            value.decision_time,
            bundle_content_hash(value),
            value.data_mode.value,
            value.trust_state.value,
            value.latest_source_available_at,
            list(value.dataset_version_ids),
            bundle_document(value),
        )

    @staticmethod
    def from_row(row: Sequence[object]) -> ValuationImprovementInputBundle:
        if len(row) != 9:
            raise ValueError("stored valuation input bundle row has an invalid shape")
        value = bundle_from_document(row[8])
        expected = (
            value.bundle_version_id,
            value.security_id,
            value.decision_time,
            value.data_mode.value,
            value.trust_state.value,
            value.latest_source_available_at,
            tuple(value.dataset_version_ids),
        )
        stored = (
            str(row[0]),
            str(row[1]),
            cast(datetime, row[2]),
            str(row[4]),
            str(row[5]),
            cast(datetime, row[6]),
            tuple(str(item) for item in _array(row[7], "dataset_version_ids")),
        )
        if stored != expected:
            raise ValueError("stored valuation input bundle columns do not match document")
        if str(row[3]) != bundle_content_hash(value):
            raise ValueError("stored valuation input bundle hash mismatch")
        return value

    @staticmethod
    def _unavailable() -> ValuationImprovementInputUnavailable:
        return ValuationImprovementInputUnavailable(
            "PostgreSQL frozen valuation input store is unavailable"
        )


__all__ = [
    "PostgresValuationImprovementInputRepository",
    "bundle_content_hash",
    "bundle_document",
    "bundle_from_document",
]
