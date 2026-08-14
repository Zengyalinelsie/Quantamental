"""Authoritative PostgreSQL schema ownership for persistent platform objects."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Final


class SchemaLayer(str, Enum):
    GOVERNANCE = "governance"
    EVIDENCE = "evidence"
    OBSERVATION = "observation"
    CANONICAL = "canonical"
    RESEARCH = "research"
    SERVING = "serving"


PERSISTENT_TABLE_SCHEMAS: Final[Mapping[str, SchemaLayer]] = MappingProxyType(
    {
        # Cross-layer control plane.
        "artifacts": SchemaLayer.GOVERNANCE,
        "canonical_metrics": SchemaLayer.GOVERNANCE,
        "dataset_coverage_reports": SchemaLayer.GOVERNANCE,
        "dataset_quality_reports": SchemaLayer.GOVERNANCE,
        "dataset_versions": SchemaLayer.GOVERNANCE,
        "factor_promotion_reviews": SchemaLayer.GOVERNANCE,
        "financial_authority_rules": SchemaLayer.GOVERNANCE,
        "financial_backfill_persist_receipts": SchemaLayer.GOVERNANCE,
        "financial_backfill_work_units": SchemaLayer.GOVERNANCE,
        "financial_quality_rules": SchemaLayer.GOVERNANCE,
        "ingestion_checkpoints": SchemaLayer.GOVERNANCE,
        "ingestion_job_events": SchemaLayer.GOVERNANCE,
        "ingestion_jobs": SchemaLayer.GOVERNANCE,
        "lineage_edges": SchemaLayer.GOVERNANCE,
        "metric_mapping_versions": SchemaLayer.GOVERNANCE,
        "provider_field_mappings": SchemaLayer.GOVERNANCE,
        "run_records": SchemaLayer.GOVERNANCE,
        "unmapped_metric_fields": SchemaLayer.GOVERNANCE,
        # Immutable source evidence.
        "official_disclosures": SchemaLayer.EVIDENCE,
        "raw_objects": SchemaLayer.EVIDENCE,
        # Provider-shaped observations.
        "corporate_action_observations": SchemaLayer.OBSERVATION,
        "daily_market_states": SchemaLayer.OBSERVATION,
        "market_data_partitions": SchemaLayer.OBSERVATION,
        "normalized_current_financial_observations": SchemaLayer.OBSERVATION,
        "share_capital_observations": SchemaLayer.OBSERVATION,
        "timing_benchmark_bars": SchemaLayer.OBSERVATION,
        # Governed identity and facts.
        "companies": SchemaLayer.CANONICAL,
        "corporate_actions": SchemaLayer.CANONICAL,
        "exchange_calendar_days": SchemaLayer.CANONICAL,
        "financial_fact_observations": SchemaLayer.CANONICAL,
        "identifier_history": SchemaLayer.CANONICAL,
        "industry_memberships": SchemaLayer.CANONICAL,
        "listing_state_periods": SchemaLayer.CANONICAL,
        "listings": SchemaLayer.CANONICAL,
        "official_identifier_aliases": SchemaLayer.CANONICAL,
        "price_limits": SchemaLayer.CANONICAL,
        "provider_identifier_corrections": SchemaLayer.CANONICAL,
        "securities": SchemaLayer.CANONICAL,
        "share_capital_periods": SchemaLayer.CANONICAL,
        "universe_definitions": SchemaLayer.CANONICAL,
        "universe_memberships": SchemaLayer.CANONICAL,
        "universe_versions": SchemaLayer.CANONICAL,
        # Reproducible research and validation artifacts.
        "experiment_runs": SchemaLayer.RESEARCH,
        "experiment_specs": SchemaLayer.RESEARCH,
        "factor_qualification_audits": SchemaLayer.RESEARCH,
        "factor_validation_reports": SchemaLayer.RESEARCH,
        "feature_snapshots": SchemaLayer.RESEARCH,
        "expected_return_calibrations": SchemaLayer.RESEARCH,
        "investment_view_outcomes": SchemaLayer.RESEARCH,
        "investment_views": SchemaLayer.RESEARCH,
        "research_labels": SchemaLayer.RESEARCH,
        "signal_snapshots": SchemaLayer.RESEARCH,
        "timing_forecasts": SchemaLayer.RESEARCH,
        "valuation_input_bundles": SchemaLayer.RESEARCH,
    }
)


def qualified_table(table: str) -> str:
    try:
        layer = PERSISTENT_TABLE_SCHEMAS[table]
    except KeyError as error:
        raise KeyError(f"unknown persistent table: {table}") from error
    return f"{layer.value}.{table}"
