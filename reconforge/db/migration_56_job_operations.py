"""Frozen SQLite migration for least-privilege durable-job operations."""

SQLITE_JOB_OPERATIONS_UPGRADE_SQL = """
INSERT OR IGNORE INTO permissions(name,description)
 VALUES('jobs.manage','Cancel unleased jobs or requeue failed/paused work with reviewed version and retained evidence.');
INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
 SELECT id,'jobs.manage' FROM roles WHERE name='admin';
CREATE INDEX IF NOT EXISTS durable_jobs_operator_lane_id
 ON durable_jobs(tenant_id,workspace_id,organization_id,entity_id,id);
CREATE INDEX IF NOT EXISTS durable_jobs_operator_lane_status_id
 ON durable_jobs(tenant_id,workspace_id,organization_id,entity_id,status,id);
"""
