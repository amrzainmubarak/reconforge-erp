"""Add WebAuthn MFA challenges, public credentials, and assurance evidence."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_WEBAUTHN_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_webauthn", "POSTGRES_WEBAUTHN_SCHEMA_SQL"
)

revision = "0040_postgres_webauthn_mfa"
down_revision = "0039_postgres_emergency_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_WEBAUTHN_SCHEMA_SQL)
    op.execute("ALTER TABLE reconforge.identity_step_up_assertions DROP CONSTRAINT identity_step_up_assertions_method_check")
    op.execute(
        "ALTER TABLE reconforge.identity_step_up_assertions ADD CONSTRAINT identity_step_up_assertions_method_check "
        "CHECK (method IN ('password_reauthentication','webauthn_user_verified'))"
    )
    op.execute("ALTER TABLE reconforge.identity_step_up_assertions ADD COLUMN credential_id TEXT")
    op.execute(
        "ALTER TABLE reconforge.identity_step_up_assertions ADD CONSTRAINT identity_step_up_assertions_webauthn_credential_fk "
        "FOREIGN KEY (tenant_id,credential_id) REFERENCES reconforge.identity_webauthn_credentials(tenant_id,credential_id)"
    )
    op.execute(
        "ALTER TABLE reconforge.identity_step_up_assertions ADD CONSTRAINT identity_step_up_assertions_method_credential_check "
        "CHECK ((method='webauthn_user_verified')=(credential_id IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE reconforge.identity_step_up_assertions "
        "DISABLE TRIGGER identity_step_up_assertions_append_only"
    )
    op.execute("DELETE FROM reconforge.identity_step_up_assertions WHERE method='webauthn_user_verified'")
    op.execute(
        "ALTER TABLE reconforge.identity_step_up_assertions "
        "ENABLE TRIGGER identity_step_up_assertions_append_only"
    )
    op.execute("ALTER TABLE reconforge.identity_step_up_assertions DROP CONSTRAINT identity_step_up_assertions_method_credential_check")
    op.execute("ALTER TABLE reconforge.identity_step_up_assertions DROP CONSTRAINT identity_step_up_assertions_webauthn_credential_fk")
    op.execute("ALTER TABLE reconforge.identity_step_up_assertions DROP COLUMN credential_id")
    op.execute("ALTER TABLE reconforge.identity_step_up_assertions DROP CONSTRAINT identity_step_up_assertions_method_check")
    op.execute(
        "ALTER TABLE reconforge.identity_step_up_assertions ADD CONSTRAINT identity_step_up_assertions_method_check "
        "CHECK (method='password_reauthentication')"
    )
    op.execute("DROP TABLE IF EXISTS reconforge.identity_webauthn_events")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_webauthn_challenges")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_webauthn_credentials")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_webauthn_credential_update()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_webauthn_challenge_update()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_webauthn_event_mutation()")
