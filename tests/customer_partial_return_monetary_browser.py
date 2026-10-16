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
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from psycopg import Error as PostgresError
from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.io.structured import parse_json_document
from tests.customer_partial_return_monetary_posted_oracle import (
    MAX_CAPTURE_BYTES as MAX_CAPTURE_BYTES,
)
from tests.customer_partial_return_monetary_posted_oracle import (
    MAX_CAPTURE_ENVELOPE_BYTES,
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
FOREIGN_HISTORY_VERSIONS = (0, 0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7)
REFUSED_REQUEST = "active-valuation-refused-request.json"
AUDIT = frozenset({"domain_audit_events", "domain_audit_ledger_state"})
MAX_ROWS = 4096
CAPTURE_FILE_BYTES = MAX_CAPTURE_ENVELOPE_BYTES + 1  # Retained final LF.
OBSERVATION_FILE_BYTES = MAX_CAPTURE_ENVELOPE_BYTES + 4096  # Closed identity/refusal metadata and LF.
FAILURE_TRACE_BYTES = 8192
_FAILURE_STAGES = {"main": "capture_dispatch", "_root": "custody_boundary", "_files": "custody_membership",
                   "_load": "existing_capture_decode", "_snapshot": "snapshot_read", "_plan_pin": "posted_plan_affinity",
                   "_unchanged_business": "observation_business_binding", "_request_pin": "refused_request_binding",
                   "capture_monetary_browser": "capture_contract", "assemble_monetary_browser": "packet_assembly"}


def _capture_failure(error: Exception) -> dict[str, Any]:
    """Retain the raw failure privately; publish only a closed diagnostic."""
    cause = "observation_contract_refused" if isinstance(error, (ValueError, TypeError, KeyError)) else "observer_failed"
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, PostgresError):
            cause = {"57014": "statement_cancelled", "42501": "permission_denied", "23514": "native_constraint_refused",
                     "55P03": "lock_unavailable", "40P01": "deadlock_refused", "40001": "serialization_refused"}.get(current.sqlstate or "", "database_failure")
            break
        current = current.__cause__ or current.__context__
    stage, line = "capture_dispatch", 0
    frame = error.__traceback__
    while frame is not None:
        if frame.tb_frame.f_globals.get("__name__") == __name__ and frame.tb_frame.f_code.co_name in _FAILURE_STAGES:
            stage, line = _FAILURE_STAGES[frame.tb_frame.f_code.co_name], frame.tb_lineno
        frame = frame.tb_next
    result: dict[str, Any] = {"schema_version": "monetary-capture-python-failure-v1", "cause": cause, "stage": stage,
                              "line": line, "trace_retained": False, "trace_bytes": 0, "trace_sha256": None, "trace_truncated": False}
    try:
        root = _root(Path(os.environ["RECONFORGE_MONETARY_CUSTODY_ROOT"]), os.environ["RECONFORGE_MONETARY_CASE"])
        failed = _storage(root.parent.parent / REFUSED / root.name)
        require(len(list(failed.iterdir())) < 16)
        original = "".join(traceback.format_exception(error)).encode("utf-8", errors="replace")
        raw = original[:FAILURE_TRACE_BYTES]
        _retain(failed / ("capture-python-" + uuid4().hex + ".traceback.bin"), raw)
        result.update(trace_retained=True, trace_bytes=len(raw), trace_sha256=hashlib.sha256(raw).hexdigest(),
                      trace_truncated=len(original) > len(raw))
    except Exception:
        # Diagnostics must never replace the original failure with a path,
        # credential, raw SQL exception, or a successful capture indication.
        result["trace_retained"] = False
    return result


def _versions(case: str) -> tuple[int, ...]:
    require(case in {"identity", "foreign"})
    return FOREIGN_HISTORY_VERSIONS if case == "foreign" else HISTORY_VERSIONS


def _kinds(case: str) -> dict[str, str]:
    return {"ActiveValuationRefusal": "active-valuation-refusal.json", **KINDS} if case == "foreign" else dict(KINDS)


def _observation_index(case: str, kind: str) -> int:
    require(kind in _kinds(case))
    return 5 if kind == "ActiveValuationRefusal" else len(_versions(case)) - (3 if kind == "RetainedReplay" else 1)


def _root(root: Path, case: str) -> Path:
    require(type(case) is str and case in {"identity", "foreign"} and root.name == case and root.parent.name == FAMILY)
    return _storage(root)


