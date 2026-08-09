"""Workspace-scoped immutable persistence for professional invoice/payment evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.domain.professional_invoice_payment_control import (
    ProfessionalInvoicePaymentError,
    ProfessionalInvoicePaymentRun,
    verify_professional_invoice_payment_payload,
)
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_sqlite_professional_invoice_payment,
    encode_sqlite_professional_invoice_payment,
)
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)


class ProfessionalInvoicePaymentPersistenceError(ValueError):
    """Safe persistence failure without source or financial-value disclosure."""


_ARTIFACT_TYPE = "reconforge-professional-invoice-payment-control"


def _artifact_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_payload(run: ProfessionalInvoicePaymentRun) -> dict[str, object]:
    payload = run.to_dict()
    payload["artifact_type"] = _ARTIFACT_TYPE
    payload["artifact_digest"] = _artifact_digest(payload)
    return payload


class SQLiteProfessionalInvoicePaymentRepository:
    """Persist verified invoice/payment reports without posting or provider I/O."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._assert_schema()

    def _assert_schema(self) -> None:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='professional_invoice_payment_runs'",
        ).fetchone()
        if exists is None:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persistence migration is required"
            )

    def _actor(self, actor_label: str) -> str:
        try:
            user = require_permission(
                self.connection,
                actor_label=actor_label,
                permission="finance_core.manage",
            )
        except PlatformError as exc:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment actor is not authorized"
            ) from exc
        return user.username if user is not None else str(actor_label).strip()

    @staticmethod
    def _validate_payload(payload: Mapping[str, object]) -> None:
        if payload.get("artifact_type") != _ARTIFACT_TYPE:
            raise ProfessionalInvoicePaymentPersistenceError("professional invoice/payment artifact type is invalid")
        digest = payload.get("artifact_digest")
        without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
        if not isinstance(digest, str) or digest != _artifact_digest(without_digest):
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment artifact digest mismatch"
            )
        try:
            verify_professional_invoice_payment_payload(dict(payload))
        except (ProfessionalInvoicePaymentError, KeyError, TypeError, ValueError) as exc:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment replay verification failed"
            ) from exc

    def put(
        self,
        run: ProfessionalInvoicePaymentRun,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if not isinstance(run, ProfessionalInvoicePaymentRun):
            raise ProfessionalInvoicePaymentPersistenceError("professional invoice/payment run is invalid")
        return self.put_payload(_artifact_payload(run), workspace=workspace, actor_label=actor_label)

    def put_payload(
        self,
        payload: Mapping[str, object],
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ProfessionalInvoicePaymentPersistenceError("professional invoice/payment report is invalid")
        payload_value = dict(payload)
        try:
            encoded = encode_sqlite_professional_invoice_payment(payload_value)
        except PersistedJsonError as exc:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment payload exceeds persistence bounds"
            ) from exc
        self._validate_payload(payload_value)
        decision_digest = payload_value.get("decision_digest")
        algorithm_version = payload_value.get("algorithm_version")
        status_counts = payload_value.get("status_counts")
        artifact_digest = payload_value.get("artifact_digest")
        if not all(isinstance(value, str) for value in (decision_digest, algorithm_version, artifact_digest)):
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment report identity is invalid"
            )
        if not isinstance(status_counts, Mapping):
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment report status counts are invalid"
            )
        actor = self._actor(actor_label)
        workspace_id = ensure_workspace(self.connection, workspace)
        run_id = platform_id("PIP", workspace_id, decision_digest)
        existing = self.connection.execute(
            "SELECT * FROM professional_invoice_payment_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["artifact_digest"]) != artifact_digest:
                raise ProfessionalInvoicePaymentPersistenceError(
                    "professional invoice/payment id conflicts with a different artifact"
                )
            return self._row_to_public(existing)
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO professional_invoice_payment_runs(
                    id,workspace_id,decision_digest,artifact_digest,algorithm_version,
                    status_counts_json,payload_json,prepared_by,prepared_at,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    workspace_id,
                    decision_digest,
                    artifact_digest,
                    algorithm_version,
                    json.dumps(status_counts, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
                    encoded.text,
                    actor,
                    now,
                    now,
                ),
            )
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="professional_invoice_payment_run",
                object_id=run_id,
                action="professional_invoice_payment_persisted",
                metadata={
                    "workspace_id": workspace_id,
                    "decision_digest": decision_digest,
                    "artifact_digest": artifact_digest,
                },
            )
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raced = self.connection.execute(
                "SELECT * FROM professional_invoice_payment_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if raced is not None:
                if str(raced["artifact_digest"]) == artifact_digest:
                    return self._row_to_public(raced)
                raise ProfessionalInvoicePaymentPersistenceError(
                    "professional invoice/payment id conflicts with a different artifact"
                ) from exc
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persistence failed"
            ) from exc
        except (PlatformError, sqlite3.DatabaseError) as exc:
            self.connection.rollback()
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persistence failed"
            ) from exc
        row = self.connection.execute(
            "SELECT * FROM professional_invoice_payment_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        return self._row_to_public(row)

    def get(self, *, decision_digest: str, workspace: str = "default") -> dict[str, Any] | None:
        workspace_id = ensure_workspace(self.connection, workspace)
        row = self.connection.execute(
            "SELECT * FROM professional_invoice_payment_runs WHERE workspace_id=? AND decision_digest=?",
            (workspace_id, decision_digest),
        ).fetchone()
        return None if row is None else self._row_to_public(row)

    def list(
        self,
        *,
        workspace: str = "default",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment list limit is invalid"
            )
        if isinstance(offset, bool) or offset < 0:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment list offset is invalid"
            )
        workspace_id = ensure_workspace(self.connection, workspace)
        rows = self.connection.execute(
            "SELECT * FROM professional_invoice_payment_runs WHERE workspace_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        ).fetchall()
        return tuple(self._row_to_public(row) for row in rows)

    def _row_to_public(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persistence row is missing"
            )
        try:
            document = decode_sqlite_professional_invoice_payment(str(row["payload_json"]))
        except PersistedJsonError as exc:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persisted JSON is invalid"
            ) from exc
        payload = document.payload
        self._validate_payload(payload)
        if str(row["artifact_digest"]) != str(payload.get("artifact_digest")):
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persisted digest mismatch"
            )
        if str(row["decision_digest"]) != str(payload.get("decision_digest")):
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persisted decision mismatch"
            )
        if str(row["algorithm_version"]) != str(payload.get("algorithm_version")):
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persisted algorithm mismatch"
            )
        expected_status_counts = json.dumps(
            payload.get("status_counts"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if str(row["status_counts_json"]) != expected_status_counts:
            raise ProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persisted status mismatch"
            )
        return {
            "id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "decision_digest": str(row["decision_digest"]),
            "artifact_digest": str(row["artifact_digest"]),
            "algorithm_version": str(row["algorithm_version"]),
            "prepared_by": str(row["prepared_by"]),
            "prepared_at": str(row["prepared_at"]),
            "created_at": str(row["created_at"]),
            "report": payload,
        }


__all__ = [
    "ProfessionalInvoicePaymentPersistenceError",
    "SQLiteProfessionalInvoicePaymentRepository",
]
