"""Immutable, audited creator/reviewer authority for new NCR records only."""

from __future__ import annotations

import sqlite3

SQLITE_UPGRADE_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS quality_ncr_scope_identity ON quality_ncrs(workspace_id,ncr_id);
CREATE TABLE IF NOT EXISTS quality_ncr_actor_authorities (
 workspace_id TEXT NOT NULL,ncr_id TEXT NOT NULL,
 authority_kind TEXT NOT NULL CHECK(authority_kind IN('creator','reviewer')),
 user_id TEXT NOT NULL,actor_label TEXT NOT NULL,
 identity_contract TEXT NOT NULL CHECK(identity_contract='canonical-user-v1'),
 audit_event_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL DEFAULT(datetime('now')),
 PRIMARY KEY(workspace_id,ncr_id,authority_kind),
 FOREIGN KEY(workspace_id,ncr_id) REFERENCES quality_ncrs(workspace_id,ncr_id),
 FOREIGN KEY(user_id) REFERENCES users(id),FOREIGN KEY(audit_event_id) REFERENCES audit_events(id)
);
CREATE TRIGGER IF NOT EXISTS quality_ncr_authority_no_update
 BEFORE UPDATE ON quality_ncr_actor_authorities BEGIN SELECT RAISE(ABORT,'NCR authority is immutable'); END;
CREATE TRIGGER IF NOT EXISTS quality_ncr_authority_no_delete
 BEFORE DELETE ON quality_ncr_actor_authorities BEGIN SELECT RAISE(ABORT,'NCR authority is immutable'); END;
CREATE TRIGGER IF NOT EXISTS quality_ncr_authority_insert_guard
 BEFORE INSERT ON quality_ncr_actor_authorities BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM audit_events a WHERE a.id=NEW.audit_event_id AND a.actor_user_id=NEW.user_id
   AND a.actor_label=NEW.actor_label AND a.object_type='quality.ncr' AND a.object_id=NEW.ncr_id
   AND a.action=CASE NEW.authority_kind WHEN 'creator' THEN 'quality_ncr_recorded' ELSE 'quality_ncr_dispositioned' END
   AND json_extract(a.metadata_json,'$.workspace_id')=NEW.workspace_id
   AND json_extract(a.metadata_json,'$.identity_contract')='canonical-user-v1'
 ) THEN RAISE(ABORT,'NCR authority requires its original actor audit event') END;
 SELECT CASE WHEN NEW.authority_kind='reviewer' AND NOT EXISTS(
  SELECT 1 FROM quality_ncr_actor_authorities c WHERE c.workspace_id=NEW.workspace_id
   AND c.ncr_id=NEW.ncr_id AND c.authority_kind='creator' AND c.user_id<>NEW.user_id
 ) THEN RAISE(ABORT,'Independent NCR reviewer authority is required') END;
END;
"""

POSTGRES_UPGRADE_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.quality_ncr_actor_authorities (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,ncr_id TEXT NOT NULL,
 authority_kind TEXT NOT NULL CHECK(authority_kind IN('creator','reviewer')),
 user_id TEXT NOT NULL,actor_label TEXT NOT NULL,
 identity_contract TEXT NOT NULL CHECK(identity_contract='canonical-user-v1'),
 audit_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,workspace_id,ncr_id,authority_kind),UNIQUE(tenant_id,audit_event_id),
 FOREIGN KEY(tenant_id,workspace_id,ncr_id) REFERENCES reconforge.quality_ncrs(tenant_id,workspace_id,ncr_id),
 FOREIGN KEY(tenant_id,user_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id)
);
ALTER TABLE reconforge.quality_ncr_actor_authorities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_ncr_actor_authorities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_ncr_actor_authorities;
CREATE POLICY tenant_scope ON reconforge.quality_ncr_actor_authorities
 USING(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true));
CREATE OR REPLACE FUNCTION reconforge.quality_ncr_actor_authority_guard() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='NCR authority is immutable'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a
  WHERE a.tenant_id=NEW.tenant_id AND a.id=NEW.audit_event_id AND a.actor_user_id=NEW.user_id
   AND a.actor_label=NEW.actor_label AND a.object_type='quality.ncr' AND a.object_id=NEW.ncr_id
   AND a.action=CASE NEW.authority_kind WHEN 'creator' THEN 'quality_ncr_recorded' ELSE 'quality_ncr_dispositioned' END
   AND a.metadata_json->>'workspace_id'=NEW.workspace_id
   AND a.metadata_json->>'identity_contract'='canonical-user-v1') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='NCR authority requires its original actor audit event'; END IF;
 IF NEW.authority_kind='reviewer' AND NOT EXISTS(
  SELECT 1 FROM reconforge.quality_ncr_actor_authorities c
  WHERE c.tenant_id=NEW.tenant_id AND c.workspace_id=NEW.workspace_id AND c.ncr_id=NEW.ncr_id
   AND c.authority_kind='creator' AND c.user_id<>NEW.user_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Independent NCR reviewer authority is required'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS quality_ncr_actor_authority_guard ON reconforge.quality_ncr_actor_authorities;
CREATE TRIGGER quality_ncr_actor_authority_guard BEFORE INSERT OR UPDATE OR DELETE
 ON reconforge.quality_ncr_actor_authorities FOR EACH ROW EXECUTE FUNCTION reconforge.quality_ncr_actor_authority_guard();
"""

POSTGRES_DOWNGRADE_SQL = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.quality_ncr_actor_authorities) THEN
  RAISE EXCEPTION 'Populated NCR authority prevents downgrade; retain data and use forward recovery';
 END IF;
END $$;
DROP TABLE reconforge.quality_ncr_actor_authorities;
DROP FUNCTION reconforge.quality_ncr_actor_authority_guard();
"""


def execute_quality_actor_schema(connection: sqlite3.Connection) -> None:
    """Execute the fixed owned DDL including triggers without an implicit commit."""
    statement = ""
    for line in SQLITE_UPGRADE_SQL.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise sqlite3.DatabaseError("Incomplete quality actor schema statement")