def _files(root: Path) -> list[Path]:
    paths = []
    for path in root.iterdir():
        _regular_path(path)
        match = re.fullmatch(r"committed-capture-([0-9]|1[01])\.json", path.name)
        require(match is not None or path.name in {PACKET, RESTORE})
        if match:
            paths.append(path)
    paths.sort(key=lambda item: int(item.stem.removeprefix("committed-capture-")))
    require([path.name for path in paths] == [f"committed-capture-{index}.json" for index in range(len(paths))] and len(paths) <= len(_versions(root.name)))
    return paths


def _load(path: Path, *, index: int, tenant: str) -> dict[str, Any]:
    _regular_path(path)
    value = parse_json_document(_read(path, CAPTURE_FILE_BYTES).decode("utf-8"), policy=LOAD_POLICY, reject_fractional_numbers=True)
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


def _snapshot(runtime: ReceiptRuntime, source: str, *, index: int, case: str) -> tuple[dict[str, Any], int]:
    require(type(index) is int and 0 <= index < len(_versions(case)))
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
        require([row["sequence"] for row in versions] == list(range(1, _versions(case)[index] + 1)))
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
        rows = connection.execute("""SELECT p.phase,p.payload->>'plan_digest' digest FROM reconforge.operational_fx_plans p
            JOIN reconforge.stock_sales_monetary_origins o ON(o.tenant_id,o.fx_source_id)=(p.tenant_id,p.source_id)
            WHERE p.tenant_id=%s AND p.id=%s AND o.stock_order_id=%s""", (tenant, plan, source)).fetchall()
    else:
        rows = connection.execute("""SELECT p.phase,p.payload->>'plan_digest' digest FROM reconforge.customer_partial_return_monetary_plans p
            JOIN reconforge.stock_sales_monetary_origins o ON(o.tenant_id,o.id)=(p.tenant_id,p.origin_id)
            WHERE p.tenant_id=%s AND p.id=%s AND o.stock_order_id=%s""", (tenant, plan, source)).fetchall()
    require(len(rows) == 1 and type(rows[0]["phase"]) is int and rows[0]["phase"] == 2 and rows[0]["digest"] == digest)


