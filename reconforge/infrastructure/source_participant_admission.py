"""Finite native participant types; no user-selected plugin/code loading."""

from importlib import import_module
from typing import Any, Literal, cast

ParticipantKind = Literal["manufacturing-v2-post", "manufacturing-v2-receipt", "intercompany-fx", "people-payroll", "accrual-deferral", "project-billing", "manufacturing-supply", "customer-partial-return", "customer-partial-return-monetary"]
_PARTICIPANTS = {
    "manufacturing-v2-post": ("reconforge.infrastructure.postgres_manufacturing_execution_v2", "_ManufacturingV2PostingParticipant"),
    "manufacturing-v2-receipt": ("reconforge.infrastructure.postgres_manufacturing_execution_v2", "_ManufacturingV2ReceiptParticipant"),
    "intercompany-fx": ("reconforge.infrastructure.postgres_intercompany_fx", "_IntercompanyFxPostingParticipant"),
    "accrual-deferral": ("reconforge.infrastructure.postgres_accrual_deferral", "_AccrualDeferralPostingParticipant"),
    "project-billing": ("reconforge.infrastructure.postgres_project_time_billing", "_ProjectBillingPostingParticipant"),
    "manufacturing-supply": ("reconforge.infrastructure.postgres_manufacturing_supply_plan", "_ManufacturingSupplyParticipant"),
    "people-payroll": ("reconforge.infrastructure.postgres_people_project_payroll", "_PeoplePayrollPostingParticipant"),
    "customer-partial-return": ("reconforge.infrastructure.postgres_customer_partial_returns", "_CustomerPartialReturnPostingParticipant"),
    "customer-partial-return-monetary": ("reconforge.infrastructure.postgres_monetary_customer_partial_returns", "_MonetaryCustomerReturnPostingParticipant"),
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


def require_manufacturing_supply_owner(
    connection: Any, tenant_id: str, identifier: str, number: str, participant: object | None,
) -> None:
    """A retained namespace establishes relevance; the exact live owner admits it."""
    if not number.upper().startswith(("SRC5-MSP-", "BPC1-SRC5-MSP-")):
        return
    from reconforge.domain.procurement_partial import ProcurementPartialError

    participant_type = source_participant_type("manufacturing-supply")
    if participant_type is None or not isinstance(participant, participant_type) or not participant.admits(
        connection, tenant_id, identifier,
    ):
        raise ProcurementPartialError(
            "manufacturing_supply_owner_required", "Planned sourcing and procurement require their complete active supply command.",
        )
