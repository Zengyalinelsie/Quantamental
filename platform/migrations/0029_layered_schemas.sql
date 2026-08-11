-- Physical responsibility layers. Moving an object does not change its data trust state.
CREATE SCHEMA governance;
CREATE SCHEMA evidence;
CREATE SCHEMA observation;
CREATE SCHEMA canonical;
CREATE SCHEMA research;
CREATE SCHEMA serving;

ALTER TABLE public.artifacts SET SCHEMA governance;
ALTER TABLE public.canonical_metrics SET SCHEMA governance;
ALTER TABLE public.dataset_coverage_reports SET SCHEMA governance;
ALTER TABLE public.dataset_quality_reports SET SCHEMA governance;
ALTER TABLE public.dataset_versions SET SCHEMA governance;
ALTER TABLE public.factor_promotion_reviews SET SCHEMA governance;
ALTER TABLE public.financial_authority_rules SET SCHEMA governance;
ALTER TABLE public.financial_backfill_persist_receipts SET SCHEMA governance;
ALTER TABLE public.financial_backfill_work_units SET SCHEMA governance;
ALTER TABLE public.financial_quality_rules SET SCHEMA governance;
ALTER TABLE public.ingestion_checkpoints SET SCHEMA governance;
ALTER TABLE public.ingestion_job_events SET SCHEMA governance;
ALTER TABLE public.ingestion_jobs SET SCHEMA governance;
ALTER TABLE public.lineage_edges SET SCHEMA governance;
ALTER TABLE public.metric_mapping_versions SET SCHEMA governance;
ALTER TABLE public.provider_field_mappings SET SCHEMA governance;
ALTER TABLE public.run_records SET SCHEMA governance;
ALTER TABLE public.unmapped_metric_fields SET SCHEMA governance;

ALTER TABLE public.official_disclosures SET SCHEMA evidence;
ALTER TABLE public.raw_objects SET SCHEMA evidence;

ALTER TABLE public.corporate_action_observations SET SCHEMA observation;
ALTER TABLE public.daily_market_states SET SCHEMA observation;
ALTER TABLE public.market_data_partitions SET SCHEMA observation;
ALTER TABLE public.normalized_current_financial_observations SET SCHEMA observation;
ALTER TABLE public.share_capital_observations SET SCHEMA observation;
ALTER TABLE public.timing_benchmark_bars SET SCHEMA observation;

ALTER TABLE public.companies SET SCHEMA canonical;
ALTER TABLE public.corporate_actions SET SCHEMA canonical;
ALTER TABLE public.exchange_calendar_days SET SCHEMA canonical;
ALTER TABLE public.financial_fact_observations SET SCHEMA canonical;
ALTER TABLE public.identifier_history SET SCHEMA canonical;
ALTER TABLE public.industry_memberships SET SCHEMA canonical;
ALTER TABLE public.listing_state_periods SET SCHEMA canonical;
ALTER TABLE public.listings SET SCHEMA canonical;
ALTER TABLE public.official_identifier_aliases SET SCHEMA canonical;
ALTER TABLE public.price_limits SET SCHEMA canonical;
ALTER TABLE public.provider_identifier_corrections SET SCHEMA canonical;
ALTER TABLE public.securities SET SCHEMA canonical;
ALTER TABLE public.share_capital_periods SET SCHEMA canonical;
ALTER TABLE public.universe_definitions SET SCHEMA canonical;
ALTER TABLE public.universe_memberships SET SCHEMA canonical;
ALTER TABLE public.universe_versions SET SCHEMA canonical;

ALTER TABLE public.experiment_runs SET SCHEMA research;
ALTER TABLE public.experiment_specs SET SCHEMA research;
ALTER TABLE public.factor_qualification_audits SET SCHEMA research;
ALTER TABLE public.factor_validation_reports SET SCHEMA research;
ALTER TABLE public.feature_snapshots SET SCHEMA research;
ALTER TABLE public.research_labels SET SCHEMA research;
ALTER TABLE public.timing_forecasts SET SCHEMA research;

ALTER FUNCTION public.reject_factor_promotion_review_mutation() SET SCHEMA governance;
ALTER FUNCTION public.prevent_identifier_alias_mutation() SET SCHEMA canonical;
ALTER FUNCTION public.reject_market_structure_observation_mutation() SET SCHEMA observation;
ALTER FUNCTION public.reject_normalized_current_financial_mutation() SET SCHEMA observation;
ALTER FUNCTION public.reject_timing_benchmark_bar_mutation() SET SCHEMA observation;
ALTER FUNCTION public.enforce_failed_factor_qualification_run() SET SCHEMA research;
ALTER FUNCTION public.prevent_factor_qualification_mutation() SET SCHEMA research;
ALTER FUNCTION public.reject_experiment_run_mutation() SET SCHEMA research;
ALTER FUNCTION public.reject_experiment_spec_mutation() SET SCHEMA research;
ALTER FUNCTION public.reject_feature_snapshot_mutation() SET SCHEMA research;
ALTER FUNCTION public.reject_research_label_mutation() SET SCHEMA research;
ALTER FUNCTION public.reject_timing_forecast_mutation() SET SCHEMA research;

-- PL/pgSQL relation names are resolved when the function executes, so the
-- migrated function body must not depend on the caller's search_path.
CREATE OR REPLACE FUNCTION research.enforce_failed_factor_qualification_run()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM research.experiment_runs
        WHERE run_id = NEW.experiment_run_id
          AND status = 'failed'
          AND jsonb_array_length(metrics) = 0
    ) THEN
        RAISE EXCEPTION 'factor qualification requires a failed metric-free ExperimentRun';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER VIEW public.strict_pit_universe_versions SET SCHEMA serving;
