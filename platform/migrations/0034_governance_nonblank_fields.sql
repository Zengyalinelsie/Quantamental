-- Match domain text invariants so malformed rows fail at the database boundary.
ALTER TABLE governance.run_records
    ADD CONSTRAINT run_records_fields_not_blank
    CHECK (
        btrim(run_id) <> ''
        AND btrim(run_kind) <> ''
        AND btrim(code_version) <> ''
        AND btrim(environment_fingerprint) <> ''
    );

ALTER TABLE governance.lineage_edges
    ADD CONSTRAINT lineage_edges_fields_not_blank
    CHECK (
        btrim(upstream_id) <> ''
        AND btrim(downstream_id) <> ''
        AND btrim(relation) <> ''
    );
