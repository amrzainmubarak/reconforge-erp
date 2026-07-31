"""Keep sensitive PostgreSQL audit administration human-governed."""

from __future__ import annotations

from alembic import op

revision = "0053_audit_administration_acl"
down_revision = "0052_security_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Deny future service-account grants without deleting existing permissions.

    Existing installations may already contain ``audit.read`` grants.  A NOT
    VALID constraint preserves upgrade availability while enforcing the new
    rule for every inserted or changed row.  Runtime central policy denies old
    grants until an operator remediates them.
    """

    op.execute(
        """
        ALTER TABLE reconforge.service_account_permissions
          DROP CONSTRAINT IF EXISTS service_account_permissions_human_only;
        ALTER TABLE reconforge.service_account_permissions
          ADD CONSTRAINT service_account_permissions_human_only CHECK (
            permission_name NOT IN (
              'roles.manage','users.manage','service_accounts.manage','security.emergency',
              'security.policy.manage','security.center.read','audit.read','audit.verify',
              'finance_core.manage','close.manage'
            )
          ) NOT VALID;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE reconforge.service_account_permissions
          DROP CONSTRAINT IF EXISTS service_account_permissions_human_only;
        ALTER TABLE reconforge.service_account_permissions
          ADD CONSTRAINT service_account_permissions_human_only CHECK (
            permission_name NOT IN (
              'roles.manage','users.manage','service_accounts.manage','security.emergency',
              'security.policy.manage','security.center.read','finance_core.manage','close.manage'
            )
          ) NOT VALID;
        """
    )
