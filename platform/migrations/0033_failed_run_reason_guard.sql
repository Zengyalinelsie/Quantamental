-- PostgreSQL CHECK treats NULL as satisfied; make failed-run reason explicit.
ALTER TABLE governance.run_records
    DROP CONSTRAINT run_records_terminal_shape,
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
            AND coalesce(btrim(failure_reason), '') <> ''
        )
    );
