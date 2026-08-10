CREATE TABLE feature_snapshots (
    snapshot_id TEXT PRIMARY KEY CHECK (snapshot_id <> ''),
    content_hash TEXT NOT NULL UNIQUE CHECK (
        content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    feature_id TEXT NOT NULL CHECK (feature_id <> ''),
    feature_version TEXT NOT NULL CHECK (feature_version <> ''),
    feature_definition_hash TEXT NOT NULL CHECK (
        feature_definition_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    formula_version TEXT NOT NULL CHECK (formula_version <> ''),
    missing_policy_version TEXT NOT NULL CHECK (missing_policy_version <> ''),
    winsorization_version TEXT NOT NULL CHECK (winsorization_version <> ''),
    standardization_version TEXT NOT NULL CHECK (standardization_version <> ''),
    neutralization_version TEXT NOT NULL CHECK (neutralization_version <> ''),
    entity_id TEXT NOT NULL CHECK (entity_id <> ''),
    as_of TIMESTAMPTZ NOT NULL,
    system_as_of TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('quantified', 'unavailable')),
    feature_value NUMERIC,
    value_stage TEXT NOT NULL CHECK (
        value_stage IN ('raw', 'winsorized', 'standardized', 'neutralized')
    ),
    unit TEXT NOT NULL CHECK (
        unit IN ('currency', 'currency_per_share', 'shares', 'ratio', 'count', 'days')
    ),
    currency TEXT,
    period TEXT NOT NULL CHECK (
        period IN ('instant', 'daily', 'q1', 'half_year', 'q3', 'annual', 'ttm')
    ),
    missing_input_names JSONB NOT NULL CHECK (
        jsonb_typeof(missing_input_names) = 'array'
    ),
    dataset_version_ids JSONB NOT NULL CHECK (
        jsonb_typeof(dataset_version_ids) = 'array'
        AND jsonb_array_length(dataset_version_ids) > 0
    ),
    input_content_hashes JSONB NOT NULL CHECK (
        jsonb_typeof(input_content_hashes) = 'array'
        AND jsonb_array_length(input_content_hashes) > 0
    ),
    CHECK (system_as_of >= as_of),
    CHECK (
        (unit IN ('currency', 'currency_per_share') AND currency ~ '^[A-Z]{3}$')
        OR (unit NOT IN ('currency', 'currency_per_share') AND currency IS NULL)
    ),
    CHECK (
        (status = 'quantified' AND feature_value IS NOT NULL
            AND jsonb_array_length(missing_input_names) = 0)
        OR (status = 'unavailable' AND feature_value IS NULL
            AND jsonb_array_length(missing_input_names) > 0)
    )
);

CREATE INDEX feature_snapshot_lookup
ON feature_snapshots (feature_id, entity_id, as_of, system_as_of);

CREATE FUNCTION reject_feature_snapshot_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'feature snapshots are append-only';
END;
$$;

CREATE TRIGGER feature_snapshots_append_only
BEFORE UPDATE OR DELETE ON feature_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_feature_snapshot_mutation();

CREATE TABLE research_labels (
    content_hash TEXT PRIMARY KEY CHECK (
        content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    label_id TEXT NOT NULL CHECK (label_id <> ''),
    label_version TEXT NOT NULL CHECK (label_version <> ''),
    schema_hash TEXT NOT NULL CHECK (
        schema_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    horizon_sessions INTEGER NOT NULL CHECK (horizon_sessions > 0),
    unit TEXT NOT NULL CHECK (
        unit IN ('currency', 'currency_per_share', 'shares', 'ratio', 'count', 'days')
    ),
    currency TEXT,
    period TEXT NOT NULL CHECK (
        period IN ('instant', 'daily', 'q1', 'half_year', 'q3', 'annual', 'ttm')
    ),
    label_value NUMERIC NOT NULL,
    entity_id TEXT NOT NULL CHECK (entity_id <> ''),
    as_of TIMESTAMPTZ NOT NULL,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    CHECK (
        (unit IN ('currency', 'currency_per_share') AND currency ~ '^[A-Z]{3}$')
        OR (unit NOT IN ('currency', 'currency_per_share') AND currency IS NULL)
    )
);

CREATE INDEX research_label_lookup
ON research_labels (label_id, entity_id, as_of);

CREATE FUNCTION reject_research_label_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'research labels are append-only';
END;
$$;

CREATE TRIGGER research_labels_append_only
BEFORE UPDATE OR DELETE ON research_labels
FOR EACH ROW EXECUTE FUNCTION reject_research_label_mutation();
