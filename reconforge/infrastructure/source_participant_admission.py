"""Finite native participant types; no user-selected plugin/code loading."""

from importlib import import_module
from typing import Any, Literal, cast

ParticipantKind = Literal["manufacturing-v2-post", "manufacturing-v2-receipt", "intercompany-fx", "people-payroll", "accrual-deferral", "project-billing"]
_PARTICIPANTS = {
    "manufacturing-v2-post": ("reconforge.infrastructure.postgres_manufacturing_execution_v2", "_ManufacturingV2PostingParticipant"),
    "manufacturing-v2-receipt": ("reconforge.infrastructure.postgres_manufacturing_execution_v2", "_ManufacturingV2ReceiptParticipant"),
    "intercompany-fx": ("reconforge.infrastructure.postgres_intercompany_fx", "_IntercompanyFxPostingParticipant"),
    "accrual-deferral": ("reconforge.infrastructure.postgres_accrual_deferral", "_AccrualDeferralPostingParticipant"),
    "project-billing": ("reconforge.infrastructure.postgres_project_time_billing", "_ProjectBillingPostingParticipant"),
    "people-payroll": ("reconforge.infrastructure.postgres_people_project_payroll", "_PeoplePayrollPostingParticipant"),
}


def source_participant_type(kind: ParticipantKind) -> type[Any] | None:
    """An unavailable versioned source remains inadmissible, including its prefix."""
    module_name, class_name = _PARTICIPANTS[kind]
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None
    return cast(type[Any], getattr(module, class_name))
