ALTER TABLE normalized_current_financial_observations
    ADD COLUMN identity_resolution_method TEXT NOT NULL
        DEFAULT 'effective_dated_report_period';

DO $$
DECLARE
    legacy_identity_constraint TEXT;
BEGIN
    SELECT conname
    INTO legacy_identity_constraint
    FROM pg_constraint
    WHERE conrelid = 'normalized_current_financial_observations'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ~ 'identity_as_of = report_period_end';

    IF legacy_identity_constraint IS NULL THEN
        RAISE EXCEPTION
            'legacy normalized-current financial identity constraint was not found';
    END IF;

    EXECUTE format(
        'ALTER TABLE normalized_current_financial_observations DROP CONSTRAINT %I',
        legacy_identity_constraint
    );
END;
$$;

ALTER TABLE normalized_current_financial_observations
    ADD CONSTRAINT normalized_current_financial_identity_method_check CHECK (
        (
            identity_resolution_method = 'effective_dated_report_period'
            AND identity_as_of = report_period_end
        )
        OR (
            identity_resolution_method = 'current_known_retrieval_date'
            AND identity_as_of = (retrieved_at AT TIME ZONE 'UTC')::date
        )
    );

ALTER TABLE normalized_current_financial_observations
    ALTER COLUMN identity_resolution_method DROP DEFAULT;

ALTER TABLE financial_backfill_persist_receipts
    ADD COLUMN identity_resolution_method TEXT NOT NULL
        DEFAULT 'effective_dated_report_period',
    ADD CONSTRAINT financial_backfill_receipts_identity_method_check CHECK (
        identity_resolution_method IN (
            'effective_dated_report_period',
            'current_known_retrieval_date'
        )
    );

ALTER TABLE financial_backfill_persist_receipts
    ALTER COLUMN identity_resolution_method DROP DEFAULT;
