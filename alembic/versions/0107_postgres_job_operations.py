"""Least-privilege operator access and bounded durable-job inspection indexes."""

from alembic import op

revision = "0107_pg_job_operations"
down_revision = "0106_pg_ap_link_reversal"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
DO $jobs$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'job operations migration requires bypass of forced row security';
 END IF;
END $jobs$;
LOCK TABLE reconforge.tenants,reconforge.identity_roles,reconforge.identity_permissions,
 reconforge.identity_role_permissions IN SHARE ROW EXCLUSIVE MODE;
INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT id,'jobs.manage','Cancel unleased jobs or requeue failed/paused work with reviewed version and retained evidence.'
 FROM reconforge.tenants ON CONFLICT DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
 SELECT tenant_id,id,'jobs.manage' FROM reconforge.identity_roles WHERE name='admin' ON CONFLICT DO NOTHING;
CREATE FUNCTION reconforge.seed_job_operations_permission() RETURNS trigger
 LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $jobs$
BEGIN
 IF TG_TABLE_NAME='tenants' THEN
  INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES
   (NEW.id,'jobs.manage','Cancel unleased jobs or requeue failed/paused work with reviewed version and retained evidence.')
  ON CONFLICT DO NOTHING;
 ELSIF TG_TABLE_NAME='identity_roles' AND NEW.name='admin' THEN
  INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
   VALUES(NEW.tenant_id,NEW.id,'jobs.manage') ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $jobs$;
CREATE TRIGGER job_operations_permission_tenant_seed AFTER INSERT ON reconforge.tenants
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_job_operations_permission();
CREATE TRIGGER job_operations_permission_role_seed AFTER INSERT ON reconforge.identity_roles
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_job_operations_permission();
CREATE INDEX durable_jobs_operator_lane_id ON reconforge.durable_jobs
 (tenant_id,workspace_id,(COALESCE(organization_id,'')),entity_id,id COLLATE "C");
CREATE INDEX durable_jobs_operator_lane_status_id ON reconforge.durable_jobs
 (tenant_id,workspace_id,(COALESCE(organization_id,'')),entity_id,status,id COLLATE "C");
"""

DOWNGRADE_SQL = r"""
DO $jobs$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'job operations downgrade requires bypass of forced row security';
 END IF;
END $jobs$;
LOCK TABLE reconforge.identity_roles,reconforge.identity_permissions,reconforge.identity_role_permissions
 IN SHARE ROW EXCLUSIVE MODE;
DO $jobs$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.identity_role_permissions p JOIN reconforge.identity_roles r
 ON r.tenant_id=p.tenant_id AND r.id=p.role_id WHERE p.permission_name='jobs.manage' AND r.name<>'admin') THEN
  RAISE EXCEPTION 'job operations downgrade refuses to discard nondefault permission grants';
 END IF;
END $jobs$;
DROP TRIGGER job_operations_permission_tenant_seed ON reconforge.tenants;
DROP TRIGGER job_operations_permission_role_seed ON reconforge.identity_roles;
DROP FUNCTION reconforge.seed_job_operations_permission();
DELETE FROM reconforge.identity_role_permissions WHERE permission_name='jobs.manage';
DELETE FROM reconforge.identity_permissions WHERE name='jobs.manage';
DROP INDEX reconforge.durable_jobs_operator_lane_id;
DROP INDEX reconforge.durable_jobs_operator_lane_status_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
