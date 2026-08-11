-- Reconcile append-only enforcement for databases that recorded migration 0019
-- before its trigger definitions were added.  This migration changes schema
-- objects only; identifier-alias and provider-correction rows remain untouched.

DROP TRIGGER IF EXISTS official_identifier_aliases_append_only
ON official_identifier_aliases;

DROP TRIGGER IF EXISTS provider_identifier_corrections_append_only
ON provider_identifier_corrections;

CREATE OR REPLACE FUNCTION prevent_identifier_alias_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER official_identifier_aliases_append_only
BEFORE UPDATE OR DELETE ON official_identifier_aliases
FOR EACH ROW EXECUTE FUNCTION prevent_identifier_alias_mutation();

CREATE TRIGGER provider_identifier_corrections_append_only
BEFORE UPDATE OR DELETE ON provider_identifier_corrections
FOR EACH ROW EXECUTE FUNCTION prevent_identifier_alias_mutation();
