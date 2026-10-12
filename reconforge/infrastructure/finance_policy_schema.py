"""Additive economic-identity and retained-ledger-policy database invariants."""

SQLITE_FINANCE_POLICY_MIGRATION_SQL = """
ALTER TABLE ledger_entries ADD COLUMN currency_precision INTEGER CHECK (currency_precision BETWEEN 0 AND 8);
ALTER TABLE ledger_entries ADD COLUMN currency_rounding_policy TEXT CHECK (currency_rounding_policy='ROUND_HALF_UP');
ALTER TABLE ledger_entries ADD COLUMN currency_registry_version TEXT CHECK (length(currency_registry_version) BETWEEN 1 AND 128);
ALTER TABLE ledger_entries ADD COLUMN currency_registry_digest TEXT REFERENCES currency_registry_snapshots(registry_digest)
 CHECK (length(currency_registry_digest)=64 AND currency_registry_digest NOT GLOB '*[^0-9a-f]*');
CREATE TRIGGER currencies_economic_identity_immutable BEFORE UPDATE ON currencies
WHEN NEW.code IS NOT OLD.code OR NEW.minor_units IS NOT OLD.minor_units
BEGIN SELECT RAISE(ABORT,'Currency code and precision are immutable; create an explicit new policy instead.'); END;
CREATE TRIGGER entity_functional_currency_immutable BEFORE UPDATE ON legal_entities
WHEN NEW.currency IS NOT OLD.currency
BEGIN SELECT RAISE(ABORT,'Legal entity functional currency is immutable.'); END;
CREATE TRIGGER currency_snapshot_update_immutable BEFORE UPDATE ON currency_registry_snapshots
BEGIN SELECT RAISE(ABORT,'Currency snapshots are immutable.'); END;
CREATE TRIGGER currency_snapshot_delete_immutable BEFORE DELETE ON currency_registry_snapshots
BEGIN SELECT RAISE(ABORT,'Currency snapshots are immutable.'); END;
CREATE TRIGGER ledger_currency_policy_required BEFORE INSERT ON ledger_entries
WHEN NEW.currency_precision IS NULL OR NEW.currency_rounding_policy IS NULL
 OR NEW.currency_registry_version IS NULL OR NEW.currency_registry_digest IS NULL
BEGIN SELECT RAISE(ABORT,'A verified currency policy is required for new ledger entries.'); END;
CREATE TRIGGER ledger_currency_policy_immutable BEFORE UPDATE ON ledger_entries
WHEN NEW.currency_code IS NOT OLD.currency_code OR NEW.currency_precision IS NOT OLD.currency_precision
 OR NEW.currency_rounding_policy IS NOT OLD.currency_rounding_policy
 OR NEW.currency_registry_version IS NOT OLD.currency_registry_version
 OR NEW.currency_registry_digest IS NOT OLD.currency_registry_digest
BEGIN SELECT RAISE(ABORT,'Ledger currency policy is immutable.'); END;
ALTER TABLE inventory_valuation_documents ADD COLUMN currency_precision INTEGER CHECK (currency_precision BETWEEN 0 AND 8);
ALTER TABLE inventory_valuation_documents ADD COLUMN currency_rounding_policy TEXT CHECK (currency_rounding_policy='ROUND_HALF_UP');
ALTER TABLE inventory_valuation_documents ADD COLUMN currency_registry_version TEXT CHECK (length(currency_registry_version) BETWEEN 1 AND 128);
ALTER TABLE inventory_valuation_documents ADD COLUMN currency_registry_digest TEXT REFERENCES currency_registry_snapshots(registry_digest)
 CHECK (length(currency_registry_digest)=64 AND currency_registry_digest NOT GLOB '*[^0-9a-f]*');
CREATE TRIGGER valuation_currency_policy_required BEFORE INSERT ON inventory_valuation_documents
WHEN NEW.currency_precision IS NULL OR NEW.currency_rounding_policy IS NULL
 OR NEW.currency_registry_version IS NULL OR NEW.currency_registry_digest IS NULL
BEGIN SELECT RAISE(ABORT,'A verified currency policy is required for new valuation documents.'); END;
CREATE TRIGGER valuation_currency_policy_immutable BEFORE UPDATE ON inventory_valuation_documents
WHEN NEW.currency_code IS NOT OLD.currency_code OR NEW.currency_precision IS NOT OLD.currency_precision
 OR NEW.currency_rounding_policy IS NOT OLD.currency_rounding_policy
 OR NEW.currency_registry_version IS NOT OLD.currency_registry_version
 OR NEW.currency_registry_digest IS NOT OLD.currency_registry_digest
BEGIN SELECT RAISE(ABORT,'Valuation currency policy is immutable.'); END;
"""

