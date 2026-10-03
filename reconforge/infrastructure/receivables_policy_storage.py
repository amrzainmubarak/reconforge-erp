"""Verify retained AR policy evidence before publishing a SQLite backup/restore."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.domain.finance_policy import POLICY_COLUMNS
from reconforge.domain.receivables_policy import (
    ReceivablesMonetaryPolicy,
    require_policy_affinity,
    verify_receivables_policy,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore


def verify_sqlite_receivables_policy_storage(connection: sqlite3.Connection) -> None:
    """Preserve all-null historical rows; reject partial, forged or mixed evidence."""

    columns = {row[1] for row in connection.execute("PRAGMA table_info(ar_customers)")}
    if "currency_precision" not in columns:
        return
    store = FinancePolicyStore(connection)
    records: dict[str, dict[str, dict[str, Any]]] = {}
    policies: dict[str, dict[str, ReceivablesMonetaryPolicy]] = {}
    for table in ("ar_customers", "ar_invoices", "ar_receipts"):
        records[table] = {}
        policies[table] = {}
        # Fixed internal table identifiers; no user-supplied SQL fragments.
        for row in connection.execute(f"SELECT * FROM {table}"):  # nosec B608
            record = dict(row)
            context = None
            if any(record[column] is not None for column in POLICY_COLUMNS):
                _, context = store.entry(record)
            policy = verify_receivables_policy(record, snapshot=context)
            records[table][record["id"]] = record
            policies[table][record["id"]] = policy
            if table != "ar_customers":
                parent = records["ar_customers"].get(record["customer_id"])
                if parent is None:
                    raise ValueError("AR policy parent is missing.")
                parent_policy = policies["ar_customers"][record["customer_id"]]
                if policy.captured is not None or parent_policy.captured is not None:
                    require_policy_affinity(policy, parent_policy)
                    if parent["workspace_id"] != record["workspace_id"]:
                        raise ValueError("AR policy workspace differs from its parent.")
    for row in connection.execute("SELECT * FROM ar_receipt_allocations"):
        receipt = records["ar_receipts"].get(row["receipt_id"])
        invoice = records["ar_invoices"].get(row["invoice_id"])
        if receipt is None or invoice is None:
            raise ValueError("AR allocation policy parent is missing.")
        receipt_policy = policies["ar_receipts"][row["receipt_id"]]
        invoice_policy = policies["ar_invoices"][row["invoice_id"]]
        if receipt_policy.captured is not None or invoice_policy.captured is not None:
            require_policy_affinity(receipt_policy, invoice_policy)
            if receipt["customer_id"] != invoice["customer_id"] or not (
                receipt["workspace_id"] == invoice["workspace_id"] == row["workspace_id"]
            ):
                raise ValueError("AR allocation policy parent scope differs.")
