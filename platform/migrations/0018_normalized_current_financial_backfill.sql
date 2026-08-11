ALTER TABLE ingestion_jobs
    DROP CONSTRAINT ingestion_jobs_adjustment_mode_check;

ALTER TABLE ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_adjustment_mode_check CHECK (
        adjustment_mode IN ('unadjusted', 'not_applicable')
    );

ALTER TABLE ingestion_checkpoints
    DROP CONSTRAINT ingestion_checkpoints_adjustment_mode_check;

ALTER TABLE ingestion_checkpoints
    ADD CONSTRAINT ingestion_checkpoints_adjustment_mode_check CHECK (
        adjustment_mode IS NULL
        OR (
            data_domain = 'raw_daily_bar'
            AND adjustment_mode = 'unadjusted'
        )
        OR (
            data_domain IN (
                'security_master',
                'universe',
                'share_capital',
                'corporate_action',
                'trading_calendar',
                'financial_statement'
            )
            AND adjustment_mode = 'not_applicable'
        )
    );

ALTER TABLE raw_objects
    ADD CONSTRAINT raw_objects_financial_evidence_identity_unique UNIQUE (
        raw_object_id,
        provider_id,
        content_hash
    );

ALTER TABLE provider_field_mappings
    ADD CONSTRAINT provider_field_mappings_financial_identity_unique UNIQUE (
        mapping_id,
        mapping_version_id,
        provider_id,
        statement_type,
        source_field,
        metric_code
    );

ALTER TABLE securities
    ADD CONSTRAINT securities_financial_identity_unique UNIQUE (security_id, company_id);

ALTER TABLE listings
    ADD CONSTRAINT listings_financial_identity_unique UNIQUE (listing_id, security_id);

CREATE TABLE normalized_current_financial_observations (
    observation_id TEXT PRIMARY KEY CHECK (observation_id <> ''),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    job_id TEXT NOT NULL,
    checkpoint_key TEXT NOT NULL,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    security_id TEXT NOT NULL REFERENCES securities(security_id),
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    canonical_symbol TEXT NOT NULL CHECK (canonical_symbol ~ '^(SH|SZ)\.[0-9]{6}$'),
    identity_as_of DATE NOT NULL,
    mapped_row_id TEXT NOT NULL CHECK (mapped_row_id <> ''),
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    provider_table TEXT NOT NULL CHECK (provider_table <> ''),
    provider_record_id TEXT NOT NULL CHECK (provider_record_id <> ''),
    provider_field TEXT NOT NULL CHECK (provider_field <> ''),
    statement_type TEXT NOT NULL CHECK (
        statement_type IN ('balance_sheet', 'income_statement', 'cash_flow_statement')
    ),
    statement_scope TEXT NOT NULL CHECK (
        statement_scope IN ('consolidated', 'parent_company', 'unknown')
    ),
    report_period_start DATE NOT NULL,
    report_period_end DATE NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('q1', 'half_year', 'q3', 'annual', 'ttm')),
    value_basis TEXT NOT NULL CHECK (
        value_basis IN ('point_in_time', 'cumulative_ytd', 'single_quarter', 'ttm')
    ),
    raw_value NUMERIC NOT NULL,
    provider_unit TEXT NOT NULL CHECK (provider_unit <> ''),
    scale_to_canonical NUMERIC NOT NULL CHECK (scale_to_canonical <> 0),
    canonical_value NUMERIC NOT NULL,
    canonical_unit TEXT NOT NULL CHECK (
        canonical_unit IN (
            'currency', 'currency_per_share', 'shares', 'ratio', 'count', 'days', 'text'
        )
    ),
    currency TEXT,
    report_version_type TEXT NOT NULL CHECK (
        report_version_type IN ('original', 'corrected', 'restated', 'unknown')
    ),
    revision_sequence INTEGER NOT NULL CHECK (revision_sequence >= 0),
    announced_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ,
    availability_method TEXT NOT NULL CHECK (
        availability_method IN (
            'provider_exact',
            'official_disclosure_exact',
            'conservative_retrieval_time',
            'unavailable'
        )
    ),
    provider_updated_at TIMESTAMPTZ,
    retrieved_at TIMESTAMPTZ NOT NULL,
    raw_object_id TEXT NOT NULL,
    raw_object_hash TEXT NOT NULL CHECK (raw_object_hash ~ '^sha256:[0-9a-f]{64}$'),
    source_url TEXT NOT NULL CHECK (source_url <> ''),
    mapping_id TEXT NOT NULL,
    mapping_version_id TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    trust_state TEXT NOT NULL CHECK (trust_state = 'normalized_current'),
    data_mode TEXT NOT NULL CHECK (data_mode = 'current_research'),
    warnings JSONB NOT NULL CHECK (jsonb_typeof(warnings) = 'array'),
    FOREIGN KEY (job_id, checkpoint_key)
        REFERENCES financial_backfill_work_units(job_id, checkpoint_key),
    FOREIGN KEY (security_id, company_id)
        REFERENCES securities(security_id, company_id),
    FOREIGN KEY (listing_id, security_id)
        REFERENCES listings(listing_id, security_id),
    FOREIGN KEY (raw_object_id, provider_id, raw_object_hash)
        REFERENCES raw_objects(raw_object_id, provider_id, content_hash),
    FOREIGN KEY (
        mapping_id,
        mapping_version_id,
        provider_id,
        statement_type,
        provider_field,
        metric_code
    ) REFERENCES provider_field_mappings(
        mapping_id,
        mapping_version_id,
        provider_id,
        statement_type,
        source_field,
        metric_code
    ),
    FOREIGN KEY (metric_code, statement_type)
        REFERENCES canonical_metrics(metric_code, statement_type),
    CHECK (report_period_end >= report_period_start),
    CHECK (identity_as_of = report_period_end),
    CHECK (canonical_value = raw_value * scale_to_canonical),
    CHECK (
        (canonical_unit IN ('currency', 'currency_per_share') AND currency ~ '^[A-Z]{3}$')
        OR (canonical_unit NOT IN ('currency', 'currency_per_share') AND currency IS NULL)
    ),
    CHECK (announced_at IS NULL OR available_at IS NULL OR available_at >= announced_at),
    CHECK (available_at IS NULL OR available_at <= retrieved_at),
    CHECK (
        (availability_method IN ('provider_exact', 'official_disclosure_exact')
            AND available_at IS NOT NULL)
        OR (availability_method = 'conservative_retrieval_time'
            AND available_at = retrieved_at)
        OR (availability_method = 'unavailable' AND available_at IS NULL)
    ),
    UNIQUE (dataset_version_id, mapped_row_id, listing_id)
);