def capture_monetary_browser(runtime: ReceiptRuntime, source: str, root: Path, *, case: str, index: int,
                             observation: str | None = None, plan_id: str | None = None, plan_digest: str | None = None,
                             refusal: dict[str, Any] | None = None, request: dict[str, Any] | None = None) -> dict[str, Any]:
    root = _root(root, case)
    files = _files(root)
    for number, path in enumerate(files):
        _load(path, index=number, tenant=runtime.tenant)
    value, version = _snapshot(runtime, source, index=index, case=case)
    if observation is None:
        require(index == len(files) and plan_id is None and plan_digest is None and refusal is None and request is None)
        _retain(root / f"committed-capture-{index}.json", _bytes(value, CAPTURE_FILE_BYTES))
        if index == len(_versions(case)) - 1:
            assemble_monetary_browser(root, case=case, tenant=runtime.tenant, source=source)
    else:
        require(observation in _kinds(case) and index == _observation_index(case, observation) and len(files) > index)
        require((plan_id is None and plan_digest is None) == (observation not in {"RetainedReplay", "ActiveValuationRefusal"}))
        if observation in {"RetainedReplay", "ActiveValuationRefusal"}:
            with runtime.actor("browser-poster") as (connection, _, _actor):
                _plan_pin(connection, runtime.tenant, source, str(plan_id), str(plan_digest))
        if observation in {"ScopeRefusal", "ActiveValuationRefusal"}:
            require(type(refusal) is dict and set(refusal) == {"operation", "status", "code"}
                    and refusal["operation"] == ("PrepareReturn" if observation == "ActiveValuationRefusal" else "ReadSource")
                    and type(refusal["status"]) is int and refusal["status"] == (409 if observation == "ActiveValuationRefusal" else 403) and type(refusal["code"]) is str
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", refusal["code"]) is not None)
        else:
            require(refusal is None)
        baseline = _load(root / f"committed-capture-{index}.json", index=index, tenant=runtime.tenant)
        envelope = {"schema_version": OBSERVATION_SCHEMA, "kind": observation, "tenant_id": runtime.tenant, "source_order_id": source,
                    "capture": index, "history_version": version, "plan_id": plan_id, "plan_digest": plan_digest, "tables": value["tables"], "refusal": refusal}
        folder = _storage(root.parent.parent / OBSERVATIONS / case)
        try:
            _unchanged_business(baseline["tables"], value["tables"])
            if observation == "ActiveValuationRefusal":
                _request_pin(request, source)
                _retain(folder / REFUSED_REQUEST, _bytes(request, 8192), same_allowed=True)
            else:
                require(request is None)
            for path in folder.iterdir():
                _regular_path(path)
                require(path.name in {*_kinds(case).values(), OBSERVATION_PACKET, *({REFUSED_REQUEST} if case == "foreign" else set())})
            _retain(folder / _kinds(case)[observation], _bytes(envelope, OBSERVATION_FILE_BYTES), same_allowed=True)
        except (ValueError, TypeError, KeyError):
            failed = _storage(root.parent.parent / REFUSED / case)
            require(len(list(failed.iterdir())) < 16)
            suffix = uuid4().hex
            _retain(failed / ("refused-" + suffix + ".json"), _bytes(envelope, OBSERVATION_FILE_BYTES))
            if request is not None:
                _retain(failed / ("refused-request-" + suffix + ".json"), _bytes(request, 8192))
            raise ValueError("Private monetary browser observation refused.") from None
    return {"capture": index, "history_version": version, "tables": 91, "raw_financial_rows_published": False,
            "independent_financial_and_audit_verification_required": True}


def assemble_monetary_browser(root: Path, *, case: str, tenant: str, source: str) -> dict[str, Any]:
    root = _root(root, case)
    files = _files(root)
    require(len(files) == len(_versions(case)))
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


def _request_pin(value: Any, source: str) -> None:
    require(type(value) is dict and set(value) == {"method", "route", "body"}
            and value["method"] == "POST" and value["route"] == "/api/v3/customer-partial-returns/plans")
    body = value["body"]
    require(type(body) is dict and set(body) == {"command_id", "source_order_id", "quantity_scaled", "period_id", "posting_date", "reason", "expected_history_version"}
            and body["source_order_id"] == source and body["quantity_scaled"] == "4"
            and type(body["expected_history_version"]) is int and body["expected_history_version"] == 2)
    for name, maximum in (("command_id", 140), ("period_id", 160), ("posting_date", 10), ("reason", 500)):
        require(type(body[name]) is str and 0 < len(body[name]) <= maximum and body[name] == body[name].strip() and all(ord(char) >= 32 and ord(char) != 127 for char in body[name]))
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", body["posting_date"]) is not None
            and date.fromisoformat(body["posting_date"]).isoformat() == body["posting_date"])


