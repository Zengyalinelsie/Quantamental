CREATE TABLE share_capital_observations (
    observation_id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    provider_record_id TEXT NOT NULL CHECK (provider_record_id <> ''),
    effective_on DATE NOT NULL,
    announced_on DATE,
    total_shares NUMERIC NOT NULL CHECK (total_shares > 0),
    circulating_shares NUMERIC,
    restricted_shares NUMERIC,
    free_float_shares NUMERIC,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    retrieved_at TIMESTAMPTZ NOT NULL,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    trust_state TEXT NOT NULL CHECK (trust_state = 'normalized_current'),
    batch_content_hash TEXT NOT NULL CHECK (batch_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (circulating_shares IS NULL OR circulating_shares BETWEEN 0 AND total_shares),
    CHECK (restricted_shares IS NULL OR restricted_shares BETWEEN 0 AND total_shares),
    CHECK (
        circulating_shares IS NULL OR restricted_shares IS NULL OR
        circulating_shares + restricted_shares <= total_shares
    ),
    CHECK (
        free_float_shares IS NULL OR
        (circulating_shares IS NOT NULL AND free_float_shares BETWEEN 0 AND circulating_shares)
    ),
    UNIQUE (provider_id, provider_record_id, dataset_version_id)
);

CREATE INDEX share_capital_observations_lookup
    ON share_capital_observations(listing_id, effective_on, provider_id);

CREATE TABLE corporate_action_observations (
    observation_id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    provider_id TEXT NOT NULL CHECK (provider_id <> ''),
    provider_record_id TEXT NOT NULL CHECK (provider_record_id <> ''),
    announced_on DATE,
    record_date DATE,
    ex_date DATE,
    cash_per_share NUMERIC,
    bonus_shares_per_share NUMERIC,
    capitalization_shares_per_share NUMERIC,
    rights_shares_per_share NUMERIC,
    rights_subscription_price NUMERIC,
    currency CHAR(3) NOT NULL,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    retrieved_at TIMESTAMPTZ NOT NULL,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    trust_state TEXT NOT NULL CHECK (trust_state = 'normalized_current'),
    batch_content_hash TEXT NOT NULL CHECK (batch_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (record_date IS NULL OR ex_date IS NULL OR record_date <= ex_date),
    CHECK (cash_per_share IS NULL OR cash_per_share > 0),
    CHECK (bonus_shares_per_share IS NULL OR bonus_shares_per_share > 0),
    CHECK (
        capitalization_shares_per_share IS NULL OR
        capitalization_shares_per_share > 0
    ),
    CHECK (rights_shares_per_share IS NULL OR rights_shares_per_share > 0),
    CHECK (rights_subscription_price IS NULL OR rights_subscription_price > 0),
    CHECK (
        cash_per_share IS NOT NULL OR
        bonus_shares_per_share IS NOT NULL OR
        capitalization_shares_per_share IS NOT NULL OR
        rights_shares_per_share IS NOT NULL
    ),
    CHECK (
        (rights_shares_per_share IS NULL) = (rights_subscription_price IS NULL)
    ),
    UNIQUE (provider_id, provider_record_id, dataset_version_id)
);

CREATE INDEX corporate_action_observations_lookup
    ON corporate_action_observations(listing_id, ex_date, announced_on, provider_id);

CREATE FUNCTION reject_market_structure_observation_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'market-structure observations are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER share_capital_observations_append_only
BEFORE UPDATE OR DELETE ON share_capital_observations
FOR EACH ROW EXECUTE FUNCTION reject_market_structure_observation_mutation();

CREATE TRIGGER corporate_action_observations_append_only
BEFORE UPDATE OR DELETE ON corporate_action_observations
FOR EACH ROW EXECUTE FUNCTION reject_market_structure_observation_mutation();
