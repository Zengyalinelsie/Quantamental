-- Schema-explicit P5 valuation bundles. Legacy v1 JSON and content hashes are
-- never rewritten; only the relational discriminator is populated for them.

ALTER TABLE research.valuation_input_bundles
    ADD COLUMN document_schema_version TEXT NOT NULL
        DEFAULT 'valuation-input-bundle:v1';

ALTER TABLE research.valuation_input_bundles
    ALTER COLUMN document_schema_version DROP DEFAULT,
    ADD CONSTRAINT valuation_input_bundle_known_schema CHECK (
        document_schema_version IN (
            'valuation-input-bundle:v1',
            'valuation-input-bundle:v2'
        )
    ),
    ADD CONSTRAINT valuation_input_bundle_required_keys CHECK (
        bundle_document ?& ARRAY[
            'bundle_version_id',
            'security_id',
            'decision_time',
            'latest_source_available_at',
            'data_mode',
            'trust_state',
            'dataset_version_ids',
            'industry_template_id',
            'valuation_formula_version',
            'improvement_formula_version',
            'scenario_method_id',
            'scenario_method_version',
            'valuation_metric_inputs',
            'valuation_exposures',
            'currency',
            'comparable_set_version_id',
            'improvement_inputs',
            'improvement_exposures',
            'scenario_inputs'
        ]
    ),
    ADD CONSTRAINT valuation_input_bundle_schema_document_match CHECK (
        (
            document_schema_version = 'valuation-input-bundle:v1'
            AND NOT (bundle_document ? 'document_schema_version')
            AND NOT (bundle_document ? 'valuation_model_suite_inputs')
            AND bundle_document ? 'market_implied'
            AND bundle_document ? 'fundamental_anchor'
        )
        OR (
            document_schema_version = 'valuation-input-bundle:v2'
            AND bundle_document ? 'document_schema_version'
            AND bundle_document ->> 'document_schema_version'
                = 'valuation-input-bundle:v2'
            AND bundle_document ? 'valuation_model_suite_inputs'
            AND NOT (bundle_document ? 'market_implied')
            AND NOT (bundle_document ? 'fundamental_anchor')
        )
    );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM research.valuation_input_bundles AS bundles
        CROSS JOIN LATERAL jsonb_array_elements_text(
            bundles.dataset_version_ids
        ) AS dataset(dataset_version_id)
        LEFT JOIN governance.dataset_versions AS versions
          ON versions.dataset_version_id = dataset.dataset_version_id
        WHERE versions.dataset_version_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'valuation bundle dataset lineage references an unknown DatasetVersion';
    END IF;
END;
$$;

CREATE TABLE research.valuation_input_bundle_datasets (
    bundle_version_id TEXT NOT NULL
        REFERENCES research.valuation_input_bundles(bundle_version_id),
    dataset_version_id TEXT NOT NULL
        REFERENCES governance.dataset_versions(dataset_version_id),
    PRIMARY KEY (bundle_version_id, dataset_version_id),
    CHECK (btrim(bundle_version_id) <> ''),
    CHECK (btrim(dataset_version_id) <> '')
);

INSERT INTO research.valuation_input_bundle_datasets (
    bundle_version_id,
    dataset_version_id
)
SELECT bundles.bundle_version_id, dataset.dataset_version_id
FROM research.valuation_input_bundles AS bundles
CROSS JOIN LATERAL jsonb_array_elements_text(
    bundles.dataset_version_ids
) AS dataset(dataset_version_id);

CREATE TRIGGER valuation_input_bundle_datasets_append_only
BEFORE UPDATE OR DELETE ON research.valuation_input_bundle_datasets
FOR EACH ROW EXECUTE FUNCTION research.reject_p5_decision_mutation();
