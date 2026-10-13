"""Scoped inventory quantity custody over the existing movement and FIFO engines.

Install after the owned142 source tables, before owned msp_close and before
shared native triggers are admitted. Owner supplies msp_close(t,plan_id).
Native integration must touch both gates before relevance and call check after
withdrawal, including unallocated FIFO mutation before posted stock changes.
"""

UPGRADE_SQL = r"""
ALTER TABLE reconforge.inventory_items ADD CONSTRAINT quantity_source_item_tuple UNIQUE(tenant_id,id,workspace_id,uom_id,item_type,tracking_mode,inventory_account_id);
ALTER TABLE reconforge.inventory_units_of_measure ADD CONSTRAINT quantity_source_uom_tuple UNIQUE(tenant_id,id,workspace_id,decimal_places);
ALTER TABLE reconforge.inventory_locations ADD CONSTRAINT quantity_source_location_tuple UNIQUE(tenant_id,id,warehouse_id);
ALTER TABLE reconforge.inventory_warehouses ADD CONSTRAINT quantity_source_warehouse_tuple UNIQUE(tenant_id,id,workspace_id,organization_id);
CREATE TABLE reconforge.inventory_quantity_source_guards (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),location_id TEXT NOT NULL,
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND 9000000000000000000),
 owner_namespace TEXT NOT NULL CHECK(owner_namespace='MSP1'),owner_claim_id TEXT NOT NULL,source_receipt_plan_id TEXT,
 warehouse_id TEXT NOT NULL,inventory_account_id TEXT NOT NULL,item_type TEXT NOT NULL CHECK(item_type IN('Stock','Consumable')),
 tracking_mode TEXT NOT NULL DEFAULT 'None' CHECK(tracking_mode='None'),
 PRIMARY KEY(tenant_id,id),CHECK(id=owner_claim_id),
 FOREIGN KEY(tenant_id,owner_claim_id) REFERENCES reconforge.manufacturing_supply_stock_claims(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,source_receipt_plan_id) REFERENCES reconforge.inventory_receipt_plans(tenant_id,id)
 ,FOREIGN KEY(tenant_id,item_id,workspace_id,uom_id,item_type,tracking_mode,inventory_account_id)
 REFERENCES reconforge.inventory_items(tenant_id,id,workspace_id,uom_id,item_type,tracking_mode,inventory_account_id)
 ,FOREIGN KEY(tenant_id,uom_id,workspace_id,quantity_precision)
 REFERENCES reconforge.inventory_units_of_measure(tenant_id,id,workspace_id,decimal_places)
 ,FOREIGN KEY(tenant_id,location_id,warehouse_id) REFERENCES reconforge.inventory_locations(tenant_id,id,warehouse_id)
 ,FOREIGN KEY(tenant_id,warehouse_id,workspace_id,organization_id)
 REFERENCES reconforge.inventory_warehouses(tenant_id,id,workspace_id,organization_id)
);
CREATE INDEX inventory_quantity_source_pool ON reconforge.inventory_quantity_source_guards(tenant_id,workspace_id,legal_entity_id,item_id,location_id);
CREATE TABLE reconforge.inventory_quantity_source_releases (
 tenant_id TEXT NOT NULL,guard_id TEXT NOT NULL,release_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,guard_id),UNIQUE(tenant_id,release_id),
 FOREIGN KEY(tenant_id,guard_id) REFERENCES reconforge.inventory_quantity_source_guards(tenant_id,id),
 FOREIGN KEY(tenant_id,release_id) REFERENCES reconforge.manufacturing_supply_stock_releases(tenant_id,id)
);
CREATE TABLE reconforge.inventory_quantity_claim_gates (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,item_id TEXT NOT NULL,
 pool_kind TEXT NOT NULL CHECK(pool_kind IN('Location','FIFO')),location_id TEXT NOT NULL,version BIGINT NOT NULL CHECK(version>0),
 PRIMARY KEY(tenant_id,workspace_id,legal_entity_id,item_id,pool_kind,location_id),
 CHECK((pool_kind='FIFO' AND location_id='') OR(pool_kind='Location' AND length(location_id)>0)),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id)
);
CREATE FUNCTION reconforge.inventory_quantity_source_pool_lock(t TEXT,w TEXT,e TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $quantity$
DECLARE org TEXT;
BEGIN
 SELECT o.id INTO org FROM reconforge.organizations o JOIN reconforge.legal_entities entity
 ON entity.tenant_id=o.tenant_id AND entity.organization_id=o.id WHERE o.tenant_id=t AND o.application_workspace_id=w AND entity.id=e;
 IF org IS NULL OR NOT reconforge.irp_scope(t,w,org,e) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Quantity custody requires its exact existing native hierarchy';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'inventory_quantity_source',w,e,i)::text,0));
 INSERT INTO reconforge.inventory_quantity_claim_gates(tenant_id,workspace_id,organization_id,legal_entity_id,item_id,pool_kind,location_id,version)
 VALUES(t,w,org,e,i,'FIFO','',1) ON CONFLICT(tenant_id,workspace_id,legal_entity_id,item_id,pool_kind,location_id)
 DO UPDATE SET version=inventory_quantity_claim_gates.version+1;
END $quantity$;
CREATE FUNCTION reconforge.touch_inventory_quantity_claim_gate(t TEXT,w TEXT,e TEXT,i TEXT,l TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $quantity$
DECLARE org TEXT;
BEGIN
 PERFORM reconforge.inventory_quantity_source_pool_lock(t,w,e,i);
 IF l='' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='FIFO sentinel is internal; supply NULL for FIFO-only native mutation';END IF;
 SELECT o.id INTO org FROM reconforge.organizations o JOIN reconforge.legal_entities entity
 ON entity.tenant_id=o.tenant_id AND entity.organization_id=o.id WHERE o.tenant_id=t AND o.application_workspace_id=w AND entity.id=e;
 IF org IS NULL OR NOT reconforge.irp_scope(t,w,org,e) OR(l IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM reconforge.inventory_locations loc JOIN reconforge.inventory_warehouses warehouse
 ON warehouse.tenant_id=loc.tenant_id AND warehouse.id=loc.warehouse_id
 WHERE loc.tenant_id=t AND loc.id=l AND warehouse.workspace_id=w AND warehouse.organization_id=org
 AND(warehouse.legal_entity_id IS NULL OR warehouse.legal_entity_id=e))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Inventory quantity gate requires the exact native pool hierarchy';END IF;
 -- Same existing native physical and FIFO advisory keys; no location assumption on a cost layer.
 IF l IS NOT NULL THEN PERFORM pg_advisory_xact_lock(hashtextextended(w||'|'||e||'|'||l||'|'||i||'|',0));END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(e||'|'||i||'|',0));
 IF l IS NOT NULL THEN
 INSERT INTO reconforge.inventory_quantity_claim_gates(tenant_id,workspace_id,organization_id,legal_entity_id,item_id,pool_kind,location_id,version)
 VALUES(t,w,org,e,i,'Location',l,1) ON CONFLICT(tenant_id,workspace_id,legal_entity_id,item_id,pool_kind,location_id)
 DO UPDATE SET version=inventory_quantity_claim_gates.version+1;END IF;
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_free_fifo(t TEXT,w TEXT,e TEXT,i TEXT) RETURNS NUMERIC
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $quantity$
DECLARE remaining NUMERIC;claimed NUMERIC;native RECORD;
BEGIN
 SELECT item.uom_id,u.decimal_places INTO native FROM reconforge.inventory_items item
 JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=item.tenant_id AND u.id=item.uom_id
 WHERE item.tenant_id=t AND item.workspace_id=w AND item.id=i;
 IF native.uom_id IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='FIFO quantity needs its current scoped native base unit';END IF;
 IF EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers layer
 JOIN reconforge.inventory_valuation_lines detail ON detail.tenant_id=layer.tenant_id AND detail.id=layer.source_valuation_line_id
 JOIN reconforge.inventory_valuation_documents document ON document.tenant_id=detail.tenant_id AND document.id=detail.valuation_document_id
 WHERE layer.tenant_id=t AND layer.workspace_id=w AND layer.legal_entity_id=e AND layer.item_id=i
 AND layer.inventory_lot_id IS NULL AND layer.remaining_quantity_scaled>0 AND document.status='Approved'
 AND((layer.uom_id,layer.quantity_precision) IS DISTINCT FROM(native.uom_id,native.decimal_places)
 OR(detail.item_id,detail.uom_id,detail.quantity_precision,detail.inventory_lot_id)
 IS DISTINCT FROM(layer.item_id,layer.uom_id,layer.quantity_precision,layer.inventory_lot_id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original valued FIFO quantities cannot be reinterpreted through changed native units';END IF;
 SELECT COALESCE(sum(layer.remaining_quantity_scaled),0) INTO remaining
 FROM reconforge.inventory_cost_layers layer
 JOIN reconforge.inventory_valuation_lines detail ON detail.tenant_id=layer.tenant_id AND detail.id=layer.source_valuation_line_id
 JOIN reconforge.inventory_valuation_documents document ON document.tenant_id=detail.tenant_id AND document.id=detail.valuation_document_id
 WHERE layer.tenant_id=t AND layer.workspace_id=w AND layer.legal_entity_id=e AND layer.item_id=i
 AND layer.inventory_lot_id IS NULL AND layer.remaining_value_minor>0 AND document.status='Approved'
 AND document.workspace_id=w AND document.legal_entity_id=e AND detail.flow_direction='Inbound'
 AND(detail.item_id,detail.uom_id,detail.quantity_precision,detail.inventory_lot_id)
 IS NOT DISTINCT FROM(layer.item_id,layer.uom_id,layer.quantity_precision,layer.inventory_lot_id);
 SELECT COALESCE(sum(g.quantity_scaled),0) INTO claimed FROM reconforge.inventory_quantity_source_guards g
 WHERE g.tenant_id=t AND g.workspace_id=w AND g.legal_entity_id=e AND g.item_id=i
 AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases r WHERE r.tenant_id=g.tenant_id AND r.guard_id=g.id);
 IF remaining<claimed THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Active planning quantities require unallocated native FIFO backing';END IF;
 RETURN remaining-claimed;
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_directory_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $quantity$
DECLARE c RECORD;r RECORD;g RECORD;owner TEXT;t TEXT;
BEGIN
 t:=NEW.tenant_id;
 IF TG_TABLE_NAME='inventory_quantity_source_guards' THEN
  g:=NEW;
  SELECT * INTO c FROM reconforge.manufacturing_supply_stock_claims claim WHERE claim.tenant_id=t AND claim.id=g.owner_claim_id;
  IF c.id IS NULL OR(g.id,g.workspace_id,g.organization_id,g.legal_entity_id,g.item_id,g.uom_id,g.quantity_precision,g.location_id,g.quantity_scaled,g.source_receipt_plan_id)
  IS DISTINCT FROM(c.id,c.workspace_id,c.organization_id,c.legal_entity_id,c.item_id,c.uom_id,c.quantity_precision,c.location_id,c.quantity_scaled,c.native_receipt_plan_id)
  THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Core quantity guard must equal its original complete source claim';END IF;
  owner:=c.plan_id;
 ELSE
  SELECT * INTO g FROM reconforge.inventory_quantity_source_guards guard WHERE guard.tenant_id=t AND guard.id=NEW.guard_id;
  SELECT * INTO c FROM reconforge.manufacturing_supply_stock_claims claim WHERE claim.tenant_id=t AND claim.id=g.owner_claim_id;
  SELECT * INTO r FROM reconforge.manufacturing_supply_stock_releases released WHERE released.tenant_id=t AND released.id=NEW.release_id;
  IF g.id IS NULL OR c.id IS NULL OR r.id IS NULL OR(r.claim_id,r.plan_id,r.workspace_id,r.organization_id,r.legal_entity_id)
  IS DISTINCT FROM(c.id,c.plan_id,c.workspace_id,c.organization_id,c.legal_entity_id)
  OR c.state IS DISTINCT FROM (CASE r.purpose WHEN'Handoff'THEN'HandedOff' ELSE'Released' END)
  THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Core quantity release must equal its immutable source and target disposition';END IF;
  owner:=c.plan_id;
 END IF;
 PERFORM reconforge.msp_close(t,owner);RETURN NEW;
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_gate_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $quantity$
BEGIN
 IF TG_OP='DELETE' OR(TG_OP='INSERT' AND NEW.version<>1)
 OR(TG_OP='UPDATE' AND(to_jsonb(NEW)-'version' IS DISTINCT FROM to_jsonb(OLD)-'version'
 OR OLD.version=9223372036854775807 OR NEW.version<>OLD.version+1)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Native quantity coordination identity is fixed and its version advances exactly once';END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_items item
 JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=item.tenant_id AND u.id=item.uom_id
 WHERE item.tenant_id=NEW.tenant_id AND item.id=NEW.item_id AND item.workspace_id=NEW.workspace_id
 AND(item.organization_id IS NULL OR item.organization_id=NEW.organization_id)
 AND item.item_type IN('Stock','Consumable') AND item.tracking_mode='None') THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Native quantity gate requires a real scoped untracked stock item';END IF;
 IF NEW.pool_kind='Location' AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_locations loc
 JOIN reconforge.inventory_warehouses warehouse ON warehouse.tenant_id=loc.tenant_id AND warehouse.id=loc.warehouse_id
 WHERE loc.tenant_id=NEW.tenant_id AND loc.id=NEW.location_id AND warehouse.workspace_id=NEW.workspace_id
 AND warehouse.organization_id=NEW.organization_id AND(warehouse.legal_entity_id IS NULL OR warehouse.legal_entity_id=NEW.legal_entity_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Physical quantity gate requires its actual scoped native location';END IF;
 RETURN NEW;
END $quantity$;
CREATE TRIGGER inventory_quantity_gate_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_quantity_claim_gates
 FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_gate_guard();
CREATE FUNCTION reconforge.inventory_quantity_guard_birth() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $quantity$
DECLARE g RECORD;metadata RECORD;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Inventory source guard/release history is immutable';END IF;
 IF TG_TABLE_NAME='inventory_quantity_source_guards' THEN
 SELECT item.item_type,item.inventory_account_id,loc.warehouse_id INTO metadata FROM reconforge.inventory_items item
 JOIN reconforge.inventory_locations loc ON loc.tenant_id=item.tenant_id AND loc.id=NEW.location_id
 WHERE item.tenant_id=NEW.tenant_id AND item.id=NEW.item_id AND item.workspace_id=NEW.workspace_id;
 IF metadata.item_type IS NULL OR metadata.inventory_account_id IS NULL OR metadata.warehouse_id IS NULL THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Quantity source needs its actual native item and warehouse';END IF;
 NEW.item_type:=metadata.item_type;NEW.inventory_account_id:=metadata.inventory_account_id;
 NEW.warehouse_id:=metadata.warehouse_id;NEW.tracking_mode:='None';g:=NEW;
 ELSE SELECT * INTO g FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=NEW.tenant_id AND id=NEW.guard_id;END IF;
 IF g.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Inventory release needs its original guard';END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_items item
 JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=item.tenant_id AND u.id=item.uom_id
 WHERE item.tenant_id=g.tenant_id AND item.id=g.item_id AND item.workspace_id=g.workspace_id
 AND(item.organization_id IS NULL OR item.organization_id=g.organization_id)
 AND item.item_type IN('Stock','Consumable') AND item.tracking_mode='None'
 AND item.uom_id=g.uom_id AND u.decimal_places=g.quantity_precision) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Core source quantity retains its original scoped item and exact base UOM';END IF;
 PERFORM reconforge.touch_inventory_quantity_claim_gate(g.tenant_id,g.workspace_id,g.legal_entity_id,g.item_id,g.location_id);RETURN NEW;
END $quantity$;
DO $quantity$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['inventory_quantity_source_guards','inventory_quantity_source_releases','inventory_quantity_claim_gates'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
 IF n='inventory_quantity_source_releases' THEN
  EXECUTE format('CREATE POLICY inventory_quantity_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_guards g WHERE g.tenant_id=inventory_quantity_source_releases.tenant_id AND g.id=inventory_quantity_source_releases.guard_id AND reconforge.irp_scope(g.tenant_id,g.workspace_id,g.organization_id,g.legal_entity_id)))',n);
 ELSE EXECUTE format('CREATE POLICY inventory_quantity_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);END IF;
 IF n<>'inventory_quantity_claim_gates' THEN
  EXECUTE format('CREATE TRIGGER inventory_quantity_birth BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_guard_birth()',n);
  EXECUTE format('CREATE CONSTRAINT TRIGGER inventory_quantity_close AFTER INSERT ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_directory_close()',n);
 END IF;
 END LOOP;
END $quantity$;
"""

