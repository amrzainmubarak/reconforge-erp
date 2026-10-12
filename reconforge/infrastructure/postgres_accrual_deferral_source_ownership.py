"""Additive AD1 ownership in the existing Financial Core directory.

Existing ME2 owner closure and the serialized
gate function remain byte-exact. Only directory dispatch/FKs are extended.
Install after owned AD1 tables/functions. Revert this fragment before them.
"""

from reconforge.infrastructure.postgres_financial_source_ownership import UPGRADE_SQL as ORIGINAL_SQL

REVIEWED_CORE_SOURCE_SHA256 = "ab28e31cc81859b228421297ea49f61081bb6fef496ee2df431e75a642966802"


def definition(name: str) -> str:
    start = ORIGINAL_SQL.index("CREATE FUNCTION reconforge." + name + "(")
    end = ORIGINAL_SQL.index("END $ownership$;", start) + len("END $ownership$;")
    return ORIGINAL_SQL[start:end]


def replace_once(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("Root-owned source anchor changed; proposal must be reviewed again")
    return value.replace(old, new, 1)


old_directory = definition("financial_source_directory_guard")
directory = old_directory.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
directory = replace_once(directory,
    "  SELECT * INTO claim FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=NEW.tenant_id AND id=NEW.owner_claim_id;",
    """  PERFORM reconforge.financial_source_assert(NOT EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_guards other
   WHERE other.tenant_id=NEW.tenant_id AND other.source_effect_id=NEW.source_effect_id
    AND (NEW.owner_namespace='AD1' OR other.owner_namespace='AD1')
    AND NOT EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_releases released
     WHERE released.tenant_id=other.tenant_id AND released.guard_id=other.id)),
   'Whole-original AD1 and active operating ownership are mutually exclusive under one financial source gate');
  IF NEW.owner_namespace='AD1' THEN
   SELECT * INTO claim FROM reconforge.accrual_deferral_original_claims WHERE tenant_id=NEW.tenant_id AND id=NEW.owner_claim_id;
  ELSE
   SELECT * INTO claim FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=NEW.tenant_id AND id=NEW.owner_claim_id;
  END IF;""")
directory = replace_once(directory,
    "  SELECT * INTO owned_release FROM reconforge.manufacturing_execution_v2_cost_releases WHERE tenant_id=NEW.tenant_id AND id=NEW.release_id;",
    """  NEW.owner_namespace:=directory.owner_namespace;
  IF directory.owner_namespace='AD1' THEN
   SELECT * INTO owned_release FROM reconforge.accrual_deferral_original_releases WHERE tenant_id=NEW.tenant_id AND id=NEW.release_id;
   PERFORM reconforge.financial_source_assert(owned_release.id IS NOT NULL AND EXISTS(
    SELECT 1 FROM reconforge.accrual_deferral_plans p WHERE p.tenant_id=NEW.tenant_id AND p.id=owned_release.cancellation_plan_id
     AND p.source_id=owned_release.source_id AND p.kind='cancel' AND p.phase=2)
    AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events e
     JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=e.tenant_id AND p.id=e.plan_id
     WHERE p.tenant_id=NEW.tenant_id AND p.source_id=owned_release.source_id AND e.posting_effect_id IS NOT NULL),
    'AD1 directory release needs the exact posted non-financial cancellation and no consumed voucher');
  ELSE
   SELECT * INTO owned_release FROM reconforge.manufacturing_execution_v2_cost_releases WHERE tenant_id=NEW.tenant_id AND id=NEW.release_id;
  END IF;""")

old_deferred = definition("financial_source_directory_deferred")
deferred = old_deferred.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
deferred = replace_once(deferred,
    "ELSIF TG_TABLE_NAME='manufacturing_execution_v2_cost_claims' THEN selected_claim:=NEW.id;",
    "ELSIF TG_TABLE_NAME IN('manufacturing_execution_v2_cost_claims','accrual_deferral_original_claims') THEN selected_claim:=NEW.id;")
deferred = replace_once(deferred,
    " PERFORM reconforge.financial_source_claim_close(NEW.tenant_id,selected_claim);RETURN NEW;",
    """ IF TG_TABLE_NAME IN('accrual_deferral_original_claims','accrual_deferral_original_releases')
  OR to_jsonb(NEW)->>'owner_namespace'='AD1' THEN
  PERFORM reconforge.financial_source_ad1_claim_close(NEW.tenant_id,selected_claim);
 ELSE
  PERFORM reconforge.financial_source_claim_close(NEW.tenant_id,selected_claim);
 END IF;RETURN NEW;""")

DDL = r"""
ALTER TABLE reconforge.financial_effect_ownership_guards
 DROP CONSTRAINT financial_effect_ownership_guards_owner_namespace_check,
 DROP CONSTRAINT financial_effect_ownership_guards_tenant_id_owner_claim_id_fkey,
 ADD CONSTRAINT financial_effect_owner_namespace CHECK(owner_namespace IN('ME2','AD1')),
 ADD COLUMN me2_owner_claim_id TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='ME2' THEN owner_claim_id END) STORED,
 ADD COLUMN ad1_owner_claim_id TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='AD1' THEN owner_claim_id END) STORED,
 ADD CONSTRAINT financial_effect_guard_namespace UNIQUE(tenant_id,id,owner_namespace),
 ADD CONSTRAINT financial_effect_me2_owner FOREIGN KEY(tenant_id,me2_owner_claim_id)
  REFERENCES reconforge.manufacturing_execution_v2_cost_claims(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 ADD CONSTRAINT financial_effect_ad1_owner FOREIGN KEY(tenant_id,ad1_owner_claim_id)
  REFERENCES reconforge.accrual_deferral_original_claims(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reconforge.financial_effect_ownership_releases
 DROP CONSTRAINT financial_effect_ownership_releases_tenant_id_release_id_fkey,
 ADD COLUMN owner_namespace TEXT NOT NULL DEFAULT 'ME2' CHECK(owner_namespace IN('ME2','AD1')),
 ADD COLUMN me2_release_id TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='ME2' THEN release_id END) STORED,
 ADD COLUMN ad1_release_id TEXT GENERATED ALWAYS AS(CASE WHEN owner_namespace='AD1' THEN release_id END) STORED,
 ADD CONSTRAINT financial_effect_release_namespace FOREIGN KEY(tenant_id,guard_id,owner_namespace)
  REFERENCES reconforge.financial_effect_ownership_guards(tenant_id,id,owner_namespace) DEFERRABLE INITIALLY DEFERRED,
 ADD CONSTRAINT financial_effect_me2_release FOREIGN KEY(tenant_id,me2_release_id)
  REFERENCES reconforge.manufacturing_execution_v2_cost_releases(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 ADD CONSTRAINT financial_effect_ad1_release FOREIGN KEY(tenant_id,ad1_release_id)
  REFERENCES reconforge.accrual_deferral_original_releases(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION reconforge.financial_source_ad1_claim_close(t TEXT,claim_id TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE claim RECORD;directory RECORD;released RECORD;directory_release RECORD;
BEGIN
 SELECT * INTO claim FROM reconforge.accrual_deferral_original_claims c WHERE c.tenant_id=t AND c.id=$2;
 SELECT * INTO directory FROM reconforge.financial_effect_ownership_guards g WHERE g.tenant_id=t AND g.id=$2 AND g.owner_namespace='AD1';
 PERFORM reconforge.financial_source_assert(claim.id IS NOT NULL AND directory.id=claim.id AND directory.owner_claim_id=claim.id
  AND directory.source_effect_id=claim.effect_id
  AND(directory.workspace_id,directory.organization_id,directory.legal_entity_id)=(claim.workspace_id,claim.organization_id,claim.legal_entity_id),
  'Every whole-original AD1 claim retains its exact conditional source owner');
 SELECT * INTO released FROM reconforge.accrual_deferral_original_releases r WHERE r.tenant_id=t AND r.claim_id=claim.id;
 SELECT * INTO directory_release FROM reconforge.financial_effect_ownership_releases r WHERE r.tenant_id=t AND r.guard_id=directory.id;
 PERFORM reconforge.financial_source_assert((claim.state='Released' AND released.id IS NOT NULL AND released.source_id=claim.source_id
  AND directory_release.release_id=released.id AND directory_release.owner_namespace='AD1')
  OR(claim.state IN('Reserved','Consumed') AND released.id IS NULL AND directory_release.guard_id IS NULL),
  'Exact AD1 cancellation release and shared directory state close atomically');
 IF claim.state<>'Released' THEN PERFORM reconforge.financial_source_assert(NOT EXISTS(
  SELECT 1 FROM reconforge.financial_effect_ownership_guards other WHERE other.tenant_id=t AND other.source_effect_id=claim.effect_id AND other.id<>directory.id
   AND NOT EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_releases r WHERE r.tenant_id=other.tenant_id AND r.guard_id=other.id)),
  'Active whole-original AD1 ownership excludes every other active financial source');END IF;
 PERFORM reconforge.ad1_source_close(t,claim.source_id);
END $ownership$;
CREATE CONSTRAINT TRIGGER financial_source_close AFTER INSERT OR UPDATE ON reconforge.accrual_deferral_original_claims
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_deferred();
CREATE CONSTRAINT TRIGGER financial_source_close AFTER INSERT ON reconforge.accrual_deferral_original_releases
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_deferred();
"""

UPGRADE_SQL = DDL + "\n" + directory + "\n" + deferred
DOWNGRADE_SQL = r"""
DO $ownership$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_guards WHERE owner_namespace='AD1')
  OR EXISTS(SELECT 1 FROM reconforge.accrual_deferral_sources) THEN
  RAISE EXCEPTION 'Populated AD1 ownership requires restore; destructive downgrade refused';
 END IF;
END $ownership$;
DROP TRIGGER financial_source_close ON reconforge.accrual_deferral_original_releases;
DROP TRIGGER financial_source_close ON reconforge.accrual_deferral_original_claims;
DROP FUNCTION reconforge.financial_source_ad1_claim_close(TEXT,TEXT);
ALTER TABLE reconforge.financial_effect_ownership_releases
 DROP CONSTRAINT financial_effect_ad1_release,DROP CONSTRAINT financial_effect_me2_release,DROP CONSTRAINT financial_effect_release_namespace,
 DROP COLUMN ad1_release_id,DROP COLUMN me2_release_id,DROP COLUMN owner_namespace,
 ADD FOREIGN KEY(tenant_id,release_id) REFERENCES reconforge.manufacturing_execution_v2_cost_releases(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reconforge.financial_effect_ownership_guards
 DROP CONSTRAINT financial_effect_ad1_owner,DROP CONSTRAINT financial_effect_me2_owner,DROP CONSTRAINT financial_effect_guard_namespace,
 DROP CONSTRAINT financial_effect_owner_namespace,DROP COLUMN ad1_owner_claim_id,DROP COLUMN me2_owner_claim_id,
 ADD CHECK(owner_namespace='ME2'),
 ADD FOREIGN KEY(tenant_id,owner_claim_id) REFERENCES reconforge.manufacturing_execution_v2_cost_claims(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
""" + "\n" + old_directory.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) + "\n" + old_deferred.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
