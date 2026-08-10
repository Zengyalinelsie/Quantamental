ALTER TABLE ingestion_checkpoints
    DROP CONSTRAINT ingestion_checkpoints_data_domain_check;

ALTER TABLE ingestion_checkpoints
    ADD CONSTRAINT ingestion_checkpoints_data_domain_check CHECK (
        data_domain IN (
            'security_master',
            'universe',
            'raw_daily_bar',
            'share_capital',
            'corporate_action',
            'trading_calendar',
            'financial_statement'
        )
    );

CREATE TABLE financial_backfill_work_units (
    job_id TEXT NOT NULL,
    checkpoint_key TEXT NOT NULL,
    plan_id TEXT NOT NULL CHECK (plan_id <> ''),
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    provider_profile_version TEXT NOT NULL CHECK (provider_profile_version <> ''),
    benchmark_id TEXT NOT NULL CHECK (benchmark_id IN ('index:000300', 'index:000905')),
    universe_version_id TEXT NOT NULL REFERENCES universe_versions(universe_version_id),
    mapping_version_id TEXT NOT NULL REFERENCES metric_mapping_versions(mapping_version_id),
    statement_type TEXT NOT NULL CHECK (
        statement_type IN ('balance_sheet', 'income_statement', 'cash_flow_statement')
    ),
    provider_table TEXT NOT NULL CHECK (provider_table <> ''),
    report_period_end DATE NOT NULL,
    symbol_bucket_id TEXT NOT NULL CHECK (symbol_bucket_id <> ''),
    symbols JSONB NOT NULL CHECK (jsonb_typeof(symbols) = 'array'),
    symbol_count INTEGER NOT NULL CHECK (
        symbol_count > 0 AND symbol_count = jsonb_array_length(symbols)
    ),
    PRIMARY KEY (job_id, checkpoint_key),
    FOREIGN KEY (job_id, checkpoint_key)
        REFERENCES ingestion_checkpoints(job_id, checkpoint_key)
);

ALTER TABLE dataset_coverage_reports
    DROP CONSTRAINT dataset_coverage_reports_data_domain_check;

ALTER TABLE dataset_coverage_reports
    ADD CONSTRAINT dataset_coverage_reports_data_domain_check CHECK (
        data_domain IN (
            'security_master',
            'universe',
            'raw_daily_bar',
            'share_capital',
            'corporate_action',
            'trading_calendar',
            'financial_statement'
        )
    );

CREATE INDEX ingestion_financial_checkpoint_resume
    ON ingestion_checkpoints(
        job_id,
        status,
        start_date,
        end_date
    )
    WHERE data_domain = 'financial_statement';

CREATE INDEX financial_backfill_work_unit_lookup
    ON financial_backfill_work_units(
        provider_id,
        provider_table,
        report_period_end,
        symbol_bucket_id
    );
