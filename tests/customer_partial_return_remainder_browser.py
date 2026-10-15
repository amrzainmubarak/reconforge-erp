"""PRIVATE committed originals for three finite governed remainder HTTPS cycles.

Only native fixtures create business effects. This observer reads committed
ordinary-role PostgreSQL rows and retains opaque original row text. The separate
stdlib oracle owns every financial expectation and authorization-audit check.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.io.structured import parse_json_document
from tests.customer_partial_return_posted_cycle_oracle import TABLES as LEGACY_TABLES
from tests.customer_partial_returns_browser import (
    LOAD_POLICY,
    MAX_CAPTURE_BYTES,
    MAX_OBSERVATION_BYTES,
    MAX_PACKET_BYTES,
    MAX_ROWS,
    _bytes,
    _original_locks,
    _read,
    _retain,
    _text,
    require,
)
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

TABLES = (*LEGACY_TABLES, "customer_partial_return_allocation_witnesses")
FAMILY = "native-customer-partial-return-remainder-originals"
OBSERVATIONS = "native-customer-partial-return-remainder-observation-originals"
REFUSED = "native-customer-partial-return-remainder-failed-observation-originals"
EVENTS = {"ordinary": 3, "zero": 7, "refund": 6}
REPLAY = {"ordinary": 1, "zero": 1, "refund": 4}
PACKET = "posted-cycle-input.json"
RESTORE = "posted-cycle-restored-input.json"
OBSERVATION_PACKET = "posted-cycle-observations-input.json"
CAPTURE_SCHEMA = "customer-partial-return-remainder-browser-capture-v1"
OBSERVATION_SCHEMA = "customer-partial-return-remainder-browser-observation-v1"
CAPTURE_FIELDS = {"schema_version", "tenant_id", "source_order_id", "history_version", "posted_plan_id", "plan_digest", "tables"}


def _regular_path(path: Path, *, directory: bool = False) -> None:
    require(path.is_absolute() and ".." not in path.parts)
    for item in (path, *path.parents):
        require(not item.is_symlink())
        if item.exists():
            require(not getattr(item.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    if path.exists():
        require(path.is_dir() if directory else path.is_file())


def _storage(root: Path) -> Path:
    _regular_path(root, directory=True)
    root.mkdir(parents=True, exist_ok=True)
    _regular_path(root, directory=True)
    return root


def _case(case: str) -> int:
    require(type(case) is str and case in EVENTS)
    return EVENTS[case]


def _root(root: Path, case: str) -> Path:
    _case(case)
    require(root.name == case and root.parent.name == FAMILY)
    return _storage(root)


def _tables(value: Any) -> dict[str, list[str]]:
    require(type(value) is dict and set(value) == set(TABLES))
    for rows in value.values():
        require(type(rows) is list and len(rows) <= MAX_ROWS and all(type(row) is str for row in rows)
                and rows == sorted(rows) and len(set(rows)) == len(rows))
    return cast(dict[str, list[str]], value)


def _load(path: Path, *, case: str, observation: str | None = None) -> dict[str, Any]:
    _regular_path(path)
    require(observation is None or observation in {"RetainedReplay", "FinalRead"})
    raw = parse_json_document(_read(path, MAX_OBSERVATION_BYTES if observation else MAX_CAPTURE_BYTES).decode("utf-8"),
                              policy=LOAD_POLICY, reject_fractional_numbers=True)
    require(type(raw) is dict and set(raw) == CAPTURE_FIELDS | ({"kind"} if observation else set()))
    value = cast(dict[str, Any], raw)
    require(value["schema_version"] == (OBSERVATION_SCHEMA if observation else CAPTURE_SCHEMA))
    require(type(value["history_version"]) is int and 0 <= value["history_version"] <= _case(case))
    _text(value["tenant_id"])
    _text(value["source_order_id"])
    if value["history_version"] == 0:
        require(value["posted_plan_id"] is None and value["plan_digest"] is None and observation is None)
    else:
        require(type(value["posted_plan_id"]) is str and re.fullmatch(r"CR(?:2|F2|2R|F2R)-[a-f0-9]{32}", value["posted_plan_id"]) is not None)
        require(type(value["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["plan_digest"]) is not None)
    if observation:
        require(value["kind"] == observation and value["history_version"] == (REPLAY[case] if observation == "RetainedReplay" else EVENTS[case]))
    _tables(value["tables"])
    return value


def _files(root: Path, case: str) -> list[Path]:
    files = []
    for path in root.iterdir():
        _regular_path(path)
        match = re.fullmatch(r"committed-capture-([0-7])\.json", path.name)
        require(match is not None or path.name in {PACKET, RESTORE})
        if match:
            files.append(path)
    files.sort(key=lambda path: path.name)
    require(len(files) <= _case(case) + 1 and [path.name for path in files] == [f"committed-capture-{number}.json" for number in range(len(files))])
    return files


def _snapshot(runtime: ReceiptRuntime, source: str, case: str) -> tuple[int, dict[str, list[str]], dict[str, Any] | None]:
    with runtime.actor("browser-poster") as (connection, _, _actor):
        flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
        require(flags is not None and all(type(flags[name]) is bool and not flags[name]
                for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication")))
        secured = connection.execute("""SELECT count(*) n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity
            AND c.relowner<>current_user::regrole""", (list(TABLES),)).fetchone()
        require(secured is not None and secured["n"] == 79)
        _original_locks(connection, runtime.tenant, source)
        audit = connection.execute("SELECT tenant_id FROM reconforge.domain_audit_ledger_state WHERE tenant_id=%s FOR SHARE", (runtime.tenant,)).fetchall()
        require(len(audit) == 1 and audit[0]["tenant_id"] == runtime.tenant)
        history = connection.execute("""SELECT h.sequence,h.plan_id,p.plan_digest,p.phase FROM reconforge.customer_partial_return_history h
            JOIN reconforge.customer_partial_return_sources s ON(s.tenant_id,s.id)=(h.tenant_id,h.source_id)
            LEFT JOIN reconforge.customer_partial_return_plans p ON(p.tenant_id,p.id)=(h.tenant_id,h.plan_id)
            WHERE h.tenant_id=%s AND s.source_order_id=%s ORDER BY h.sequence""", (runtime.tenant, source)).fetchall()
        require([row["sequence"] for row in history] == list(range(1, len(history) + 1)) and len(history) <= _case(case))
        tables = {}
        for name in TABLES:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text LIMIT 4097")
                                      .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
            require(len(rows) <= MAX_ROWS)
            tables[name] = sorted(row["original"] for row in rows)
        current = {key: history[-1][key] for key in ("sequence", "plan_id", "plan_digest", "phase")} if history else None
        return len(history), _tables(tables), current


def _audit(before: dict[str, list[str]], after: dict[str, list[str]], tenant: str) -> None:
    from tests.customer_partial_return_remainder_posted_oracle import verify_audit_only_transition
    verify_audit_only_transition(before, after, tenant_id=tenant)


def _observe(root: Path, case: str, candidate: dict[str, Any], kind: str) -> dict[str, Any]:
    version = candidate["history_version"]
    require(kind in {"RetainedReplay", "FinalRead"} and version == (REPLAY[case] if kind == "RetainedReplay" else EVENTS[case]))
    baseline = _load(root / f"committed-capture-{version}.json", case=case)
    require(all(candidate[key] == baseline[key] for key in CAPTURE_FIELDS - {"tables"}))
    value = {**candidate, "schema_version": OBSERVATION_SCHEMA, "kind": kind}
    folder = _storage(root.parent.parent / OBSERVATIONS / case)
    replay = f"retained-replay-{REPLAY[case]}.json"
    name = replay if kind == "RetainedReplay" else "final-observation.json"
    try:
        _audit(baseline["tables"], candidate["tables"], candidate["tenant_id"])
        for path in folder.iterdir():
            _regular_path(path)
            require(path.name in {replay, "final-observation.json", OBSERVATION_PACKET})
        _retain(folder / name, _bytes(value, MAX_OBSERVATION_BYTES), same_allowed=True)
    except (ValueError, TypeError, KeyError):
        refused = _storage(root.parent.parent / REFUSED / case)
        require(len(list(refused.iterdir())) < 16)
        attempt = {"schema_version": "customer-partial-return-remainder-refused-observation-v1", "case": case,
                   "reason_code": "audit_only_transition_refused", "candidate": candidate,
                   "retained_original_sha256": hashlib.sha256(_read(root / f"committed-capture-{version}.json", MAX_CAPTURE_BYTES)).hexdigest()}
        _retain(refused / ("refused-observation-" + uuid4().hex + ".json"), _bytes(attempt, MAX_OBSERVATION_BYTES))
        raise ValueError("Remainder browser observation refused.") from None
    return value


def capture_remainder_browser(runtime: ReceiptRuntime, source: str, root: Path, *, case: str,
                              posted_plan_id: str | None = None, plan_digest: str | None = None) -> dict[str, Any]:
    root = _root(root, case)
    files = _files(root, case)
    for number, path in enumerate(files):
        previous = _load(path, case=case)
        require((previous["tenant_id"], previous["source_order_id"], previous["history_version"]) == (runtime.tenant, source, number))
    version, tables, last = _snapshot(runtime, _text(source), case)
    require((last is None and posted_plan_id is None and plan_digest is None and version == 0)
            or (last is not None and last["phase"] == 2 and (last["plan_id"], last["plan_digest"]) == (posted_plan_id, plan_digest)))
    require(version in {len(files), len(files) - 1})
    candidate = {"schema_version": CAPTURE_SCHEMA, "tenant_id": runtime.tenant, "source_order_id": source,
                 "history_version": version, "posted_plan_id": posted_plan_id, "plan_digest": plan_digest, "tables": tables}
    raw = _bytes(candidate, MAX_CAPTURE_BYTES)
    if version == len(files) - 1:
        _observe(root, case, candidate, "RetainedReplay")
    else:
        _retain(root / f"committed-capture-{version}.json", raw)
    return {"history_version": version, "tables": 79, "original_sha256": hashlib.sha256(raw).hexdigest(), "raw_rows_published": False}


def assemble_remainder_browser(root: Path, *, case: str, tenant: str, source: str) -> dict[str, Any]:
    root = _root(root, case)
    files = _files(root, case)
    require(len(files) == EVENTS[case] + 1)
    values = [_load(path, case=case) for path in files]
    require(all((value["tenant_id"], value["source_order_id"], value["history_version"]) == (tenant, source, index)
                for index, value in enumerate(values)))
    packet = {"schema_version": "customer-partial-return-remainder-posted-cycle-input-v1", "case": case,
              "tenant_id": tenant, "source_order_id": source, "captures": values}
    _retain(root / PACKET, _bytes(packet, MAX_PACKET_BYTES), same_allowed=True)
    return packet


def seed_remainder_browser(admin_dsn: str, app_dsn: str, *, case: str) -> tuple[ReceiptRuntime, str]:
    from tests.test_postgres_customer_partial_return_rounding import create_remainder_runtime
    _case(case)
    if case == "refund":
        from tests.test_postgres_customer_partial_returns import create_partial_runtime
        runtime, source, _invoice = create_partial_runtime((admin_dsn, app_dsn), paid=10000)
    else:
        runtime, source = create_remainder_runtime((admin_dsn, app_dsn), zero=case == "zero")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "audit.verify", "users.manage", "roles.manage", "security.center.read",
                           "security.policy.manage", "security.integrations.manage", "security.retention.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    seed_erp_browser_principals(runtime)
    return runtime, source


def verify_remainder_browser(runtime: ReceiptRuntime, *, custody_root: Path, source: str, case: str, original_app_dsn: str) -> dict[str, Any]:
    root = _root(custody_root, case)
    assemble_remainder_browser(root, case=case, tenant=runtime.tenant, source=source)
    version, tables, last = _snapshot(runtime, source, case)
    if last is None:
        raise ValueError("Final committed remainder history is required.")
    require(version == EVENTS[case] and last["phase"] == 2)
    if runtime.factory.settings.dsn == original_app_dsn:
        _observe(root, case, {"schema_version": CAPTURE_SCHEMA, "tenant_id": runtime.tenant, "source_order_id": source,
                 "history_version": version, "posted_plan_id": last["plan_id"], "plan_digest": last["plan_digest"], "tables": tables}, "FinalRead")
    folder = _storage(root.parent.parent / OBSERVATIONS / case)
    replay = f"retained-replay-{REPLAY[case]}.json"
    require({path.name for path in folder.iterdir()} in ({replay, "final-observation.json"},
            {replay, "final-observation.json", OBSERVATION_PACKET}))
    observations = [_load(folder / name, case=case, observation=kind) for name, kind in
                    ((replay, "RetainedReplay"), ("final-observation.json", "FinalRead"))]
    for value in observations:
        baseline = _load(root / f"committed-capture-{value['history_version']}.json", case=case)
        require((value["tenant_id"], value["source_order_id"], value["posted_plan_id"], value["plan_digest"])
                == (runtime.tenant, source, baseline["posted_plan_id"], baseline["plan_digest"]))
        _audit(baseline["tables"], value["tables"], runtime.tenant)
    require(tables == observations[-1]["tables"])
    packet = {"schema_version": "customer-partial-return-remainder-posted-observations-input-v1", "case": case,
              "tenant_id": runtime.tenant, "source_order_id": source, "observations": observations}
    _retain(folder / OBSERVATION_PACKET, _bytes(packet, MAX_PACKET_BYTES), same_allowed=True)
    if runtime.factory.settings.dsn != original_app_dsn:
        restored = {"schema_version": "customer-partial-return-remainder-posted-restored-input-v1", "case": case,
                    "tenant_id": runtime.tenant, "source_order_id": source, "tables": tables}
        _retain(root / RESTORE, _bytes(restored, MAX_CAPTURE_BYTES), same_allowed=True)
    return {"schema_version": "customer-partial-return-remainder-browser-custody-proof-v1", "case": case, "history_version": version,
            "tables": [{"table": name, "rows": len(tables[name]), "sha256": hashlib.sha256(_bytes(tables[name], MAX_CAPTURE_BYTES)).hexdigest()} for name in TABLES],
            "raw_financial_rows_published": False, "independent_financial_verification_required": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture",))
    parser.parse_args()
    try:
        runtime = ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=os.environ["RECONFORGE_GFO_APP_DSN"], require_tls=False)),
                                 "", os.environ["RECONFORGE_ERP_TENANT"], os.environ["RECONFORGE_ERP_PASSWORD"])
        capture_remainder_browser(runtime, os.environ["RECONFORGE_CUSTOMER_PARTIAL_RETURN_SOURCE"],
            Path(os.environ["RECONFORGE_PARTIAL_REMAINDER_CUSTODY_ROOT"]), case=os.environ["RECONFORGE_PARTIAL_REMAINDER_CASE"],
            posted_plan_id=os.environ["RECONFORGE_PARTIAL_POSTED_PLAN"], plan_digest=os.environ["RECONFORGE_PARTIAL_POSTED_DIGEST"])
    except Exception:
        print("Committed remainder browser observation refused.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
