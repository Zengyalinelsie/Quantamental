"""Provider-neutral valuation scenario and sensitivity contracts.

The V0 method evaluates bounded affine sensitivities for explicit bear, base,
and bull assumptions.  It produces expectation intervals, never a point target
price, and is deliberately marked as scientifically unevaluated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .metrics import MetricUnit
from .pit import DataTrustState
from .run_context import DataMode
from .valuation_expectation_gap import ValuationExpectationMetric

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCENARIO_ORDER = {
    "bear": 0,
    "base": 1,
    "bull": 2,
}


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result or any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty text")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be unique")
    return result


def _evidence_gate(
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
    decision_time: datetime | None,
    latest_source_available_at: datetime | None,
) -> tuple[DataMode, DataTrustState]:
    mode = DataMode(data_mode)
    trust = DataTrustState(trust_state)
    if trust is DataTrustState.RAW:
        raise ValueError("raw inputs cannot enter valuation scenario sensitivity")
    if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
        raise PermissionError("strict_historical scenarios require pit_verified inputs")
    clocks = (decision_time, latest_source_available_at)
    if any(value is None for value in clocks) and any(value is not None for value in clocks):
        raise ValueError("decision_time and latest_source_available_at must be present together")
    if decision_time is not None and latest_source_available_at is not None:
        decision = _aware(decision_time, "decision_time")
        available = _aware(latest_source_available_at, "latest_source_available_at")
        if available > decision:
            raise ValueError("available_at cannot exceed decision_time")
    elif mode is DataMode.STRICT_HISTORICAL:
        raise PermissionError(
            "strict_historical scenarios require available_at <= decision_time evidence"
        )
    return mode, trust


class ValuationScenario(str, Enum):
    BASE = "base"
    BULL = "bull"
    BEAR = "bear"


class SensitivityDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ValuationScenarioStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


class ValuationScenarioSetStatus(str, Enum):
    QUANTIFIED = "quantified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ScenarioScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class ValuationScenarioProvenance:
    dataset_version_id: str
    source_observation_ids: tuple[str, ...]
    content_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.dataset_version_id, "dataset_version_id")
        observations = _unique_texts(self.source_observation_ids, "source_observation_ids")
        hashes = tuple(self.content_hashes)
        if not hashes or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in hashes
        ):
            raise ValueError("content_hashes must contain sha256 hashes")
        if len(hashes) != len(set(hashes)):
            raise ValueError("content_hashes must be unique")
        object.__setattr__(self, "source_observation_ids", tuple(sorted(observations)))
        object.__setattr__(self, "content_hashes", tuple(sorted(hashes)))


@dataclass(frozen=True)
class ValuationScenarioInput:
    scenario: ValuationScenario
    driver_lower: Decimal | None
    driver_upper: Decimal | None
    driver_unit: MetricUnit
    assumptions: tuple[str, ...]
    provenance: ValuationScenarioProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    unavailable_reasons: tuple[str, ...] = ()
    decision_time: datetime | None = None
    latest_source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", ValuationScenario(self.scenario))
        if (self.driver_lower is None) != (self.driver_upper is None):
            raise ValueError("driver interval bounds must be available together")
        if self.driver_lower is not None and self.driver_upper is not None:
            lower = _decimal(self.driver_lower, "driver_lower")
            upper = _decimal(self.driver_upper, "driver_upper")
            if upper < lower:
                raise ValueError("driver interval upper cannot be below lower")
        unit = MetricUnit(self.driver_unit)
        if unit is not MetricUnit.RATIO:
            raise ValueError("valuation sensitivity V0 driver unit must be ratio")
        object.__setattr__(self, "driver_unit", unit)
        object.__setattr__(self, "assumptions", _unique_texts(self.assumptions, "assumptions"))
        if not isinstance(self.provenance, ValuationScenarioProvenance):
            raise TypeError("provenance must be ValuationScenarioProvenance")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
        )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        reasons = tuple(self.unavailable_reasons)
        if self.driver_lower is None:
            if not reasons:
                raise ValueError("missing driver interval requires unavailable_reasons")
            _unique_texts(reasons, "unavailable_reasons")
        elif reasons:
            raise ValueError("available driver interval cannot carry unavailable_reasons")
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class ValuationSensitivityInterval:
    lower: Decimal
    upper: Decimal
    unit: MetricUnit

    def __post_init__(self) -> None:
        lower = _decimal(self.lower, "lower")
        upper = _decimal(self.upper, "upper")
        if upper < lower:
            raise ValueError("sensitivity interval upper cannot be below lower")
        unit = MetricUnit(self.unit)
        if unit is not MetricUnit.RATIO:
            raise ValueError("valuation sensitivity V0 interval unit must be ratio")
        object.__setattr__(self, "unit", unit)


@dataclass(frozen=True)
class ValuationScenarioResult:
    scenario: ValuationScenario
    status: ValuationScenarioStatus
    driver_interval: ValuationSensitivityInterval | None
    output_interval: ValuationSensitivityInterval | None
    assumptions: tuple[str, ...]
    provenance: ValuationScenarioProvenance
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", ValuationScenario(self.scenario))
        status = ValuationScenarioStatus(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "assumptions", _unique_texts(self.assumptions, "assumptions"))
        if not isinstance(self.provenance, ValuationScenarioProvenance):
            raise TypeError("provenance must be ValuationScenarioProvenance")
        reasons = tuple(self.unavailable_reasons)
        if status is ValuationScenarioStatus.QUANTIFIED:
            if self.driver_interval is None or self.output_interval is None:
                raise ValueError("quantified scenario requires driver and output intervals")
            if reasons:
                raise ValueError("quantified scenario cannot carry unavailable_reasons")
        else:
            if self.driver_interval is not None or self.output_interval is not None:
                raise ValueError("unavailable scenario cannot carry numeric intervals")
            _unique_texts(reasons, "unavailable_reasons")
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class ValuationScenarioSensitivityResult:
    status: ValuationScenarioSetStatus
    scenario_results: tuple[ValuationScenarioResult, ...]
    driver_name: str
    driver_unit: MetricUnit
    expectation_metric: ValuationExpectationMetric
    output_unit: MetricUnit
    direction: SensitivityDirection
    coefficient: Decimal
    intercept: Decimal
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    method_id: str
    method_version: str
    definition_hash: str
    input_dataset_version_ids: tuple[str, ...]
    input_source_observation_ids: tuple[str, ...]
    input_content_hashes: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    decision_time: datetime | None
    latest_input_available_at: datetime | None
    warnings: tuple[str, ...]
    scientific_status: ScenarioScientificStatus

    def component(self, scenario: ValuationScenario) -> ValuationScenarioResult:
        selected = [value for value in self.scenario_results if value.scenario is scenario]
        if len(selected) != 1:
            raise LookupError(f"valuation scenario is unavailable: {scenario.value}")
        return selected[0]

    @property
    def sensitivity_points(self) -> tuple[Decimal, ...]:
        return tuple(
            point
            for result in self.scenario_results
            if result.output_interval is not None
            for point in (result.output_interval.lower, result.output_interval.upper)
        )


@dataclass(frozen=True)
class ValuationScenarioSensitivityDefinition:
    method_id: str
    method_version: str
    driver_name: str
    driver_unit: MetricUnit
    expectation_metric: ValuationExpectationMetric
    output_unit: MetricUnit
    direction: SensitivityDirection
    coefficient: Decimal
    intercept: Decimal
    method_assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    scientific_status: ScenarioScientificStatus
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("method_id", "method_version", "driver_name"):
            _text(getattr(self, name), name)
        driver_unit = MetricUnit(self.driver_unit)
        output_unit = MetricUnit(self.output_unit)
        if driver_unit is not MetricUnit.RATIO or output_unit is not MetricUnit.RATIO:
            raise ValueError("valuation sensitivity V0 driver and output units must be ratio")
        object.__setattr__(self, "driver_unit", driver_unit)
        object.__setattr__(self, "output_unit", output_unit)
        object.__setattr__(
            self,
            "expectation_metric",
            ValuationExpectationMetric(self.expectation_metric),
        )
        direction = SensitivityDirection(self.direction)
        object.__setattr__(self, "direction", direction)
        coefficient = _decimal(self.coefficient, "coefficient")
        _decimal(self.intercept, "intercept")
        if coefficient == 0:
            raise ValueError("coefficient must not be zero")
        if (direction is SensitivityDirection.POSITIVE and coefficient < 0) or (
            direction is SensitivityDirection.NEGATIVE and coefficient > 0
        ):
            raise ValueError("coefficient sign must match sensitivity direction")
        assumptions = _unique_texts(self.method_assumptions, "method_assumptions")
        invalidations = _unique_texts(
            self.invalidation_conditions,
            "invalidation_conditions",
        )
        object.__setattr__(self, "method_assumptions", assumptions)
        object.__setattr__(self, "invalidation_conditions", invalidations)
        scientific_status = ScenarioScientificStatus(self.scientific_status)
        if scientific_status is not ScenarioScientificStatus.NOT_EVALUATED:
            raise ValueError("valuation scenario V0 must remain scientifically unevaluated")
        object.__setattr__(self, "scientific_status", scientific_status)
        payload = {
            "method_id": self.method_id,
            "method_version": self.method_version,
            "driver_name": self.driver_name,
            "driver_unit": driver_unit.value,
            "expectation_metric": self.expectation_metric.value,
            "output_unit": output_unit.value,
            "direction": direction.value,
            "coefficient": str(coefficient),
            "intercept": str(self.intercept),
            "method_assumptions": assumptions,
            "invalidation_conditions": invalidations,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "definition_hash", f"sha256:{hashlib.sha256(encoded).hexdigest()}")

    def calculate(
        self,
        inputs: tuple[ValuationScenarioInput, ...],
        *,
        data_mode: DataMode,
    ) -> ValuationScenarioSensitivityResult:
        values = tuple(inputs)
        if any(not isinstance(value, ValuationScenarioInput) for value in values):
            raise TypeError("scenario inputs must be ValuationScenarioInput values")
        scenarios = tuple(value.scenario for value in values)
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("duplicate valuation scenario input")
        if set(scenarios) != set(ValuationScenario):
            raise ValueError("valuation sensitivity requires base, bull, and bear inputs")

        mode = DataMode(data_mode)
        for value in values:
            if value.data_mode is not mode:
                raise PermissionError(
                    "current_research scenario inputs cannot be relabelled as strict historical"
                )
            if (
                mode is DataMode.STRICT_HISTORICAL
                and value.trust_state is not DataTrustState.PIT_VERIFIED
            ):
                raise PermissionError("strict_historical scenarios require pit_verified inputs")
            if value.driver_unit is not self.driver_unit:
                raise ValueError("scenario driver unit does not match sensitivity definition")

        results = tuple(
            sorted(
                (self._calculate_scenario(value) for value in values),
                key=lambda value: _SCENARIO_ORDER[value.scenario.value],
            )
        )
        quantified = tuple(
            value for value in results if value.status is ValuationScenarioStatus.QUANTIFIED
        )
        self._require_monotonic_outputs(quantified)
        if not quantified:
            status = ValuationScenarioSetStatus.UNAVAILABLE
        elif len(quantified) == len(results):
            status = ValuationScenarioSetStatus.QUANTIFIED
        else:
            status = ValuationScenarioSetStatus.PARTIAL

        if mode is DataMode.STRICT_HISTORICAL:
            decision_times = {value.decision_time for value in values}
            if len(decision_times) != 1:
                raise ValueError("strict_historical scenarios must share decision_time")
            decision_time = next(iter(decision_times))
            assert decision_time is not None
            available_times = tuple(value.latest_source_available_at for value in values)
            assert all(value is not None for value in available_times)
            latest_available = max(value for value in available_times if value is not None)
        else:
            decision_time = None
            latest_available = None

        warnings: list[str] = []
        if mode is DataMode.CURRENT_RESEARCH:
            warnings.append(
                "current_research scenario sensitivity is current-only, not historical evidence"
            )
        if status is ValuationScenarioSetStatus.PARTIAL:
            warnings.append("partial scenario sensitivity excludes unavailable scenarios")
        provenances = tuple(value.provenance for value in values)
        return ValuationScenarioSensitivityResult(
            status=status,
            scenario_results=results,
            driver_name=self.driver_name,
            driver_unit=self.driver_unit,
            expectation_metric=self.expectation_metric,
            output_unit=self.output_unit,
            direction=self.direction,
            coefficient=self.coefficient,
            intercept=self.intercept,
            assumptions=tuple(
                dict.fromkeys(
                    (
                        *self.method_assumptions,
                        *(assumption for value in results for assumption in value.assumptions),
                    )
                )
            ),
            invalidation_conditions=self.invalidation_conditions,
            method_id=self.method_id,
            method_version=self.method_version,
            definition_hash=self.definition_hash,
            input_dataset_version_ids=tuple(
                sorted({value.dataset_version_id for value in provenances})
            ),
            input_source_observation_ids=tuple(
                sorted(
                    {
                        observation
                        for value in provenances
                        for observation in value.source_observation_ids
                    }
                )
            ),
            input_content_hashes=tuple(
                sorted({item for value in provenances for item in value.content_hashes})
            ),
            data_mode=mode,
            historical_eligible=mode is DataMode.STRICT_HISTORICAL,
            decision_time=decision_time,
            latest_input_available_at=latest_available,
            warnings=tuple(warnings),
            scientific_status=self.scientific_status,
        )

    def _calculate_scenario(self, value: ValuationScenarioInput) -> ValuationScenarioResult:
        if value.driver_lower is None or value.driver_upper is None:
            return ValuationScenarioResult(
                scenario=value.scenario,
                status=ValuationScenarioStatus.UNAVAILABLE,
                driver_interval=None,
                output_interval=None,
                assumptions=value.assumptions,
                provenance=value.provenance,
                unavailable_reasons=value.unavailable_reasons,
            )
        driver = ValuationSensitivityInterval(
            lower=value.driver_lower,
            upper=value.driver_upper,
            unit=value.driver_unit,
        )
        first = self.intercept + self.coefficient * driver.lower
        second = self.intercept + self.coefficient * driver.upper
        output = ValuationSensitivityInterval(
            lower=min(first, second),
            upper=max(first, second),
            unit=self.output_unit,
        )
        return ValuationScenarioResult(
            scenario=value.scenario,
            status=ValuationScenarioStatus.QUANTIFIED,
            driver_interval=driver,
            output_interval=output,
            assumptions=value.assumptions,
            provenance=value.provenance,
            unavailable_reasons=(),
        )

    @staticmethod
    def _require_monotonic_outputs(
        results: tuple[ValuationScenarioResult, ...],
    ) -> None:
        previous: ValuationSensitivityInterval | None = None
        for result in results:
            current = result.output_interval
            assert current is not None
            if previous is not None and (
                current.lower < previous.lower or current.upper < previous.upper
            ):
                raise ValueError(
                    "scenario output intervals must be monotonic from bear to base to bull"
                )
            previous = current


__all__ = [
    "ScenarioScientificStatus",
    "SensitivityDirection",
    "ValuationScenario",
    "ValuationScenarioInput",
    "ValuationScenarioProvenance",
    "ValuationScenarioResult",
    "ValuationScenarioSensitivityDefinition",
    "ValuationScenarioSensitivityResult",
    "ValuationScenarioSetStatus",
    "ValuationScenarioStatus",
    "ValuationSensitivityInterval",
]
