"""Notification inbox schemas: immutable publications and append-only read evidence."""

SQLITE_NOTIFICATION_INBOX_SQL = r"""
CREATE TABLE notification_inbox (
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL CHECK(length(tenant_id) BETWEEN 1 AND 160),
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) CHECK(length(workspace_id) BETWEEN 1 AND 160),
 organization_id TEXT NOT NULL DEFAULT '', legal_entity_id TEXT NOT NULL DEFAULT '',
 recipient_id TEXT NOT NULL REFERENCES users(id),
 publisher_id TEXT NOT NULL REFERENCES users(id),
 topic TEXT NOT NULL CHECK(topic IN ('workflow.review_required','job.failed','control.exception_opened','evidence.available')),
 resource_type TEXT NOT NULL CHECK(length(resource_type) BETWEEN 1 AND 160),
 resource_id TEXT NOT NULL CHECK(length(resource_id) BETWEEN 1 AND 160),
 idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 160),
 payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
 created_at TEXT NOT NULL,
 CHECK(legal_entity_id='' OR organization_id<>''),
 UNIQUE(tenant_id,workspace_id,publisher_id,idempotency_key),
 UNIQUE(tenant_id,workspace_id,id,recipient_id)
);
CREATE TABLE notification_inbox_reads (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 notification_id TEXT NOT NULL, recipient_id TEXT NOT NULL, read_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,notification_id,recipient_id),
 FOREIGN KEY(tenant_id,workspace_id,notification_id,recipient_id)
 REFERENCES notification_inbox(tenant_id,workspace_id,id,recipient_id)
);
CREATE INDEX notification_inbox_recipient_page ON notification_inbox
 (tenant_id,workspace_id,recipient_id,created_at DESC,id DESC);
CREATE TRIGGER notification_inbox_admission BEFORE INSERT ON notification_inbox
 WHEN (NEW.organization_id<>'' AND NOT EXISTS(SELECT 1 FROM organizations o
 WHERE o.id=NEW.organization_id AND o.workspace_id=NEW.workspace_id AND o.active=1))
 OR (NEW.legal_entity_id<>'' AND NOT EXISTS(SELECT 1 FROM legal_entities e
 WHERE e.id=NEW.legal_entity_id AND e.organization_id=NEW.organization_id AND e.active=1))
 OR NOT EXISTS(SELECT 1 FROM users u WHERE u.id=NEW.recipient_id AND u.disabled=0)
 OR NOT EXISTS(SELECT 1 FROM users u WHERE u.id=NEW.publisher_id AND u.disabled=0)
 BEGIN SELECT RAISE(ABORT,'Notification canonical scope or active identity is unavailable.'); END;
CREATE TRIGGER notification_inbox_immutable_update BEFORE UPDATE ON notification_inbox
 BEGIN SELECT RAISE(ABORT,'Notification publication is immutable.'); END;
CREATE TRIGGER notification_inbox_immutable_delete BEFORE DELETE ON notification_inbox
 BEGIN SELECT RAISE(ABORT,'Notification publication is retained evidence.'); END;
CREATE TRIGGER notification_inbox_reads_immutable_update BEFORE UPDATE ON notification_inbox_reads
 BEGIN SELECT RAISE(ABORT,'Notification read evidence is append-only.'); END;
CREATE TRIGGER notification_inbox_reads_immutable_delete BEFORE DELETE ON notification_inbox_reads
 BEGIN SELECT RAISE(ABORT,'Notification read evidence is append-only.'); END;
INSERT OR IGNORE INTO permissions(name,description) VALUES
 ('notifications.read','Read and acknowledge own operational notification inbox'),
 ('notifications.publish','Publish bounded operational notifications to active users');
INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
 SELECT id,'notifications.read' FROM roles WHERE name IN ('admin','controller','preparer','reviewer','auditor-readonly');
INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
 SELECT id,'notifications.publish' FROM roles WHERE name='admin';
"""

