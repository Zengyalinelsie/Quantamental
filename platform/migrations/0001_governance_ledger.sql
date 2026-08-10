CREATE TABLE dataset_versions (
    dataset_version_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    schema_version TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE run_records (
    run_id TEXT PRIMARY KEY,
    run_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    deployment_stage TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    failure_reason TEXT,
    code_version TEXT NOT NULL,
    environment_fingerprint TEXT NOT NULL
);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    run_id TEXT NOT NULL REFERENCES run_records(run_id)
);

CREATE TABLE lineage_edges (
    upstream_id TEXT NOT NULL,
    downstream_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (upstream_id, downstream_id, relation),
    CHECK (upstream_id <> downstream_id)
);
