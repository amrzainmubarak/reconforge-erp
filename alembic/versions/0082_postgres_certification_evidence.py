"""Bind close certifications to a replay-verified evidence bundle digest."""

from alembic import op
from reconforge.infrastructure.postgres_approvals import (
    POSTGRES_CERTIFICATION_EVIDENCE_MIGRATION_SQL,
)

revision = "0082_pg_cert_evidence"
down_revision = "0081_pg_prof_invoice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CERTIFICATION_EVIDENCE_MIGRATION_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM reconforge.certification_records
                WHERE evidence_digest <> ''
            ) THEN
                RAISE EXCEPTION 'refusing to discard certification evidence bindings';
            END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS certification_records_guard
            ON reconforge.certification_records;
        ALTER TABLE reconforge.certification_records
            DROP COLUMN IF EXISTS evidence_digest;
        CREATE OR REPLACE FUNCTION reconforge.certification_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
         IF TG_OP='INSERT' AND (NEW.status<>'Prepared' OR NEW.prepared_by='' OR NEW.reviewed_by<>'' OR NEW.reviewed_at IS NOT NULL) THEN RAISE EXCEPTION 'certification metadata must be prepared before review'; END IF;
         IF TG_OP='UPDATE' AND OLD.status='Reviewed' THEN RAISE EXCEPTION 'reviewed certification metadata is immutable'; END IF;
         IF TG_OP='UPDATE' AND (NEW.object_type,NEW.object_id,NEW.period_name,NEW.entity_code,NEW.prepared_by,NEW.prepared_at,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.object_type,OLD.object_id,OLD.period_name,OLD.entity_code,OLD.prepared_by,OLD.prepared_at,OLD.created_by,OLD.created_at) THEN RAISE EXCEPTION 'prepared certification scope and preparer evidence are immutable'; END IF;
         IF TG_OP='UPDATE' AND (NEW.status<>'Reviewed' OR NEW.reviewed_by='' OR NEW.reviewed_at IS NULL OR lower(trim(NEW.reviewed_by))=lower(trim(OLD.prepared_by))) THEN RAISE EXCEPTION 'certification review requires separation of duties'; END IF;
         IF TG_OP='DELETE' THEN RAISE EXCEPTION 'certification metadata history is immutable'; END IF;
         RETURN NEW;
        END $$;
        CREATE TRIGGER certification_records_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.certification_records FOR EACH ROW EXECUTE FUNCTION reconforge.certification_record_guard();
        """
    )
