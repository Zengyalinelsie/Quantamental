CREATE TABLE experiment_specs (
    spec_id TEXT PRIMARY KEY CHECK (spec_id <> ''),
    content_hash TEXT NOT NULL UNIQUE CHECK (
        content_hash ~ '^[0-9a-f]{64}$'
    ),
    data_mode TEXT NOT NULL CHECK (
        data_mode IN ('current_research', 'strict_historical')
    ),
    deployment_stage TEXT NOT NULL CHECK (
        deployment_stage IN ('research', 'shadow', 'paper', 'limited_live')
    ),
    universe_version_id TEXT NOT NULL CHECK (universe_version_id <> ''),
    spec_document JSONB NOT NULL CHECK (jsonb_typeof(spec_document) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        data_mode <> 'strict_historical' OR deployment_stage = 'research'
    ),
    CHECK (spec_document ->> 'spec_id' = spec_id),
    CHECK (spec_document ->> 'universe_version_id' = universe_version_id),
    CHECK (
        jsonb_typeof(spec_document -> 'dataset_version_ids') = 'array'
        AND jsonb_array_length(spec_document -> 'dataset_version_ids') > 0
    ),
    CHECK (
        jsonb_typeof(spec_document -> 'feature_bindings') = 'array'
        AND jsonb_array_length(spec_document -> 'feature_bindings') > 0
    ),
    CHECK (
        jsonb_typeof(spec_document -> 'label_bindings') = 'array'
        AND jsonb_array_length(spec_document -> 'label_bindings') > 0
    )
);

CREATE UNIQUE INDEX experiment_specs_identity_hash
ON experiment_specs (spec_id, content_hash);

CREATE TABLE experiment_runs (
    run_id TEXT PRIMARY KEY CHECK (run_id <> ''),
    content_hash TEXT NOT NULL UNIQUE CHECK (
        content_hash ~ '^[0-9a-f]{64}$'
    ),
    spec_hash TEXT NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    spec_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('planned', 'running', 'succeeded', 'failed')
    ),
    started_at TIMESTAMPTZ,
    metrics JSONB NOT NULL CHECK (jsonb_typeof(metrics) = 'array'),
    artifacts JSONB NOT NULL CHECK (jsonb_typeof(artifacts) = 'array'),
    finished_at TIMESTAMPTZ,
    failure_evidence JSONB,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (spec_id, spec_hash)
        REFERENCES experiment_specs(spec_id, content_hash),
    CHECK (finished_at IS NULL OR started_at IS NOT NULL),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (failure_evidence IS NULL OR jsonb_typeof(failure_evidence) = 'object'),
    CHECK (
        (status = 'planned'
            AND started_at IS NULL
            AND finished_at IS NULL
            AND jsonb_array_length(metrics) = 0
            AND jsonb_array_length(artifacts) = 0
            AND failure_evidence IS NULL)
        OR
        (status = 'running'
            AND started_at IS NOT NULL
            AND finished_at IS NULL
            AND jsonb_array_length(metrics) = 0
            AND jsonb_array_length(artifacts) = 0
            AND failure_evidence IS NULL)
        OR
        (status = 'succeeded'
            AND started_at IS NOT NULL
            AND finished_at IS NOT NULL
            AND jsonb_array_length(metrics) > 0
            AND jsonb_array_length(artifacts) > 0
            AND failure_evidence IS NULL)
        OR
        (status = 'failed'
            AND started_at IS NOT NULL
            AND finished_at IS NOT NULL
            AND failure_evidence IS NOT NULL)
    )
);

CREATE INDEX experiment_runs_status_recorded
ON experiment_runs (status, recorded_at, run_id);

CREATE FUNCTION reject_experiment_spec_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'experiment specs are append-only';
END;
$$;

CREATE TRIGGER experiment_specs_append_only
BEFORE UPDATE OR DELETE ON experiment_specs
FOR EACH ROW EXECUTE FUNCTION reject_experiment_spec_mutation();

CREATE FUNCTION reject_experiment_run_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'experiment runs are append-only';
END;
$$;

CREATE TRIGGER experiment_runs_append_only
BEFORE UPDATE OR DELETE ON experiment_runs
FOR EACH ROW EXECUTE FUNCTION reject_experiment_run_mutation();
