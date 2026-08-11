"""Provider-neutral V0 industry templates for governed fundamental features.

The catalog contains formulas, applicable inputs, incomparable fields, and the
kind of governed threshold source required by each feature.  It deliberately
contains no numerical threshold defaults.  A feature can be resolved only with
an effective, independently versioned, approved threshold binding or an
approved company exception that marks it not applicable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .metrics import MetricUnit

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _plain_date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date")
    return value


def _content_hash(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")
    return value


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    for value in result:
        _text(value, field_name)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be unique")
    return result


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class IndustryTemplateId(str, Enum):
    NON_FINANCIAL_GENERAL = "non_financial_general"
    BANK = "bank"
    MANUFACTURING_CONSUMER = "manufacturing_consumer"


class FeatureSourceLayer(str, Enum):
    UNIVERSAL = "universal"
    INDUSTRY = "industry"
    COMPANY_EXCEPTION = "company_exception"


class ThresholdSourceKind(str, Enum):
    RESEARCH_POLICY = "research_policy"
    REGULATORY_RULE = "regulatory_rule"
    ACCOUNTING_STANDARD = "accounting_standard"
    PEER_DISTRIBUTION = "peer_distribution"


class ThresholdComparator(str, Enum):
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class GovernanceApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CompanyExceptionCategory(str, Enum):
    LIFECYCLE = "lifecycle"
    BUSINESS_MODEL = "business_model"
    ACCOUNTING_POLICY = "accounting_policy"
    MATERIAL_EVENT = "material_event"


class CompanyExceptionDecision(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    USE_TEMPLATE_RULE_WITH_DISCLOSURE = "use_template_rule_with_disclosure"


@dataclass(frozen=True)
class TemplateMetricRule:
    feature_id: str
    formula_id: str
    formula_version: str
    input_metric_codes: tuple[str, ...]
    output_unit: MetricUnit
    source_layer: FeatureSourceLayer
    threshold_key: str

    def __post_init__(self) -> None:
        for name in ("feature_id", "formula_id", "formula_version", "threshold_key"):
            _text(getattr(self, name), name)
        object.__setattr__(
            self,
            "input_metric_codes",
            _unique_texts(self.input_metric_codes, "input_metric_codes"),
        )
        output_unit = MetricUnit(self.output_unit)
        if output_unit is MetricUnit.TEXT:
            raise ValueError("template metric output must be numeric")
        object.__setattr__(self, "output_unit", output_unit)
        object.__setattr__(self, "source_layer", FeatureSourceLayer(self.source_layer))


@dataclass(frozen=True)
class ThresholdRequirement:
    threshold_key: str
    unit: MetricUnit
    comparator: ThresholdComparator
    source_kind: ThresholdSourceKind
    description: str

    def __post_init__(self) -> None:
        _text(self.threshold_key, "threshold_key")
        _text(self.description, "description")
        unit = MetricUnit(self.unit)
        if unit is MetricUnit.TEXT:
            raise ValueError("threshold unit must be numeric")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "comparator", ThresholdComparator(self.comparator))
        object.__setattr__(self, "source_kind", ThresholdSourceKind(self.source_kind))


@dataclass(frozen=True)
class ThresholdBinding:
    threshold_key: str
    value: Decimal
    unit: MetricUnit
    source_kind: ThresholdSourceKind
    source_id: str
    source_version: str
    content_hash: str
    effective_from: date
    effective_to: date | None
    approval_status: GovernanceApprovalStatus
    approval_id: str | None
    approved_by: str | None
    approved_at: datetime | None

    def __post_init__(self) -> None:
        for name in ("threshold_key", "source_id", "source_version"):
            _text(getattr(self, name), name)
        if not isinstance(self.value, Decimal):
            raise TypeError("threshold value must be a Decimal")
        if not self.value.is_finite():
            raise ValueError("threshold value must be finite")
        unit = MetricUnit(self.unit)
        if unit is MetricUnit.TEXT:
            raise ValueError("threshold unit must be numeric")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "source_kind", ThresholdSourceKind(self.source_kind))
        _content_hash(self.content_hash)
        effective_from = _plain_date(self.effective_from, "effective_from")
        if self.effective_to is not None:
            effective_to = _plain_date(self.effective_to, "effective_to")
            if effective_to <= effective_from:
                raise ValueError("effective_to must be after effective_from")
        status = GovernanceApprovalStatus(self.approval_status)
        object.__setattr__(self, "approval_status", status)
        approval_values = (self.approval_id, self.approved_by, self.approved_at)
        if status is GovernanceApprovalStatus.APPROVED:
            _text(self.approval_id or "", "approval_id")
            _text(self.approved_by or "", "approved_by")
            assert self.approved_at is not None
            _aware(self.approved_at, "approved_at")
        elif any(value is not None for value in approval_values):
            raise ValueError("only approved threshold bindings can carry approval metadata")

    def effective_on(self, as_of: date) -> bool:
        value = _plain_date(as_of, "as_of")
        return self.effective_from <= value and (
            self.effective_to is None or value < self.effective_to
        )


@dataclass(frozen=True)
class CompanyExceptionPolicy:
    policy_id: str
    version: str
    allowed_categories: tuple[CompanyExceptionCategory, ...]
    minimum_evidence_items: int

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id")
        _text(self.version, "version")
        categories = tuple(CompanyExceptionCategory(value) for value in self.allowed_categories)
        if not categories or len(categories) != len(set(categories)):
            raise ValueError("allowed exception categories must be non-empty and unique")
        object.__setattr__(self, "allowed_categories", categories)
        if type(self.minimum_evidence_items) is not int or self.minimum_evidence_items <= 0:
            raise ValueError("minimum_evidence_items must be a positive integer")


@dataclass(frozen=True)
class CompanyFeatureException:
    exception_id: str
    company_id: str
    template_id: IndustryTemplateId
    feature_id: str
    category: CompanyExceptionCategory
    decision: CompanyExceptionDecision
    rationale: str
    evidence_ids: tuple[str, ...]
    status: GovernanceApprovalStatus
    approval_id: str | None
    approved_by: str | None
    approved_at: datetime | None

    def __post_init__(self) -> None:
        for name in ("exception_id", "company_id", "feature_id", "rationale"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "template_id", IndustryTemplateId(self.template_id))
        object.__setattr__(self, "category", CompanyExceptionCategory(self.category))
        object.__setattr__(self, "decision", CompanyExceptionDecision(self.decision))
        object.__setattr__(
            self,
            "evidence_ids",
            _unique_texts(self.evidence_ids, "evidence_ids"),
        )
        status = GovernanceApprovalStatus(self.status)
        object.__setattr__(self, "status", status)
        approval_values = (self.approval_id, self.approved_by, self.approved_at)
        if status is GovernanceApprovalStatus.APPROVED:
            _text(self.approval_id or "", "approval_id")
            _text(self.approved_by or "", "approved_by")
            assert self.approved_at is not None
            _aware(self.approved_at, "approved_at")
        elif any(value is not None for value in approval_values):
            raise ValueError("only approved company exceptions can carry approval metadata")


@dataclass(frozen=True)
class FeatureProvenance:
    feature_id: str
    source_layer: FeatureSourceLayer
    template_id: IndustryTemplateId
    template_version: str
    threshold_source_id: str | None
    threshold_source_version: str | None
    exception_id: str | None

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id")
        object.__setattr__(self, "source_layer", FeatureSourceLayer(self.source_layer))
        object.__setattr__(self, "template_id", IndustryTemplateId(self.template_id))
        _text(self.template_version, "template_version")
        if self.source_layer is FeatureSourceLayer.COMPANY_EXCEPTION:
            _text(self.exception_id or "", "exception_id")
        elif self.exception_id is not None:
            raise ValueError("only company-exception provenance can carry exception_id")
        threshold_values = (self.threshold_source_id, self.threshold_source_version)
        if any(value is None for value in threshold_values) and any(
            value is not None for value in threshold_values
        ):
            raise ValueError("threshold source id and version must be present together")


@dataclass(frozen=True)
class ResolvedTemplateFeature:
    applicable: bool
    rule: TemplateMetricRule | None
    threshold_binding: ThresholdBinding | None
    provenance: FeatureProvenance

    def __post_init__(self) -> None:
        if type(self.applicable) is not bool:
            raise TypeError("applicable must be a boolean")
        if not isinstance(self.provenance, FeatureProvenance):
            raise TypeError("provenance must be FeatureProvenance")
        if self.applicable:
            if not isinstance(self.rule, TemplateMetricRule):
                raise ValueError("applicable feature requires a template rule")
            if not isinstance(self.threshold_binding, ThresholdBinding):
                raise ValueError("applicable feature requires a threshold binding")
        elif self.rule is not None or self.threshold_binding is not None:
            raise ValueError("not-applicable feature cannot carry rule or threshold")


@dataclass(frozen=True)
class IndustryTemplateDefinition:
    template_id: IndustryTemplateId
    version: str
    name: str
    key_metric_rules: tuple[TemplateMetricRule, ...]
    incomparable_metric_codes: tuple[str, ...]
    threshold_requirements: tuple[ThresholdRequirement, ...]
    exception_policy: CompanyExceptionPolicy
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_id", IndustryTemplateId(self.template_id))
        _text(self.version, "version")
        _text(self.name, "name")
        rules = tuple(self.key_metric_rules)
        if not rules or any(not isinstance(value, TemplateMetricRule) for value in rules):
            raise ValueError("key_metric_rules must contain template metric rules")
        feature_ids = tuple(value.feature_id for value in rules)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("template feature identifiers must be unique")
        layers = {value.source_layer for value in rules}
        if layers != {FeatureSourceLayer.UNIVERSAL, FeatureSourceLayer.INDUSTRY}:
            raise ValueError("template rules must include universal and industry layers")
        object.__setattr__(self, "key_metric_rules", rules)
        incomparable = _unique_texts(
            self.incomparable_metric_codes,
            "incomparable_metric_codes",
        )
        applicable_inputs = {
            metric for rule in rules for metric in rule.input_metric_codes
        }
        if applicable_inputs.intersection(incomparable):
            raise ValueError("incomparable metrics cannot be template inputs")
        object.__setattr__(self, "incomparable_metric_codes", incomparable)
        requirements = tuple(self.threshold_requirements)
        if not requirements or any(
            not isinstance(value, ThresholdRequirement) for value in requirements
        ):
            raise ValueError("threshold_requirements must contain threshold requirements")
        keys = tuple(value.threshold_key for value in requirements)
        if len(keys) != len(set(keys)):
            raise ValueError("threshold requirement keys must be unique")
        if set(keys) != {value.threshold_key for value in rules}:
            raise ValueError("every template rule requires one threshold source")
        requirements_by_key = {value.threshold_key: value for value in requirements}
        for rule in rules:
            if requirements_by_key[rule.threshold_key].unit is not rule.output_unit:
                raise ValueError("threshold unit must match template rule output unit")
        object.__setattr__(self, "threshold_requirements", requirements)
        if not isinstance(self.exception_policy, CompanyExceptionPolicy):
            raise TypeError("exception_policy must be CompanyExceptionPolicy")
        object.__setattr__(self, "definition_hash", _canonical_hash(self._hash_payload()))

    def threshold_requirement(self, threshold_key: str) -> ThresholdRequirement:
        matches = tuple(
            value
            for value in self.threshold_requirements
            if value.threshold_key == threshold_key
        )
        if len(matches) != 1:
            raise LookupError(f"unknown template threshold requirement: {threshold_key}")
        return matches[0]

    def _hash_payload(self) -> object:
        return {
            "template_id": self.template_id.value,
            "version": self.version,
            "name": self.name,
            "rules": [
                {
                    "feature_id": value.feature_id,
                    "formula_id": value.formula_id,
                    "formula_version": value.formula_version,
                    "inputs": list(value.input_metric_codes),
                    "output_unit": value.output_unit.value,
                    "source_layer": value.source_layer.value,
                    "threshold_key": value.threshold_key,
                }
                for value in self.key_metric_rules
            ],
            "incomparable_metric_codes": list(self.incomparable_metric_codes),
            "threshold_requirements": [
                {
                    "threshold_key": value.threshold_key,
                    "unit": value.unit.value,
                    "comparator": value.comparator.value,
                    "source_kind": value.source_kind.value,
                    "description": value.description,
                }
                for value in self.threshold_requirements
            ],
            "exception_policy": {
                "policy_id": self.exception_policy.policy_id,
                "version": self.exception_policy.version,
                "allowed_categories": [
                    value.value for value in self.exception_policy.allowed_categories
                ],
                "minimum_evidence_items": self.exception_policy.minimum_evidence_items,
            },
        }


@dataclass(frozen=True)
class IndustryTemplateCatalog:
    templates: tuple[IndustryTemplateDefinition, ...]

    def __post_init__(self) -> None:
        templates = tuple(self.templates)
        if not templates or any(
            not isinstance(value, IndustryTemplateDefinition) for value in templates
        ):
            raise ValueError("catalog must contain industry template definitions")
        identifiers = tuple(value.template_id for value in templates)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("industry template identifiers must be unique")
        object.__setattr__(self, "templates", templates)
        if {
            IndustryTemplateId.BANK,
            IndustryTemplateId.MANUFACTURING_CONSUMER,
        }.issubset(identifiers):
            bank = self.get(IndustryTemplateId.BANK)
            manufacturing = self.get(IndustryTemplateId.MANUFACTURING_CONSUMER)
            bank_rules = tuple(
                value
                for value in bank.key_metric_rules
                if value.source_layer is FeatureSourceLayer.INDUSTRY
            )
            manufacturing_rules = tuple(
                value
                for value in manufacturing.key_metric_rules
                if value.source_layer is FeatureSourceLayer.INDUSTRY
            )
            if {value.formula_id for value in bank_rules} == {
                value.formula_id for value in manufacturing_rules
            }:
                raise ValueError("bank and manufacturing formulas must differ")
            if {
                metric for value in bank_rules for metric in value.input_metric_codes
            } == {
                metric
                for value in manufacturing_rules
                for metric in value.input_metric_codes
            }:
                raise ValueError("bank and manufacturing applicable fields must differ")

    def get(self, template_id: IndustryTemplateId) -> IndustryTemplateDefinition:
        identifier = IndustryTemplateId(template_id)
        matches = tuple(value for value in self.templates if value.template_id is identifier)
        if len(matches) != 1:
            raise LookupError(f"unknown industry template: {identifier.value}")
        return matches[0]

    def resolve_feature(
        self,
        *,
        template_id: IndustryTemplateId,
        feature_id: str,
        company_id: str,
        as_of: date,
        threshold_bindings: tuple[ThresholdBinding, ...],
        company_exception: CompanyFeatureException | None = None,
    ) -> ResolvedTemplateFeature:
        template = self.get(template_id)
        _text(feature_id, "feature_id")
        _text(company_id, "company_id")
        effective_on = _plain_date(as_of, "as_of")
        rules = tuple(
            value for value in template.key_metric_rules if value.feature_id == feature_id
        )
        if len(rules) != 1:
            raise LookupError(f"unknown template feature: {feature_id}")
        rule = rules[0]
        exception = company_exception
        if exception is not None:
            if not isinstance(exception, CompanyFeatureException):
                raise TypeError("company_exception must be CompanyFeatureException")
            if (
                exception.company_id != company_id
                or exception.template_id is not template.template_id
                or exception.feature_id != feature_id
            ):
                raise ValueError("company exception scope does not match resolution request")
            if exception.category not in template.exception_policy.allowed_categories:
                raise PermissionError("company exception category is not allowed")
            if len(exception.evidence_ids) < template.exception_policy.minimum_evidence_items:
                raise PermissionError("company exception evidence requirement is not met")
            if exception.status is not GovernanceApprovalStatus.APPROVED:
                raise PermissionError("company exception is not approved")
            if exception.decision is CompanyExceptionDecision.NOT_APPLICABLE:
                return ResolvedTemplateFeature(
                    applicable=False,
                    rule=None,
                    threshold_binding=None,
                    provenance=FeatureProvenance(
                        feature_id=feature_id,
                        source_layer=FeatureSourceLayer.COMPANY_EXCEPTION,
                        template_id=template.template_id,
                        template_version=template.version,
                        threshold_source_id=None,
                        threshold_source_version=None,
                        exception_id=exception.exception_id,
                    ),
                )

        bindings = tuple(threshold_bindings)
        if any(not isinstance(value, ThresholdBinding) for value in bindings):
            raise TypeError("threshold_bindings must contain ThresholdBinding values")
        binding_keys = tuple(value.threshold_key for value in bindings)
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("threshold bindings must have unique keys")
        matches = tuple(
            value for value in bindings if value.threshold_key == rule.threshold_key
        )
        if len(matches) != 1:
            raise LookupError(f"threshold binding is missing: {rule.threshold_key}")
        binding = matches[0]
        requirement = template.threshold_requirement(rule.threshold_key)
        if binding.source_kind is not requirement.source_kind:
            raise ValueError("threshold source kind does not match template requirement")
        if binding.unit is not requirement.unit:
            raise ValueError("threshold unit does not match template requirement")
        if binding.approval_status is not GovernanceApprovalStatus.APPROVED:
            raise PermissionError("threshold binding is not approved")
        if not binding.effective_on(effective_on):
            raise PermissionError("threshold binding is not effective on as_of")
        source_layer = (
            FeatureSourceLayer.COMPANY_EXCEPTION
            if exception is not None
            else rule.source_layer
        )
        return ResolvedTemplateFeature(
            applicable=True,
            rule=rule,
            threshold_binding=binding,
            provenance=FeatureProvenance(
                feature_id=feature_id,
                source_layer=source_layer,
                template_id=template.template_id,
                template_version=template.version,
                threshold_source_id=binding.source_id,
                threshold_source_version=binding.source_version,
                exception_id=None if exception is None else exception.exception_id,
            ),
        )


def _rule(
    feature_id: str,
    formula_id: str,
    inputs: tuple[str, ...],
    unit: MetricUnit,
    layer: FeatureSourceLayer,
    threshold_key: str,
) -> TemplateMetricRule:
    return TemplateMetricRule(
        feature_id=feature_id,
        formula_id=formula_id,
        formula_version="v1",
        input_metric_codes=inputs,
        output_unit=unit,
        source_layer=layer,
        threshold_key=threshold_key,
    )


def _requirement(
    threshold_key: str,
    unit: MetricUnit,
    comparator: ThresholdComparator,
    source_kind: ThresholdSourceKind,
    description: str,
) -> ThresholdRequirement:
    return ThresholdRequirement(
        threshold_key=threshold_key,
        unit=unit,
        comparator=comparator,
        source_kind=source_kind,
        description=description,
    )


def _universal_rules() -> tuple[TemplateMetricRule, ...]:
    return (
        _rule(
            "quality.universal.cash_flow_to_profit",
            "formula:quality:cash-flow-to-profit:v1",
            ("cash_flow.net_operating_cash_flow", "income.net_profit"),
            MetricUnit.RATIO,
            FeatureSourceLayer.UNIVERSAL,
            "universal.cash_flow_to_profit.minimum",
        ),
        _rule(
            "quality.universal.balance_sheet_leverage",
            "formula:quality:liabilities-to-assets:v1",
            ("balance.total_liabilities", "balance.total_assets"),
            MetricUnit.RATIO,
            FeatureSourceLayer.UNIVERSAL,
            "universal.balance_sheet_leverage.maximum",
        ),
    )


def _universal_requirements() -> tuple[ThresholdRequirement, ...]:
    return (
        _requirement(
            "universal.cash_flow_to_profit.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.RESEARCH_POLICY,
            "Governed minimum cash conversion policy; no default value is embedded.",
        ),
        _requirement(
            "universal.balance_sheet_leverage.maximum",
            MetricUnit.RATIO,
            ThresholdComparator.MAXIMUM,
            ThresholdSourceKind.RESEARCH_POLICY,
            "Governed maximum leverage policy; no default value is embedded.",
        ),
    )


def _exception_policy(template_id: IndustryTemplateId) -> CompanyExceptionPolicy:
    return CompanyExceptionPolicy(
        policy_id=f"company-exception-policy:{template_id.value}:v1",
        version="v1",
        allowed_categories=tuple(CompanyExceptionCategory),
        minimum_evidence_items=1,
    )


def industry_template_catalog_v0() -> IndustryTemplateCatalog:
    universal_rules = _universal_rules()
    universal_requirements = _universal_requirements()
    non_financial_rules = (
        _rule(
            "quality.non_financial.roic",
            "formula:quality:non-financial-roic:v1",
            ("income.nopat", "balance.invested_capital"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "non_financial.roic.minimum",
        ),
        _rule(
            "quality.non_financial.interest_coverage",
            "formula:quality:non-financial-interest-coverage:v1",
            ("income.ebit", "income.interest_expense"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "non_financial.interest_coverage.minimum",
        ),
    )
    bank_rules = (
        _rule(
            "quality.bank.core_tier1_capital_adequacy",
            "formula:quality:bank-core-tier1-capital-adequacy:v1",
            ("bank.core_tier1_capital", "bank.risk_weighted_assets"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "bank.core_tier1_capital_adequacy.minimum",
        ),
        _rule(
            "quality.bank.nonperforming_loan_ratio",
            "formula:quality:bank-npl-ratio:v1",
            ("bank.nonperforming_loans", "bank.total_loans"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "bank.nonperforming_loan_ratio.maximum",
        ),
        _rule(
            "quality.bank.net_interest_margin",
            "formula:quality:bank-net-interest-margin:v1",
            ("bank.net_interest_income", "bank.average_interest_earning_assets"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "bank.net_interest_margin.minimum",
        ),
    )
    manufacturing_rules = (
        _rule(
            "quality.manufacturing.gross_margin_stability",
            "formula:quality:manufacturing-gross-margin-stability:v1",
            ("income.gross_profit", "income.operating_revenue"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "manufacturing.gross_margin_stability.minimum",
        ),
        _rule(
            "quality.manufacturing.inventory_turnover",
            "formula:quality:manufacturing-inventory-turnover:v1",
            ("income.cost_of_sales", "balance.average_inventory"),
            MetricUnit.RATIO,
            FeatureSourceLayer.INDUSTRY,
            "manufacturing.inventory_turnover.minimum",
        ),
        _rule(
            "quality.manufacturing.cash_conversion_cycle",
            "formula:quality:manufacturing-cash-conversion-cycle:v1",
            (
                "manufacturing.days_inventory",
                "manufacturing.days_receivable",
                "manufacturing.days_payable",
            ),
            MetricUnit.DAYS,
            FeatureSourceLayer.INDUSTRY,
            "manufacturing.cash_conversion_cycle.maximum",
        ),
    )
    non_financial_requirements = (
        _requirement(
            "non_financial.roic.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.PEER_DISTRIBUTION,
            "Versioned industry peer distribution is required for ROIC.",
        ),
        _requirement(
            "non_financial.interest_coverage.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.RESEARCH_POLICY,
            "Versioned solvency policy is required for interest coverage.",
        ),
    )
    bank_requirements = (
        _requirement(
            "bank.core_tier1_capital_adequacy.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.REGULATORY_RULE,
            "Versioned banking regulatory rule is required for capital adequacy.",
        ),
        _requirement(
            "bank.nonperforming_loan_ratio.maximum",
            MetricUnit.RATIO,
            ThresholdComparator.MAXIMUM,
            ThresholdSourceKind.PEER_DISTRIBUTION,
            "Versioned bank peer distribution is required for asset quality.",
        ),
        _requirement(
            "bank.net_interest_margin.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.PEER_DISTRIBUTION,
            "Versioned bank peer distribution is required for net interest margin.",
        ),
    )
    manufacturing_requirements = (
        _requirement(
            "manufacturing.gross_margin_stability.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.PEER_DISTRIBUTION,
            "Versioned manufacturing peer distribution is required for margin stability.",
        ),
        _requirement(
            "manufacturing.inventory_turnover.minimum",
            MetricUnit.RATIO,
            ThresholdComparator.MINIMUM,
            ThresholdSourceKind.PEER_DISTRIBUTION,
            "Versioned manufacturing peer distribution is required for inventory turnover.",
        ),
        _requirement(
            "manufacturing.cash_conversion_cycle.maximum",
            MetricUnit.DAYS,
            ThresholdComparator.MAXIMUM,
            ThresholdSourceKind.PEER_DISTRIBUTION,
            "Versioned manufacturing peer distribution is required for cash conversion.",
        ),
    )
    return IndustryTemplateCatalog(
        templates=(
            IndustryTemplateDefinition(
                template_id=IndustryTemplateId.NON_FINANCIAL_GENERAL,
                version="v0",
                name="Non-financial general quality template",
                key_metric_rules=(*universal_rules, *non_financial_rules),
                incomparable_metric_codes=(
                    "bank.core_tier1_capital_adequacy",
                    "bank.nonperforming_loan_ratio",
                    "bank.net_interest_margin",
                ),
                threshold_requirements=(
                    *universal_requirements,
                    *non_financial_requirements,
                ),
                exception_policy=_exception_policy(
                    IndustryTemplateId.NON_FINANCIAL_GENERAL
                ),
            ),
            IndustryTemplateDefinition(
                template_id=IndustryTemplateId.BANK,
                version="v0",
                name="Bank quality template",
                key_metric_rules=(*universal_rules, *bank_rules),
                incomparable_metric_codes=(
                    "manufacturing.inventory_turnover",
                    "manufacturing.cash_conversion_cycle",
                    "income.gross_margin",
                    "valuation.ev_to_ebit",
                ),
                threshold_requirements=(*universal_requirements, *bank_requirements),
                exception_policy=_exception_policy(IndustryTemplateId.BANK),
            ),
            IndustryTemplateDefinition(
                template_id=IndustryTemplateId.MANUFACTURING_CONSUMER,
                version="v0",
                name="Manufacturing and consumer quality template",
                key_metric_rules=(*universal_rules, *manufacturing_rules),
                incomparable_metric_codes=(
                    "bank.core_tier1_capital_adequacy",
                    "bank.nonperforming_loan_ratio",
                    "bank.net_interest_margin",
                ),
                threshold_requirements=(
                    *universal_requirements,
                    *manufacturing_requirements,
                ),
                exception_policy=_exception_policy(
                    IndustryTemplateId.MANUFACTURING_CONSUMER
                ),
            ),
        )
    )


__all__ = [
    "CompanyExceptionCategory",
    "CompanyExceptionDecision",
    "CompanyExceptionPolicy",
    "CompanyFeatureException",
    "FeatureProvenance",
    "FeatureSourceLayer",
    "GovernanceApprovalStatus",
    "IndustryTemplateCatalog",
    "IndustryTemplateDefinition",
    "IndustryTemplateId",
    "ResolvedTemplateFeature",
    "TemplateMetricRule",
    "ThresholdBinding",
    "ThresholdComparator",
    "ThresholdRequirement",
    "ThresholdSourceKind",
    "industry_template_catalog_v0",
]
