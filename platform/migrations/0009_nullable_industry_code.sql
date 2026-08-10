-- Some qualified classifications publish a taxonomy and name without a stable code.
-- Preserve that absence as NULL rather than manufacturing a sentinel identifier.
ALTER TABLE industry_memberships
    ALTER COLUMN industry_code DROP NOT NULL;

ALTER TABLE companies
    ADD COLUMN legal_name_source_id TEXT,
    ADD COLUMN observed_on DATE,
    ADD COLUMN dataset_version_id TEXT REFERENCES dataset_versions(dataset_version_id),
    ADD COLUMN trust_state TEXT CHECK (
        trust_state IS NULL OR trust_state IN ('raw', 'normalized_current', 'pit_verified')
    );