POSTGRES_FINANCE_POLICY_SCHEMA_SQL = """
ALTER TABLE reconforge.finance_entries
 ADD COLUMN IF NOT EXISTS currency_precision INTEGER CHECK (currency_precision BETWEEN 0 AND 8),
 ADD COLUMN IF NOT EXISTS currency_rounding_policy TEXT CHECK (currency_rounding_policy='ROUND_HALF_UP'),
 ADD COLUMN IF NOT EXISTS currency_registry_version TEXT CHECK (length(currency_registry_version) BETWEEN 1 AND 128),
 ADD COLUMN IF NOT EXISTS currency_registry_digest TEXT CHECK (currency_registry_digest ~ '^[0-9a-f]{64}$');
DO $reconforge$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='finance_entry_currency_snapshot_fk'
  AND conrelid='reconforge.finance_entries'::regclass) THEN
  ALTER TABLE reconforge.finance_entries ADD CONSTRAINT finance_entry_currency_snapshot_fk
   FOREIGN KEY (tenant_id,currency_registry_digest)
   REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest) ON DELETE RESTRICT;
 END IF;
END $reconforge$;
CREATE OR REPLACE FUNCTION reconforge.guard_currency_economic_identity() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
BEGIN
 IF (NEW.tenant_id,NEW.code,NEW.minor_units) IS DISTINCT FROM (OLD.tenant_id,OLD.code,OLD.minor_units) THEN
  RAISE EXCEPTION 'Currency code and precision are immutable; create an explicit new policy instead.';
 END IF;
 RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS currencies_economic_identity_immutable ON reconforge.currencies;
CREATE TRIGGER currencies_economic_identity_immutable BEFORE UPDATE ON reconforge.currencies
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_currency_economic_identity();
CREATE OR REPLACE FUNCTION reconforge.guard_entity_functional_currency() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
BEGIN
 IF NEW.currency_code IS DISTINCT FROM OLD.currency_code THEN
  RAISE EXCEPTION 'Legal entity functional currency is immutable.';
 END IF;
 RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS entity_functional_currency_immutable ON reconforge.legal_entities;
CREATE TRIGGER entity_functional_currency_immutable BEFORE UPDATE ON reconforge.legal_entities
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_entity_functional_currency();
CREATE OR REPLACE FUNCTION reconforge.guard_currency_snapshot_immutable() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
BEGIN
 RAISE EXCEPTION 'Currency snapshots are immutable.';
END $reconforge$;
DROP TRIGGER IF EXISTS currency_snapshot_immutable ON reconforge.currency_registry_snapshots;
CREATE TRIGGER currency_snapshot_immutable BEFORE UPDATE OR DELETE ON reconforge.currency_registry_snapshots
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_currency_snapshot_immutable();
CREATE OR REPLACE FUNCTION reconforge.guard_ledger_currency_policy() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.currency_precision IS NULL OR NEW.currency_rounding_policy IS NULL
   OR NEW.currency_registry_version IS NULL OR NEW.currency_registry_digest IS NULL THEN
   RAISE EXCEPTION 'A verified currency policy is required for new ledger entries.';
  END IF;
 ELSE
  IF (NEW.currency_code,NEW.currency_precision,NEW.currency_rounding_policy,
      NEW.currency_registry_version,NEW.currency_registry_digest)
   IS DISTINCT FROM (OLD.currency_code,OLD.currency_precision,OLD.currency_rounding_policy,
      OLD.currency_registry_version,OLD.currency_registry_digest) THEN
   RAISE EXCEPTION 'Ledger currency policy is immutable.';
  END IF;
 END IF;
 RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS ledger_currency_policy_guard ON reconforge.finance_entries;
CREATE TRIGGER ledger_currency_policy_guard BEFORE INSERT OR UPDATE ON reconforge.finance_entries
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ledger_currency_policy();
"""

POSTGRES_VALUATION_POLICY_SCHEMA_SQL = """
ALTER TABLE reconforge.inventory_valuation_documents
 ADD COLUMN IF NOT EXISTS currency_precision INTEGER CHECK (currency_precision BETWEEN 0 AND 8),
 ADD COLUMN IF NOT EXISTS currency_rounding_policy TEXT CHECK (currency_rounding_policy='ROUND_HALF_UP'),
 ADD COLUMN IF NOT EXISTS currency_registry_version TEXT CHECK (length(currency_registry_version) BETWEEN 1 AND 128),
 ADD COLUMN IF NOT EXISTS currency_registry_digest TEXT CHECK (currency_registry_digest ~ '^[0-9a-f]{64}$');
DO $reconforge$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='valuation_currency_snapshot_fk'
  AND conrelid='reconforge.inventory_valuation_documents'::regclass) THEN
  ALTER TABLE reconforge.inventory_valuation_documents ADD CONSTRAINT valuation_currency_snapshot_fk
   FOREIGN KEY (tenant_id,currency_registry_digest)
   REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest) ON DELETE RESTRICT;
 END IF;
END $reconforge$;
DROP TRIGGER IF EXISTS valuation_currency_policy_guard ON reconforge.inventory_valuation_documents;
CREATE TRIGGER valuation_currency_policy_guard BEFORE INSERT OR UPDATE ON reconforge.inventory_valuation_documents
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ledger_currency_policy();
"""
