-- A sparse provider snapshot must never be interpreted as evidence that index
-- membership remained unchanged until the next request. Persist observation
-- dates and their complement so consumers can distinguish "not a member" from
-- "not observed".

ALTER TABLE universe_versions
    ADD COLUMN observation_mode TEXT NOT NULL DEFAULT 'continuous_daily'
        CHECK (observation_mode IN ('continuous_daily', 'discrete_month_end')),
    ADD COLUMN observed_dates JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(observed_dates) = 'array'),
    ADD COLUMN unobserved_intervals JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(unobserved_intervals) = 'array'),
    ADD CONSTRAINT universe_versions_discrete_observation_evidence
        CHECK (
            observation_mode <> 'discrete_month_end'
            OR jsonb_array_length(observed_dates) > 0
        );

DROP VIEW strict_pit_universe_versions;

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
    available_at,
    observation_mode,
    observed_dates,
    unobserved_intervals
FROM universe_versions
WHERE trust_state = 'pit_verified'
  AND available_at IS NOT NULL;

-- Defaults above exist only to backfill rows created before this migration.
-- Every new version must name its observation evidence explicitly.
ALTER TABLE universe_versions
    ALTER COLUMN observation_mode DROP DEFAULT,
    ALTER COLUMN observed_dates DROP DEFAULT,
    ALTER COLUMN unobserved_intervals DROP DEFAULT;
