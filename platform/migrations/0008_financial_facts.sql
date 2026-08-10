CREATE TABLE financial_authority_rules (
    rule_version TEXT PRIMARY KEY,
    provider_priority JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    code_version TEXT NOT NULL,
    CHECK (jsonb_typeof(provider_priority) = 'array'),
    CHECK (jsonb_array_length(provider_priority) > 0)
);

CREATE TABLE financial_fact_observations (
    fact_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    security_id TEXT NOT NULL REFERENCES securities(security_id),
    metric_code TEXT NOT NULL REFERENCES canonical_metrics(metric_code),
    fact_value JSONB NOT NULL,
    unit TEXT NOT NULL
        CHECK (unit IN ('currency', 'currency_per_share', 'shares', 'ratio', 'count', 'days', 'text')),
    currency TEXT,
    report_period_end DATE NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('q1', 'half_year', 'q3', 'annual', 'ttm')),
    statement_type TEXT NOT NULL
        CHECK (statement_type IN ('balance_sheet', 'income_statement', 'cash_flow_statement')),
    announced_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    known_from TIMESTAMPTZ NOT NULL,
    known_to TIMESTAMPTZ,
    revision_sequence INTEGER NOT NULL CHECK (revision_sequence >= 0),
    provider_id TEXT NOT NULL,
    source_field TEXT NOT NULL,
    raw_object_hash TEXT NOT NULL CHECK (raw_object_hash ~ '^sha256:[0-9a-f]{64}$'),
    trust_state TEXT NOT NULL CHECK (trust_state IN ('raw', 'normalized_current', 'pit_verified')),
    quality_state TEXT NOT NULL CHECK (quality_state IN ('passed', 'warning', 'blocked', 'unavailable')),
    mapping_version_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL REFERENCES raw_objects(raw_object_id),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    quality_issue_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    FOREIGN KEY (mapping_version_id, provider_id)
        REFERENCES metric_mapping_versions(mapping_version_id, provider_id),
    FOREIGN KEY (metric_code, statement_type)
        REFERENCES canonical_metrics(metric_code, statement_type),
    CHECK (jsonb_typeof(fact_value) IN ('string', 'number', 'boolean')),
    CHECK (
        (unit IN ('currency', 'currency_per_share') AND currency ~ '^[A-Z]{3}$')
        OR (unit NOT IN ('currency', 'currency_per_share') AND currency IS NULL)
    ),
    CHECK (available_at >= announced_at),
    CHECK (known_to IS NULL OR known_to > known_from),
    CHECK (jsonb_typeof(quality_issue_ids) = 'array'),
    CHECK (
        quality_state NOT IN ('blocked', 'unavailable')
        OR jsonb_array_length(quality_issue_ids) > 0
    )
);

CREATE UNIQUE INDEX financial_fact_open_source_revision_idx
    ON financial_fact_observations (
        company_id, security_id, metric_code, report_period_end,
        period_type, statement_type, provider_id, revision_sequence
    )
    WHERE known_to IS NULL;

CREATE INDEX financial_fact_economic_query_idx
    ON financial_fact_observations (
        company_id, security_id, metric_code, report_period_end,
        period_type, statement_type, provider_id, available_at, known_from
    );

CREATE INDEX financial_fact_dataset_idx
    ON financial_fact_observations(dataset_version_id);
