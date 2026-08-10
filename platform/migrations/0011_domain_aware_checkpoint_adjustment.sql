ALTER TABLE ingestion_checkpoints
    DROP CONSTRAINT ingestion_checkpoints_adjustment_mode_check;

UPDATE ingestion_checkpoints
SET adjustment_mode = 'not_applicable'
WHERE data_domain <> 'raw_daily_bar'
  AND adjustment_mode = 'unadjusted';

ALTER TABLE ingestion_checkpoints
    ADD CONSTRAINT ingestion_checkpoints_adjustment_mode_check CHECK (
        adjustment_mode IS NULL
        OR (
            data_domain = 'raw_daily_bar'
            AND adjustment_mode = 'unadjusted'
        )
        OR (
            data_domain <> 'raw_daily_bar'
            AND adjustment_mode = 'not_applicable'
        )
    );
