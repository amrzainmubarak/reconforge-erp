"""Finite IT1 quantity custody; retain the complete original MSP1 contracts."""

import hashlib
import re

from reconforge.infrastructure.postgres_inventory_quantity_source_ownership import UPGRADE_SQL as ORIGINAL_SQL


def _original(name: str) -> str:
    matches = re.findall(r"CREATE FUNCTION reconforge\." + re.escape(name) + r"\(.*?END \$quantity\$;", ORIGINAL_SQL, re.S)
    if len(matches) != 1:
        raise RuntimeError("Original quantity contract is ambiguous or absent: " + name)
    return matches[0].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


NAMES = ("inventory_quantity_directory_close", "inventory_quantity_guard_birth", "inventory_quantity_plan_namespace_guard")
ORIGINAL_FUNCTIONS = tuple(_original(name) for name in NAMES)


def _pinned_functions() -> str:
    checks = []
    for name, definition in zip(NAMES, ORIGINAL_FUNCTIONS, strict=True):
        body = definition.split("$quantity$")[1]
        digest = hashlib.sha256(body.encode("utf8")).hexdigest()
        checks.append(
            "SELECT * INTO f FROM pg_proc WHERE oid=to_regprocedure('reconforge." + name + "()');\n"
            "IF f.oid IS NULL OR f.prosecdef OR f.prorettype<>'pg_catalog.trigger'::regtype "
            "OR f.provolatile<>'v' OR f.proparallel<>'u' "
            "OR f.prokind<>'f' OR f.proretset OR f.pronargs<>0 OR f.proleakproof "
            "OR f.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql') "
            "OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[] "
            "OR encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')<>'" + digest + "' THEN\n"
            "RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original quantity contract drift: " + name + "'; END IF;"
        )
    return "DO $transfer$ DECLARE f RECORD; BEGIN\n" + "\n".join(checks) + "\nEND $transfer$;"


def _directory() -> str:
    original = _original("inventory_quantity_directory_close")
    anchor = " t:=NEW.tenant_id;"
    if original.count(anchor) != 1:
        raise RuntimeError("Original directory dispatch contract changed")
    return original.replace(anchor, anchor + r"""
 IF NEW.owner_namespace='IT1' THEN
  IF TG_TABLE_NAME='inventory_quantity_source_guards' THEN
   PERFORM reconforge.it1_core_claim_close(t,NEW.owner_claim_id);
  ELSE
   PERFORM reconforge.it1_core_release_close(t,NEW.release_id);
  END IF;
  RETURN NEW;
 END IF;
""", 1)


def _birth() -> str:
    original = _original("inventory_quantity_guard_birth")
    anchor = " IF g.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Inventory release needs its original guard';END IF;"
    if original.count(anchor) != 1:
        raise RuntimeError("Original guard birth contract changed")
    return original.replace(anchor, anchor + r"""
 IF TG_TABLE_NAME='inventory_quantity_source_releases'
 AND NEW.owner_namespace IS DISTINCT FROM g.owner_namespace THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Quantity release retains its exact finite source namespace';END IF;
""", 1)


def _financial_namespace() -> str:
    original = _original("inventory_quantity_plan_namespace_guard")
    anchor = "ARRAY['MSP1-%','MSP1D-%','MSP1K-%','MSP1Q-%']"
    if original.count(anchor) != 2:
        raise RuntimeError("Original financial namespace contract changed")
    return original.replace(anchor, "ARRAY['MSP1-%','MSP1D-%','MSP1K-%','MSP1Q-%','IT1-%']")


