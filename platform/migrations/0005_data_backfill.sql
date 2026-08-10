CREATE TABLE ingestion_jobs (
    job_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL UNIQUE CHECK (plan_id <> ''),
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    status TEXT NOT NULL CHECK (status IN ('planned', 'blocked', 'running', 'succeeded', 'failed')),
    plan JSONB NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
    qualification JSONB NOT NULL CHECK (jsonb_typeof(qualification) = 'object'),
    output_trust_state TEXT NOT NULL CHECK (
        output_trust_state IN ('raw', 'normalized_current', 'pit_verified')
    ),
    adjustment_mode TEXT NOT NULL CHECK (adjustment_mode = 'unadjusted'),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    dataset_version_id TEXT REFERENCES dataset_versions(dataset_version_id),
    failure_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    CHECK (end_date >= start_date),
    CHECK (updated_at >= created_at),
    CHECK (jsonb_typeof(failure_reasons) = 'array'),
    CHECK (status <> 'succeeded' OR dataset_version_id IS NOT NULL),
    CHECK (status NOT IN ('blocked', 'failed') OR jsonb_array_length(failure_reasons) > 0)
);

CREATE TABLE ingestion_job_events (
    job_id TEXT NOT NULL REFERENCES ingestion_jobs(job_id),
    sequence BIGINT GENERATED ALWAYS AS IDENTITY,
    status TEXT NOT NULL CHECK (status IN ('planned', 'blocked', 'running', 'succeeded', 'failed')),
    recorded_at TIMESTAMPTZ NOT NULL,
    failure_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    dataset_version_id TEXT REFERENCES dataset_versions(dataset_version_id),
    PRIMARY KEY (job_id, sequence),
    CHECK (jsonb_typeof(failure_reasons) = 'array')
);

CREATE TABLE ingestion_checkpoints (
    job_id TEXT NOT NULL REFERENCES ingestion_jobs(job_id),
    checkpoint_key TEXT NOT NULL CHECK (checkpoint_key <> ''),
    scope_id TEXT NOT NULL CHECK (scope_id <> ''),
    data_domain TEXT NOT NULL CHECK (
        data_domain IN (
            'security_master',
            'universe',
            'raw_daily_bar',
            'share_capital',
            'corporate_action',
            'trading_calendar'
        )
    ),
    market TEXT CHECK (market IN ('XSHG', 'XSHE', 'XBSE')),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    cursor TEXT,
    processed_rows BIGINT NOT NULL DEFAULT 0 CHECK (processed_rows >= 0),
    rejected_rows BIGINT NOT NULL DEFAULT 0 CHECK (rejected_rows >= 0),
    content_hash TEXT,
    provider_id TEXT CHECK (provider_id IS NULL OR provider_id <> ''),
    provider_cutoff_date DATE,
    retrieved_at TIMESTAMPTZ,
    adjustment_mode TEXT CHECK (adjustment_mode IS NULL OR adjustment_mode = 'unadjusted'),
    units JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (job_id, checkpoint_key),
    CHECK (end_date >= start_date),
    CHECK (jsonb_typeof(units) = 'object'),
    CHECK (jsonb_typeof(warnings) = 'array'),
    CHECK (status <> 'succeeded' OR content_hash IS NOT NULL),
    CHECK (status <> 'succeeded' OR provider_id IS NOT NULL),
    CHECK (status <> 'failed' OR error IS NOT NULL)
);

CREATE INDEX ingestion_checkpoint_resume
    ON ingestion_checkpoints(job_id, status, data_domain, start_date, end_date);

CREATE TABLE dataset_quality_reports (
    quality_report_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    job_id TEXT NOT NULL REFERENCES ingestion_jobs(job_id),
    status TEXT NOT NULL CHECK (status IN ('passed', 'warned', 'failed')),
    checks_passed INTEGER NOT NULL CHECK (checks_passed >= 0),
    checks_failed INTEGER NOT NULL CHECK (checks_failed >= 0),
    issue_counts JSONB NOT NULL CHECK (jsonb_typeof(issue_counts) = 'object'),
    warnings JSONB NOT NULL CHECK (jsonb_typeof(warnings) = 'array'),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE dataset_coverage_reports (
    coverage_report_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    job_id TEXT NOT NULL REFERENCES ingestion_jobs(job_id),
    scope_id TEXT NOT NULL CHECK (scope_id <> ''),
    data_domain TEXT NOT NULL CHECK (
        data_domain IN (
            'security_master',
            'universe',
            'raw_daily_bar',
            'share_capital',
            'corporate_action',
            'trading_calendar'
        )
    ),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    expected_rows BIGINT CHECK (expected_rows IS NULL OR expected_rows >= 0),
    observed_rows BIGINT NOT NULL CHECK (observed_rows >= 0),
    coverage_ratio DOUBLE PRECISION CHECK (
        coverage_ratio IS NULL OR coverage_ratio BETWEEN 0.0 AND 1.0
    ),
    warnings JSONB NOT NULL CHECK (jsonb_typeof(warnings) = 'array'),
    created_at TIMESTAMPTZ NOT NULL,
    CHECK (end_date >= start_date)
);

CREATE INDEX dataset_coverage_lookup
    ON dataset_coverage_reports(dataset_version_id, scope_id, data_domain, start_date, end_date);
