-- Official identity changes and provider-local corrections are different facts.
-- Only the first table is eligible for global identity resolution. A consumer of
-- the second table must name the provider whose payload is being corrected.

CREATE TABLE official_identifier_aliases (
    official_identifier_alias_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    kind TEXT NOT NULL CHECK (kind IN ('code', 'name')),
    value TEXT NOT NULL CHECK (value <> ''),
    valid_from DATE NOT NULL,
    valid_to DATE,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    evidence_url TEXT NOT NULL CHECK (evidence_url ~ '^https://'),
    published_on DATE NOT NULL,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (listing_id, kind, valid_from)
);

CREATE INDEX official_identifier_alias_lookup
    ON official_identifier_aliases(kind, value, valid_from, valid_to);

CREATE TABLE provider_identifier_corrections (
    provider_identifier_correction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    kind TEXT NOT NULL CHECK (kind IN ('code', 'name')),
    observed_value TEXT NOT NULL CHECK (observed_value <> ''),
    valid_from DATE NOT NULL,
    valid_to DATE,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    reason TEXT NOT NULL CHECK (reason <> ''),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (provider_id, kind, observed_value, valid_from)
);

CREATE INDEX provider_identifier_correction_lookup
    ON provider_identifier_corrections(
        provider_id, kind, observed_value, valid_from, valid_to
    );

CREATE FUNCTION prevent_identifier_alias_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER official_identifier_aliases_append_only
BEFORE UPDATE OR DELETE ON official_identifier_aliases
FOR EACH ROW EXECUTE FUNCTION prevent_identifier_alias_mutation();

CREATE TRIGGER provider_identifier_corrections_append_only
BEFORE UPDATE OR DELETE ON provider_identifier_corrections
FOR EACH ROW EXECUTE FUNCTION prevent_identifier_alias_mutation();
