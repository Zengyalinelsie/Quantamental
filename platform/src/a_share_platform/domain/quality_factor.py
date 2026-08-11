"""Provider-neutral, scientifically unvalidated Quality factor V0.

The V0 baseline reports the fraction of governed industry-template checks that
pass.  It consumes no provider object and embeds no numerical threshold.  The
approved threshold and template provenance travel with each component input.

This is deliberately a partial contract: gaps against SPEC-017 remain explicit
until the corresponding rules are governed by the industry-template catalog.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .features import FeatureCalculationStatus, FeaturePeriod, MissingPolicy
from .industry_templates import (
    FeatureSourceLayer,
    GovernanceApprovalStatus,
    IndustryTemplateCatalog,
    IndustryTemplateId,
    ResolvedTemplateFeature,
    ThresholdComparator,
    ThresholdSourceKind,
    industry_template_catalog_v0,
)
from .metrics import MetricUnit


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


class QualityCoverageStatus(str, Enum):
    """Coverage against SPEC-017, distinct from a calculation status."""

    PARTIAL = "partial"
    FULL = "full"


class FactorScientificStatus(str, Enum):
    """A Capability implementation is not evidence of scientific validity."""

    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class QualityFactorExposures:
    """Risk controls carried beside, and never fed into, the quality formula."""

    industry_code: str | None
    log_market_cap: Decimal | None
    beta: Decimal | None
    missing_exposure_names: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        if self.industry_code is not None:
            _text(self.industry_code, "industry_code")
        if self.log_market_cap is not None:
            _decimal(self.log_market_cap, "log_market_cap")
        if self.beta is not None:
            _decimal(self.beta, "beta")
        object.__setattr__(
            self,
            "missing_exposure_names",
            tuple(
                name
                for name, value in (
                    ("industry", self.industry_code),
                    ("size", self.log_market_cap),
                    ("beta", self.beta),
                )
                if value is None
            ),
        )


@dataclass(frozen=True)
class QualityComponentSpec:
    feature_id: str
    unit: MetricUnit
    period: FeaturePeriod
    comparator: ThresholdComparator
    source_layer: FeatureSourceLayer
    template_formula_id: str
    template_formula_version: str
    threshold_key: str
    threshold_source_kind: ThresholdSourceKind

    def __post_init__(self) -> None:
        for name in (
            "feature_id",
            "template_formula_id",
            "template_formula_version",
            "threshold_key",
        ):
            _text(getattr(self, name), name)
        unit = MetricUnit(self.unit)
        if unit is MetricUnit.TEXT:
            raise ValueError("quality component unit must be numeric")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "period", FeaturePeriod(self.period))
        object.__setattr__(self, "comparator", ThresholdComparator(self.comparator))
        object.__setattr__(self, "source_layer", FeatureSourceLayer(self.source_layer))
        object.__setattr__(
            self,
            "threshold_source_kind",
            ThresholdSourceKind(self.threshold_source_kind),
        )

    @property
    def is_industry_specific(self) -> bool:
        return self.source_layer is FeatureSourceLayer.INDUSTRY


@dataclass(frozen=True)
class QualityComponentInput:
    feature_id: str
    value: Decimal | None
    unit: MetricUnit
    period: FeaturePeriod
    resolved_feature: ResolvedTemplateFeature

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id")
        if self.value is not None:
            _decimal(self.value, "value")
        unit = MetricUnit(self.unit)
        if unit is MetricUnit.TEXT:
            raise ValueError("quality component input must be numeric")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "period", FeaturePeriod(self.period))
        if not isinstance(self.resolved_feature, ResolvedTemplateFeature):
            raise TypeError("resolved_feature must be ResolvedTemplateFeature")


@dataclass(frozen=True)
class QualityComponentResult:
    feature_id: str
    value: Decimal | None
    threshold: Decimal | None
    passed: bool | None
    unit: MetricUnit
    period: FeaturePeriod
    source_layer: FeatureSourceLayer
    template_formula_id: str | None
    template_formula_version: str | None
    threshold_source_id: str | None
    threshold_source_version: str | None

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id")
        if self.value is not None:
            _decimal(self.value, "value")
        if self.threshold is not None:
            _decimal(self.threshold, "threshold")
        object.__setattr__(self, "unit", MetricUnit(self.unit))
        object.__setattr__(self, "period", FeaturePeriod(self.period))
        object.__setattr__(self, "source_layer", FeatureSourceLayer(self.source_layer))
        if self.passed is not None and type(self.passed) is not bool:
            raise TypeError("passed must be a boolean or None")
        if self.passed is None:
            if self.value is not None:
                raise ValueError("unavailable component cannot carry a numeric value")
        elif self.value is None or self.threshold is None:
            raise ValueError("evaluated component requires value and threshold")


@dataclass(frozen=True)
class QualityFactorResult:
    status: FeatureCalculationStatus
    value: Decimal | None
    output_unit: MetricUnit
    formula_id: str
    formula_version: str
    template_id: IndustryTemplateId
    template_version: str
    template_definition_hash: str
    coverage_status: QualityCoverageStatus
    coverage_gaps: tuple[str, ...]
    component_results: tuple[QualityComponentResult, ...]
    missing_component_ids: tuple[str, ...]
    exposures: QualityFactorExposures
    scientific_status: FactorScientificStatus

    def __post_init__(self) -> None:
        status = FeatureCalculationStatus(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "output_unit", MetricUnit(self.output_unit))
        object.__setattr__(self, "template_id", IndustryTemplateId(self.template_id))
        object.__setattr__(
            self,
            "coverage_status",
            QualityCoverageStatus(self.coverage_status),
        )
        object.__setattr__(
            self,
            "scientific_status",
            FactorScientificStatus(self.scientific_status),
        )
        for name in ("formula_id", "formula_version", "template_version"):
            _text(getattr(self, name), name)
        gaps = tuple(self.coverage_gaps)
        missing = tuple(self.missing_component_ids)
        if len(gaps) != len(set(gaps)) or len(missing) != len(set(missing)):
            raise ValueError("coverage gaps and missing components must be unique")
        if self.coverage_status is QualityCoverageStatus.FULL and gaps:
            raise ValueError("full coverage cannot carry coverage gaps")
        if self.coverage_status is QualityCoverageStatus.PARTIAL and not gaps:
            raise ValueError("partial coverage requires coverage gaps")
        if not isinstance(self.exposures, QualityFactorExposures):
            raise TypeError("exposures must be QualityFactorExposures")
        if status is FeatureCalculationStatus.QUANTIFIED:
            if self.value is None:
                raise ValueError("quantified quality factor requires a value")
            _decimal(self.value, "value")
            if missing:
                raise ValueError("quantified quality factor cannot have missing components")
        else:
            if self.value is not None:
                raise ValueError("unavailable quality factor cannot carry a value")
            if not missing:
                raise ValueError("unavailable quality factor requires missing components")


@dataclass(frozen=True)
class QualityFactorDefinition:
    factor_id: str
    formula_id: str
    formula_version: str
    template_id: IndustryTemplateId
    template_version: str
    template_definition_hash: str
    components: tuple[QualityComponentSpec, ...]
    missing_policy: MissingPolicy
    coverage_status: QualityCoverageStatus
    coverage_gaps: tuple[str, ...]
    scientific_status: FactorScientificStatus

    def __post_init__(self) -> None:
        for name in (
            "factor_id",
            "formula_id",
            "formula_version",
            "template_version",
            "template_definition_hash",
        ):
            _text(getattr(self, name), name)
        object.__setattr__(self, "template_id", IndustryTemplateId(self.template_id))
        components = tuple(self.components)
        if not components or any(
            not isinstance(value, QualityComponentSpec) for value in components
        ):
            raise ValueError("quality factor requires component specs")
        identifiers = tuple(value.feature_id for value in components)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("quality component identifiers must be unique")
        object.__setattr__(self, "components", components)
        policy = MissingPolicy(self.missing_policy)
        if policy is not MissingPolicy.UNAVAILABLE:
            raise ValueError("Quality V0 missing policy must be unavailable")
        object.__setattr__(self, "missing_policy", policy)
        coverage = QualityCoverageStatus(self.coverage_status)
        gaps = tuple(self.coverage_gaps)
        if coverage is QualityCoverageStatus.PARTIAL and not gaps:
            raise ValueError("partial Quality V0 requires explicit coverage gaps")
        object.__setattr__(self, "coverage_status", coverage)
        object.__setattr__(self, "coverage_gaps", gaps)
        status = FactorScientificStatus(self.scientific_status)
        if status is not FactorScientificStatus.NOT_EVALUATED:
            raise ValueError("Quality V0 cannot claim scientific validation")
        object.__setattr__(self, "scientific_status", status)

    def calculate(
        self,
        values: Mapping[str, QualityComponentInput],
        *,
        exposures: QualityFactorExposures,
    ) -> QualityFactorResult:
        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping of QualityComponentInput values")
        if not isinstance(exposures, QualityFactorExposures):
            raise TypeError("exposures must be QualityFactorExposures")
        expected = {value.feature_id for value in self.components}
        unknown = tuple(sorted(set(values) - expected))
        if unknown:
            raise ValueError(f"unknown quality components: {', '.join(unknown)}")

        results: list[QualityComponentResult] = []
        missing: list[str] = []
        passed = 0
        for spec in self.components:
            value = values.get(spec.feature_id)
            if value is None:
                missing.append(spec.feature_id)
                continue
            result = self._evaluate_component(spec, value)
            results.append(result)
            if result.passed is None:
                missing.append(spec.feature_id)
            elif result.passed:
                passed += 1

        if missing:
            factor_value = None
            calculation_status = FeatureCalculationStatus.UNAVAILABLE
        else:
            factor_value = Decimal(passed) / Decimal(len(self.components))
            calculation_status = FeatureCalculationStatus.QUANTIFIED
        return QualityFactorResult(
            status=calculation_status,
            value=factor_value,
            output_unit=MetricUnit.RATIO,
            formula_id=self.formula_id,
            formula_version=self.formula_version,
            template_id=self.template_id,
            template_version=self.template_version,
            template_definition_hash=self.template_definition_hash,
            coverage_status=self.coverage_status,
            coverage_gaps=self.coverage_gaps,
            component_results=tuple(results),
            missing_component_ids=tuple(missing),
            exposures=exposures,
            scientific_status=self.scientific_status,
        )

    def _evaluate_component(
        self,
        spec: QualityComponentSpec,
        value: QualityComponentInput,
    ) -> QualityComponentResult:
        if not isinstance(value, QualityComponentInput):
            raise TypeError(f"quality component {spec.feature_id} has an invalid type")
        if value.feature_id != spec.feature_id:
            raise ValueError(f"quality component feature mismatch: {spec.feature_id}")
        if value.unit is not spec.unit:
            raise ValueError(f"quality component {spec.feature_id} unit is incompatible")
        if value.period is not spec.period:
            raise ValueError(f"quality component {spec.feature_id} period is incompatible")
        resolved = value.resolved_feature
        provenance = resolved.provenance
        if (
            provenance.feature_id != spec.feature_id
            or provenance.template_id is not self.template_id
            or provenance.template_version != self.template_version
        ):
            raise ValueError("quality component template provenance is incompatible")
        if not resolved.applicable:
            if value.value is not None:
                raise ValueError("not-applicable template component cannot carry a value")
            return QualityComponentResult(
                feature_id=spec.feature_id,
                value=None,
                threshold=None,
                passed=None,
                unit=spec.unit,
                period=spec.period,
                source_layer=FeatureSourceLayer.COMPANY_EXCEPTION,
                template_formula_id=None,
                template_formula_version=None,
                threshold_source_id=None,
                threshold_source_version=None,
            )

        rule = resolved.rule
        binding = resolved.threshold_binding
        assert rule is not None
        assert binding is not None
        if (
            rule.feature_id != spec.feature_id
            or rule.formula_id != spec.template_formula_id
            or rule.formula_version != spec.template_formula_version
            or rule.output_unit is not spec.unit
            or rule.threshold_key != spec.threshold_key
        ):
            raise ValueError("quality component template rule is incompatible")
        if (
            binding.threshold_key != spec.threshold_key
            or binding.unit is not spec.unit
            or binding.source_kind is not spec.threshold_source_kind
            or binding.approval_status is not GovernanceApprovalStatus.APPROVED
        ):
            raise ValueError("quality component threshold provenance is incompatible")
        if value.value is None:
            component_passed = None
        elif spec.comparator is ThresholdComparator.MINIMUM:
            component_passed = value.value >= binding.value
        else:
            component_passed = value.value <= binding.value
        return QualityComponentResult(
            feature_id=spec.feature_id,
            value=value.value,
            threshold=binding.value,
            passed=component_passed,
            unit=spec.unit,
            period=spec.period,
            source_layer=provenance.source_layer,
            template_formula_id=rule.formula_id,
            template_formula_version=rule.formula_version,
            threshold_source_id=binding.source_id,
            threshold_source_version=binding.source_version,
        )


_COMPONENT_PERIODS = {
    "quality.universal.cash_flow_to_profit": FeaturePeriod.TTM,
    "quality.universal.balance_sheet_leverage": FeaturePeriod.INSTANT,
    "quality.non_financial.roic": FeaturePeriod.TTM,
    "quality.non_financial.interest_coverage": FeaturePeriod.TTM,
    "quality.bank.core_tier1_capital_adequacy": FeaturePeriod.INSTANT,
    "quality.bank.nonperforming_loan_ratio": FeaturePeriod.INSTANT,
    "quality.bank.net_interest_margin": FeaturePeriod.TTM,
    "quality.manufacturing.gross_margin_stability": FeaturePeriod.TTM,
    "quality.manufacturing.inventory_turnover": FeaturePeriod.TTM,
    "quality.manufacturing.cash_conversion_cycle": FeaturePeriod.TTM,
}

_SPEC017_COVERAGE_GAPS = {
    IndustryTemplateId.NON_FINANCIAL_GENERAL: (
        "spec017.accruals",
        "spec017.roe",
        "spec017.net_margin_stability",
    ),
    IndustryTemplateId.BANK: (
        "spec017.accruals",
        "spec017.roe",
        "spec017.net_margin_stability",
    ),
    IndustryTemplateId.MANUFACTURING_CONSUMER: (
        "spec017.accruals",
        "spec017.roe",
        "spec017.net_margin_stability",
    ),
}


def quality_factor_definition_v0(
    template_id: IndustryTemplateId,
    *,
    catalog: IndustryTemplateCatalog | None = None,
) -> QualityFactorDefinition:
    """Build a partial V0 definition strictly from governed W02 template rules."""

    template_catalog = industry_template_catalog_v0() if catalog is None else catalog
    if not isinstance(template_catalog, IndustryTemplateCatalog):
        raise TypeError("catalog must be IndustryTemplateCatalog")
    template = template_catalog.get(IndustryTemplateId(template_id))
    components: list[QualityComponentSpec] = []
    for rule in template.key_metric_rules:
        try:
            period = _COMPONENT_PERIODS[rule.feature_id]
        except KeyError as error:
            raise LookupError(f"Quality V0 has no governed period for {rule.feature_id}") from error
        requirement = template.threshold_requirement(rule.threshold_key)
        components.append(
            QualityComponentSpec(
                feature_id=rule.feature_id,
                unit=rule.output_unit,
                period=period,
                comparator=requirement.comparator,
                source_layer=rule.source_layer,
                template_formula_id=rule.formula_id,
                template_formula_version=rule.formula_version,
                threshold_key=rule.threshold_key,
                threshold_source_kind=requirement.source_kind,
            )
        )
    return QualityFactorDefinition(
        factor_id=f"factor:quality:{template.template_id.value}:v0",
        formula_id="factor-formula:quality:governed-threshold-pass-rate",
        formula_version="v0",
        template_id=template.template_id,
        template_version=template.version,
        template_definition_hash=template.definition_hash,
        components=tuple(components),
        missing_policy=MissingPolicy.UNAVAILABLE,
        coverage_status=QualityCoverageStatus.PARTIAL,
        coverage_gaps=_SPEC017_COVERAGE_GAPS[template.template_id],
        scientific_status=FactorScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "FactorScientificStatus",
    "QualityComponentInput",
    "QualityComponentResult",
    "QualityComponentSpec",
    "QualityCoverageStatus",
    "QualityFactorDefinition",
    "QualityFactorExposures",
    "QualityFactorResult",
    "quality_factor_definition_v0",
]