CREATE INDEX normalized_current_financial_lookup
    ON normalized_current_financial_observations (
        company_id,
        security_id,
        metric_code,
        report_period_end,
        statement_scope,
        provider_id
    );

CREATE TABLE financial_backfill_persist_receipts (
    job_id TEXT NOT NULL,
    checkpoint_key TEXT NOT NULL,
    dataset_version_id TEXT NOT NULL UNIQUE REFERENCES dataset_versions(dataset_version_id),
    observation_count INTEGER NOT NULL CHECK (observation_count > 0),
    observation_ids JSONB NOT NULL CHECK (
        jsonb_typeof(observation_ids) = 'array'
        AND jsonb_array_length(observation_ids) > 0
    ),
    warnings JSONB NOT NULL CHECK (jsonb_typeof(warnings) = 'array'),
    trust_state TEXT NOT NULL CHECK (trust_state = 'normalized_current'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (job_id, checkpoint_key),
    FOREIGN KEY (job_id, checkpoint_key)
        REFERENCES financial_backfill_work_units(job_id, checkpoint_key),
    CHECK (observation_count = jsonb_array_length(observation_ids))
);

CREATE FUNCTION reject_normalized_current_financial_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'normalized-current financial records are append-only';
END;
$$;

CREATE TRIGGER normalized_current_financial_observations_append_only
BEFORE UPDATE OR DELETE ON normalized_current_financial_observations
FOR EACH ROW EXECUTE FUNCTION reject_normalized_current_financial_mutation();

CREATE TRIGGER financial_backfill_persist_receipts_append_only
BEFORE UPDATE OR DELETE ON financial_backfill_persist_receipts
FOR EACH ROW EXECUTE FUNCTION reject_normalized_current_financial_mutation();
