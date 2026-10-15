"""Private, ordinary-role originals for actual Stock v2 / CR3 HTTPS cycles.

This observer issues SELECT statements only. It never creates an original sale,
posts a correction, returns raw proof through an API, or supplies financial math.
The independent monetary reader owns financial and audit-chain qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.io.structured import parse_json_document
from tests.customer_partial_return_monetary_posted_oracle import (
    MAX_CAPTURE_BYTES,
    MAX_PACKET_BYTES,
    SCHEMA,
    TABLES,
    decode_capture,
    decode_packet,
)
from tests.customer_partial_return_remainder_browser import _regular_path, _storage
from tests.customer_partial_returns_browser import LOAD_POLICY, _bytes, _read, _retain, _text, require
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

FAMILY = "native-customer-partial-return-monetary-originals"
OBSERVATIONS = "native-customer-partial-return-monetary-observation-originals"
REFUSED = "native-customer-partial-return-monetary-failed-observation-originals"
PACKET = "posted-cycle-input.json"
RESTORE = "posted-cycle-restored-input.json"
OBSERVATION_PACKET = "observations-input.json"
OBSERVATION_SCHEMA = "customer-partial-return-monetary-browser-observation-v1"
KINDS = {"RetainedReplay": "retained-replay.json", "ScopeRefusal": "scope-refusal.json", "FinalRead": "final-observation.json"}
HISTORY_VERSIONS = (0, 0, 0, 1, 2, 3, 4, 5, 6, 7)
AUDIT = frozenset({"domain_audit_events", "domain_audit_ledger_state"})
MAX_ROWS = 4096


def _root(root: Path, case: str) -> Path:
    require(type(case) is str and case in {"identity", "foreign"} and root.name == case and root.parent.name == FAMILY)
    return _storage(root)


def _files(root: Path) -> list[Path]:
    paths = []
    for path in root.iterdir():
        _regular_path(path)
        match = re.fullmatch(r"committed-capture-([0-9])\.json", path.name)
        require(match is not None or path.name in {PACKET, RESTORE})
        if match:
            paths.append(path)
    paths.sort(key=lambda item: item.name)
    require([path.name for path in paths] == [f"committed-capture-{index}.json" for index in range(len(paths))] and len(paths) <= 10)
    return paths


def _load(path: Path, *, index: int, tenant: str) -> dict[str, Any]:
    _regular_path(path)
    value = parse_json_document(_read(path, MAX_CAPTURE_BYTES).decode("utf-8"), policy=LOAD_POLICY, reject_fractional_numbers=True)
    decode_capture(value, index=index, tenant_id=tenant)
    return cast(dict[str, Any], value)


def _parents(connection: Any, tenant: str, source: str) -> None:
    rows = connection.execute("SELECT customer_id,invoice_id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s", (tenant, source)).fetchall()
    require(len(rows) == 1)
    parent = {key: rows[0][key] for key in ("customer_id", "invoice_id")}
    for table, identifier in (("ar_customers", parent["customer_id"]), ("ar_invoices", parent["invoice_id"]), ("stock_sales_orders", source)):
        if identifier is None:
            require(table == "ar_invoices")
            continue
        held = connection.execute(sql.SQL("SELECT id FROM reconforge.{} WHERE tenant_id=%s AND id=%s FOR SHARE").format(sql.Identifier(table)), (tenant, identifier)).fetchall()
        require(len(held) == 1)
    current = connection.execute("SELECT customer_id,invoice_id,source->>'schema_version' schema_version FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s", (tenant, source)).fetchone()
    require(current is not None and all(current[key] == parent[key] for key in parent) and current["schema_version"] == "stock-sales-monetary-order-v2")
    # A coherent audit prefix is frozen only after the actual business parents.
    audit = connection.execute("SELECT tenant_id FROM reconforge.domain_audit_ledger_state WHERE tenant_id=%s FOR SHARE", (tenant,)).fetchall()
    require(len(audit) == 1 and audit[0]["tenant_id"] == tenant)


def _snapshot(runtime: ReceiptRuntime, source: str, *, index: int) -> tuple[dict[str, Any], int]:
    require(type(index) is int and 0 <= index < len(HISTORY_VERSIONS))
    with runtime.actor("browser-poster") as (connection, _, _actor):
        flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
        require(flags is not None and all(type(flags[name]) is bool and not flags[name] for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication")))
        secured = connection.execute("""SELECT count(*) n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity
            AND c.relowner<>current_user::regrole""", (list(TABLES),)).fetchone()
        require(secured is not None and secured["n"] == 91)
        _parents(connection, runtime.tenant, _text(source))
        source_row = connection.execute("SELECT status FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s", (runtime.tenant, source)).fetchone()
        require(source_row is not None and source_row["status"] == ("Draft" if index == 0 else "Delivered" if index == 1 else "Invoiced"))
        versions = connection.execute("""SELECT h.sequence FROM reconforge.customer_partial_return_monetary_history h
            JOIN reconforge.stock_sales_monetary_origins o ON(o.tenant_id,o.id)=(h.tenant_id,h.origin_id)
            WHERE h.tenant_id=%s AND o.stock_order_id=%s ORDER BY h.sequence""", (runtime.tenant, source)).fetchall()
        require([row["sequence"] for row in versions] == list(range(1, HISTORY_VERSIONS[index] + 1)))
        tables = {}
        for name in TABLES:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text LIMIT 4097")
                                      .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
            require(len(rows) <= MAX_ROWS)
            tables[name] = [row["original"] for row in rows]
        value = {"capture": index, "tables": tables}
        decode_capture(value, index=index, tenant_id=runtime.tenant)
        return value, len(versions)


def _unchanged_business(before: dict[str, Any], after: dict[str, Any]) -> None:
    require(set(before) == set(after) == set(TABLES))
    require(all(before[name] == after[name] for name in TABLES if name not in AUDIT))
    # Retain every original audit row; independent C qualification proves the
    # canonical chain, chronological order and finite action/actor bindings.
    require(set(before["domain_audit_events"]) <= set(after["domain_audit_events"]))


def _plan_pin(connection: Any, tenant: str, source: str, plan: str, digest: str) -> None:
    require(type(plan) is str and re.fullmatch(r"(?:CR(?:3|F3|3R|F3R)|FX1)-[a-f0-9]{32}", plan) is not None)
    require(type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest) is not None)
    if plan.startswith("FX1-"):
        rows = connection.execute("""SELECT p.phase,p.plan_digest digest FROM reconforge.operational_fx_plans p
            JOIN reconforge.stock_sales_monetary_origins o ON(o.tenant_id,o.fx_source_id)=(p.tenant_id,p.source_id)
            WHERE p.tenant_id=%s AND p.id=%s AND o.stock_order_id=%s""", (tenant, plan, source)).fetchall()
    else:
        rows = connection.execute("""SELECT p.phase,p.payload->>'plan_digest' digest FROM reconforge.customer_partial_return_monetary_plans p
            JOIN reconforge.stock_sales_monetary_origins o ON(o.tenant_id,o.id)=(p.tenant_id,p.origin_id)
            WHERE p.tenant_id=%s AND p.id=%s AND o.stock_order_id=%s""", (tenant, plan, source)).fetchall()
    require(len(rows) == 1 and type(rows[0]["phase"]) is int and rows[0]["phase"] == 2 and rows[0]["digest"] == digest)


def capture_monetary_browser(runtime: ReceiptRuntime, source: str, root: Path, *, case: str, index: int,
                             observation: str | None = None, plan_id: str | None = None, plan_digest: str | None = None,
                             refusal: dict[str, Any] | None = None) -> dict[str, Any]:
    root = _root(root, case)
    files = _files(root)
    for number, path in enumerate(files):
        _load(path, index=number, tenant=runtime.tenant)
    value, version = _snapshot(runtime, source, index=index)
    if observation is None:
        require(index == len(files) and plan_id is None and plan_digest is None and refusal is None)
        _retain(root / f"committed-capture-{index}.json", _bytes(value, MAX_CAPTURE_BYTES))
        if index == 9:
            assemble_monetary_browser(root, case=case, tenant=runtime.tenant, source=source)
    else:
        require(observation in KINDS and index == (7 if observation == "RetainedReplay" else 9) and len(files) > index)
        require((plan_id is None and plan_digest is None) == (observation != "RetainedReplay"))
        if observation == "RetainedReplay":
            with runtime.actor("browser-poster") as (connection, _, _actor):
                _plan_pin(connection, runtime.tenant, source, str(plan_id), str(plan_digest))
        if observation == "ScopeRefusal":
            require(type(refusal) is dict and set(refusal) == {"operation", "status", "code"} and refusal["operation"] == "ReadSource"
                    and type(refusal["status"]) is int and refusal["status"] == 403 and type(refusal["code"]) is str
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", refusal["code"]) is not None)
        else:
            require(refusal is None)
        baseline = _load(root / f"committed-capture-{index}.json", index=index, tenant=runtime.tenant)
        envelope = {"schema_version": OBSERVATION_SCHEMA, "kind": observation, "tenant_id": runtime.tenant, "source_order_id": source,
                    "capture": index, "history_version": version, "plan_id": plan_id, "plan_digest": plan_digest, "tables": value["tables"], "refusal": refusal}
        folder = _storage(root.parent.parent / OBSERVATIONS / case)
        try:
            _unchanged_business(baseline["tables"], value["tables"])
            for path in folder.iterdir():
                _regular_path(path)
                require(path.name in {*KINDS.values(), OBSERVATION_PACKET})
            _retain(folder / KINDS[observation], _bytes(envelope, MAX_CAPTURE_BYTES + 4096), same_allowed=True)
        except (ValueError, TypeError, KeyError):
            failed = _storage(root.parent.parent / REFUSED / case)
            require(len(list(failed.iterdir())) < 16)
            _retain(failed / ("refused-" + uuid4().hex + ".json"), _bytes(envelope, MAX_CAPTURE_BYTES + 4096))
            raise ValueError("Private monetary browser observation refused.") from None
    return {"capture": index, "history_version": version, "tables": 91, "raw_financial_rows_published": False,
            "independent_financial_and_audit_verification_required": True}


def assemble_monetary_browser(root: Path, *, case: str, tenant: str, source: str) -> dict[str, Any]:
    root = _root(root, case)
    files = _files(root)
    require(len(files) == 10)
    value = {"schema_version": SCHEMA, "tenant_id": tenant, "source_order_id": source,
             "captures": [_load(path, index=index, tenant=tenant) for index, path in enumerate(files)]}
    raw = _bytes(value, MAX_PACKET_BYTES)
    decode_packet(raw)
    _retain(root / PACKET, raw, same_allowed=True)
    return value


def seed_monetary_browser(admin_dsn: str, app_dsn: str, *, case: str) -> ReceiptRuntime:
    """Genuine receipt and scoped master setup; the browser creates the sale."""
    require(case in {"identity", "foreign"})
    from tests.test_postgres_customer_returns import configure_runtime
    from tests.test_postgres_operational_fx_tax import seed_fx_masters
    from tests.test_postgres_stock_sales import create_stock_runtime
    runtime = create_stock_runtime((admin_dsn, app_dsn))
    configure_runtime(runtime)
    seed_fx_masters(runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "audit.verify", "users.manage", "roles.manage", "security.center.read", "security.policy.manage", "security.integrations.manage", "security.retention.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    seed_erp_browser_principals(runtime)
    return runtime


def _load_observation(path: Path, *, kind: str, tenant: str, source: str) -> dict[str, Any]:
    _regular_path(path)
    value = parse_json_document(_read(path, MAX_CAPTURE_BYTES + 4096).decode("utf-8"), policy=LOAD_POLICY, reject_fractional_numbers=True)
    require(type(value) is dict and set(value) == {"schema_version", "kind", "tenant_id", "source_order_id", "capture", "history_version", "plan_id", "plan_digest", "tables", "refusal"})
    row = cast(dict[str, Any], value)
    require(row["schema_version"] == OBSERVATION_SCHEMA and row["kind"] == kind and row["tenant_id"] == tenant and row["source_order_id"] == source)
    expected = 7 if kind == "RetainedReplay" else 9
    require(type(row["capture"]) is int and row["capture"] == expected and type(row["history_version"]) is int and row["history_version"] == HISTORY_VERSIONS[expected])
    decode_capture({"capture": expected, "tables": row["tables"]}, index=expected, tenant_id=tenant)
    if kind == "RetainedReplay":
        require(type(row["plan_id"]) is str and re.fullmatch(r"CRF3-[a-f0-9]{32}", row["plan_id"]) is not None
                and type(row["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", row["plan_digest"]) is not None and row["refusal"] is None)
    else:
        require(row["plan_id"] is None and row["plan_digest"] is None)
        if kind == "ScopeRefusal":
            refusal = row["refusal"]
            require(type(refusal) is dict and set(refusal) == {"operation", "status", "code"} and refusal["operation"] == "ReadSource"
                    and type(refusal["status"]) is int and refusal["status"] == 403 and type(refusal["code"]) is str
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", refusal["code"]) is not None)
        else:
            require(row["refusal"] is None)
    return row


def verify_seeded_monetary_browser(runtime: ReceiptRuntime, *, custody_root: Path, case: str, original_app_dsn: str) -> dict[str, Any]:
    """Bind the browser-created identity from its sealed packet, including restore."""
    root = _root(custody_root, case)
    packet = decode_packet(_read(root / PACKET, MAX_PACKET_BYTES))
    require(packet.tenant_id == runtime.tenant and len(packet.captures) == 10)
    source = packet.source_order_id
    assemble_monetary_browser(root, case=case, tenant=runtime.tenant, source=source)
    if runtime.factory.settings.dsn == original_app_dsn:
        capture_monetary_browser(runtime, source, root, case=case, index=9, observation="FinalRead")
    folder = _storage(root.parent.parent / OBSERVATIONS / case)
    require({path.name for path in folder.iterdir()} in (set(KINDS.values()), {*KINDS.values(), OBSERVATION_PACKET}))
    values = [_load_observation(folder / name, kind=kind, tenant=runtime.tenant, source=source) for kind, name in KINDS.items()]
    for value in values:
        before = _load(root / f"committed-capture-{value['capture']}.json", index=value["capture"], tenant=runtime.tenant)
        _unchanged_business(before["tables"], value["tables"])
    observations = {"schema_version": "customer-partial-return-monetary-posted-observations-input-v1", "tenant_id": runtime.tenant,
                    "source_order_id": source, "observations": values}
    _retain(folder / OBSERVATION_PACKET, _bytes(observations, MAX_PACKET_BYTES), same_allowed=True)
    final, version = _snapshot(runtime, source, index=9)
    require(final["tables"] == values[-1]["tables"] and version == 7)
    if runtime.factory.settings.dsn != original_app_dsn:
        restored = {"schema_version": "customer-partial-return-monetary-posted-restored-input-v1", "tenant_id": runtime.tenant,
                    "source_order_id": source, "tables": final["tables"]}
        _retain(root / RESTORE, _bytes(restored, MAX_CAPTURE_BYTES), same_allowed=True)
    return {"schema_version": "customer-partial-return-monetary-browser-custody-proof-v1", "captures": 10, "history_version": 7,
            "tables": [{"table": name, "rows": len(final["tables"][name]), "sha256": hashlib.sha256(_bytes(final["tables"][name], MAX_CAPTURE_BYTES)).hexdigest()} for name in TABLES],
            "raw_financial_rows_published": False, "independent_financial_and_audit_verification_required": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture",))
    parser.parse_args()
    try:
        runtime = ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=os.environ["RECONFORGE_GFO_APP_DSN"], require_tls=False)),
                                 "", os.environ["RECONFORGE_ERP_TENANT"], os.environ["RECONFORGE_ERP_PASSWORD"])
        refusal = None
        kind = os.environ.get("RECONFORGE_MONETARY_OBSERVATION")
        if kind == "ScopeRefusal":
            refusal = {"operation": "ReadSource", "status": int(os.environ["RECONFORGE_MONETARY_REFUSAL_STATUS"]), "code": os.environ["RECONFORGE_MONETARY_REFUSAL_CODE"]}
        capture_monetary_browser(runtime, os.environ["RECONFORGE_MONETARY_STOCK_SOURCE"], Path(os.environ["RECONFORGE_MONETARY_CUSTODY_ROOT"]),
            case=os.environ["RECONFORGE_MONETARY_CASE"], index=int(os.environ["RECONFORGE_MONETARY_CAPTURE"]), observation=kind,
            plan_id=os.environ.get("RECONFORGE_MONETARY_POSTED_PLAN"), plan_digest=os.environ.get("RECONFORGE_MONETARY_POSTED_DIGEST"), refusal=refusal)
    except Exception:
        print("Private monetary committed-row observation refused.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