STRUCTURAL_UPGRADE_SQL = r"""
DO $transfer$ DECLARE found RECORD; BEGIN
 SELECT count(*) n,min(c.conname) name INTO found FROM pg_constraint c
 WHERE c.conrelid='reconforge.inventory_quantity_source_guards'::regclass AND c.contype='f'
 AND c.confrelid='reconforge.manufacturing_supply_stock_claims'::regclass
 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='tenant_id'),
 (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='owner_claim_id')]::smallint[];
 IF found.n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original MSP quantity claim FK is absent or ambiguous';END IF;
 SELECT count(*) n,min(c.conname) name INTO found FROM pg_constraint c
 WHERE c.conrelid='reconforge.inventory_quantity_source_releases'::regclass AND c.contype='f'
 AND c.confrelid='reconforge.manufacturing_supply_stock_releases'::regclass
 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='tenant_id'),
 (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='release_id')]::smallint[];
 IF found.n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original MSP quantity release FK is absent or ambiguous';END IF;
 SELECT count(*) n,min(c.conname) name INTO found FROM pg_constraint c
 WHERE c.conrelid='reconforge.inventory_quantity_source_guards'::regclass AND c.contype='c'
 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='owner_namespace')]::smallint[];
 IF found.n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original finite quantity namespace check is absent or ambiguous';END IF;
END $transfer$;
ALTER TABLE reconforge.inventory_quantity_source_guards
 ADD COLUMN msp_claim_pin TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='MSP1' THEN owner_claim_id END) STORED,
 ADD COLUMN it1_claim_pin TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='IT1' THEN owner_claim_id END) STORED,
 ADD CONSTRAINT quantity_guard_namespace_tuple UNIQUE(tenant_id,id,owner_namespace),
 ADD CONSTRAINT quantity_msp_claim_pin FOREIGN KEY(tenant_id,msp_claim_pin)
 REFERENCES reconforge.manufacturing_supply_stock_claims(tenant_id,id),
 ADD CONSTRAINT quantity_it1_claim_pin FOREIGN KEY(tenant_id,it1_claim_pin)
 REFERENCES reconforge.inventory_transfer_claims(tenant_id,id);
ALTER TABLE reconforge.inventory_quantity_source_releases
 ADD COLUMN owner_namespace TEXT NOT NULL DEFAULT 'MSP1',
 ADD COLUMN msp_release_pin TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='MSP1' THEN release_id END) STORED,
 ADD COLUMN it1_release_pin TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='IT1' THEN release_id END) STORED,
 ADD CONSTRAINT quantity_release_namespace CHECK(owner_namespace IN('MSP1','IT1')),
 ADD CONSTRAINT quantity_release_guard_namespace FOREIGN KEY(tenant_id,guard_id,owner_namespace)
 REFERENCES reconforge.inventory_quantity_source_guards(tenant_id,id,owner_namespace),
 ADD CONSTRAINT quantity_msp_release_pin FOREIGN KEY(tenant_id,msp_release_pin)
 REFERENCES reconforge.manufacturing_supply_stock_releases(tenant_id,id),
 ADD CONSTRAINT quantity_it1_release_pin FOREIGN KEY(tenant_id,it1_release_pin)
 REFERENCES reconforge.inventory_transfer_releases(tenant_id,id);
DO $transfer$ DECLARE found RECORD;BEGIN
 SELECT c.conname name INTO STRICT found FROM pg_constraint c
 WHERE c.conrelid='reconforge.inventory_quantity_source_guards'::regclass AND c.contype='f'
 AND c.confrelid='reconforge.manufacturing_supply_stock_claims'::regclass
 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='tenant_id'),
 (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='owner_claim_id')]::smallint[];
 EXECUTE format('ALTER TABLE reconforge.inventory_quantity_source_guards DROP CONSTRAINT %I',found.name);
 SELECT c.conname name INTO STRICT found FROM pg_constraint c
 WHERE c.conrelid='reconforge.inventory_quantity_source_releases'::regclass AND c.contype='f'
 AND c.confrelid='reconforge.manufacturing_supply_stock_releases'::regclass
 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='tenant_id'),
 (SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='release_id')]::smallint[];
 EXECUTE format('ALTER TABLE reconforge.inventory_quantity_source_releases DROP CONSTRAINT %I',found.name);
 SELECT c.conname name INTO STRICT found FROM pg_constraint c
 WHERE c.conrelid='reconforge.inventory_quantity_source_guards'::regclass AND c.contype='c'
 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='owner_namespace')]::smallint[];
 EXECUTE format('ALTER TABLE reconforge.inventory_quantity_source_guards DROP CONSTRAINT %I',found.name);
END $transfer$;
ALTER TABLE reconforge.inventory_quantity_source_guards
 ADD CONSTRAINT quantity_source_finite_namespace CHECK(owner_namespace IN('MSP1','IT1'));
"""