POSTGRES_NOTIFICATION_INBOX_SQL = r"""
CREATE TABLE reconforge.notification_inbox (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL,
 workspace_id TEXT NOT NULL, organization_id TEXT NOT NULL DEFAULT '', legal_entity_id TEXT NOT NULL DEFAULT '',
 recipient_id TEXT NOT NULL, publisher_id TEXT NOT NULL,
 topic TEXT NOT NULL CHECK(topic IN ('workflow.review_required','job.failed','control.exception_opened','evidence.available')),
 resource_type TEXT NOT NULL CHECK(resource_type ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
 resource_id TEXT NOT NULL CHECK(resource_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
 idempotency_key TEXT NOT NULL CHECK(idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
 payload_digest TEXT NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
 created_at TIMESTAMPTZ NOT NULL,
 CHECK(legal_entity_id='' OR organization_id<>''),
 PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,publisher_id,idempotency_key),
 UNIQUE(tenant_id,workspace_id,id,recipient_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,recipient_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,publisher_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.notification_inbox_reads (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 notification_id TEXT NOT NULL, recipient_id TEXT NOT NULL, read_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,notification_id,recipient_id),
 FOREIGN KEY(tenant_id,workspace_id,notification_id,recipient_id)
 REFERENCES reconforge.notification_inbox(tenant_id,workspace_id,id,recipient_id)
);
CREATE INDEX notification_inbox_recipient_page ON reconforge.notification_inbox
 (tenant_id,workspace_id,recipient_id,created_at DESC,id DESC);
CREATE FUNCTION reconforge.inbox_can_act(t TEXT,w TEXT,o TEXT,e TEXT,u TEXT,p TEXT) RETURNS BOOLEAN
 LANGUAGE SQL STABLE SET search_path=pg_catalog AS $inbox$
 SELECT EXISTS(SELECT 1 FROM reconforge.identity_users x
 JOIN reconforge.identity_user_roles ur ON ur.tenant_id=x.tenant_id AND ur.user_id=x.id AND ur.active
 JOIN reconforge.identity_roles r ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id AND r.active
 JOIN reconforge.identity_role_permissions rp ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active AND rp.permission_name=p
 WHERE x.tenant_id=t AND x.id=u AND NOT x.disabled)
 AND EXISTS(SELECT 1 FROM reconforge.principal_scope_grants g WHERE g.tenant_id=t AND g.principal_type='user'
 AND g.principal_id=u AND g.scope_type='workspace' AND g.scope_id=w AND g.revoked_at IS NULL)
 AND (o='' OR EXISTS(SELECT 1 FROM reconforge.principal_scope_grants g WHERE g.tenant_id=t AND g.principal_type='user'
 AND g.principal_id=u AND g.scope_type='organization' AND g.scope_id=o AND g.revoked_at IS NULL))
 AND (e='' OR EXISTS(SELECT 1 FROM reconforge.principal_scope_grants g WHERE g.tenant_id=t AND g.principal_type='user'
 AND g.principal_id=u AND g.scope_type='legal_entity' AND g.scope_id=e AND g.revoked_at IS NULL));
 $inbox$;
CREATE FUNCTION reconforge.guard_notification_inbox_admission() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $inbox$
BEGIN
 IF NOT reconforge.inbox_can_act(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.publisher_id,'notifications.publish')
 OR NOT reconforge.inbox_can_act(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.recipient_id,'notifications.read')
 OR (NEW.organization_id<>'' AND NOT EXISTS(SELECT 1 FROM reconforge.organizations o
 JOIN reconforge.master_data_workspace_organizations m ON m.tenant_id=o.tenant_id AND m.organization_id=o.id
 WHERE o.tenant_id=NEW.tenant_id AND o.id=NEW.organization_id AND o.active AND m.workspace_id=NEW.workspace_id))
 OR (NEW.legal_entity_id<>'' AND NOT EXISTS(SELECT 1 FROM reconforge.legal_entities e
 WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.legal_entity_id AND e.organization_id=NEW.organization_id AND e.active))
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Notification canonical scope or current authority is unavailable.'; END IF;
 RETURN NEW;
END $inbox$;
CREATE TRIGGER notification_inbox_admission BEFORE INSERT ON reconforge.notification_inbox
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_notification_inbox_admission();
CREATE FUNCTION reconforge.guard_notification_inbox() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $inbox$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Notification evidence is append-only.'; END $inbox$;
CREATE TRIGGER notification_inbox_immutable BEFORE UPDATE OR DELETE ON reconforge.notification_inbox
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_notification_inbox();
CREATE TRIGGER notification_inbox_reads_immutable BEFORE UPDATE OR DELETE ON reconforge.notification_inbox_reads
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_notification_inbox();
ALTER TABLE reconforge.notification_inbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.notification_inbox FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.notification_inbox_reads ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.notification_inbox_reads FORCE ROW LEVEL SECURITY;
CREATE POLICY inbox_scope ON reconforge.notification_inbox
 USING (tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true))
 AND ((recipient_id=current_setting('app.inbox_actor_id',true)
 AND reconforge.inbox_can_act(tenant_id,workspace_id,organization_id,legal_entity_id,recipient_id,'notifications.read'))
 OR (current_setting('app.inbox_publish',true)='1' AND publisher_id=current_setting('app.inbox_actor_id',true))))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND organization_id=COALESCE(current_setting('app.organization_id',true),'')
 AND legal_entity_id=COALESCE(current_setting('app.legal_entity_id',true),'')
 AND current_setting('app.inbox_publish',true)='1' AND publisher_id=current_setting('app.inbox_actor_id',true));
CREATE POLICY inbox_read_scope ON reconforge.notification_inbox_reads
 USING (tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND recipient_id=current_setting('app.inbox_actor_id',true)
 AND EXISTS(SELECT 1 FROM reconforge.notification_inbox n WHERE n.tenant_id=notification_inbox_reads.tenant_id
 AND n.id=notification_inbox_reads.notification_id AND n.recipient_id=notification_inbox_reads.recipient_id))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND recipient_id=current_setting('app.inbox_actor_id',true)
 AND EXISTS(SELECT 1 FROM reconforge.notification_inbox n WHERE n.tenant_id=notification_inbox_reads.tenant_id
 AND n.id=notification_inbox_reads.notification_id AND n.recipient_id=notification_inbox_reads.recipient_id
 AND reconforge.inbox_can_act(n.tenant_id,n.workspace_id,n.organization_id,n.legal_entity_id,n.recipient_id,'notifications.read')));
INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT t.id,p.name,p.description FROM reconforge.tenants t CROSS JOIN (VALUES
 ('notifications.read','Read and acknowledge own operational notification inbox'),
 ('notifications.publish','Publish bounded operational notifications to active users')) p(name,description)
 ON CONFLICT(tenant_id,name) DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
 SELECT tenant_id,id,'notifications.read' FROM reconforge.identity_roles
 WHERE name IN ('admin','controller','preparer','reviewer','auditor-readonly') ON CONFLICT DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
 SELECT tenant_id,id,'notifications.publish' FROM reconforge.identity_roles WHERE name='admin' ON CONFLICT DO NOTHING;
"""
