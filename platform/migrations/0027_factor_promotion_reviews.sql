CREATE TABLE factor_promotion_reviews (
    review_id TEXT PRIMARY KEY CHECK (review_id <> ''),
    content_hash TEXT NOT NULL UNIQUE CHECK (
        content_hash ~ '^[0-9a-f]{64}$'
    ),
    factor_version_id TEXT NOT NULL CHECK (factor_version_id <> ''),
    factor_lifecycle_status TEXT NOT NULL CHECK (
        factor_lifecycle_status = 'candidate'
    ),
    factor_version_hash TEXT NOT NULL CHECK (
        factor_version_hash ~ '^[0-9a-f]{64}$'
    ),
    validation_report_id TEXT NOT NULL CHECK (validation_report_id <> ''),
    scientific_gate_passed BOOLEAN NOT NULL,
    scope TEXT NOT NULL CHECK (
        scope IN ('research_backtest', 'shadow', 'paper', 'limited_live')
    ),
    decision TEXT NOT NULL CHECK (
        decision IN ('approved', 'rejected', 'request_changes')
    ),
    reviewer_id TEXT NOT NULL CHECK (reviewer_id <> ''),
    reviewer_role TEXT NOT NULL CHECK (
        reviewer_role IN ('reviewer', 'administrator')
    ),
    validation_report_hash TEXT NOT NULL CHECK (
        validation_report_hash ~ '^[0-9a-f]{64}$'
    ),
    decided_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL CHECK (reason <> ''),
    evidence_hashes JSONB NOT NULL CHECK (
        jsonb_typeof(evidence_hashes) = 'array'
        AND jsonb_array_length(evidence_hashes) > 0
    ),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (decision <> 'approved' OR scientific_gate_passed)
);

CREATE INDEX factor_promotion_reviews_target
ON factor_promotion_reviews (
    factor_version_id, validation_report_id, scope, decided_at, review_id
);

CREATE FUNCTION reject_factor_promotion_review_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'factor promotion reviews are append-only';
END;
$$;

CREATE TRIGGER factor_promotion_reviews_append_only
BEFORE UPDATE OR DELETE ON factor_promotion_reviews
FOR EACH ROW EXECUTE FUNCTION reject_factor_promotion_review_mutation();
