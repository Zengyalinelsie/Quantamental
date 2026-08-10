CREATE TABLE raw_objects (
    raw_object_id TEXT PRIMARY KEY,
    object_kind TEXT NOT NULL CHECK (object_kind IN ('request', 'response', 'file')),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    source_url TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    media_type TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    license_id TEXT NOT NULL,
    retention_policy TEXT NOT NULL
        CHECK (retention_policy IN ('indefinite', 'until_date', 'metadata_only')),
    retention_until DATE,
    redistribution_allowed BOOLEAN NOT NULL,
    parent_raw_object_id TEXT REFERENCES raw_objects(raw_object_id),
    CHECK (parent_raw_object_id IS NULL OR parent_raw_object_id <> raw_object_id),
    CHECK (
        (retention_policy = 'until_date' AND retention_until IS NOT NULL)
        OR (retention_policy <> 'until_date' AND retention_until IS NULL)
    )
);

CREATE INDEX raw_objects_content_hash_idx ON raw_objects(content_hash);
CREATE INDEX raw_objects_provider_retrieved_idx ON raw_objects(provider_id, retrieved_at);

CREATE TABLE official_disclosures (
    disclosure_id TEXT PRIMARY KEY,
    document_key TEXT NOT NULL,
    external_document_id TEXT NOT NULL,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    security_id TEXT REFERENCES securities(security_id),
    source_system TEXT NOT NULL CHECK (source_system IN ('cninfo', 'sse', 'szse', 'bse', 'company')),
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    report_period_end DATE,
    published_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    first_tradable_at TIMESTAMPTZ NOT NULL,
    version_sequence INTEGER NOT NULL CHECK (version_sequence >= 0),
    status TEXT NOT NULL CHECK (status IN ('published', 'corrected', 'withdrawn')),
    raw_object_id TEXT NOT NULL REFERENCES raw_objects(raw_object_id),
    supersedes_disclosure_id TEXT REFERENCES official_disclosures(disclosure_id),
    status_reason TEXT,
    UNIQUE (document_key, version_sequence),
    UNIQUE (source_system, external_document_id),
    CHECK (available_at >= published_at),
    CHECK (first_tradable_at >= available_at),
    CHECK (
        (version_sequence = 0 AND status = 'published'
            AND supersedes_disclosure_id IS NULL AND status_reason IS NULL)
        OR (version_sequence > 0 AND status IN ('corrected', 'withdrawn')
            AND supersedes_disclosure_id IS NOT NULL AND status_reason IS NOT NULL)
    )
);

CREATE INDEX official_disclosures_company_time_idx
    ON official_disclosures(company_id, published_at);
CREATE INDEX official_disclosures_security_time_idx
    ON official_disclosures(security_id, published_at);
