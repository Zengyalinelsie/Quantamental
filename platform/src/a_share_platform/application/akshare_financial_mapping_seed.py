"""Versioned canonical metrics and current-only AkShare field mappings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from a_share_platform.adapters.providers.akshare_financial_profile import (
    AKSHARE_FINANCIAL_FIELD_BINDINGS_V1,
    AKSHARE_FINANCIAL_FIELD_PROFILE_VERSION,
)
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.metrics import (
    CanonicalMetric,
    CurrencyRequirement,
    MappingMethod,
    MappingUseScope,
    MappingVersion,
    MetricUnit,
    ProviderFieldMapping,
)

AKSHARE_CURRENT_MAPPING_VERSION_ID = "metric-mapping:akshare-eastmoney:v1"
_RELEASED_AT = datetime(2026, 8, 11, tzinfo=UTC)


@dataclass(frozen=True)
class AkShareCurrentMappingPackage:
    metrics: tuple[CanonicalMetric, ...]
    version: MappingVersion
    mappings: tuple[ProviderFieldMapping, ...]


def akshare_current_mapping_package_v1() -> AkShareCurrentMappingPackage:
    metrics = tuple(
        CanonicalMetric(
            metric_code=binding.metric_code,
            canonical_name=binding.canonical_name,
            statement_type=binding.statement_type,
            unit=MetricUnit.CURRENCY,
            currency_requirement=CurrencyRequirement.REQUIRED,
            sign_convention=binding.sign_convention,
            description=binding.description,
        )
        for binding in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1
    )
    mappings = tuple(
        ProviderFieldMapping(
            mapping_id=(
                f"mapping:akshare-eastmoney:{binding.statement_type.value}:"
                f"{binding.provider_field}:v1"
            ),
            mapping_version_id=AKSHARE_CURRENT_MAPPING_VERSION_ID,
            provider_id="akshare",
            statement_type=binding.statement_type,
            source_field=binding.provider_field,
            metric_code=binding.metric_code,
            method=MappingMethod.EXACT,
            formula=None,
            allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH}),
        )
        for binding in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1
    )
    manifest = {
        "field_profile_version": AKSHARE_FINANCIAL_FIELD_PROFILE_VERSION,
        "mapping_version_id": AKSHARE_CURRENT_MAPPING_VERSION_ID,
        "mappings": [
            {
                "allowed_use_scopes": sorted(scope.value for scope in item.allowed_use_scopes),
                "mapping_id": item.mapping_id,
                "method": item.method.value,
                "metric_code": item.metric_code,
                "provider_field": item.source_field,
                "provider_id": item.provider_id,
                "statement_type": item.statement_type.value,
            }
            for item in mappings
        ],
        "metrics": [
            {
                "canonical_name": item.canonical_name,
                "currency_requirement": item.currency_requirement.value,
                "description": item.description,
                "metric_code": item.metric_code,
                "sign_convention": item.sign_convention.value,
                "statement_type": item.statement_type.value,
                "unit": item.unit.value,
            }
            for item in metrics
        ],
        "provider_id": "akshare",
        "schema": "akshare-current-financial-mapping-package:v1",
    }
    encoded = json.dumps(
        manifest,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    version = MappingVersion(
        mapping_version_id=AKSHARE_CURRENT_MAPPING_VERSION_ID,
        provider_id="akshare",
        created_at=_RELEASED_AT,
        content_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        code_version=AKSHARE_FINANCIAL_FIELD_PROFILE_VERSION,
    )
    return AkShareCurrentMappingPackage(
        metrics=metrics,
        version=version,
        mappings=mappings,
    )


def install_akshare_current_mapping_v1(
    service: MetricRegistryService,
) -> AkShareCurrentMappingPackage:
    if not isinstance(service, MetricRegistryService):
        raise TypeError("service must be a MetricRegistryService")
    package = akshare_current_mapping_package_v1()
    for metric in package.metrics:
        service.register_metric(metric)
    service.register_mapping_version(package.version)
    for mapping in package.mappings:
        service.register_mapping(mapping)
    return package


__all__ = [
    "AKSHARE_CURRENT_MAPPING_VERSION_ID",
    "AkShareCurrentMappingPackage",
    "akshare_current_mapping_package_v1",
    "install_akshare_current_mapping_v1",
]
