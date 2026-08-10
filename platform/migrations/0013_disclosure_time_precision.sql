ALTER TABLE official_disclosures
    ADD COLUMN publication_time_precision TEXT NOT NULL DEFAULT 'exact'
    CHECK (publication_time_precision IN ('exact', 'date_only'));

COMMENT ON COLUMN official_disclosures.publication_time_precision IS
    'exact means the official index supplied a clock time; date_only forbids treating local midnight as exact publication time';
