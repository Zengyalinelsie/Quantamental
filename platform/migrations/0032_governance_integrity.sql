-- Enforce the governance contracts below the application adapter boundary.

ALTER TABLE governance.dataset_versions
    ADD CONSTRAINT dataset_versions_content_hash_format
    CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    ADD CONSTRAINT dataset_versions_identifiers_not_blank
    CHECK (btrim(dataset_version_id) <> '' AND btrim(schema_version) <> '');

ALTER TABLE governance.run_records
    ADD CONSTRAINT run_records_status_domain
    CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    ADD CONSTRAINT run_records_data_mode_domain
    CHECK (data_mode IN ('current_research', 'strict_historical')),
    ADD CONSTRAINT run_records_deployment_stage_domain
    CHECK (deployment_stage IN ('research', 'shadow', 'paper', 'limited_live')),
    ADD CONSTRAINT run_records_context_is_legal
    CHECK (NOT (data_mode = 'strict_historical' AND deployment_stage <> 'research')),
    ADD CONSTRAINT run_records_terminal_shape
    CHECK (
        (
            status IN ('pending', 'running')
            AND finished_at IS NULL
            AND failure_reason IS NULL
        ) OR (
            status IN ('succeeded', 'cancelled')
            AND finished_at IS NOT NULL
            AND finished_at >= started_at
            AND failure_reason IS NULL
        ) OR (
            status = 'failed'
            AND finished_at IS NOT NULL
            AND finished_at >= started_at
            AND btrim(failure_reason) <> ''
        )
    );

ALTER TABLE governance.artifacts
    ADD CONSTRAINT artifacts_content_hash_format
    CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    ADD CONSTRAINT artifacts_fields_not_blank
    CHECK (
        btrim(artifact_id) <> ''
        AND btrim(media_type) <> ''
        AND btrim(storage_uri) <> ''
        AND btrim(run_id) <> ''
    );

CREATE OR REPLACE FUNCTION governance.reject_immutable_ledger_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER dataset_versions_are_append_only
BEFORE UPDATE OR DELETE ON governance.dataset_versions
FOR EACH ROW EXECUTE FUNCTION governance.reject_immutable_ledger_mutation();

CREATE TRIGGER artifacts_are_append_only
BEFORE UPDATE OR DELETE ON governance.artifacts
FOR EACH ROW EXECUTE FUNCTION governance.reject_immutable_ledger_mutation();

CREATE TRIGGER lineage_edges_are_append_only
BEFORE UPDATE OR DELETE ON governance.lineage_edges
FOR EACH ROW EXECUTE FUNCTION governance.reject_immutable_ledger_mutation();

CREATE OR REPLACE FUNCTION governance.enforce_run_record_transition()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'run_records cannot be deleted';
    END IF;
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.run_kind IS DISTINCT FROM OLD.run_kind
       OR NEW.data_mode IS DISTINCT FROM OLD.data_mode
       OR NEW.deployment_stage IS DISTINCT FROM OLD.deployment_stage
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.code_version IS DISTINCT FROM OLD.code_version
       OR NEW.environment_fingerprint IS DISTINCT FROM OLD.environment_fingerprint THEN
        RAISE EXCEPTION 'run record immutable fields cannot change';
    END IF;
    IF OLD.status = 'pending' AND NEW.status = 'running' THEN
        RETURN NEW;
    END IF;
    IF OLD.status <> 'running'
       OR NEW.status NOT IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'invalid run status transition: % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER run_records_have_one_way_transitions
BEFORE UPDATE OR DELETE ON governance.run_records
FOR EACH ROW EXECUTE FUNCTION governance.enforce_run_record_transition();
