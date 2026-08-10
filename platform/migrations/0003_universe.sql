CREATE TABLE universe_definitions (
    definition_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (name <> ''),
    ruleset_version TEXT NOT NULL CHECK (ruleset_version <> ''),
    benchmark_id TEXT NOT NULL CHECK (benchmark_id <> '')
);

CREATE TABLE universe_versions (
    universe_version_id TEXT PRIMARY KEY,
    definition_id TEXT NOT NULL REFERENCES universe_definitions(definition_id),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE universe_memberships (
    universe_membership_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_version_id TEXT NOT NULL REFERENCES universe_versions(universe_version_id),
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    research_eligible BOOLEAN NOT NULL,
    tradable_eligible BOOLEAN NOT NULL,
    inclusion_reasons JSONB NOT NULL,
    exclusion_reasons JSONB NOT NULL,
    benchmark_member BOOLEAN NOT NULL,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (NOT tradable_eligible OR research_eligible),
    CHECK (jsonb_typeof(inclusion_reasons) = 'array'),
    CHECK (jsonb_typeof(exclusion_reasons) = 'array'),
    UNIQUE (universe_version_id, listing_id, valid_from)
);

CREATE INDEX universe_membership_as_of
    ON universe_memberships(universe_version_id, valid_from, valid_to);
