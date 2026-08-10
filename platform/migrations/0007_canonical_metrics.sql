CREATE TABLE canonical_metrics (
    metric_code TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    statement_type TEXT NOT NULL
        CHECK (statement_type IN ('balance_sheet', 'income_statement', 'cash_flow_statement')),
    unit TEXT NOT NULL
        CHECK (unit IN ('currency', 'currency_per_share', 'shares', 'ratio', 'count', 'days', 'text')),
    currency_requirement TEXT NOT NULL CHECK (currency_requirement IN ('required', 'forbidden')),
    sign_convention TEXT NOT NULL
        CHECK (sign_convention IN ('natural', 'inflow_positive', 'outflow_positive', 'expense_negative')),
    description TEXT NOT NULL,
    UNIQUE (metric_code, statement_type),
    CHECK (
        (unit IN ('currency', 'currency_per_share') AND currency_requirement = 'required')
        OR (unit NOT IN ('currency', 'currency_per_share') AND currency_requirement = 'forbidden')
    )
);

CREATE TABLE metric_mapping_versions (
    mapping_version_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    code_version TEXT NOT NULL,
    UNIQUE (provider_id, content_hash),
    UNIQUE (mapping_version_id, provider_id)
);

CREATE TABLE provider_field_mappings (
    mapping_id TEXT PRIMARY KEY,
    mapping_version_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    statement_type TEXT NOT NULL
        CHECK (statement_type IN ('balance_sheet', 'income_statement', 'cash_flow_statement')),
    source_field TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('exact', 'formula', 'manual_verified', 'fuzzy')),
    formula TEXT,
    production_allowed BOOLEAN NOT NULL,
    UNIQUE (mapping_version_id, provider_id, statement_type, source_field),
    FOREIGN KEY (mapping_version_id, provider_id)
        REFERENCES metric_mapping_versions(mapping_version_id, provider_id),
    FOREIGN KEY (metric_code, statement_type)
        REFERENCES canonical_metrics(metric_code, statement_type),
    CHECK ((method = 'formula' AND formula IS NOT NULL) OR (method <> 'formula' AND formula IS NULL)),
    CHECK (method <> 'fuzzy' OR production_allowed = FALSE)
);

CREATE TABLE financial_quality_rules (
    rule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rule_kind TEXT NOT NULL CHECK (rule_kind IN ('accounting_identity', 'cross_statement', 'range')),
    terms JSONB NOT NULL,
    tolerance NUMERIC NOT NULL CHECK (tolerance >= 0),
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'block'))
);

CREATE TABLE unmapped_metric_fields (
    unmapped_field_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    statement_type TEXT NOT NULL
        CHECK (statement_type IN ('balance_sheet', 'income_statement', 'cash_flow_statement')),
    source_field TEXT NOT NULL,
    mapping_version_id TEXT NOT NULL REFERENCES metric_mapping_versions(mapping_version_id),
    discovered_at TIMESTAMPTZ NOT NULL,
    raw_object_id TEXT NOT NULL REFERENCES raw_objects(raw_object_id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'mapped', 'ignored')),
    resolved_mapping_id TEXT REFERENCES provider_field_mappings(mapping_id),
    resolution_reason TEXT,
    CHECK (
        (status = 'pending' AND resolved_mapping_id IS NULL AND resolution_reason IS NULL)
        OR (status = 'mapped' AND resolved_mapping_id IS NOT NULL)
        OR (status = 'ignored' AND resolution_reason IS NOT NULL)
    )
);

CREATE INDEX unmapped_metric_fields_queue_idx
    ON unmapped_metric_fields(status, provider_id, discovered_at);
