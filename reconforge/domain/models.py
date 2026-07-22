"""Pydantic domain reference models for the local database backbone."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reconforge.utils.time import utc_now_text

DEFAULT_LOCAL_FIRST_NOTE = "Local-first workspace. Data remains in user-selected local paths."


def new_domain_id(prefix: str) -> str:
    """Create a compact local domain identifier."""

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Workspace(_DomainModel):
    """A local ReconForge workspace."""

    id: str = Field(default_factory=lambda: new_domain_id("WS"))
    name: str
    created_at: str = Field(default_factory=utc_now_text)
    local_first_note: str = DEFAULT_LOCAL_FIRST_NOTE


class Organization(_DomainModel):
    """An organization inside a local workspace."""

    id: str = Field(default_factory=lambda: new_domain_id("ORG"))
    workspace_id: str
    name: str
    organization_code: str = ""
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class LegalEntity(_DomainModel):
    """A legal entity reference for export-based finance workflows."""

    id: str = Field(default_factory=lambda: new_domain_id("LE"))
    organization_id: str
    entity_code: str
    name: str
    currency: str
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class Branch(_DomainModel):
    """An operating branch optionally assigned to a legal entity."""

    id: str = Field(default_factory=lambda: new_domain_id("BR"))
    organization_id: str
    branch_code: str
    name: str
    legal_entity_id: str | None = None
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class Currency(_DomainModel):
    """A governed local currency reference; this is not an exchange-rate feed."""

    code: str
    name: str
    minor_units: int = Field(default=2, ge=0, le=6)
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class ChartOfAccounts(_DomainModel):
    """A governed chart-of-accounts reference inside a local workspace."""

    id: str = Field(default_factory=lambda: new_domain_id("COA"))
    workspace_id: str
    chart_code: str
    name: str
    organization_id: str | None = None
    description: str = ""
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class FinancialAccount(_DomainModel):
    """One account in a governed local chart of accounts."""

    id: str = Field(default_factory=lambda: new_domain_id("ACC"))
    workspace_id: str
    chart_id: str
    account_code: str
    account_name: str
    parent_account_id: str | None = None
    account_type: str = "Asset"
    normal_balance: str = "Debit"
    allow_posting: bool = True
    allow_manual_posting: bool = True
    reconciliation_required: bool = False
    active: bool = True
    description: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class AccountingDimension(_DomainModel):
    """A governed analytic dimension such as cost center or project."""

    id: str = Field(default_factory=lambda: new_domain_id("DIM"))
    workspace_id: str
    dimension_code: str
    name: str
    organization_id: str | None = None
    dimension_type: str = "Custom"
    required_on_entries: bool = False
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class AccountingDimensionValue(_DomainModel):
    """One governed value belonging to an accounting dimension."""

    id: str = Field(default_factory=lambda: new_domain_id("DIMV"))
    dimension_id: str
    value_code: str
    name: str
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class FinanceJournal(_DomainModel):
    """A journal definition for local ledger-control entries."""

    id: str = Field(default_factory=lambda: new_domain_id("FJ"))
    workspace_id: str
    organization_id: str
    journal_code: str
    name: str
    journal_type: str = "General"
    currency_code: str
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class LedgerEntry(_DomainModel):
    """A balanced local ledger-control entry; it does not post to a source ERP."""

    id: str = Field(default_factory=lambda: new_domain_id("GLE"))
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    period_id: str
    finance_journal_id: str
    entry_number: str
    posting_date: str
    currency_code: str
    description: str
    status: str = "Draft"
    created_by: str = "local-cli"
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class LedgerLine(_DomainModel):
    """One debit or credit line stored in currency minor units."""

    id: str = Field(default_factory=lambda: new_domain_id("GLL"))
    entry_id: str
    line_number: int = Field(ge=1)
    account_id: str
    description: str = ""
    debit_minor: int = Field(default=0, ge=0)
    credit_minor: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=utc_now_text)


class UnitOfMeasure(_DomainModel):
    """A governed quantity unit with fixed local decimal precision."""

    id: str = Field(default_factory=lambda: new_domain_id("UOM"))
    workspace_id: str
    uom_code: str
    name: str
    category: str = "Count"
    decimal_places: int = Field(default=0, ge=0, le=6)
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class InventoryItem(_DomainModel):
    """A local item master for inventory-control movements."""

    id: str = Field(default_factory=lambda: new_domain_id("ITEM"))
    workspace_id: str
    item_code: str
    name: str
    uom_id: str
    organization_id: str | None = None
    inventory_account_id: str | None = None
    item_type: str = "Stock"
    tracking_mode: str = "None"
    description: str = ""
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class Warehouse(_DomainModel):
    """A governed local warehouse belonging to one organization."""

    id: str = Field(default_factory=lambda: new_domain_id("WH"))
    workspace_id: str
    organization_id: str
    warehouse_code: str
    name: str
    legal_entity_id: str | None = None
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class InventoryLocation(_DomainModel):
    """A hierarchical warehouse location used by local stock movements."""

    id: str = Field(default_factory=lambda: new_domain_id("LOC"))
    warehouse_id: str
    location_code: str
    name: str
    parent_location_id: str | None = None
    location_type: str = "Internal"
    allow_negative: bool = False
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class InventoryLot(_DomainModel):
    """A lot or serial reference for an explicitly tracked local item."""

    id: str = Field(default_factory=lambda: new_domain_id("LOT"))
    workspace_id: str
    organization_id: str
    item_id: str
    lot_serial_code: str
    tracking_type: str
    manufactured_on: str | None = None
    expires_on: str | None = None
    active: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class InventoryMovement(_DomainModel):
    """A locally posted inventory movement; it does not update a source ERP."""

    id: str = Field(default_factory=lambda: new_domain_id("MOV"))
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    period_id: str
    movement_number: str
    movement_type: str
    movement_date: str
    description: str
    source_reference: str = ""
    source_type: str = "Manual"
    status: str = "Draft"
    created_by: str = "local-cli"
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class InventoryMovementLine(_DomainModel):
    """One exact-quantity line in a local inventory movement."""

    id: str = Field(default_factory=lambda: new_domain_id("MOVL"))
    movement_id: str
    line_number: int = Field(ge=1)
    item_id: str
    uom_id: str
    quantity_scaled: int = Field(gt=0)
    quantity_precision: int = Field(ge=0, le=6)
    inventory_lot_id: str | None = None
    from_location_id: str | None = None
    to_location_id: str | None = None
    description: str = ""
    created_at: str = Field(default_factory=utc_now_text)


class InventoryCountSession(_DomainModel):
    """A governed physical-count snapshot and review lifecycle."""

    id: str = Field(default_factory=lambda: new_domain_id("ICNT"))
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    period_id: str
    location_id: str
    count_number: str
    count_date: str
    description: str = ""
    status: str = "Draft"
    created_by: str = "local-cli"
    adjustment_movement_id: str | None = None
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class InventoryCountLine(_DomainModel):
    """One immutable expected balance and optional counted result."""

    id: str = Field(default_factory=lambda: new_domain_id("ICNL"))
    session_id: str
    line_number: int = Field(ge=1)
    item_id: str
    uom_id: str
    expected_quantity_scaled: int
    quantity_precision: int = Field(ge=0, le=6)
    inventory_lot_id: str | None = None
    counted_quantity_scaled: int | None = Field(default=None, ge=0)
    count_note: str = ""
    counted_by: str = ""
    counted_at: str | None = None
    created_at: str = Field(default_factory=utc_now_text)


class InventoryReorderRule(_DomainModel):
    """A local threshold rule that emits advice but creates no purchase order."""

    id: str = Field(default_factory=lambda: new_domain_id("IROR"))
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    item_id: str
    location_id: str
    minimum_quantity_scaled: int = Field(ge=0)
    target_quantity_scaled: int = Field(gt=0)
    quantity_precision: int = Field(ge=0, le=6)
    lead_time_days: int = Field(default=0, ge=0, le=3650)
    active: bool = True
    created_by: str = "local-cli"
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class Period(_DomainModel):
    """A local finance period reference."""

    id: str = Field(default_factory=lambda: new_domain_id("PER"))
    workspace_id: str
    name: str
    start_date: str
    end_date: str
    status: str = "Open"
    fiscal_year: int = 0
    period_number: int = 0
    status_reason: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = ""


class UserReference(_DomainModel):
    """A user reference without authentication credentials."""

    id: str = Field(default_factory=lambda: new_domain_id("USR"))
    username: str
    display_name: str
    email: str | None = None
    disabled: bool = False
    created_at: str = Field(default_factory=utc_now_text)


class Role(_DomainModel):
    """A role reference for later RBAC primitives."""

    id: str = Field(default_factory=lambda: new_domain_id("ROLE"))
    name: str


class Permission(_DomainModel):
    """A permission reference for later RBAC primitives."""

    name: str
    description: str


class ReconciliationReference(_DomainModel):
    """A reconciliation reference for DB-backed workflows."""

    id: str = Field(default_factory=lambda: new_domain_id("REC"))
    workspace_id: str
    period_id: str
    account_id: str | None = None
    type: str = "account"
    status: str = "Draft"
    owner_user_id: str | None = None
    created_at: str = Field(default_factory=utc_now_text)


class EvidenceReference(_DomainModel):
    """A local evidence object reference."""

    id: str = Field(default_factory=lambda: new_domain_id("EVD"))
    workspace_id: str
    source_path: str
    checksum_sha256: str
    provenance_type: str
    redaction_status: str
    created_at: str = Field(default_factory=utc_now_text)


class AuditEventReference(_DomainModel):
    """An append-only audit event record reference."""

    id: str
    sequence: int = Field(ge=1)
    previous_hash: str
    event_hash: str
    actor_user_id: str | None = None
    actor_label: str
    object_type: str
    object_id: str
    action: str
    before_hash: str | None = None
    after_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
