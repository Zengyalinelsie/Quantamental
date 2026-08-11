ALTER TABLE financial_backfill_persist_receipts
    DROP CONSTRAINT financial_backfill_persist_receipts_observation_count_check,
    DROP CONSTRAINT financial_backfill_persist_receipts_observation_ids_check,
    DROP CONSTRAINT financial_backfill_receipts_identity_method_check;

ALTER TABLE financial_backfill_persist_receipts
    ADD CONSTRAINT financial_backfill_receipts_observation_count_check CHECK (
        observation_count >= 0
    ),
    ADD CONSTRAINT financial_backfill_receipts_observation_ids_check CHECK (
        jsonb_typeof(observation_ids) = 'array'
    ),
    ADD CONSTRAINT financial_backfill_receipts_count_matches_ids_check CHECK (
        observation_count = jsonb_array_length(observation_ids)
    ),
    ADD CONSTRAINT financial_backfill_receipts_identity_method_check CHECK (
        identity_resolution_method IN (
            'effective_dated_report_period',
            'current_known_retrieval_date',
            'no_observations'
        )
    ),
    ADD CONSTRAINT financial_backfill_receipts_empty_identity_check CHECK (
        (
            observation_count = 0
            AND identity_resolution_method = 'no_observations'
        )
        OR (
            observation_count > 0
            AND identity_resolution_method <> 'no_observations'
        )
    );

COMMENT ON CONSTRAINT financial_backfill_receipts_empty_identity_check
    ON financial_backfill_persist_receipts IS
    'no_observations records an explicit provider absence; missing values are never zero-filled';
