-- Canonical universe snapshots must carry enough lineage to distinguish a
-- retrieval-time current observation from a point-in-time verified version.
-- The new NOT NULL columns intentionally make this migration fail closed when
-- an installation already contains unqualified universe versions: those rows
-- require an explicit audited migration, not manufactured provenance.

ALTER TABLE listing_state_periods
    ALTER COLUMN special_treatment DROP NOT NULL;

ALTER TABLE dataset_versions
    ADD CONSTRAINT dataset_versions_metadata_object
    CHECK (jsonb_typeof(metadata) = 'object');

ALTER TABLE universe_versions
    ADD COLUMN trust_state TEXT NOT NULL
        CHECK (trust_state IN ('raw', 'normalized_current', 'pit_verified')),
    ADD COLUMN provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    ADD COLUMN source_ids JSONB NOT NULL
        CHECK (
            jsonb_typeof(source_ids) = 'array'
            AND jsonb_array_length(source_ids) > 0
        ),
    ADD COLUMN retrieved_at TIMESTAMPTZ NOT NULL,
    ADD COLUMN system_as_of TIMESTAMPTZ NOT NULL,
    ADD COLUMN available_at TIMESTAMPTZ,
    ADD CONSTRAINT universe_versions_system_time_order
        CHECK (system_as_of >= retrieved_at),
    ADD CONSTRAINT universe_versions_pit_qualification
        CHECK (
            (
                trust_state = 'pit_verified'
                AND available_at IS NOT NULL
                AND available_at <= retrieved_at
            )
            OR (
                trust_state = 'normalized_current'
                AND available_at IS NULL
            )
            OR (
                trust_state = 'raw'
                AND available_at IS NULL
            )
        );

ALTER TABLE universe_memberships
    ADD COLUMN source_id TEXT NOT NULL CHECK (source_id <> '');

-- Strict historical consumers query this view. A normalized_current row has
-- no valid route into the view, even when it describes a historical date.
CREATE VIEW strict_pit_universe_versions AS
SELECT
    universe_version_id,
    definition_id,
    dataset_version_id,
    created_at,
    trust_state,
    provider_id,
    source_ids,
    retrieved_at,
    system_as_of,
    available_at
FROM universe_versions
WHERE trust_state = 'pit_verified'
  AND available_at IS NOT NULL;
