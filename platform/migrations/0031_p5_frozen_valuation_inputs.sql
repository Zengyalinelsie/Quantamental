-- Immutable P5 inputs. Persisting a bundle freezes evidence; it does not
-- promote normalized_current inputs to PIT or assert scientific validity.

-- Existing classification rows deliberately remain unqualified (NULL lineage).
-- A later Security Master observation supplies all lineage columns together;
-- migration-time values are never manufactured for historical rows.
ALTER TABLE canonical.industry_memberships
    ADD COLUMN dataset_version_id TEXT REFERENCES governance.dataset_versions(dataset_version_id),
    ADD COLUMN trust_state TEXT CHECK (
        trust_state IS NULL OR trust_state IN ('normalized_current', 'pit_verified')
    ),
    ADD COLUMN observed_at TIMESTAMPTZ,
    ADD COLUMN available_at TIMESTAMPTZ,
    ADD CONSTRAINT industry_membership_qualification_complete CHECK (
        (
            dataset_version_id IS NULL
            AND trust_state IS NULL
            AND observed_at IS NULL
            AND available_at IS NULL
        )
        OR (
            dataset_version_id IS NOT NULL
            AND trust_state IS NOT NULL
            AND observed_at IS NOT NULL
            AND (
                (trust_state = 'normalized_current' AND available_at IS NULL)
                OR (
                    trust_state = 'pit_verified'
                    AND available_at IS NOT NULL
                    AND available_at <= observed_at
                )
            )
        )
    );

CREATE TABLE research.valuation_input_bundles (
    bundle_version_id TEXT PRIMARY KEY CHECK (bundle_version_id <> ''),
    security_id TEXT NOT NULL CHECK (security_id <> ''),
    decision_time TIMESTAMPTZ NOT NULL,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    data_mode TEXT NOT NULL CHECK (
        data_mode IN ('current_research', 'strict_historical')
    ),
    trust_state TEXT NOT NULL CHECK (
        trust_state IN ('normalized_current', 'pit_verified')
    ),
    latest_source_available_at TIMESTAMPTZ NOT NULL CHECK (
        latest_source_available_at <= decision_time
    ),
    dataset_version_ids JSONB NOT NULL CHECK (
        jsonb_typeof(dataset_version_ids) = 'array'
        AND jsonb_array_length(dataset_version_ids) > 0
    ),
    bundle_document JSONB NOT NULL CHECK (
        jsonb_typeof(bundle_document) = 'object'
    ),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (
        security_id,
        decision_time,
        data_mode,
        trust_state,
        bundle_version_id
    ),
    CHECK (data_mode <> 'strict_historical' OR trust_state = 'pit_verified'),
    CHECK (bundle_document ->> 'bundle_version_id' = bundle_version_id),
    CHECK (bundle_document ->> 'security_id' = security_id),
    CHECK (bundle_document ->> 'data_mode' = data_mode),
    CHECK (bundle_document ->> 'trust_state' = trust_state)
);

CREATE INDEX valuation_input_bundle_lookup
    ON research.valuation_input_bundles (
        security_id,
        decision_time,
        data_mode,
        trust_state
    );

CREATE TRIGGER valuation_input_bundles_append_only
BEFORE UPDATE OR DELETE ON research.valuation_input_bundles
FOR EACH ROW EXECUTE FUNCTION research.reject_p5_decision_mutation();
