CREATE TABLE companies (
    company_id TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL CHECK (legal_name <> '')
);

CREATE TABLE securities (
    security_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    security_class TEXT NOT NULL CHECK (security_class IN ('a_share', 'b_share', 'h_share')),
    currency CHAR(3) NOT NULL
);

CREATE TABLE listings (
    listing_id TEXT PRIMARY KEY,
    security_id TEXT NOT NULL REFERENCES securities(security_id),
    exchange TEXT NOT NULL CHECK (exchange IN ('XSHG', 'XSHE', 'XBSE')),
    board TEXT NOT NULL CHECK (board IN ('main', 'star', 'chinext', 'bse')),
    listed_on DATE NOT NULL,
    delisted_on DATE,
    CHECK (delisted_on IS NULL OR delisted_on > listed_on),
    CHECK (
        (board = 'star' AND exchange = 'XSHG') OR
        (board = 'chinext' AND exchange = 'XSHE') OR
        (board = 'bse' AND exchange = 'XBSE') OR
        (board = 'main' AND exchange IN ('XSHG', 'XSHE'))
    )
);

CREATE TABLE identifier_history (
    identifier_history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    kind TEXT NOT NULL CHECK (kind IN ('code', 'name')),
    value TEXT NOT NULL CHECK (value <> ''),
    valid_from DATE NOT NULL,
    valid_to DATE,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (listing_id, kind, valid_from)
);

CREATE INDEX identifier_history_lookup
    ON identifier_history(kind, value, valid_from, valid_to);

CREATE TABLE listing_state_periods (
    listing_state_period_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    state TEXT NOT NULL CHECK (state IN ('active', 'suspended_listing', 'terminated')),
    special_treatment TEXT NOT NULL CHECK (special_treatment IN ('none', 'st', 'star_st')),
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (listing_id, valid_from)
);

CREATE TABLE industry_memberships (
    industry_membership_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    security_id TEXT NOT NULL REFERENCES securities(security_id),
    taxonomy TEXT NOT NULL CHECK (taxonomy <> ''),
    industry_code TEXT NOT NULL CHECK (industry_code <> ''),
    industry_name TEXT NOT NULL CHECK (industry_name <> ''),
    valid_from DATE NOT NULL,
    valid_to DATE,
    source_id TEXT NOT NULL CHECK (source_id <> ''),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (security_id, taxonomy, valid_from)
);
