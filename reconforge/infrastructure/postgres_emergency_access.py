"""Governed, temporary emergency authority for the PostgreSQL server profile."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id

EMERGENCY_ELIGIBLE_PERMISSIONS = frozenset(
    {
        "close.manage",
        "finance_core.manage",
        "finance_core.validate",
        "inventory.post",
        "receivables.credit_override",
    }
)
EmergencyStatus = Literal["Pending", "Approved", "Active", "Rejected", "ReviewPending", "Reviewed"]
ReviewOutcome = Literal["Confirmed", "Concern", "Incident"]
_PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class EmergencyAccessError(RuntimeError):
    """Raised when an emergency-access operation fails safely."""


@dataclass(frozen=True)
class EmergencyAccessRecord:
    id: str
    requester_user_id: str
    target_user_id: str
    permissions: frozenset[str]
    status: EmergencyStatus
    reason: str
    incident_reference: str
    requested_minutes: int
    version: int
    requested_at: str
    approved_by: str | None = None
    activated_session_id: str | None = None
    activated_at: str | None = None
    expires_at: str | None = None
    reviewed_by: str | None = None
    review_outcome: str | None = None


@dataclass(frozen=True)
class ActiveEmergencyAuthority:
    """Active session-local grants, keyed deterministically by permission."""

    permissions: frozenset[str]
    access_id_by_permission: tuple[tuple[str, str], ...]


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise EmergencyAccessError(str(exc)) from exc


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise EmergencyAccessError(str(exc)) from exc


def _text(value: object, field_name: str, *, minimum: int = 1, maximum: int = 500) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise EmergencyAccessError(f"{field_name} must be between {minimum} and {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise EmergencyAccessError(f"{field_name} must contain printable characters only.")
    return normalized


def _permissions(values: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(str(value).strip().casefold() for value in values)
    if not 1 <= len(normalized) <= 5:
        raise EmergencyAccessError("Emergency access requires one to five permissions.")
    if any(not _PERMISSION_PATTERN.fullmatch(value) for value in normalized):
        raise EmergencyAccessError("Emergency permission contains unsupported characters.")
    unsupported = normalized.difference(EMERGENCY_ELIGIBLE_PERMISSIONS)
    if unsupported:
        raise EmergencyAccessError("Emergency access contains a non-eligible permission.")
    return normalized


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _utc_text(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise EmergencyAccessError("Stored emergency-access timestamp is invalid.") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _token_digest(token: str) -> str:
    if not token:
        raise EmergencyAccessError("Session token must not be blank.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PostgresEmergencyAccessRepository:
    """Apply maker-checker emergency authority transitions in one tenant transaction."""

    connection: Any

    _PROJECTION = (
        "id,requester_user_id,target_user_id,status,reason,incident_reference,requested_minutes,version,"
        "requested_at,approved_by,activated_session_id,activated_at,expires_at,reviewed_by,review_outcome"
    )

    def _lock(self, tenant_id: str, access_id: str) -> None:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"{tenant_id}:emergency:{access_id}",),
        )

    def _event(self, tenant_id: str, access_id: str, action: str, actor_id: str, request_id: str = "") -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.emergency_access_events
                (tenant_id,id,access_id,action,actor_id,request_id)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                tenant_id,
                f"eae-{secrets.token_hex(16)}",
                access_id,
                action,
                _scope(actor_id, "actor_id"),
                str(request_id or "")[:128],
            ),
        )

    def _record(self, tenant_id: str, access_id: str) -> EmergencyAccessRecord:
        row = self.connection.execute(
            f"SELECT {self._PROJECTION} FROM reconforge.emergency_access_requests "  # nosec B608 - static projection
            "WHERE tenant_id=%s AND id=%s",
            (tenant_id, access_id),
        ).fetchone()
        if row is None:
            raise EmergencyAccessError("Emergency-access request was not found.")
        permission_rows = self.connection.execute(
            "SELECT permission_name FROM reconforge.emergency_access_permissions "
            "WHERE tenant_id=%s AND access_id=%s ORDER BY permission_name",
            (tenant_id, access_id),
        ).fetchall()
        return EmergencyAccessRecord(
            id=str(_value(row, "id", 0)),
            requester_user_id=str(_value(row, "requester_user_id", 1)),
            target_user_id=str(_value(row, "target_user_id", 2)),
            permissions=frozenset(str(_value(item, "permission_name", 0)) for item in permission_rows),
            status=str(_value(row, "status", 3)),  # type: ignore[arg-type]
            reason=str(_value(row, "reason", 4)),
            incident_reference=str(_value(row, "incident_reference", 5)),
            requested_minutes=int(_value(row, "requested_minutes", 6)),
            version=int(_value(row, "version", 7)),
            requested_at=str(_utc_text(_value(row, "requested_at", 8))),
            approved_by=str(_value(row, "approved_by", 9)) if _value(row, "approved_by", 9) else None,
            activated_session_id=(
                str(_value(row, "activated_session_id", 10)) if _value(row, "activated_session_id", 10) else None
            ),
            activated_at=_utc_text(_value(row, "activated_at", 11)),
            expires_at=_utc_text(_value(row, "expires_at", 12)),
            reviewed_by=str(_value(row, "reviewed_by", 13)) if _value(row, "reviewed_by", 13) else None,
            review_outcome=(str(_value(row, "review_outcome", 14)) if _value(row, "review_outcome", 14) else None),
        )

    def request_access(
        self,
        *,
        tenant_id: str,
        requester_user_id: str,
        target_user_id: str,
        permissions: Iterable[str],
        reason: str,
        incident_reference: str,
        requested_minutes: int,
        request_id: str = "",
    ) -> EmergencyAccessRecord:
        tenant = _tenant(tenant_id)
        requester = _scope(requester_user_id, "requester_user_id")
        target = _scope(target_user_id, "target_user_id")
        if requester != target:
            raise EmergencyAccessError("Emergency access may only be requested for the current user.")
        grants = _permissions(permissions)
        if not 5 <= requested_minutes <= 60:
            raise EmergencyAccessError("Emergency duration must be between 5 and 60 minutes.")
        access_id = f"eac-{secrets.token_hex(16)}"
        self._lock(tenant, target)
        active_conflict = self.connection.execute(
            """
            SELECT 1 FROM reconforge.emergency_access_requests requests
            JOIN reconforge.emergency_access_permissions permissions
              ON permissions.tenant_id=requests.tenant_id AND permissions.access_id=requests.id
            WHERE requests.tenant_id=%s AND requests.target_user_id=%s
              AND requests.status IN ('Pending','Approved','Active')
              AND permissions.permission_name = ANY(%s)
            LIMIT 1
            """,
            (tenant, target, sorted(grants)),
        ).fetchone()
        if active_conflict is not None:
            raise EmergencyAccessError("A pending or active emergency grant already covers this permission.")
        user = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND disabled=FALSE",
            (tenant, target),
        ).fetchone()
        if user is None:
            raise EmergencyAccessError("Emergency target user is not active.")
        permission_count = self.connection.execute(
            "SELECT count(*) FROM reconforge.identity_permissions WHERE tenant_id=%s AND name = ANY(%s)",
            (tenant, sorted(grants)),
        ).fetchone()
        if permission_count is None or int(_value(permission_count, "count", 0)) != len(grants):
            raise EmergencyAccessError("Emergency permission is not registered in the tenant.")
        self.connection.execute(
            """
            INSERT INTO reconforge.emergency_access_requests
                (tenant_id,id,requester_user_id,target_user_id,status,reason,incident_reference,requested_minutes)
            VALUES (%s,%s,%s,%s,'Pending',%s,%s,%s)
            """,
            (
                tenant,
                access_id,
                requester,
                target,
                _text(reason, "reason", minimum=20, maximum=1000),
                _text(incident_reference, "incident_reference", minimum=3, maximum=128),
                requested_minutes,
            ),
        )
        for permission in sorted(grants):
            self.connection.execute(
                "INSERT INTO reconforge.emergency_access_permissions(tenant_id,access_id,permission_name) "
                "VALUES (%s,%s,%s)",
                (tenant, access_id, permission),
            )
        self._event(tenant, access_id, "requested", requester, request_id)
        return self._record(tenant, access_id)

    def approve(
        self, *, tenant_id: str, access_id: str, approver_user_id: str, expected_version: int, request_id: str = ""
    ) -> EmergencyAccessRecord:
        tenant = _tenant(tenant_id)
        identifier = _scope(access_id, "access_id")
        approver = _scope(approver_user_id, "approver_user_id")
        self._lock(tenant, identifier)
        cursor = self.connection.execute(
            """
            UPDATE reconforge.emergency_access_requests
            SET status='Approved',approved_by=%s,approved_at=now(),version=version+1
            WHERE tenant_id=%s AND id=%s AND status='Pending' AND version=%s
              AND requester_user_id<>%s AND target_user_id<>%s
            RETURNING id
            """,
            (approver, tenant, identifier, expected_version, approver, approver),
        )
        if cursor.fetchone() is None:
            raise EmergencyAccessError("Emergency approval failed maker-checker or version validation.")
        self._event(tenant, identifier, "approved", approver, request_id)
        return self._record(tenant, identifier)

    def reject(
        self,
        *,
        tenant_id: str,
        access_id: str,
        approver_user_id: str,
        expected_version: int,
        note: str,
        request_id: str = "",
    ) -> EmergencyAccessRecord:
        tenant = _tenant(tenant_id)
        identifier = _scope(access_id, "access_id")
        approver = _scope(approver_user_id, "approver_user_id")
        cursor = self.connection.execute(
            """
            UPDATE reconforge.emergency_access_requests
            SET status='Rejected',approved_by=%s,approved_at=now(),decision_note=%s,version=version+1
            WHERE tenant_id=%s AND id=%s AND status='Pending' AND version=%s
              AND requester_user_id<>%s AND target_user_id<>%s
            RETURNING id
            """,
            (approver, _text(note, "rejection note", minimum=10), tenant, identifier, expected_version, approver, approver),
        )
        if cursor.fetchone() is None:
            raise EmergencyAccessError("Emergency rejection failed maker-checker or version validation.")
        self._event(tenant, identifier, "rejected", approver, request_id)
        return self._record(tenant, identifier)

    def activate(
        self,
        *,
        tenant_id: str,
        access_id: str,
        target_user_id: str,
        session_id: str,
        expected_version: int,
        step_up_active: bool,
        request_id: str = "",
    ) -> EmergencyAccessRecord:
        if not step_up_active:
            raise EmergencyAccessError("Emergency activation requires recent human reauthentication.")
        tenant = _tenant(tenant_id)
        identifier = _scope(access_id, "access_id")
        target = _scope(target_user_id, "target_user_id")
        session = _scope(session_id, "session_id")
        self._lock(tenant, identifier)
        cursor = self.connection.execute(
            """
            UPDATE reconforge.emergency_access_requests requests
            SET status='Active',activated_session_id=%s,activated_at=now(),
                expires_at=now()+(requested_minutes * interval '1 minute'),
                review_due_at=now()+(requested_minutes * interval '1 minute')+interval '24 hours',
                version=version+1
            WHERE tenant_id=%s AND id=%s AND status='Approved' AND version=%s
              AND target_user_id=%s
              AND EXISTS (
                  SELECT 1 FROM reconforge.identity_sessions sessions
                  WHERE sessions.tenant_id=requests.tenant_id AND sessions.id=%s
                    AND sessions.user_id=requests.target_user_id
                    AND sessions.revoked_at IS NULL AND sessions.expires_at>now()
              )
            RETURNING id
            """,
            (session, tenant, identifier, expected_version, target, session),
        )
        if cursor.fetchone() is None:
            raise EmergencyAccessError("Emergency activation failed session, target, state, or version validation.")
        self._event(tenant, identifier, "activated", target, request_id)
        return self._record(tenant, identifier)

    def _expire_due(self, tenant: str) -> None:
        rows = self.connection.execute(
            """
            UPDATE reconforge.emergency_access_requests
            SET status='ReviewPending',ended_at=expires_at,version=version+1
            WHERE tenant_id=%s AND status='Active' AND expires_at<=now()
            RETURNING id,target_user_id
            """,
            (tenant,),
        ).fetchall()
        for row in rows:
            self._event(tenant, str(_value(row, "id", 0)), "expired", str(_value(row, "target_user_id", 1)))

    def active_for_session(
        self, *, tenant_id: str, token: str, user_id: str, session_id: str
    ) -> ActiveEmergencyAuthority:
        tenant = _tenant(tenant_id)
        user = _scope(user_id, "user_id")
        session = _scope(session_id, "session_id")
        digest = _token_digest(token)
        self._expire_due(tenant)
        session_row = self.connection.execute(
            "SELECT token_hash FROM reconforge.identity_sessions WHERE tenant_id=%s AND id=%s AND user_id=%s "
            "AND revoked_at IS NULL AND expires_at>now()",
            (tenant, session, user),
        ).fetchone()
        if session_row is None or not hmac.compare_digest(str(_value(session_row, "token_hash", 0)), digest):
            return ActiveEmergencyAuthority(frozenset(), ())
        rows = self.connection.execute(
            """
            SELECT permissions.permission_name,requests.id
            FROM reconforge.emergency_access_requests requests
            JOIN reconforge.emergency_access_permissions permissions
              ON permissions.tenant_id=requests.tenant_id AND permissions.access_id=requests.id
            WHERE requests.tenant_id=%s AND requests.target_user_id=%s
              AND requests.activated_session_id=%s AND requests.status='Active'
              AND requests.activated_at<=now() AND requests.expires_at>now()
            ORDER BY permissions.permission_name,requests.activated_at DESC,requests.id
            """,
            (tenant, user, session),
        ).fetchall()
        by_permission: dict[str, str] = {}
        for row in rows:
            by_permission.setdefault(str(_value(row, "permission_name", 0)), str(_value(row, "id", 1)))
        return ActiveEmergencyAuthority(frozenset(by_permission), tuple(sorted(by_permission.items())))

    def record_use(
        self,
        *,
        tenant_id: str,
        access_id: str,
        user_id: str,
        session_id: str,
        permission: str,
        surface: str,
        request_id: str,
    ) -> None:
        tenant = _tenant(tenant_id)
        identifier = _scope(access_id, "access_id")
        user = _scope(user_id, "user_id")
        session = _scope(session_id, "session_id")
        grant = _permissions({permission})
        exists = self.connection.execute(
            """
            SELECT 1 FROM reconforge.emergency_access_requests requests
            JOIN reconforge.emergency_access_permissions permissions
              ON permissions.tenant_id=requests.tenant_id AND permissions.access_id=requests.id
            WHERE requests.tenant_id=%s AND requests.id=%s AND requests.target_user_id=%s
              AND requests.activated_session_id=%s AND requests.status='Active' AND requests.expires_at>now()
              AND permissions.permission_name=%s
            """,
            (tenant, identifier, user, session, next(iter(grant))),
        ).fetchone()
        if exists is None:
            raise EmergencyAccessError("Emergency authority is no longer active.")
        self.connection.execute(
            """
            INSERT INTO reconforge.emergency_access_events
                (tenant_id,id,access_id,action,actor_id,permission_name,surface,request_id)
            VALUES (%s,%s,%s,'used',%s,%s,%s,%s)
            """,
            (
                tenant,
                f"eae-{secrets.token_hex(16)}",
                identifier,
                user,
                next(iter(grant)),
                _text(surface, "surface", maximum=256),
                str(request_id or "")[:128],
            ),
        )

    def end_access(
        self,
        *,
        tenant_id: str,
        access_id: str,
        actor_user_id: str,
        expected_version: int,
        actor_can_administer: bool,
        note: str,
        request_id: str = "",
    ) -> EmergencyAccessRecord:
        tenant = _tenant(tenant_id)
        identifier = _scope(access_id, "access_id")
        actor = _scope(actor_user_id, "actor_user_id")
        cursor = self.connection.execute(
            """
            UPDATE reconforge.emergency_access_requests
            SET status='ReviewPending',ended_at=now(),decision_note=%s,version=version+1
            WHERE tenant_id=%s AND id=%s AND status IN ('Approved','Active') AND version=%s
              AND (target_user_id=%s OR %s)
            RETURNING id
            """,
            (_text(note, "end note", minimum=10), tenant, identifier, expected_version, actor, actor_can_administer),
        )
        if cursor.fetchone() is None:
            raise EmergencyAccessError("Emergency access could not be ended by this actor or version.")
        self._event(tenant, identifier, "ended", actor, request_id)
        return self._record(tenant, identifier)

    def review(
        self,
        *,
        tenant_id: str,
        access_id: str,
        reviewer_user_id: str,
        expected_version: int,
        outcome: ReviewOutcome,
        note: str,
        request_id: str = "",
    ) -> EmergencyAccessRecord:
        tenant = _tenant(tenant_id)
        identifier = _scope(access_id, "access_id")
        reviewer = _scope(reviewer_user_id, "reviewer_user_id")
        if outcome not in {"Confirmed", "Concern", "Incident"}:
            raise EmergencyAccessError("Emergency review outcome is invalid.")
        self._expire_due(tenant)
        cursor = self.connection.execute(
            """
            UPDATE reconforge.emergency_access_requests
            SET status='Reviewed',reviewed_by=%s,reviewed_at=now(),review_outcome=%s,review_note=%s,version=version+1
            WHERE tenant_id=%s AND id=%s AND status='ReviewPending' AND version=%s
              AND requester_user_id<>%s AND target_user_id<>%s
            RETURNING id
            """,
            (
                reviewer,
                outcome,
                _text(note, "review note", minimum=20, maximum=1000),
                tenant,
                identifier,
                expected_version,
                reviewer,
                reviewer,
            ),
        )
        if cursor.fetchone() is None:
            raise EmergencyAccessError("Emergency review failed independence, state, or version validation.")
        self._event(tenant, identifier, "reviewed", reviewer, request_id)
        return self._record(tenant, identifier)

    def list_access(self, *, tenant_id: str, actor_user_id: str, can_administer: bool) -> list[EmergencyAccessRecord]:
        tenant = _tenant(tenant_id)
        actor = _scope(actor_user_id, "actor_user_id")
        self._expire_due(tenant)
        rows = self.connection.execute(
            "SELECT id FROM reconforge.emergency_access_requests WHERE tenant_id=%s "
            "AND (requester_user_id=%s OR target_user_id=%s OR %s) ORDER BY requested_at DESC,id LIMIT 500",
            (tenant, actor, actor, can_administer),
        ).fetchall()
        return [self._record(tenant, str(_value(row, "id", 0))) for row in rows]


POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.emergency_access_requests (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    requester_user_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Pending','Approved','Active','Rejected','ReviewPending','Reviewed')),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 20 AND 1000),
    incident_reference TEXT NOT NULL CHECK (length(incident_reference) BETWEEN 3 AND 128),
    requested_minutes INTEGER NOT NULL CHECK (requested_minutes BETWEEN 5 AND 60),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    decision_note TEXT NOT NULL DEFAULT '',
    activated_session_id TEXT,
    activated_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    review_due_at TIMESTAMPTZ,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    review_outcome TEXT CHECK (review_outcome IS NULL OR review_outcome IN ('Confirmed','Concern','Incident')),
    review_note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,requester_user_id) REFERENCES reconforge.identity_users(tenant_id,id),
    FOREIGN KEY (tenant_id,target_user_id) REFERENCES reconforge.identity_users(tenant_id,id),
    FOREIGN KEY (tenant_id,approved_by) REFERENCES reconforge.identity_users(tenant_id,id),
    FOREIGN KEY (tenant_id,reviewed_by) REFERENCES reconforge.identity_users(tenant_id,id),
    FOREIGN KEY (tenant_id,activated_session_id) REFERENCES reconforge.identity_sessions(tenant_id,id),
    CHECK (requester_user_id = target_user_id),
    CHECK (approved_by IS NULL OR (approved_by <> requester_user_id AND approved_by <> target_user_id)),
    CHECK (reviewed_by IS NULL OR (reviewed_by <> requester_user_id AND reviewed_by <> target_user_id)),
    CHECK (expires_at IS NULL OR (activated_at IS NOT NULL AND expires_at > activated_at AND expires_at <= activated_at + interval '60 minutes')),
    CHECK (review_due_at IS NULL OR (expires_at IS NOT NULL AND review_due_at <= expires_at + interval '24 hours')),
    CHECK (
        (status='Pending' AND approved_by IS NULL AND activated_session_id IS NULL AND reviewed_by IS NULL) OR
        (status='Approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND activated_session_id IS NULL AND reviewed_by IS NULL) OR
        (status='Active' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND activated_session_id IS NOT NULL AND activated_at IS NOT NULL AND expires_at IS NOT NULL AND review_due_at IS NOT NULL AND reviewed_by IS NULL) OR
        (status='Rejected' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND activated_session_id IS NULL AND reviewed_by IS NULL) OR
        (status='ReviewPending' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND ended_at IS NOT NULL AND reviewed_by IS NULL) OR
        (status='Reviewed' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND ended_at IS NOT NULL AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_outcome IS NOT NULL AND length(review_note)>=20)
    )
);
CREATE TABLE IF NOT EXISTS reconforge.emergency_access_permissions (
    tenant_id TEXT NOT NULL,
    access_id TEXT NOT NULL,
    permission_name TEXT NOT NULL CHECK (permission_name IN ('close.manage','finance_core.manage','finance_core.validate','inventory.post','receivables.credit_override')),
    PRIMARY KEY (tenant_id,access_id,permission_name),
    FOREIGN KEY (tenant_id,access_id) REFERENCES reconforge.emergency_access_requests(tenant_id,id),
    FOREIGN KEY (tenant_id,permission_name) REFERENCES reconforge.identity_permissions(tenant_id,name)
);
CREATE TABLE IF NOT EXISTS reconforge.emergency_access_events (
    tenant_id TEXT NOT NULL,
    event_sequence BIGINT GENERATED ALWAYS AS IDENTITY,
    id TEXT NOT NULL,
    access_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('requested','approved','rejected','activated','used','expired','ended','reviewed')),
    actor_id TEXT NOT NULL,
    permission_name TEXT,
    surface TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,access_id) REFERENCES reconforge.emergency_access_requests(tenant_id,id),
    CHECK ((action='used') = (permission_name IS NOT NULL)),
    CHECK (length(surface) <= 256 AND length(request_id) <= 128)
);
CREATE INDEX IF NOT EXISTS idx_emergency_access_active
    ON reconforge.emergency_access_requests(tenant_id,target_user_id,status,expires_at);
CREATE INDEX IF NOT EXISTS idx_emergency_access_events
    ON reconforge.emergency_access_events(tenant_id,access_id,event_sequence);
ALTER TABLE reconforge.emergency_access_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.emergency_access_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.emergency_access_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.emergency_access_permissions FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.emergency_access_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.emergency_access_events FORCE ROW LEVEL SECURITY;
DO $reconforge$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['emergency_access_requests','emergency_access_permissions','emergency_access_events'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
            EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
        END IF;
    END LOOP;
END
$reconforge$;
CREATE OR REPLACE FUNCTION reconforge.guard_emergency_access_request_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.tenant_id,NEW.id,NEW.requester_user_id,NEW.target_user_id,NEW.reason,NEW.incident_reference,NEW.requested_minutes,NEW.requested_at)
       IS DISTINCT FROM
       (OLD.tenant_id,OLD.id,OLD.requester_user_id,OLD.target_user_id,OLD.reason,OLD.incident_reference,OLD.requested_minutes,OLD.requested_at) THEN
        RAISE EXCEPTION 'emergency request identity is immutable';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN RAISE EXCEPTION 'emergency request version transition is invalid'; END IF;
    IF NOT ((OLD.status='Pending' AND NEW.status IN ('Approved','Rejected')) OR
            (OLD.status='Approved' AND NEW.status IN ('Active','ReviewPending')) OR
            (OLD.status='Active' AND NEW.status='ReviewPending') OR
            (OLD.status='ReviewPending' AND NEW.status='Reviewed')) THEN
        RAISE EXCEPTION 'emergency request status transition is invalid';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS emergency_access_request_guard ON reconforge.emergency_access_requests;
CREATE TRIGGER emergency_access_request_guard BEFORE UPDATE ON reconforge.emergency_access_requests
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_emergency_access_request_update();
CREATE OR REPLACE FUNCTION reconforge.reject_emergency_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'emergency evidence is append-only'; END; $$;
DROP TRIGGER IF EXISTS emergency_access_requests_no_delete ON reconforge.emergency_access_requests;
CREATE TRIGGER emergency_access_requests_no_delete BEFORE DELETE ON reconforge.emergency_access_requests
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_emergency_evidence_mutation();
DROP TRIGGER IF EXISTS emergency_access_permissions_immutable ON reconforge.emergency_access_permissions;
CREATE TRIGGER emergency_access_permissions_immutable BEFORE UPDATE OR DELETE ON reconforge.emergency_access_permissions
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_emergency_evidence_mutation();
DROP TRIGGER IF EXISTS emergency_access_events_append_only ON reconforge.emergency_access_events;
CREATE TRIGGER emergency_access_events_append_only BEFORE UPDATE OR DELETE ON reconforge.emergency_access_events
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_emergency_evidence_mutation();
"""
