"""Owned HTTPS fixture and PRIVATE committed-row custody for the CR2 cycle.

The browser invokes this test-only observer after a successful POST response.
It never exposes a production proof endpoint or submits a financial command.
The separate stdlib-only posted-cycle reader supplies financial expectations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.io.structured import StructuredDocumentPolicy, parse_json_document
from tests.customer_partial_return_posted_cycle_oracle import TABLES
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

CUSTOMER_PARTIAL_RETURN_TABLES = TABLES
CUSTOMER_PARTIAL_RETURN_WORKSPACE_TABLES = tuple(name for name in TABLES if name not in {"domain_audit_events", "domain_audit_ledger_state"})
CUSTOMER_PARTIAL_RETURN_TAMPER = (
    "UPDATE reconforge.customer_partial_return_plans SET credit_minor=credit_minor+1 WHERE tenant_id=%s",
    "DELETE FROM reconforge.customer_partial_return_history WHERE tenant_id=%s",
    "UPDATE reconforge.customer_partial_return_restorations SET value_minor=value_minor+1 WHERE tenant_id=%s",
)
CAPTURE_NAME = re.compile(r"committed-capture-([0-8])\.json")
PACKET_NAME = "posted-cycle-input.json"
RESTORE_NAME = "posted-cycle-restored-input.json"
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_PACKET_BYTES = 32 * 1024 * 1024
MAX_ROWS = 4096
LOAD_POLICY = StructuredDocumentPolicy(max_file_bytes=MAX_PACKET_BYTES, max_nodes=100_000, max_depth=8,
                                       max_collection_items=4096, max_scalar_characters=MAX_CAPTURE_BYTES)


class PartialBrowserCustodyError(ValueError):
    """A constant diagnostic contains no private original or credential."""


def require(condition: bool) -> None:
    if not condition:
        raise PartialBrowserCustodyError("Partial-return committed browser custody refused.")


def _text(value: Any) -> str:
    require(type(value) is str and 0 < len(value) <= 200 and value == value.strip())
    return str(value)


def _regular_path(path: Path, *, directory: bool = False) -> None:
    for item in (path, *path.parents):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)())
    if path.exists():
        require(path.is_dir() if directory else path.is_file())


def _storage(root: Path) -> Path:
    _regular_path(root, directory=True)
    root.mkdir(parents=True, exist_ok=True)
    _regular_path(root, directory=True)
    return root


def _read(path: Path, maximum: int) -> bytes:
    _regular_path(path)
    with path.open("rb") as stream:
        original = stream.read(maximum + 1)
    require(len(original) <= maximum)
    return original


def _bytes(value: Any, maximum: int) -> bytes:
    original = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    require(len(original) <= maximum)
    return original


def _retain(path: Path, original: bytes, *, same_allowed: bool = False) -> None:
    """Publish one complete file atomically, without replacing any original."""
    _regular_path(path)
    if path.exists():
        require(same_allowed and _read(path, len(original)) == original)
        return
    temporary = path.parent / (".pending-" + uuid4().hex)
    _regular_path(temporary)
    try:
        with temporary.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link atomically admits complete bytes and refuses replacement.
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            require(same_allowed and _read(path, len(original)) == original)
        require(_read(path, len(original)) == original)
    finally:
        if temporary.exists():
            _regular_path(temporary)
            temporary.unlink()


def _capture_files(root: Path) -> list[Path]:
    files = []
    for path in root.iterdir():
        _regular_path(path)
        match = CAPTURE_NAME.fullmatch(path.name)
        require(match is not None or path.name in {PACKET_NAME, RESTORE_NAME})
        if match is not None:
            files.append(path)
    files.sort(key=lambda path: path.name)
    require([path.name for path in files] == [f"committed-capture-{number}.json" for number in range(len(files))])
    require(len(files) <= 9)
    return files


def _validate_tables(value: Any) -> dict[str, list[str]]:
    require(type(value) is dict and set(value) == set(TABLES))
    result = {}
    for name in TABLES:
        rows = value[name]
        require(type(rows) is list and len(rows) <= MAX_ROWS and all(type(row) is str for row in rows))
        require(rows == sorted(rows) and len(set(rows)) == len(rows))
        result[name] = list(rows)
    return result


def _load_capture(path: Path) -> dict[str, Any]:
    decoded = parse_json_document(_read(path, MAX_CAPTURE_BYTES).decode("utf-8"), policy=LOAD_POLICY, reject_fractional_numbers=True)
    require(type(decoded) is dict)
    value = cast(dict[str, Any], decoded)
    require(set(value) == {"schema_version", "tenant_id", "source_order_id", "history_version", "posted_plan_id", "plan_digest", "tables"})
    require(value["schema_version"] == "customer-partial-return-browser-capture-v1")
    _text(value["tenant_id"])
    _text(value["source_order_id"])
    require(type(value["history_version"]) is int and 0 <= value["history_version"] <= 8)
    if value["history_version"] == 0:
        require(value["posted_plan_id"] is None and value["plan_digest"] is None)
    else:
        _text(value["posted_plan_id"])
        require(type(value["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["plan_digest"]) is not None)
    value["tables"] = _validate_tables(value["tables"])
    return dict(value)


def _original_locks(connection: Any, tenant: str, source_order_id: str) -> None:
    rows = connection.execute("SELECT customer_id,invoice_id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s", (tenant, source_order_id)).fetchall()
    require(len(rows) == 1)
    source = rows[0]
    # Preserve the actual shared operational parent lock order while observing.
    for table, identifier in (("ar_customers", source["customer_id"]), ("ar_invoices", source["invoice_id"]), ("stock_sales_orders", source_order_id)):
        held = connection.execute(sql.SQL("SELECT id FROM reconforge.{} WHERE tenant_id=%s AND id=%s FOR SHARE").format(sql.Identifier(table)), (tenant, identifier)).fetchall()
        require(len(held) == 1)


def _snapshot(runtime: ReceiptRuntime, source_order_id: str) -> tuple[int, dict[str, list[str]], dict[str, Any] | None]:
    with runtime.actor("browser-poster") as (connection, _, _actor):
        flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
        flag_names = ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication")
        require(flags is not None and len(flags) == 5 and all(type(flags[name]) is bool and not flags[name] for name in flag_names))
        secured = connection.execute("""SELECT count(*) n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity
              AND c.relowner<>current_user::regrole""", (list(TABLES),)).fetchone()
        require(secured is not None and secured["n"] == len(TABLES))
        _original_locks(connection, runtime.tenant, source_order_id)
        history = connection.execute("""SELECT h.sequence,h.plan_id,p.plan_digest,p.phase FROM reconforge.customer_partial_return_history h
            JOIN reconforge.customer_partial_return_sources s ON(s.tenant_id,s.id)=(h.tenant_id,h.source_id)
            LEFT JOIN reconforge.customer_partial_return_plans p ON(p.tenant_id,p.id)=(h.tenant_id,h.plan_id)
            WHERE h.tenant_id=%s AND s.source_order_id=%s ORDER BY h.sequence""", (runtime.tenant, source_order_id)).fetchall()
        require([row["sequence"] for row in history] == list(range(1, len(history) + 1)) and len(history) <= 8)
        tables = {}
        for name in TABLES:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text LIMIT 4097").format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
            require(len(rows) <= MAX_ROWS)
            tables[name] = sorted(row["original"] for row in rows)
        current = {key: history[-1][key] for key in ("sequence", "plan_id", "plan_digest", "phase")} if history else None
        return len(history), _validate_tables(tables), current


def capture_customer_partial_returns(runtime: ReceiptRuntime, source_order_id: str, root: Path, *,
                                    posted_plan_id: str | None = None, plan_digest: str | None = None) -> dict[str, Any]:
    root = _storage(root)
    files = _capture_files(root)
    for number, path in enumerate(files):
        previous = _load_capture(path)
        require(previous["tenant_id"] == runtime.tenant and previous["source_order_id"] == source_order_id
                and previous["history_version"] == number)
    version, tables, last = _snapshot(runtime, _text(source_order_id))
    require((last is None and posted_plan_id is None and plan_digest is None and version == 0)
            or (last is not None and last["phase"] == 2 and last["plan_id"] == posted_plan_id and last["plan_digest"] == plan_digest))
    require(version in {len(files), len(files) - 1})
    packet = {"schema_version": "customer-partial-return-browser-capture-v1", "tenant_id": runtime.tenant,
              "source_order_id": source_order_id, "history_version": version, "posted_plan_id": posted_plan_id,
              "plan_digest": plan_digest, "tables": tables}
    original = _bytes(packet, MAX_CAPTURE_BYTES)
    _retain(root / f"committed-capture-{version}.json", original, same_allowed=version == len(files) - 1)
    return {"history_version": version, "tables": len(TABLES), "original_bytes": len(original),
            "original_sha256": hashlib.sha256(original).hexdigest(), "raw_rows_published": False}


def assemble_customer_partial_return_inputs(root: Path, *, tenant: str, source_order_id: str) -> dict[str, Any]:
    root = _storage(root)
    files = _capture_files(root)
    require(len(files) == 9)
    captures = []
    for number, path in enumerate(files):
        value = _load_capture(path)
        require(value["tenant_id"] == tenant and value["source_order_id"] == source_order_id and value["history_version"] == number)
        captures.append(value["tables"])
    packet = {"schema_version": "customer-partial-return-posted-cycle-input-v1", "tenant_id": tenant,
              "source_order_id": source_order_id, "captures": captures}
    _retain(root / PACKET_NAME, _bytes(packet, MAX_PACKET_BYTES), same_allowed=True)
    return packet


def seed_customer_partial_returns_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    from tests.test_postgres_customer_partial_return_source import create_two_layer_source
    runtime, _source, _invoice = create_two_layer_source((admin_dsn, app_dsn))
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    seed_erp_browser_principals(runtime)
    return runtime


def customer_partial_returns_browser_source(runtime: ReceiptRuntime) -> str:
    with runtime.actor("browser-poster") as (connection, _, _actor):
        rows = connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND invoice_id IS NOT NULL", (runtime.tenant,)).fetchall()
        require(len(rows) == 1)
        return str(rows[0]["id"])


def verify_customer_partial_returns_browser(runtime: ReceiptRuntime, *, custody_root: Path, original_app_dsn: str) -> dict[str, Any]:
    source = customer_partial_returns_browser_source(runtime)
    packet = assemble_customer_partial_return_inputs(custody_root, tenant=runtime.tenant, source_order_id=source)
    version, tables, _last = _snapshot(runtime, source)
    require(version == 8 and tables == packet["captures"][-1])
    if runtime.factory.settings.dsn != original_app_dsn:
        restored = {"schema_version": "customer-partial-return-posted-restore-input-v1", "tenant_id": runtime.tenant,
                    "source_order_id": source, "capture": tables}
        _retain(custody_root / RESTORE_NAME, _bytes(restored, MAX_CAPTURE_BYTES), same_allowed=True)
    # Stable row identities must compare equal on original and restored calls.
    return {"schema_version": "customer-partial-return-browser-custody-proof-v1", "history_version": version,
            "tables": [{"table": name, "rows": len(tables[name]), "sha256": hashlib.sha256(_bytes(tables[name], MAX_CAPTURE_BYTES)).hexdigest()} for name in TABLES],
            "raw_financial_rows_published": False, "independent_financial_verification_required": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture",))
    parser.parse_args()
    try:
        runtime = ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=os.environ["RECONFORGE_GFO_APP_DSN"], require_tls=False)),
                                 "", os.environ["RECONFORGE_ERP_TENANT"], os.environ["RECONFORGE_ERP_PASSWORD"])
        capture_customer_partial_returns(runtime, os.environ["RECONFORGE_CUSTOMER_PARTIAL_RETURN_SOURCE"],
            Path(os.environ["RECONFORGE_PARTIAL_CUSTODY_ROOT"]), posted_plan_id=os.environ["RECONFORGE_PARTIAL_POSTED_PLAN"],
            plan_digest=os.environ["RECONFORGE_PARTIAL_POSTED_DIGEST"])
    except Exception:
        # Never print a connection exception, DSN, original row or actor body.
        print("Committed partial-return browser observation refused.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
