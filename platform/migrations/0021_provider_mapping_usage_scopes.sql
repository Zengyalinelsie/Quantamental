ALTER TABLE provider_field_mappings
    ADD COLUMN allowed_use_scopes TEXT[] NOT NULL
        DEFAULT ARRAY['current_research']::TEXT[];

-- Existing boolean approvals are deliberately reduced to current research.  A
-- future strict-historical or production grant requires a new mapping version;
-- this migration must not infer a higher-purpose approval from the old flag.
ALTER TABLE provider_field_mappings
    ALTER COLUMN allowed_use_scopes DROP DEFAULT,
    DROP COLUMN production_allowed;

ALTER TABLE provider_field_mappings
    ADD CONSTRAINT provider_field_mappings_use_scopes_nonempty
        CHECK (cardinality(allowed_use_scopes) > 0),
    ADD CONSTRAINT provider_field_mappings_use_scopes_known
        CHECK (
            allowed_use_scopes <@ ARRAY[
                'current_research',
                'strict_historical',
                'production'
            ]::TEXT[]
            AND array_position(allowed_use_scopes, NULL) IS NULL
        ),
    ADD CONSTRAINT provider_field_mappings_fuzzy_not_production
        CHECK (
            method <> 'fuzzy'
            OR NOT ('production' = ANY(allowed_use_scopes))
        ),
    ADD CONSTRAINT provider_field_mappings_akshare_current_only
        CHECK (
            provider_id NOT IN ('akshare', 'provider:akshare')
            OR allowed_use_scopes = ARRAY['current_research']::TEXT[]
        );