_NATIVE_SQL = r"""
ALTER FUNCTION reconforge.stock_sales_capacity(TEXT,TEXT,TEXT,TEXT,TEXT) RENAME TO stock_sales_capacity_pre_supply;
CREATE FUNCTION reconforge.inventory_quantity_check_capacity(t TEXT,w TEXT,e TEXT,i TEXT,l TEXT) RETURNS VOID
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $quantity$
DECLARE available NUMERIC;reserved NUMERIC;claimed NUMERIC;native RECORD;
BEGIN
 SELECT item.uom_id,u.decimal_places INTO native FROM reconforge.inventory_items item
 JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=item.tenant_id AND u.id=item.uom_id
 WHERE item.tenant_id=t AND item.workspace_id=w AND item.id=i;
 IF native.uom_id IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Physical quantity needs its current scoped native base unit';END IF;
 IF EXISTS(SELECT 1 FROM reconforge.inventory_movement_lines x
 JOIN reconforge.inventory_movements m ON m.tenant_id=x.tenant_id AND m.id=x.movement_id
 WHERE x.tenant_id=t AND m.workspace_id=w AND m.legal_entity_id=e AND m.status='Posted' AND x.item_id=i
 AND x.inventory_lot_id IS NULL AND(x.from_location_id=l OR x.to_location_id=l)
 AND(x.uom_id,x.quantity_precision) IS DISTINCT FROM(native.uom_id,native.decimal_places)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original posted physical quantities cannot be reinterpreted through changed native units';END IF;
 SELECT COALESCE(sum(g.quantity_scaled),0) INTO claimed FROM reconforge.inventory_quantity_source_guards g
 WHERE g.tenant_id=t AND g.workspace_id=w AND g.legal_entity_id=e AND g.location_id=l AND g.item_id=i
 AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases r WHERE r.tenant_id=g.tenant_id AND r.guard_id=g.id);
 SELECT COALESCE(sum(CASE WHEN x.to_location_id=l THEN x.quantity_scaled ELSE 0 END-CASE WHEN x.from_location_id=l THEN x.quantity_scaled ELSE 0 END),0)
 INTO available FROM reconforge.inventory_movement_lines x JOIN reconforge.inventory_movements m ON m.tenant_id=x.tenant_id AND m.id=x.movement_id
 WHERE x.tenant_id=t AND m.workspace_id=w AND m.legal_entity_id=e AND m.status='Posted' AND x.item_id=i AND x.inventory_lot_id IS NULL;
 SELECT COALESCE(sum(quantity_scaled),0) INTO reserved FROM reconforge.stock_sales_reservations
 WHERE tenant_id=t AND workspace_id=w AND legal_entity_id=e AND location_id=l AND item_id=i AND state='Active';
 -- Retain the original ME1 relevance boundary before protected owner metadata.
 IF EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines x ON x.tenant_id=m.tenant_id AND x.movement_id=m.id
 WHERE m.tenant_id=t AND m.workspace_id=w AND m.legal_entity_id=e AND m.manufacturing_claim_state IN('Reserved','IssuePrepared','IssueReviewed')
 AND x.item_id=i AND x.from_location_id=l AND x.inventory_lot_id IS NULL) THEN
 SELECT reserved+COALESCE(sum(quantity_scaled),0) INTO reserved FROM reconforge.manufacturing_execution_reservations
 WHERE tenant_id=t AND workspace_id=w AND legal_entity_id=e AND location_id=l AND item_id=i AND state='Active';END IF;
 IF available<reserved+claimed THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='inventory_quantity_source_capacity',
 MESSAGE='Posted stock must cover native reservations and exclusive planning quantities';END IF;
 PERFORM reconforge.inventory_quantity_free_fifo(t,w,e,i);
END $quantity$;
CREATE FUNCTION reconforge.stock_sales_capacity(t TEXT,w TEXT,e TEXT,l TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $quantity$
BEGIN
 PERFORM reconforge.touch_inventory_quantity_claim_gate(t,w,e,i,l);
 PERFORM reconforge.stock_sales_capacity_pre_supply(t,w,e,l,i);
 PERFORM reconforge.inventory_quantity_check_capacity(t,w,e,i,l);
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_native_route() RETURNS trigger
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $quantity$
DECLARE changed JSONB;parent RECORD;layer RECORD;pool RECORD;before_row JSONB;after_row JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN before_row:=to_jsonb(OLD);END IF;
 IF TG_OP<>'DELETE' THEN after_row:=to_jsonb(NEW);END IF;
 FOR changed IN SELECT before_row WHERE before_row IS NOT NULL UNION SELECT after_row WHERE after_row IS NOT NULL LOOP
  IF TG_TABLE_NAME IN('inventory_movements','inventory_movement_lines') THEN
   IF TG_TABLE_NAME='inventory_movements' THEN
    SELECT * INTO parent FROM reconforge.inventory_movements WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'id';
   ELSE
    SELECT * INTO parent FROM reconforge.inventory_movements WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'movement_id';
   END IF;
   IF parent.id IS NULL THEN CONTINUE;END IF;
   FOR pool IN
    SELECT DISTINCT x.item_id,x.from_location_id location_id FROM reconforge.inventory_movement_lines x
    WHERE x.tenant_id=parent.tenant_id AND x.movement_id=parent.id AND x.inventory_lot_id IS NULL AND x.from_location_id IS NOT NULL
    UNION SELECT changed->>'item_id',changed->>'from_location_id'
    WHERE TG_TABLE_NAME='inventory_movement_lines' AND changed->>'inventory_lot_id' IS NULL AND changed->>'from_location_id' IS NOT NULL
    ORDER BY 1,2 LOOP
    IF TG_WHEN='BEFORE' THEN
     PERFORM reconforge.touch_inventory_quantity_claim_gate(parent.tenant_id,parent.workspace_id,parent.legal_entity_id,pool.item_id,pool.location_id);
    ELSE
     PERFORM reconforge.stock_sales_capacity(parent.tenant_id,parent.workspace_id,parent.legal_entity_id,pool.location_id,pool.item_id);
    END IF;
   END LOOP;
  ELSE
   IF TG_TABLE_NAME='inventory_cost_layers' THEN
    IF changed->>'inventory_lot_id' IS NOT NULL THEN CONTINUE;END IF;
    IF TG_WHEN='BEFORE' THEN
     PERFORM reconforge.touch_inventory_quantity_claim_gate(changed->>'tenant_id',changed->>'workspace_id',changed->>'legal_entity_id',changed->>'item_id',NULL);
    ELSE
     PERFORM reconforge.inventory_quantity_free_fifo(changed->>'tenant_id',changed->>'workspace_id',changed->>'legal_entity_id',changed->>'item_id');
    END IF;
   ELSE
    SELECT * INTO layer FROM reconforge.inventory_cost_layers WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'cost_layer_id';
    IF layer.id IS NULL OR layer.inventory_lot_id IS NOT NULL THEN CONTINUE;END IF;
    IF TG_WHEN='BEFORE' THEN
     PERFORM reconforge.touch_inventory_quantity_claim_gate(layer.tenant_id,layer.workspace_id,layer.legal_entity_id,layer.item_id,NULL);
    ELSE
     PERFORM reconforge.inventory_quantity_free_fifo(layer.tenant_id,layer.workspace_id,layer.legal_entity_id,layer.item_id);
    END IF;
   END IF;
  END IF;
 END LOOP;
 IF TG_WHEN='AFTER' THEN RETURN NULL;END IF;
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_reference_guard() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $quantity$
DECLARE changed JSONB:=to_jsonb(OLD);guard RECORD;
BEGIN
 FOR guard IN SELECT g.* FROM reconforge.inventory_quantity_source_guards g
 WHERE g.tenant_id=changed->>'tenant_id' AND(
 (TG_TABLE_NAME='inventory_items' AND g.item_id=changed->>'id')
 OR(TG_TABLE_NAME='inventory_units_of_measure' AND g.uom_id=changed->>'id')
 OR(TG_TABLE_NAME='inventory_locations' AND g.location_id=changed->>'id')
 OR(TG_TABLE_NAME='inventory_warehouses' AND g.warehouse_id=changed->>'id')) LOOP
  IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained native quantity interpretation cannot be deleted';END IF;
  IF TG_TABLE_NAME='inventory_items' THEN
   IF NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained quantity item scope cannot be reinterpreted';END IF;
  ELSIF TG_TABLE_NAME='inventory_warehouses' THEN
   IF NEW.legal_entity_id IS DISTINCT FROM OLD.legal_entity_id THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained quantity warehouse entity cannot be reinterpreted';END IF;
  END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_owned_expense_guard() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $quantity$
DECLARE entry RECORD;
BEGIN
 SELECT h.id,h.entry_number INTO entry FROM reconforge.finance_entries h JOIN reconforge.finance_posting_effects f
 ON f.tenant_id=h.tenant_id AND f.entry_id=h.id WHERE f.tenant_id=NEW.tenant_id AND f.id=NEW.effect_id;
 IF upper(entry.id) LIKE ANY(ARRAY['HC1-%','HC1P-%','AD1-%','AD1R-%','PB1-%','PB1C-%'])
 OR upper(entry.entry_number) LIKE ANY(ARRAY['HC1-%','HC1P-%','AD1-%','AD1R-%','PB1-%','PB1C-%']) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='An owned payroll, voucher or project effect is not a standalone manufacturing expense';END IF;
 RETURN NEW;
END $quantity$;
CREATE FUNCTION reconforge.inventory_quantity_plan_namespace_guard() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $quantity$
DECLARE entry RECORD;
BEGIN
 IF TG_TABLE_NAME='finance_entries' THEN entry:=NEW;
 ELSE SELECT h.id,h.entry_number INTO entry FROM reconforge.finance_entries h WHERE h.tenant_id=NEW.tenant_id AND h.id=NEW.entry_id;END IF;
 IF upper(entry.id) LIKE ANY(ARRAY['MSP1-%','MSP1D-%','MSP1K-%','MSP1Q-%'])
 OR upper(entry.entry_number) LIKE ANY(ARRAY['MSP1-%','MSP1D-%','MSP1K-%','MSP1Q-%']) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supply planning and quantity custody are not financial posting sources';END IF;
 RETURN NEW;
END $quantity$;
CREATE TRIGGER a_inventory_quantity_plan_namespace BEFORE INSERT OR UPDATE ON reconforge.finance_entries
 FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_plan_namespace_guard();
CREATE TRIGGER a_inventory_quantity_plan_namespace BEFORE INSERT ON reconforge.finance_posting_effects
 FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_plan_namespace_guard();
DO $quantity$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_cost_layers','inventory_layer_consumptions'] LOOP
  EXECUTE format('CREATE TRIGGER a_inventory_quantity_custody BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_native_route()',n);
  EXECUTE format('CREATE CONSTRAINT TRIGGER inventory_quantity_native_close AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_native_route()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_items','inventory_units_of_measure','inventory_locations','inventory_warehouses'] LOOP
  EXECUTE format('CREATE TRIGGER inventory_quantity_reference_guard BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_reference_guard()',n);
 END LOOP;
END $quantity$;
CREATE TRIGGER a_inventory_quantity_owned_expense BEFORE INSERT OR UPDATE ON reconforge.manufacturing_execution_v2_cost_claims
 FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_quantity_owned_expense_guard();
"""

