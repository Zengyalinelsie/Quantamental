CREATE TABLE timing_benchmark_bars (
    benchmark_id TEXT NOT NULL CHECK (
        benchmark_id IN ('index:000300', 'index:000905')
    ),
    session_date DATE NOT NULL,
    unadjusted_close NUMERIC NOT NULL CHECK (unadjusted_close > 0),
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    retrieved_at TIMESTAMPTZ NOT NULL,
    adjustment_mode TEXT NOT NULL CHECK (adjustment_mode = 'unadjusted'),
    trust_state TEXT NOT NULL CHECK (trust_state = 'normalized_current'),
    data_mode TEXT NOT NULL CHECK (data_mode = 'current_research'),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    PRIMARY KEY (dataset_version_id, benchmark_id, session_date)
);

CREATE INDEX timing_benchmark_bars_lookup
ON timing_benchmark_bars (benchmark_id, session_date DESC);

CREATE FUNCTION reject_timing_benchmark_bar_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'timing benchmark bars are append-only';
END;
$$;

CREATE TRIGGER timing_benchmark_bars_append_only
BEFORE UPDATE OR DELETE ON timing_benchmark_bars
FOR EACH ROW EXECUTE FUNCTION reject_timing_benchmark_bar_mutation();
