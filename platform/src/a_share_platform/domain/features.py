"""Provider-neutral contracts for deterministic feature calculation.

This module deliberately defines calculation and versioning contracts without
choosing the statistical estimators used for cross-sectional winsorization,
standardization, or neutralization.  Those estimators are later implementations
bound by the explicit specs carried by every feature definition.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import ClassVar

from .metrics import MetricUnit

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY_UNITS = {MetricUnit.CURRENCY, MetricUnit.CURRENCY_PER_SHARE}


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _content_hash(value: str, field_name: str = "content_hash") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use sha256:<64 lowercase hex chars>")
    return value


def _validate_measure(
    unit: MetricUnit | str,
    currency: str | None,
    *,
    prefix: str,
) -> tuple[MetricUnit, str | None]:
    unit = MetricUnit(unit)
    if unit is MetricUnit.TEXT:
        raise ValueError(f"{prefix} unit must be numeric")
    if unit in _CURRENCY_UNITS:
        if currency is None or re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise ValueError(f"{prefix} currency must be a three-letter uppercase ISO code")
    elif currency is not None:
        raise ValueError(f"{prefix} currency must be absent for non-currency units")
    return unit, currency


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parameters(
    value: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    items = tuple(value)
    for key, parameter_value in items:
        _text(key, "parameter name")
        _text(parameter_value, f"parameter[{key}]")
    keys = tuple(key for key, _ in items)
    if len(keys) != len(set(keys)):
        raise ValueError("parameter names must be unique")
    if items != tuple(sorted(items)):
        raise ValueError("parameters must be sorted for deterministic versioning")
    return items


class FeaturePeriod(str, Enum):
    """Economic period semantics; no implicit aggregation or conversion is allowed."""

    INSTANT = "instant"
    DAILY = "daily"
    Q1 = "q1"
    HALF_YEAR = "half_year"
    Q3 = "q3"
    ANNUAL = "annual"
    TTM = "ttm"


class MissingPolicy(str, Enum):
    """Allowed missing policies intentionally exclude numeric imputation."""

    UNAVAILABLE = "unavailable"
    REJECT = "reject"


class FeatureCalculationStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


class FeatureValueStage(str, Enum):
    RAW = "raw"
    WINSORIZED = "winsorized"
    STANDARDIZED = "standardized"
    NEUTRALIZED = "neutralized"


class NeutralizationExposure(str, Enum):
    INDUSTRY = "industry"
    SIZE = "size"


class MissingFeatureInputError(ValueError):
    """The definition explicitly rejects calculation with missing inputs."""


@dataclass(frozen=True)
class FeatureInputSpec:
    name: str
    unit: MetricUnit
    currency: str | None
    period: FeaturePeriod

    def __post_init__(self) -> None:
        _text(self.name, "name")
        unit, currency = _validate_measure(self.unit, self.currency, prefix="input")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "period", FeaturePeriod(self.period))

    def validate(self, value: FeatureInput) -> None:
        if not isinstance(value, FeatureInput):
            raise TypeError(f"feature input {self.name} must be a FeatureInput")
        if value.name != self.name:
            raise ValueError(
                f"feature input name mismatch: expected {self.name}, received {value.name}"
            )
        if value.unit is not self.unit:
            raise ValueError(f"feature input {self.name} unit is incompatible")
        if value.currency != self.currency:
            raise ValueError(f"feature input {self.name} currency is incompatible")
        if value.period is not self.period:
            raise ValueError(f"feature input {self.name} period is incompatible")


@dataclass(frozen=True)
class FeatureInput:
    name: str
    value: Decimal | None
    unit: MetricUnit
    currency: str | None
    period: FeaturePeriod
    source_id: str
    source_version_id: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in ("name", "source_id", "source_version_id"):
            _text(getattr(self, name), name)
        if self.value is not None:
            _decimal(self.value, "value")
        unit, currency = _validate_measure(self.unit, self.currency, prefix="input")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "period", FeaturePeriod(self.period))
        _content_hash(self.content_hash)


@dataclass(frozen=True)
class FeatureFormula:
    """A callable bound to immutable identity and source-content metadata."""

    formula_id: str
    version: str
    content_hash: str
    evaluator: Callable[[tuple[Decimal, ...]], Decimal] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.formula_id, "formula_id")
        _text(self.version, "version")
        _content_hash(self.content_hash, "formula content_hash")
        if not callable(self.evaluator):
            raise TypeError("evaluator must be callable")

    def evaluate(self, values: tuple[Decimal, ...]) -> Decimal:
        result = self.evaluator(values)
        return _decimal(result, "formula result")


@dataclass(frozen=True)
class MissingPolicySpec:
    policy: MissingPolicy
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy", MissingPolicy(self.policy))
        _text(self.version, "missing policy version")


@dataclass(frozen=True)
class WinsorizationSpec:
    method: str
    version: str
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _text(self.method, "winsorization method")
        _text(self.version, "winsorization version")
        object.__setattr__(self, "parameters", _parameters(self.parameters))


@dataclass(frozen=True)
class StandardizationSpec:
    method: str
    version: str
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _text(self.method, "standardization method")
        _text(self.version, "standardization version")
        object.__setattr__(self, "parameters", _parameters(self.parameters))


@dataclass(frozen=True)
class NeutralizationSpec:
    method: str
    version: str
    exposures: tuple[NeutralizationExposure, ...]
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _text(self.method, "neutralization method")
        _text(self.version, "neutralization version")
        exposures = tuple(NeutralizationExposure(value) for value in self.exposures)
        if not exposures:
            raise ValueError("neutralization exposures must not be empty")
        if len(exposures) != len(set(exposures)):
            raise ValueError("neutralization exposures must be unique")
        object.__setattr__(self, "exposures", exposures)
        object.__setattr__(self, "parameters", _parameters(self.parameters))


@dataclass(frozen=True)
class FeatureCalculation:
    status: FeatureCalculationStatus
    value: Decimal | None
    missing_input_names: tuple[str, ...]

    def __post_init__(self) -> None:
        status = FeatureCalculationStatus(self.status)
        object.__setattr__(self, "status", status)
        missing = tuple(self.missing_input_names)
        if len(missing) != len(set(missing)):
            raise ValueError("missing_input_names must be unique")
        object.__setattr__(self, "missing_input_names", missing)
        if status is FeatureCalculationStatus.QUANTIFIED:
            if self.value is None:
                raise ValueError("quantified calculation requires a value")
            _decimal(self.value, "value")
            if missing:
                raise ValueError("quantified calculation cannot have missing inputs")
        else:
            if self.value is not None:
                raise ValueError("unavailable calculation cannot carry a value")
            if not missing:
                raise ValueError("unavailable calculation requires missing inputs")


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    version: str
    name: str
    inputs: tuple[FeatureInputSpec, ...]
    output_unit: MetricUnit
    output_currency: str | None
    output_period: FeaturePeriod
    formula: FeatureFormula
    missing_policy: MissingPolicySpec
    winsorization: WinsorizationSpec
    standardization: StandardizationSpec
    neutralization: NeutralizationSpec
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("feature_id", "version", "name"):
            _text(getattr(self, name), name)
        inputs = tuple(self.inputs)
        if not inputs:
            raise ValueError("feature definition inputs must not be empty")
        if any(not isinstance(value, FeatureInputSpec) for value in inputs):
            raise TypeError("feature definition inputs must be FeatureInputSpec values")
        names = tuple(value.name for value in inputs)
        if len(names) != len(set(names)):
            raise ValueError("feature input names must be unique")
        object.__setattr__(self, "inputs", inputs)
        unit, currency = _validate_measure(
            self.output_unit,
            self.output_currency,
            prefix="output",
        )
        object.__setattr__(self, "output_unit", unit)
        object.__setattr__(self, "output_currency", currency)
        object.__setattr__(self, "output_period", FeaturePeriod(self.output_period))
        if not isinstance(self.formula, FeatureFormula):
            raise TypeError("formula must be a FeatureFormula")
        if not isinstance(self.missing_policy, MissingPolicySpec):
            raise TypeError("missing_policy must be a MissingPolicySpec")
        if not isinstance(self.winsorization, WinsorizationSpec):
            raise TypeError("winsorization must be a WinsorizationSpec")
        if not isinstance(self.standardization, StandardizationSpec):
            raise TypeError("standardization must be a StandardizationSpec")
        if not isinstance(self.neutralization, NeutralizationSpec):
            raise TypeError("neutralization must be a NeutralizationSpec")
        object.__setattr__(self, "definition_hash", _canonical_hash(self._hash_payload()))

    def _hash_payload(self) -> object:
        return {
            "feature_id": self.feature_id,
            "version": self.version,
            "name": self.name,
            "inputs": [
                {
                    "name": value.name,
                    "unit": value.unit.value,
                    "currency": value.currency,
                    "period": value.period.value,
                }
                for value in self.inputs
            ],
            "output": {
                "unit": self.output_unit.value,
                "currency": self.output_currency,
                "period": self.output_period.value,
            },
            "formula": {
                "formula_id": self.formula.formula_id,
                "version": self.formula.version,
                "content_hash": self.formula.content_hash,
            },
            "missing_policy": {
                "policy": self.missing_policy.policy.value,
                "version": self.missing_policy.version,
            },
            "winsorization": {
                "method": self.winsorization.method,
                "version": self.winsorization.version,
                "parameters": self.winsorization.parameters,
            },
            "standardization": {
                "method": self.standardization.method,
                "version": self.standardization.version,
                "parameters": self.standardization.parameters,
            },
            "neutralization": {
                "method": self.neutralization.method,
                "version": self.neutralization.version,
                "exposures": [value.value for value in self.neutralization.exposures],
                "parameters": self.neutralization.parameters,
            },
        }

    def calculate(self, values: Mapping[str, FeatureInput]) -> FeatureCalculation:
        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping of FeatureInput values")
        expected = {value.name for value in self.inputs}
        unknown = tuple(sorted(set(values) - expected))
        if unknown:
            raise ValueError(f"unknown feature inputs: {', '.join(unknown)}")

        missing: list[str] = []
        present: list[Decimal] = []
        for input_spec in self.inputs:
            value = values.get(input_spec.name)
            if value is None:
                missing.append(input_spec.name)
                continue
            if not isinstance(value, FeatureInput):
                raise TypeError(f"feature input {input_spec.name} must be a FeatureInput")
            input_spec.validate(value)
            if value.value is None:
                missing.append(input_spec.name)
            else:
                present.append(value.value)

        if missing:
            missing_names = tuple(missing)
            if self.missing_policy.policy is MissingPolicy.REJECT:
                raise MissingFeatureInputError(
                    f"missing feature inputs: {', '.join(missing_names)}"
                )
            return FeatureCalculation(
                status=FeatureCalculationStatus.UNAVAILABLE,
                value=None,
                missing_input_names=missing_names,
            )

        result = self.formula.evaluate(tuple(present))
        return FeatureCalculation(
            status=FeatureCalculationStatus.QUANTIFIED,
            value=result,
            missing_input_names=(),
        )


@dataclass(frozen=True)
class FeatureSnapshot:
    storage_namespace: ClassVar[str] = "feature_snapshots"

    snapshot_id: str
    feature_id: str
    feature_version: str
    feature_definition_hash: str
    formula_version: str
    missing_policy_version: str
    winsorization_version: str
    standardization_version: str
    neutralization_version: str
    entity_id: str
    as_of: datetime
    system_as_of: datetime
    status: FeatureCalculationStatus
    value: Decimal | None
    value_stage: FeatureValueStage
    unit: MetricUnit
    currency: str | None
    period: FeaturePeriod
    missing_input_names: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    input_content_hashes: tuple[str, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "feature_id",
            "feature_version",
            "formula_version",
            "missing_policy_version",
            "winsorization_version",
            "standardization_version",
            "neutralization_version",
            "entity_id",
        ):
            _text(getattr(self, name), name)
        _content_hash(self.feature_definition_hash, "feature_definition_hash")
        as_of = _aware(self.as_of, "as_of")
        system_as_of = _aware(self.system_as_of, "system_as_of")
        if system_as_of < as_of:
            raise ValueError("system_as_of cannot precede as_of")
        object.__setattr__(self, "status", FeatureCalculationStatus(self.status))
        object.__setattr__(self, "value_stage", FeatureValueStage(self.value_stage))
        unit, currency = _validate_measure(self.unit, self.currency, prefix="snapshot")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "period", FeaturePeriod(self.period))

        missing = tuple(self.missing_input_names)
        if len(missing) != len(set(missing)):
            raise ValueError("missing_input_names must be unique")
        object.__setattr__(self, "missing_input_names", missing)
        if self.status is FeatureCalculationStatus.QUANTIFIED:
            if self.value is None:
                raise ValueError("quantified snapshot requires a value")
            _decimal(self.value, "value")
            if missing:
                raise ValueError("quantified snapshot cannot have missing inputs")
        else:
            if self.value is not None:
                raise ValueError("unavailable snapshot cannot carry a value")
            if not missing:
                raise ValueError("unavailable snapshot requires missing inputs")

        dataset_versions = tuple(sorted(self.dataset_version_ids))
        if not dataset_versions:
            raise ValueError("dataset_version_ids must not be empty")
        for value in dataset_versions:
            _text(value, "dataset_version_id")
        if len(dataset_versions) != len(set(dataset_versions)):
            raise ValueError("dataset_version_ids must be unique")
        object.__setattr__(self, "dataset_version_ids", dataset_versions)

        input_hashes = tuple(sorted(self.input_content_hashes))
        if not input_hashes:
            raise ValueError("input_content_hashes must not be empty")
        for value in input_hashes:
            _content_hash(value, "input_content_hash")
        if len(input_hashes) != len(set(input_hashes)):
            raise ValueError("input_content_hashes must be unique")
        object.__setattr__(self, "input_content_hashes", input_hashes)
        object.__setattr__(self, "content_hash", _canonical_hash(self._hash_payload()))

    def _hash_payload(self) -> object:
        return {
            "snapshot_id": self.snapshot_id,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "feature_definition_hash": self.feature_definition_hash,
            "formula_version": self.formula_version,
            "missing_policy_version": self.missing_policy_version,
            "winsorization_version": self.winsorization_version,
            "standardization_version": self.standardization_version,
            "neutralization_version": self.neutralization_version,
            "entity_id": self.entity_id,
            "as_of": _canonical_time(self.as_of),
            "system_as_of": _canonical_time(self.system_as_of),
            "status": self.status.value,
            "value": None if self.value is None else str(self.value),
            "value_stage": self.value_stage.value,
            "unit": self.unit.value,
            "currency": self.currency,
            "period": self.period.value,
            "missing_input_names": self.missing_input_names,
            "dataset_version_ids": self.dataset_version_ids,
            "input_content_hashes": self.input_content_hashes,
        }

    @classmethod
    def from_calculation(
        cls,
        *,
        snapshot_id: str,
        definition: FeatureDefinition,
        entity_id: str,
        as_of: datetime,
        system_as_of: datetime,
        calculation: FeatureCalculation,
        value_stage: FeatureValueStage,
        dataset_version_ids: tuple[str, ...],
        input_content_hashes: tuple[str, ...],
    ) -> FeatureSnapshot:
        if not isinstance(definition, FeatureDefinition):
            raise TypeError("definition must be a FeatureDefinition")
        if not isinstance(calculation, FeatureCalculation):
            raise TypeError("calculation must be a FeatureCalculation")
        return cls(
            snapshot_id=snapshot_id,
            feature_id=definition.feature_id,
            feature_version=definition.version,
            feature_definition_hash=definition.definition_hash,
            formula_version=definition.formula.version,
            missing_policy_version=definition.missing_policy.version,
            winsorization_version=definition.winsorization.version,
            standardization_version=definition.standardization.version,
            neutralization_version=definition.neutralization.version,
            entity_id=entity_id,
            as_of=as_of,
            system_as_of=system_as_of,
            status=calculation.status,
            value=calculation.value,
            value_stage=value_stage,
            unit=definition.output_unit,
            currency=definition.output_currency,
            period=definition.output_period,
            missing_input_names=calculation.missing_input_names,
            dataset_version_ids=dataset_version_ids,
            input_content_hashes=input_content_hashes,
        )


@dataclass(frozen=True)
class LabelSchema:
    """Research-only target schema, intentionally distinct from FeatureDefinition."""

    storage_namespace: ClassVar[str] = "research_labels"

    label_id: str
    version: str
    horizon_sessions: int
    unit: MetricUnit
    currency: str | None
    period: FeaturePeriod = FeaturePeriod.DAILY
    schema_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.label_id, "label_id")
        _text(self.version, "version")
        if type(self.horizon_sessions) is not int or self.horizon_sessions <= 0:
            raise ValueError("horizon_sessions must be a positive integer")
        unit, currency = _validate_measure(self.unit, self.currency, prefix="label")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "period", FeaturePeriod(self.period))
        object.__setattr__(
            self,
            "schema_hash",
            _canonical_hash(
                {
                    "label_id": self.label_id,
                    "version": self.version,
                    "horizon_sessions": self.horizon_sessions,
                    "unit": self.unit.value,
                    "currency": self.currency,
                    "period": self.period.value,
                    "storage_namespace": self.storage_namespace,
                }
            ),
        )


@dataclass(frozen=True)
class LabelValue:
    """A research target that cannot satisfy a FeatureInput runtime type check."""

    storage_namespace: ClassVar[str] = "research_labels"

    schema: LabelSchema
    entity_id: str
    as_of: datetime
    value: Decimal
    dataset_version_id: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.schema, LabelSchema):
            raise TypeError("schema must be a LabelSchema")
        _text(self.entity_id, "entity_id")
        _aware(self.as_of, "as_of")
        _decimal(self.value, "value")
        _text(self.dataset_version_id, "dataset_version_id")
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(
                {
                    "schema_hash": self.schema.schema_hash,
                    "entity_id": self.entity_id,
                    "as_of": _canonical_time(self.as_of),
                    "value": str(self.value),
                    "dataset_version_id": self.dataset_version_id,
                    "storage_namespace": self.storage_namespace,
                }
            ),
        )


__all__ = [
    "FeatureCalculation",
    "FeatureCalculationStatus",
    "FeatureDefinition",
    "FeatureFormula",
    "FeatureInput",
    "FeatureInputSpec",
    "FeaturePeriod",
    "FeatureSnapshot",
    "FeatureValueStage",
    "LabelSchema",
    "LabelValue",
    "MissingFeatureInputError",
    "MissingPolicy",
    "MissingPolicySpec",
    "NeutralizationExposure",
    "NeutralizationSpec",
    "StandardizationSpec",
    "WinsorizationSpec",
]
