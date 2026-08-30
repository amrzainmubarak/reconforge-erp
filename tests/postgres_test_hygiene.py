"""Narrow, admin-only cleanup for synthetic PostgreSQL integration-test tenants.

These helpers deliberately live in ``tests`` rather than product code.  They
delete only rows bearing explicitly supplied, per-test tenant identifiers and
never truncate a table or use a broad ``CASCADE`` operation.  Immutable
evidence triggers are disabled only for the cleanup transaction.  If a delete
or residual assertion fails, PostgreSQL rolls the transaction back, including
the preceding trigger-state change, and the failure is allowed to reach pytest.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")
_TENANT_COLUMN = re.compile(r"(?:id|tenant_id)\Z")


@dataclass(frozen=True)
class TenantScopedTable:
    """One known test table and its tenant discriminator column."""

    name: str
    tenant_column: str = "tenant_id"

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.name):
            raise ValueError(f"Unsafe PostgreSQL test table identifier: {self.name!r}")
        if not _TENANT_COLUMN.fullmatch(self.tenant_column):
            raise ValueError(f"Unsafe PostgreSQL tenant column: {self.tenant_column!r}")


@dataclass(frozen=True)
class ImmutableTrigger:
    """An append-only trigger that test cleanup may suspend transactionally."""

    table_name: str
    trigger_name: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.table_name):
            raise ValueError(f"Unsafe PostgreSQL test table identifier: {self.table_name!r}")
        if not _IDENTIFIER.fullmatch(self.trigger_name):
            raise ValueError(f"Unsafe PostgreSQL trigger identifier: {self.trigger_name!r}")


@dataclass(frozen=True)
class PostgresTenantCleanupPlan:
    """Child-first, test-owned rows required to remove one synthetic tenant."""

    tables: tuple[TenantScopedTable, ...]
    immutable_triggers: tuple[ImmutableTrigger, ...] = ()


_TENANTS = TenantScopedTable("tenants", "id")
_DOMAIN_AUDIT_TRIGGER = ImmutableTrigger("domain_audit_events", "domain_audit_events_immutable")


RLS_TENANT_CLEANUP_PLAN = PostgresTenantCleanupPlan(tables=(_TENANTS,))

PAYABLES_TENANT_CLEANUP_PLAN = PostgresTenantCleanupPlan(
    tables=(
        TenantScopedTable("domain_audit_events"),
        TenantScopedTable("outbox_events"),
        TenantScopedTable("control_exceptions"),
        TenantScopedTable("ap_three_way_matches"),
        TenantScopedTable("ap_supplier_invoice_lines"),
        TenantScopedTable("ap_supplier_invoices"),
        TenantScopedTable("ap_goods_receipt_lines"),
        TenantScopedTable("ap_goods_receipts"),
        TenantScopedTable("ap_purchase_order_lines"),
        TenantScopedTable("ap_purchase_orders"),
        TenantScopedTable("ap_suppliers"),
        TenantScopedTable("ap_idempotency_keys"),
        TenantScopedTable("domain_audit_ledger_state"),
        TenantScopedTable("domain_workspaces"),
        TenantScopedTable("currencies"),
        _TENANTS,
    ),
    immutable_triggers=(_DOMAIN_AUDIT_TRIGGER,),
)

RECEIVABLES_TENANT_CLEANUP_PLAN = PostgresTenantCleanupPlan(
    tables=(
        TenantScopedTable("domain_audit_events"),
        TenantScopedTable("outbox_events"),
        TenantScopedTable("ar_receipt_allocations"),
        TenantScopedTable("ar_receipts"),
        TenantScopedTable("ar_invoice_lines"),
        TenantScopedTable("ar_invoices"),
        TenantScopedTable("ar_customers"),
        TenantScopedTable("ar_idempotency_keys"),
        TenantScopedTable("domain_audit_ledger_state"),
        TenantScopedTable("domain_workspaces"),
        TenantScopedTable("currencies"),
        _TENANTS,
    ),
    immutable_triggers=(
        _DOMAIN_AUDIT_TRIGGER,
        ImmutableTrigger("ar_invoice_lines", "ar_invoice_line_update_blocked"),
    ),
)

DURABLE_JOB_TENANT_CLEANUP_PLAN = PostgresTenantCleanupPlan(
    tables=(
        TenantScopedTable("durable_job_partition_effects"),
        TenantScopedTable("durable_job_lease_events"),
        TenantScopedTable("durable_job_leases"),
        TenantScopedTable("durable_job_transitions"),
        TenantScopedTable("durable_job_scheduler_cursors"),
        TenantScopedTable("durable_jobs"),
        _TENANTS,
    ),
    immutable_triggers=(
        ImmutableTrigger("durable_job_partition_effects", "durable_job_partition_effects_immutable"),
        ImmutableTrigger("durable_job_lease_events", "durable_job_lease_events_immutable"),
        ImmutableTrigger("durable_job_transitions", "durable_job_transitions_immutable"),
    ),
)


def _table_exists(admin: Any, table: TenantScopedTable) -> bool:
    row = admin.execute("SELECT to_regclass(%s)", (f"reconforge.{table.name}",)).fetchone()
    return row is not None and row[0] is not None


def cleanup_postgres_test_tenants_as_admin(
    admin: Any,
    *,
    tenant_ids: Iterable[str],
    plan: PostgresTenantCleanupPlan,
) -> None:
    """Remove only the explicitly named synthetic tenant rows through ``admin``.

    The caller must pass the dedicated admin connection, never the application
    connection under RLS.  The table order is child-first.  A failing cleanup is
    intentionally not caught: the surrounding transaction rolls back trigger
    state and pytest receives the actual database error.
    """

    scoped_tenants = tuple(dict.fromkeys(tenant_ids))
    if not scoped_tenants:
        return
    if any(not tenant_id for tenant_id in scoped_tenants):
        raise ValueError("PostgreSQL test cleanup requires non-empty tenant identifiers.")

    tenant_array = list(scoped_tenants)
    with admin.transaction():
        available_tables = {table.name: _table_exists(admin, table) for table in plan.tables}
        disabled_triggers: list[ImmutableTrigger] = []
        for trigger in plan.immutable_triggers:
            if available_tables.get(trigger.table_name, False):
                admin.execute(
                    f"ALTER TABLE reconforge.{trigger.table_name} DISABLE TRIGGER {trigger.trigger_name}"
                )
                disabled_triggers.append(trigger)

        for table in plan.tables:
            if available_tables[table.name]:
                admin.execute(
                    f"DELETE FROM reconforge.{table.name} WHERE {table.tenant_column} = ANY(%s)",
                    (tenant_array,),
                )

        # The durable-job effects FK is deferred.  PostgreSQL cannot alter a
        # trigger table while those pending trigger events exist, so force the
        # cleanup deletion graph to be checked before restoring immutability.
        # A violation raises here and rolls back the complete cleanup
        # transaction, including every trigger-state change above.
        if disabled_triggers:
            admin.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for trigger in reversed(disabled_triggers):
            admin.execute(
                f"ALTER TABLE reconforge.{trigger.table_name} ENABLE TRIGGER {trigger.trigger_name}"
            )

        residuals: list[str] = []
        for table in plan.tables:
            if not available_tables[table.name]:
                continue
            rows = admin.execute(
                f"SELECT {table.tenant_column}, COUNT(*) FROM reconforge.{table.name} "
                f"WHERE {table.tenant_column} = ANY(%s) GROUP BY {table.tenant_column} "
                f"ORDER BY {table.tenant_column}",
                (tenant_array,),
            ).fetchall()
            residuals.extend(f"{table.name}:{tenant_id}={count}" for tenant_id, count in rows)
        if residuals:
            raise AssertionError("PostgreSQL test cleanup left scoped rows: " + ", ".join(residuals))
