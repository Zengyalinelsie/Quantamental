CREATE TABLE market_data_partitions (
    partition_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    data_type TEXT NOT NULL CHECK (data_type IN ('daily_bar', 'adjustment_factor')),
    storage_uri TEXT NOT NULL UNIQUE CHECK (storage_uri <> ''),
    content_hash TEXT NOT NULL CHECK (content_hash <> ''),
    exchange TEXT CHECK (exchange IN ('XSHG', 'XSHE', 'XBSE')),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    row_count BIGINT NOT NULL CHECK (row_count >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    CHECK (end_date >= start_date),
    CHECK (data_type <> 'daily_bar' OR exchange IS NOT NULL)
);

CREATE INDEX market_data_partition_lookup
    ON market_data_partitions(data_type, dataset_version_id, exchange, start_date, end_date);

CREATE TABLE daily_market_states (
    daily_market_state_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    session_date DATE NOT NULL,
    is_trading BOOLEAN NOT NULL,
    is_suspended BOOLEAN NOT NULL,
    listing_state TEXT CHECK (listing_state IN ('active', 'suspended_listing', 'terminated')),
    special_treatment TEXT CHECK (special_treatment IN ('none', 'st', 'star_st')),
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    trust_state TEXT NOT NULL CHECK (trust_state IN ('raw', 'normalized_current', 'pit_verified')),
    CHECK (NOT (is_trading AND is_suspended)),
    CHECK (listing_state <> 'terminated' OR NOT is_trading),
    UNIQUE (listing_id, session_date, source_id, dataset_version_id)
);

CREATE TABLE price_limits (
    price_limit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    session_date DATE NOT NULL,
    lower_price NUMERIC NOT NULL CHECK (lower_price > 0),
    upper_price NUMERIC NOT NULL CHECK (upper_price > 0),
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    CHECK (lower_price <= upper_price),
    UNIQUE (listing_id, session_date, source_id)
);

CREATE TABLE share_capital_periods (
    share_capital_period_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    effective_from DATE NOT NULL,
    effective_to DATE,
    total_shares NUMERIC NOT NULL CHECK (total_shares > 0),
    circulating_shares NUMERIC,
    free_float_shares NUMERIC,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(dataset_version_id),
    CHECK (effective_to IS NULL OR effective_to > effective_from),
    CHECK (circulating_shares IS NULL OR circulating_shares BETWEEN 0 AND total_shares),
    CHECK (
        free_float_shares IS NULL OR
        (circulating_shares IS NOT NULL AND free_float_shares BETWEEN 0 AND circulating_shares)
    ),
    UNIQUE (listing_id, effective_from, source_id, dataset_version_id)
);

CREATE TABLE corporate_actions (
    action_id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    action_type TEXT NOT NULL CHECK (
        action_type IN ('cash_dividend', 'bonus_share', 'split', 'reverse_split', 'rights_issue')
    ),
    ex_date DATE NOT NULL,
    record_date DATE NOT NULL,
    cash_per_share NUMERIC,
    share_ratio NUMERIC,
    subscription_price NUMERIC,
    currency CHAR(3) NOT NULL,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    CHECK (record_date <= ex_date),
    CHECK (cash_per_share IS NULL OR cash_per_share > 0),
    CHECK (share_ratio IS NULL OR share_ratio > 0),
    CHECK (subscription_price IS NULL OR subscription_price > 0),
    CHECK (action_type <> 'cash_dividend' OR cash_per_share IS NOT NULL),
    CHECK (action_type NOT IN ('bonus_share', 'split', 'reverse_split') OR share_ratio IS NOT NULL),
    CHECK (
        action_type <> 'rights_issue' OR
        (share_ratio IS NOT NULL AND subscription_price IS NOT NULL)
    )
);

CREATE TABLE exchange_calendar_days (
    exchange TEXT NOT NULL CHECK (exchange IN ('XSHG', 'XSHE', 'XBSE')),
    calendar_date DATE NOT NULL,
    is_open BOOLEAN NOT NULL,
    closure_reason TEXT,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    PRIMARY KEY (exchange, calendar_date, source_id),
    CHECK (is_open OR (closure_reason IS NOT NULL AND closure_reason <> ''))
);
