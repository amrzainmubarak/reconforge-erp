"""Retain new ledger monetary policy without guessing legacy interpretation.

Upgrade leaves all historical entry policy columns NULL. They require reviewed
historical evidence before exact interpretation. Downgrade refuses retained new
policy bindings; restore a pre-upgrade backup instead of discarding evidence.
The SQL is frozen here; it does not import evolving application definitions.
"""

from alembic import op

revision = "0094_pg_finance_policy"
down_revision = "0093_pg_metrics"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
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


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("""
        SET LOCAL row_security = off;
        LOCK TABLE reconforge.finance_entries,reconforge.inventory_valuation_documents IN ACCESS EXCLUSIVE MODE;
        DO $reconforge$ BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.finance_entries WHERE currency_registry_digest IS NOT NULL)
             OR EXISTS (SELECT 1 FROM reconforge.inventory_valuation_documents WHERE currency_registry_digest IS NOT NULL) THEN
                RAISE EXCEPTION 'finance policy downgrade refused: verified entry policies are retained; restore a pre-upgrade backup';
            END IF;
        END $reconforge$;
        DROP TRIGGER valuation_currency_policy_guard ON reconforge.inventory_valuation_documents;
        ALTER TABLE reconforge.inventory_valuation_documents
            DROP CONSTRAINT valuation_currency_snapshot_fk,
            DROP COLUMN currency_registry_digest, DROP COLUMN currency_registry_version,
            DROP COLUMN currency_rounding_policy, DROP COLUMN currency_precision;
        DROP TRIGGER ledger_currency_policy_guard ON reconforge.finance_entries;
        DROP FUNCTION reconforge.guard_ledger_currency_policy();
        DROP TRIGGER currency_snapshot_immutable ON reconforge.currency_registry_snapshots;
        DROP FUNCTION reconforge.guard_currency_snapshot_immutable();
        DROP TRIGGER entity_functional_currency_immutable ON reconforge.legal_entities;
        DROP FUNCTION reconforge.guard_entity_functional_currency();
        DROP TRIGGER currencies_economic_identity_immutable ON reconforge.currencies;
        DROP FUNCTION reconforge.guard_currency_economic_identity();
        ALTER TABLE reconforge.finance_entries
            DROP CONSTRAINT finance_entry_currency_snapshot_fk,
            DROP COLUMN currency_registry_digest,
            DROP COLUMN currency_registry_version,
            DROP COLUMN currency_rounding_policy,
            DROP COLUMN currency_precision;
    """)