NATIVE_ROUTE_SQL = r"""
CREATE FUNCTION reconforge.inventory_transfer_native_route() RETURNS trigger
 LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path=pg_catalog AS $transfer$
DECLARE changed JSONB;prior JSONB;parent RECORD;candidate RECORD;pool RECORD;scope_row JSONB;
 movement TEXT;reserved BOOLEAN:=FALSE;
BEGIN
 IF TG_OP<>'INSERT' THEN prior:=to_jsonb(OLD);END IF;
 IF TG_OP<>'DELETE' THEN changed:=to_jsonb(NEW);ELSE changed:=prior;END IF;
 IF TG_TABLE_NAME='inventory_movements' THEN
  movement:=changed->>'id';
  scope_row:=changed;
  reserved:=upper(COALESCE(changed->>'movement_number','')) LIKE 'IT1-%'
   OR upper(COALESCE(changed->>'source_reference','')) LIKE 'IT1-%'
   OR upper(COALESCE(prior->>'movement_number','')) LIKE 'IT1-%'
   OR upper(COALESCE(prior->>'source_reference','')) LIKE 'IT1-%';
 ELSE
  FOR candidate IN SELECT changed->>'movement_id' id UNION SELECT prior->>'movement_id' id LOOP
   IF candidate.id IS NULL THEN CONTINUE;END IF;
   SELECT * INTO parent FROM reconforge.inventory_movements
    WHERE tenant_id=changed->>'tenant_id' AND id=candidate.id FOR SHARE;
   IF parent.id IS NOT NULL AND(upper(COALESCE(parent.movement_number,'')) LIKE 'IT1-%'
    OR upper(COALESCE(parent.source_reference,'')) LIKE 'IT1-%') THEN
    IF movement IS NOT NULL AND movement<>parent.id THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Owned native transfer line cannot change its parent';END IF;
    movement:=parent.id;reserved:=TRUE;scope_row:=to_jsonb(parent);
   END IF;
  END LOOP;
 END IF;
 IF reserved THEN
  -- This trigger sorts before generic outgoing-location custody. Lock all
  -- entity/item pools first, then both physical locations in canonical order.
  FOR pool IN SELECT x.item_id FROM reconforge.inventory_movement_lines x
   WHERE x.tenant_id=changed->>'tenant_id' AND x.movement_id=movement
   UNION SELECT changed->>'item_id' WHERE TG_TABLE_NAME='inventory_movement_lines'
   UNION SELECT prior->>'item_id' WHERE TG_TABLE_NAME='inventory_movement_lines' AND prior IS NOT NULL
   ORDER BY 1 LOOP
   IF pool.item_id IS NOT NULL THEN PERFORM reconforge.inventory_quantity_source_pool_lock(
    changed->>'tenant_id',scope_row->>'workspace_id',scope_row->>'legal_entity_id',pool.item_id);END IF;
  END LOOP;
  FOR pool IN
   SELECT x.item_id,physical.location_id FROM reconforge.inventory_movement_lines x
   CROSS JOIN LATERAL unnest(ARRAY[x.from_location_id,x.to_location_id]) physical(location_id)
   WHERE x.tenant_id=changed->>'tenant_id' AND x.movement_id=movement
   UNION SELECT changed->>'item_id',physical.location_id
    FROM unnest(ARRAY[changed->>'from_location_id',changed->>'to_location_id']) physical(location_id)
    WHERE TG_TABLE_NAME='inventory_movement_lines'
   UNION SELECT prior->>'item_id',physical.location_id
    FROM unnest(ARRAY[prior->>'from_location_id',prior->>'to_location_id']) physical(location_id)
    WHERE TG_TABLE_NAME='inventory_movement_lines' AND prior IS NOT NULL
   ORDER BY 1,2 LOOP
   IF pool.item_id IS NOT NULL AND pool.location_id IS NOT NULL THEN
    PERFORM reconforge.touch_inventory_quantity_claim_gate(changed->>'tenant_id',scope_row->>'workspace_id',
     scope_row->>'legal_entity_id',pool.item_id,pool.location_id);END IF;
  END LOOP;
  IF TG_WHEN='BEFORE' THEN
   PERFORM reconforge.it1_native_admit(changed->>'tenant_id',changed,prior,TG_TABLE_NAME||':'||TG_OP);
  ELSE
   PERFORM reconforge.it1_native_close(changed->>'tenant_id',movement);
  END IF;
 END IF;
 IF TG_WHEN='AFTER' THEN RETURN NULL;END IF;
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
END $transfer$;
CREATE TRIGGER a_inventory_0_transfer_native BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_movements
 FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_transfer_native_route();
CREATE TRIGGER a_inventory_0_transfer_native BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_movement_lines
 FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_transfer_native_route();
CREATE CONSTRAINT TRIGGER inventory_transfer_native_close AFTER INSERT OR UPDATE OR DELETE ON reconforge.inventory_movements
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_transfer_native_route();
CREATE CONSTRAINT TRIGGER inventory_transfer_native_close AFTER INSERT OR UPDATE OR DELETE ON reconforge.inventory_movement_lines
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_transfer_native_route();
"""