def _load_observation(path: Path, *, kind: str, tenant: str, source: str, case: str) -> dict[str, Any]:
    _regular_path(path)
    value = parse_json_document(_read(path, OBSERVATION_FILE_BYTES).decode("utf-8"), policy=LOAD_POLICY, reject_fractional_numbers=True)
    require(type(value) is dict and set(value) == {"schema_version", "kind", "tenant_id", "source_order_id", "capture", "history_version", "plan_id", "plan_digest", "tables", "refusal"})
    row = cast(dict[str, Any], value)
    require(row["schema_version"] == OBSERVATION_SCHEMA and row["kind"] == kind and row["tenant_id"] == tenant and row["source_order_id"] == source)
    expected = _observation_index(case, kind)
    require(type(row["capture"]) is int and row["capture"] == expected and type(row["history_version"]) is int and row["history_version"] == _versions(case)[expected])
    decode_capture({"capture": expected, "tables": row["tables"]}, index=expected, tenant_id=tenant)
    if kind in {"RetainedReplay", "ActiveValuationRefusal"}:
        prefix = "FX1" if kind == "ActiveValuationRefusal" else "CRF3"
        require(type(row["plan_id"]) is str and re.fullmatch(prefix + r"-[a-f0-9]{32}", row["plan_id"]) is not None
                and type(row["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", row["plan_digest"]) is not None)
    else:
        require(row["plan_id"] is None and row["plan_digest"] is None)
    if kind in {"ScopeRefusal", "ActiveValuationRefusal"}:
        refusal = row["refusal"]
        require(type(refusal) is dict and set(refusal) == {"operation", "status", "code"}
                and refusal["operation"] == ("PrepareReturn" if kind == "ActiveValuationRefusal" else "ReadSource")
                and type(refusal["status"]) is int and refusal["status"] == (409 if kind == "ActiveValuationRefusal" else 403) and type(refusal["code"]) is str
                and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", refusal["code"]) is not None)
    else:
        require(row["refusal"] is None)
    return row


def verify_seeded_monetary_browser(runtime: ReceiptRuntime, *, custody_root: Path, case: str, original_app_dsn: str) -> dict[str, Any]:
    """Bind the browser-created identity from its sealed packet, including restore."""
    root = _root(custody_root, case)
    packet = decode_packet(_read(root / PACKET, MAX_PACKET_BYTES))
    count = len(_versions(case))
    require(packet.tenant_id == runtime.tenant and len(packet.captures) == count)
    source = packet.source_order_id
    assemble_monetary_browser(root, case=case, tenant=runtime.tenant, source=source)
    if runtime.factory.settings.dsn == original_app_dsn:
        capture_monetary_browser(runtime, source, root, case=case, index=count - 1, observation="FinalRead")
    folder = _storage(root.parent.parent / OBSERVATIONS / case)
    names = {*_kinds(case).values(), *({REFUSED_REQUEST} if case == "foreign" else set())}
    require({path.name for path in folder.iterdir()} in (names, names | {OBSERVATION_PACKET}))
    if case == "foreign":
        _request_pin(parse_json_document(_read(folder / REFUSED_REQUEST, 8192).decode("utf-8"), policy=LOAD_POLICY, reject_fractional_numbers=True), source)
    values = [_load_observation(folder / name, kind=kind, tenant=runtime.tenant, source=source, case=case) for kind, name in _kinds(case).items()]
    for value in values:
        before = _load(root / f"committed-capture-{value['capture']}.json", index=value["capture"], tenant=runtime.tenant)
        _unchanged_business(before["tables"], value["tables"])
    observations = {"schema_version": "customer-partial-return-monetary-posted-observations-input-v1", "tenant_id": runtime.tenant,
                    "source_order_id": source, "observations": values}
    _retain(folder / OBSERVATION_PACKET, _bytes(observations, MAX_PACKET_BYTES), same_allowed=True)
    final, version = _snapshot(runtime, source, index=count - 1, case=case)
    require(final["tables"] == values[-1]["tables"] and version == 7)
    if runtime.factory.settings.dsn != original_app_dsn:
        restored = {"schema_version": "customer-partial-return-monetary-posted-restored-input-v1", "tenant_id": runtime.tenant,
                    "source_order_id": source, "tables": final["tables"]}
        _retain(root / RESTORE, _bytes(restored, OBSERVATION_FILE_BYTES), same_allowed=True)
    return {"schema_version": "customer-partial-return-monetary-browser-custody-proof-v2", "captures": count, "history_version": 7,
            "tables": [{"table": name, "rows": len(final["tables"][name]), "sha256": hashlib.sha256(_bytes(final["tables"][name], CAPTURE_FILE_BYTES)).hexdigest()} for name in TABLES],
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
        if kind in {"ScopeRefusal", "ActiveValuationRefusal"}:
            refusal = {"operation": "PrepareReturn" if kind == "ActiveValuationRefusal" else "ReadSource", "status": int(os.environ["RECONFORGE_MONETARY_REFUSAL_STATUS"]), "code": os.environ["RECONFORGE_MONETARY_REFUSAL_CODE"]}
        refused_request = os.environ.get("RECONFORGE_MONETARY_REFUSED_REQUEST")
        request = None
        if refused_request is not None:
            parsed = parse_json_document(refused_request, policy=LOAD_POLICY, reject_fractional_numbers=True)
            require(type(parsed) is dict)
            request = cast(dict[str, Any], parsed)
        capture_monetary_browser(runtime, os.environ["RECONFORGE_MONETARY_STOCK_SOURCE"], Path(os.environ["RECONFORGE_MONETARY_CUSTODY_ROOT"]),
            case=os.environ["RECONFORGE_MONETARY_CASE"], index=int(os.environ["RECONFORGE_MONETARY_CAPTURE"]), observation=kind,
            plan_id=os.environ.get("RECONFORGE_MONETARY_POSTED_PLAN"), plan_digest=os.environ.get("RECONFORGE_MONETARY_POSTED_DIGEST"), refusal=refusal, request=request)
    except Exception as error:
        sys.stdout.buffer.write(_bytes(_capture_failure(error), 2048) + b"\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