UPGRADE_SQL += _NATIVE_SQL


DOWNGRADE_SQL = r"""
DO $quantity$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_guards)
 OR EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases)
 OR EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_plans) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained planning and native quantity custody require an explicit compatible rollback';END IF;
END $quantity$;
DO $quantity$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_cost_layers','inventory_layer_consumptions'] LOOP
  EXECUTE format('DROP TRIGGER a_inventory_quantity_custody ON reconforge.%I',n);
  EXECUTE format('DROP TRIGGER inventory_quantity_native_close ON reconforge.%I',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_items','inventory_units_of_measure','inventory_locations','inventory_warehouses'] LOOP
  EXECUTE format('DROP TRIGGER inventory_quantity_reference_guard ON reconforge.%I',n);
 END LOOP;
END $quantity$;
DROP TRIGGER a_inventory_quantity_owned_expense ON reconforge.manufacturing_execution_v2_cost_claims;
DROP TRIGGER a_inventory_quantity_plan_namespace ON reconforge.finance_entries;
DROP TRIGGER a_inventory_quantity_plan_namespace ON reconforge.finance_posting_effects;
DROP FUNCTION reconforge.inventory_quantity_plan_namespace_guard();
DROP FUNCTION reconforge.inventory_quantity_owned_expense_guard();
DROP FUNCTION reconforge.inventory_quantity_reference_guard();
DROP FUNCTION reconforge.inventory_quantity_native_route();
DROP FUNCTION reconforge.stock_sales_capacity(TEXT,TEXT,TEXT,TEXT,TEXT);
ALTER FUNCTION reconforge.stock_sales_capacity_pre_supply(TEXT,TEXT,TEXT,TEXT,TEXT) RENAME TO stock_sales_capacity;
DROP FUNCTION reconforge.inventory_quantity_check_capacity(TEXT,TEXT,TEXT,TEXT,TEXT);
DROP TABLE reconforge.inventory_quantity_source_releases;
DROP TABLE reconforge.inventory_quantity_source_guards;
DROP TABLE reconforge.inventory_quantity_claim_gates;
DROP FUNCTION reconforge.inventory_quantity_guard_birth();
DROP FUNCTION reconforge.inventory_quantity_directory_close();
DROP FUNCTION reconforge.inventory_quantity_gate_guard();
DROP FUNCTION reconforge.inventory_quantity_free_fifo(TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.touch_inventory_quantity_claim_gate(TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_quantity_source_pool_lock(TEXT,TEXT,TEXT,TEXT);
ALTER TABLE reconforge.inventory_warehouses DROP CONSTRAINT quantity_source_warehouse_tuple;
ALTER TABLE reconforge.inventory_locations DROP CONSTRAINT quantity_source_location_tuple;
ALTER TABLE reconforge.inventory_units_of_measure DROP CONSTRAINT quantity_source_uom_tuple;
ALTER TABLE reconforge.inventory_items DROP CONSTRAINT quantity_source_item_tuple;
"""

# Direct-master UPDATE/DELETE needs ROOT-owned deferred Core-only relevance guards:
# inventory_items, inventory_units_of_measure, inventory_locations/warehouses.
# Their complete active/retained guard population must preserve item/uom/scale/scope.
# Owned msp_close independently repeats exact original component metadata (code,
# inventory account, base UOM, scale, tracking and hierarchy), including no-movement
# Draft/Approved planners. No original source financial account is reinterpreted.
# FIFO-only callers use location=NULL, never a physical empty-string key. Existing
# physical-before-FIFO lock order remains; acquire all sorted pools first for batch
# owners, then bump gates. Native opposing interleavings are REQUIRED, not certified.
# Native mutation route must inspect Core metadata before any private MSP lookup;
# zero active guards does not skip the gate bump (stale RR admission fence).
# A new quantity guard is exclusive unallocated FIFO custody only, not an exact
# bought-layer claim. Receipt_plan_id retains provenance, while handoff costs the
# current original native FIFO selection. Source receipt cancellation is refused
# until custody releases/handoffs; no assumption of layer survival from onhand alone.
