CREATE TABLE factor_validation_reports (
    report_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    report_kind TEXT NOT NULL CHECK (report_kind = 'p4_data_qualification'),
    factor_version_id TEXT NOT NULL CHECK (factor_version_id <> ''),
    experiment_run_id TEXT NOT NULL UNIQUE REFERENCES experiment_runs(run_id),
    input_trust_state TEXT NOT NULL CHECK (
        input_trust_state IN ('raw_unverified', 'normalized_current', 'pit_verified')
    ),
    passes_promotion_gate BOOLEAN NOT NULL CHECK (passes_promotion_gate = FALSE),
    report_document JSONB NOT NULL CHECK (jsonb_typeof(report_document) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE factor_qualification_audits (
    audit_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    factor_key TEXT NOT NULL CHECK (
        factor_key IN (
            'quality', 'valuation_expectation_gap', 'fundamental_improvement'
        )
    ),
    factor_version_id TEXT NOT NULL CHECK (factor_version_id <> ''),
    factor_version_hash TEXT NOT NULL CHECK (
        factor_version_hash ~ '^[0-9a-f]{64}$'
    ),
    factor_lifecycle_status TEXT NOT NULL CHECK (
        factor_lifecycle_status IN ('draft', 'research')
    ),
    study_id TEXT NOT NULL CHECK (study_id <> ''),
    snapshot_hash TEXT NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    readiness_permitted BOOLEAN NOT NULL CHECK (readiness_permitted = FALSE),
    experiment_run_id TEXT NOT NULL UNIQUE REFERENCES experiment_runs(run_id),
    validation_report_id TEXT NOT NULL UNIQUE REFERENCES factor_validation_reports(report_id),
    artifact_id TEXT NOT NULL UNIQUE CHECK (artifact_id <> ''),
    artifact_hash TEXT NOT NULL UNIQUE CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    role_dataset_version_ids JSONB NOT NULL CHECK (
        jsonb_typeof(role_dataset_version_ids) = 'object'
    ),
    readiness_document JSONB NOT NULL CHECK (
        jsonb_typeof(readiness_document) = 'object'
    ),
    factor_version_document JSONB NOT NULL CHECK (
        jsonb_typeof(factor_version_document) = 'object'
    ),
    artifact_document JSONB NOT NULL CHECK (jsonb_typeof(artifact_document) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION prevent_factor_qualification_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'factor qualification evidence is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER factor_validation_reports_append_only
BEFORE UPDATE OR DELETE ON factor_validation_reports
FOR EACH ROW EXECUTE FUNCTION prevent_factor_qualification_mutation();

CREATE TRIGGER factor_qualification_audits_append_only
BEFORE UPDATE OR DELETE ON factor_qualification_audits
FOR EACH ROW EXECUTE FUNCTION prevent_factor_qualification_mutation();

CREATE OR REPLACE FUNCTION enforce_failed_factor_qualification_run()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM experiment_runs
        WHERE run_id = NEW.experiment_run_id
          AND status = 'failed'
          AND jsonb_array_length(metrics) = 0
    ) THEN
        RAISE EXCEPTION 'factor qualification requires a failed metric-free ExperimentRun';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER factor_qualification_requires_failed_run
BEFORE INSERT ON factor_qualification_audits
FOR EACH ROW EXECUTE FUNCTION enforce_failed_factor_qualification_run();