UPGRADE_SQL = "\n".join((_pinned_functions(), STRUCTURAL_UPGRADE_SQL, _directory(), _birth(), _financial_namespace(), NATIVE_ROUTE_SQL))

SOURCE_DOWNGRADE_PREFLIGHT_SQL = r"""
DO $transfer$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources)
 OR EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_guards WHERE owner_namespace='IT1')
 OR EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases WHERE owner_namespace='IT1')
 OR EXISTS(SELECT 1 FROM reconforge.inventory_movements WHERE upper(movement_number) LIKE 'IT1-%'
 OR upper(COALESCE(source_reference,'')) LIKE 'IT1-%') THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained transfer source custody requires forward compatibility or restore';END IF;
END $transfer$;
"""

DOWNGRADE_SQL = "\n".join((SOURCE_DOWNGRADE_PREFLIGHT_SQL, r"""
DROP TRIGGER inventory_transfer_native_close ON reconforge.inventory_movements;
DROP TRIGGER inventory_transfer_native_close ON reconforge.inventory_movement_lines;
DROP TRIGGER a_inventory_0_transfer_native ON reconforge.inventory_movements;
DROP TRIGGER a_inventory_0_transfer_native ON reconforge.inventory_movement_lines;
DROP FUNCTION reconforge.inventory_transfer_native_route();
""", *ORIGINAL_FUNCTIONS, r"""
ALTER TABLE reconforge.inventory_quantity_source_guards
 ADD FOREIGN KEY(tenant_id,owner_claim_id) REFERENCES reconforge.manufacturing_supply_stock_claims(tenant_id,id);
ALTER TABLE reconforge.inventory_quantity_source_releases
 ADD FOREIGN KEY(tenant_id,release_id) REFERENCES reconforge.manufacturing_supply_stock_releases(tenant_id,id);
ALTER TABLE reconforge.inventory_quantity_source_releases
 DROP CONSTRAINT quantity_release_guard_namespace,
 DROP CONSTRAINT quantity_msp_release_pin,DROP CONSTRAINT quantity_it1_release_pin,
 DROP CONSTRAINT quantity_release_namespace,
 DROP COLUMN msp_release_pin,DROP COLUMN it1_release_pin,DROP COLUMN owner_namespace;
ALTER TABLE reconforge.inventory_quantity_source_guards
 DROP CONSTRAINT quantity_source_finite_namespace,
 DROP CONSTRAINT quantity_guard_namespace_tuple,
 DROP CONSTRAINT quantity_msp_claim_pin,DROP CONSTRAINT quantity_it1_claim_pin,
 DROP COLUMN msp_claim_pin,DROP COLUMN it1_claim_pin,
 ADD CHECK(owner_namespace='MSP1');
"""))
