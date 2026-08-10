CREATE TABLE timing_forecasts (
    forecast_id TEXT PRIMARY KEY CHECK (forecast_id <> ''),
    benchmark_id TEXT NOT NULL CHECK (benchmark_id <> ''),
    universe_version_id TEXT NOT NULL CHECK (universe_version_id <> ''),
    effective_session DATE NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    data_cutoff_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    data_mode TEXT NOT NULL CHECK (data_mode = 'current_research'),
    deployment_stage TEXT NOT NULL CHECK (deployment_stage = 'shadow'),
    horizon_forecasts JSONB NOT NULL CHECK (
        jsonb_typeof(horizon_forecasts) = 'array'
        AND jsonb_array_length(horizon_forecasts) = 4
    ),
    risk_forecast JSONB NOT NULL CHECK (jsonb_typeof(risk_forecast) = 'object'),
    static_exposure_ratio NUMERIC NOT NULL CHECK (
        static_exposure_ratio BETWEEN 0 AND 1
    ),
    passive_exposure_ratio NUMERIC NOT NULL CHECK (
        passive_exposure_ratio BETWEEN 0 AND 1
    ),
    passive_target_volatility_ratio NUMERIC NOT NULL CHECK (
        passive_target_volatility_ratio > 0
    ),
    passive_observed_volatility_ratio NUMERIC NOT NULL CHECK (
        passive_observed_volatility_ratio > 0
    ),
    passive_lookback_sessions INTEGER NOT NULL CHECK (passive_lookback_sessions > 1),
    active_adjustment JSONB NOT NULL CHECK (jsonb_typeof(active_adjustment) = 'object'),
    final_exposure_lower_ratio NUMERIC NOT NULL CHECK (
        final_exposure_lower_ratio BETWEEN 0 AND 1
    ),
    final_exposure_upper_ratio NUMERIC NOT NULL CHECK (
        final_exposure_upper_ratio BETWEEN 0 AND 1
        AND final_exposure_upper_ratio >= final_exposure_lower_ratio
    ),
    model_version_id TEXT NOT NULL CHECK (model_version_id <> ''),
    model_lifecycle TEXT NOT NULL CHECK (
        model_lifecycle IN ('baseline', 'candidate', 'validated', 'approved', 'retired')
    ),
    run_id TEXT NOT NULL REFERENCES run_records(run_id),
    approval_scope TEXT NOT NULL CHECK (approval_scope <> ''),
    dataset_version_ids JSONB NOT NULL CHECK (
        jsonb_typeof(dataset_version_ids) = 'array'
        AND jsonb_array_length(dataset_version_ids) > 0
    ),
    input_trust_state TEXT NOT NULL CHECK (
        input_trust_state IN ('normalized_current', 'pit_verified')
    ),
    CHECK (data_cutoff_at <= decision_time),
    CHECK (created_at >= decision_time),
    UNIQUE (benchmark_id, universe_version_id, effective_session)
);

CREATE FUNCTION reject_timing_forecast_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'timing forecasts are append-only';
END;
$$;

CREATE TRIGGER timing_forecasts_append_only
BEFORE UPDATE OR DELETE ON timing_forecasts
FOR EACH ROW EXECUTE FUNCTION reject_timing_forecast_mutation();
