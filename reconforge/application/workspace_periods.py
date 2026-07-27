"""Atomic workspace and first-period application use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from reconforge.domain.models import AuditEventReference, Period, Workspace
from reconforge.domain.protocols import DomainUnitOfWorkFactory

MAX_NAME_LENGTH = 200
MAX_ACTOR_LENGTH = 200


class WorkspacePeriodValidationError(ValueError):
    """Raised before persistence when setup input is invalid."""


@dataclass(frozen=True)
class WorkspacePeriodSetup:
    """Objects committed by one atomic workspace bootstrap operation."""

    workspace: Workspace
    period: Period
    audit_events: tuple[AuditEventReference, AuditEventReference]


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise WorkspacePeriodValidationError(f"{field} must be text.")
    cleaned = value.strip()
    if not cleaned:
        raise WorkspacePeriodValidationError(f"{field} is required.")
    if len(cleaned) > maximum:
        raise WorkspacePeriodValidationError(f"{field} must be at most {maximum} characters.")
    if not cleaned.isprintable():
        raise WorkspacePeriodValidationError(f"{field} must contain printable characters only.")
    return cleaned


def _business_date(value: str, *, field: str) -> date:
    if not isinstance(value, str):
        raise WorkspacePeriodValidationError(f"{field} must use YYYY-MM-DD format.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise WorkspacePeriodValidationError(f"{field} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != value:
        raise WorkspacePeriodValidationError(f"{field} must use canonical YYYY-MM-DD format.")
    return parsed


class WorkspacePeriodApplicationService:
    """Create the first workspace and fiscal period without backend coupling."""

    def __init__(self, unit_of_work_factory: DomainUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def create(
        self,
        *,
        workspace_name: str,
        period_name: str,
        start_date: str,
        end_date: str,
        actor_label: str,
        local_first_note: str | None = None,
    ) -> WorkspacePeriodSetup:
        workspace_label = _bounded_text(workspace_name, field="workspace_name", maximum=MAX_NAME_LENGTH)
        period_label = _bounded_text(period_name, field="period_name", maximum=MAX_NAME_LENGTH)
        actor = _bounded_text(actor_label, field="actor_label", maximum=MAX_ACTOR_LENGTH)
        start = _business_date(start_date, field="start_date")
        end = _business_date(end_date, field="end_date")
        if end < start:
            raise WorkspacePeriodValidationError("end_date must be on or after start_date.")
        note = None
        if local_first_note is not None:
            note = _bounded_text(local_first_note, field="local_first_note", maximum=1000)

        with self._unit_of_work_factory() as unit_of_work:
            workspace = unit_of_work.workspaces.create(name=workspace_label, local_first_note=note)
            period = unit_of_work.periods.create(
                workspace_id=workspace.id,
                name=period_label,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
            workspace_event = unit_of_work.audit_events.append(
                actor_label=actor,
                object_type="workspace",
                object_id=workspace.id,
                action="workspace.created",
                metadata={"name": workspace.name},
            )
            period_event = unit_of_work.audit_events.append(
                actor_label=actor,
                object_type="period",
                object_id=period.id,
                action="period.created",
                metadata={
                    "end_date": period.end_date,
                    "name": period.name,
                    "start_date": period.start_date,
                    "workspace_id": workspace.id,
                },
            )
            unit_of_work.commit()

        return WorkspacePeriodSetup(
            workspace=workspace,
            period=period,
            audit_events=(workspace_event, period_event),
        )
