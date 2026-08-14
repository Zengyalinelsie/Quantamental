-- Freeze the provider-neutral outcome policy beside every realized return.
-- Existing rows cannot be guessed or backfilled with an invented policy.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM research.investment_view_outcomes LIMIT 1) THEN
        RAISE EXCEPTION
            '0035 requires an empty outcome ledger; source policy cannot be inferred';
    END IF;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE research.investment_view_outcomes
    ADD COLUMN source_policy_version TEXT NOT NULL
        CHECK (btrim(source_policy_version) <> '');

ALTER TABLE research.investment_view_outcomes
    ADD COLUMN source_available_at TIMESTAMPTZ NOT NULL
        CHECK (source_available_at >= realized_at AND recorded_at >= source_available_at);

ALTER TABLE research.investment_view_outcomes
    ADD CONSTRAINT investment_view_outcome_source_policy_document_match
        CHECK (
            outcome_document ? 'source_policy_version'
            AND outcome_document ->> 'source_policy_version' = source_policy_version
            AND outcome_document ? 'source_available_at'
            AND (outcome_document ->> 'source_available_at')::timestamptz
                = source_available_at
        );
