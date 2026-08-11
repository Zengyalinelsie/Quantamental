-- P5 frozen research decisions and purpose-isolated signal read models.
-- These tables preserve engineering evidence; their presence does not assert
-- scientific validity or promote normalized_current data to PIT.

CREATE TABLE research.investment_views (
    view_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    security_id TEXT NOT NULL CHECK (security_id <> ''),
    decision_time TIMESTAMPTZ NOT NULL,
    horizon_trading_days INTEGER NOT NULL CHECK (
        horizon_trading_days IN (20, 60, 120)
    ),
    data_mode TEXT NOT NULL CHECK (
        data_mode IN ('current_research', 'strict_historical')
    ),
    deployment_stage TEXT NOT NULL CHECK (
        deployment_stage IN ('research', 'shadow', 'paper', 'limited_live')
    ),
    trust_state TEXT NOT NULL CHECK (
        trust_state IN ('normalized_current', 'pit_verified')
    ),
    data_cutoff TIMESTAMPTZ NOT NULL CHECK (data_cutoff <= decision_time),
    model_version_id TEXT NOT NULL CHECK (model_version_id <> ''),
    run_id TEXT NOT NULL CHECK (run_id <> ''),
    view_document JSONB NOT NULL CHECK (jsonb_typeof(view_document) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (data_mode <> 'strict_historical' OR trust_state = 'pit_verified'),
    CHECK (data_mode <> 'strict_historical' OR deployment_stage = 'research')
);

CREATE TABLE research.investment_view_outcomes (
    outcome_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    view_id TEXT NOT NULL REFERENCES research.investment_views(view_id),
    security_id TEXT NOT NULL CHECK (security_id <> ''),
    decision_time TIMESTAMPTZ NOT NULL,
    horizon_trading_days INTEGER NOT NULL CHECK (
        horizon_trading_days IN (20, 60, 120)
    ),
    realized_at TIMESTAMPTZ NOT NULL CHECK (realized_at > decision_time),
    dataset_version_id TEXT NOT NULL CHECK (dataset_version_id <> ''),
    outcome_document JSONB NOT NULL CHECK (jsonb_typeof(outcome_document) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL CHECK (recorded_at >= realized_at),
    UNIQUE (view_id)
);

CREATE TABLE research.expected_return_calibrations (
    calibration_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    view_id TEXT NOT NULL REFERENCES research.investment_views(view_id),
    outcome_id TEXT NOT NULL REFERENCES research.investment_view_outcomes(outcome_id),
    calibration_document JSONB NOT NULL CHECK (
        jsonb_typeof(calibration_document) = 'object'
    ),
    recorded_at TIMESTAMPTZ NOT NULL,
    UNIQUE (outcome_id)
);

CREATE TABLE research.signal_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    security_id TEXT NOT NULL CHECK (security_id <> ''),
    decision_time TIMESTAMPTZ NOT NULL,
    horizon_trading_days INTEGER NOT NULL CHECK (
        horizon_trading_days IN (20, 60, 120)
    ),
    universe_version_id TEXT NOT NULL CHECK (universe_version_id <> ''),
    rank INTEGER NOT NULL CHECK (rank > 0),
    universe_size INTEGER NOT NULL CHECK (universe_size > 0 AND rank <= universe_size),
    investment_view_id TEXT NOT NULL REFERENCES research.investment_views(view_id),
    investment_view_hash TEXT NOT NULL CHECK (
        investment_view_hash ~ '^[0-9a-f]{64}$'
    ),
    approval_scope TEXT NOT NULL CHECK (
        approval_scope IN ('research_backtest', 'shadow', 'paper', 'limited_live')
    ),
    data_mode TEXT NOT NULL CHECK (
        data_mode IN ('current_research', 'strict_historical')
    ),
    deployment_stage TEXT NOT NULL CHECK (
        deployment_stage IN ('research', 'shadow', 'paper', 'limited_live')
    ),
    trust_state TEXT NOT NULL CHECK (
        trust_state IN ('normalized_current', 'pit_verified')
    ),
    data_cutoff TIMESTAMPTZ NOT NULL CHECK (data_cutoff <= decision_time),
    factor_version_ids JSONB NOT NULL CHECK (
        jsonb_typeof(factor_version_ids) = 'array'
        AND jsonb_array_length(factor_version_ids) > 0
    ),
    factor_review_ids JSONB NOT NULL CHECK (
        jsonb_typeof(factor_review_ids) = 'array'
        AND jsonb_array_length(factor_review_ids) > 0
    ),
    snapshot_document JSONB NOT NULL CHECK (jsonb_typeof(snapshot_document) = 'object'),
    created_at TIMESTAMPTZ NOT NULL CHECK (created_at >= decision_time),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (
        universe_version_id,
        security_id,
        decision_time,
        horizon_trading_days,
        approval_scope
    ),
    CHECK (data_mode <> 'strict_historical' OR trust_state = 'pit_verified'),
    CHECK (data_mode <> 'strict_historical' OR deployment_stage = 'research'),
    CHECK (
        (deployment_stage = 'research' AND approval_scope = 'research_backtest')
        OR (deployment_stage = 'shadow' AND approval_scope = 'shadow')
        OR (deployment_stage = 'paper' AND approval_scope = 'paper')
        OR (deployment_stage = 'limited_live' AND approval_scope = 'limited_live')
    )
);

CREATE OR REPLACE FUNCTION research.reject_p5_decision_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'P5 decision ledgers are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER investment_views_append_only
BEFORE UPDATE OR DELETE ON research.investment_views
FOR EACH ROW EXECUTE FUNCTION research.reject_p5_decision_mutation();

CREATE TRIGGER investment_view_outcomes_append_only
BEFORE UPDATE OR DELETE ON research.investment_view_outcomes
FOR EACH ROW EXECUTE FUNCTION research.reject_p5_decision_mutation();

CREATE TRIGGER expected_return_calibrations_append_only
BEFORE UPDATE OR DELETE ON research.expected_return_calibrations
FOR EACH ROW EXECUTE FUNCTION research.reject_p5_decision_mutation();

CREATE TRIGGER signal_snapshots_append_only
BEFORE UPDATE OR DELETE ON research.signal_snapshots
FOR EACH ROW EXECUTE FUNCTION research.reject_p5_decision_mutation();

CREATE VIEW serving.research_signal_snapshots AS
SELECT *
FROM research.signal_snapshots
WHERE approval_scope = 'research_backtest'
  AND deployment_stage = 'research';

CREATE VIEW serving.production_signal_snapshots AS
SELECT *
FROM research.signal_snapshots
WHERE approval_scope IN ('shadow', 'paper', 'limited_live')
  AND deployment_stage IN ('shadow', 'paper', 'limited_live');
