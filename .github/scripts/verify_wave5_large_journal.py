#!/usr/bin/env python3
"""Independent stdlib oracle for the fixed synthetic 1,000-line native journal.

The SQL export is a REPEATABLE READ, READ ONLY transaction over original tables.
It runs immediately before the caller's acknowledged full-ID container cleanup.
The header remains Validated; its immutable Manual effect proves publication.
No application imports, credentials, environment inspection or financial writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CONTRACT = "wave5-large-native-journal-export-v1"
REVIEW = "finance-entry-review-v1"
NUMBER = "BENCH-SNAPSHOT-DIMENSIONS"
REVISIONS = {"0132_pg_stock_inverse_dispatch", "0136_pg_inventory_scope", "0137_pg_intercompany_projection", "0140_pg_people_project_payroll"}
HEADER_KEYS = (
    "id", "workspace_id", "organization_id", "legal_entity_id", "journal_id", "period_id", "entry_number",
    "posting_date", "description", "external_reference", "source_type", "currency_code", "currency_precision",
    "currency_rounding_policy", "currency_registry_version", "currency_registry_digest", "preparer_actor_id", "reverses_posting_id",
)
LINE_KEYS = ("line_number", "account_id", "description", "debit_minor", "credit_minor", "dimensions")

# Each fixed selector exports the native population before joins can hide a
# malformed/missing master. No caller-supplied SQL or source identifier is used.
_SELECTORS = {
    "headers": "SELECT to_jsonb(e) row FROM h e ORDER BY e.tenant_id,e.id",
    "effects": "SELECT to_jsonb(f) row FROM f ORDER BY f.tenant_id,f.id",
    "lines": "SELECT to_jsonb(l) row FROM l ORDER BY l.line_number,l.id",
    "dimension_links": "SELECT to_jsonb(d) row FROM d ORDER BY d.entry_line_id,d.dimension_id",
    "accounts": "SELECT to_jsonb(a) row FROM reconforge.finance_accounts a WHERE EXISTS(SELECT 1 FROM l WHERE l.tenant_id=a.tenant_id AND l.account_id=a.id) ORDER BY a.id",
    "dimensions": "SELECT to_jsonb(m) row FROM reconforge.finance_dimensions m WHERE EXISTS(SELECT 1 FROM d WHERE d.tenant_id=m.tenant_id AND d.dimension_id=m.id) ORDER BY m.id",
    "dimension_values": "SELECT to_jsonb(v) row FROM reconforge.finance_dimension_values v WHERE EXISTS(SELECT 1 FROM d WHERE d.tenant_id=v.tenant_id AND d.dimension_value_id=v.id) ORDER BY v.id",
    "journals": "SELECT to_jsonb(j) row FROM reconforge.finance_journals j WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=j.tenant_id AND h.journal_id=j.id) ORDER BY j.id",
    "charts": "SELECT to_jsonb(c) row FROM reconforge.finance_charts c WHERE EXISTS(SELECT 1 FROM reconforge.finance_journals j JOIN h ON h.tenant_id=j.tenant_id AND h.journal_id=j.id WHERE c.tenant_id=j.tenant_id AND c.id=j.chart_id) ORDER BY c.id",
    "periods": "SELECT to_jsonb(p) row FROM reconforge.fiscal_periods p WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=p.tenant_id AND h.period_id=p.id) ORDER BY p.id",
    "organizations": "SELECT to_jsonb(o) row FROM reconforge.organizations o WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=o.tenant_id AND h.organization_code=o.organization_code AND h.workspace_id=o.application_workspace_id) ORDER BY o.id",
    "entities": "SELECT to_jsonb(e) row FROM reconforge.legal_entities e WHERE EXISTS(SELECT 1 FROM h JOIN reconforge.organizations o ON o.tenant_id=h.tenant_id AND o.organization_code=h.organization_code AND o.application_workspace_id=h.workspace_id WHERE e.tenant_id=h.tenant_id AND e.organization_id=o.id AND e.entity_code=h.entity_code) ORDER BY e.id",
    "registries": "SELECT to_jsonb(r) row FROM reconforge.currency_registry_snapshots r WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=r.tenant_id AND h.currency_registry_digest=r.registry_digest) ORDER BY r.registry_digest",
    "audit": "SELECT to_jsonb(a) row FROM reconforge.domain_audit_events a WHERE EXISTS(SELECT 1 FROM f WHERE f.tenant_id=a.tenant_id AND f.audit_event_id=a.id) ORDER BY a.id",
    "outbox": "SELECT to_jsonb(o) row FROM reconforge.outbox_events o WHERE EXISTS(SELECT 1 FROM f WHERE f.tenant_id=o.tenant_id AND f.outbox_event_id=o.event_id) ORDER BY o.event_id",
    "commands": "SELECT to_jsonb(c) row FROM reconforge.finance_posting_commands c WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=c.tenant_id AND c.workspace_id=h.workspace_id AND c.command_id='benchmark-snapshot-post') OR EXISTS(SELECT 1 FROM f WHERE f.tenant_id=c.tenant_id AND c.result_json->>'id'=f.id) ORDER BY c.command_id",
}
SQL = """BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='20s';
WITH h AS (SELECT * FROM reconforge.finance_entries WHERE entry_number='BENCH-SNAPSHOT-DIMENSIONS'),
f AS (SELECT * FROM reconforge.finance_posting_effects f WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=f.tenant_id AND h.id=f.entry_id)),
l AS (SELECT * FROM reconforge.finance_entry_lines l WHERE EXISTS(SELECT 1 FROM h WHERE h.tenant_id=l.tenant_id AND h.id=l.entry_id)),
d AS (SELECT * FROM reconforge.finance_entry_line_dimensions d WHERE EXISTS(SELECT 1 FROM l WHERE l.tenant_id=d.tenant_id AND l.id=d.entry_line_id))
SELECT jsonb_build_object(
'schema_version','wave5-large-native-journal-export-v1','database',current_database(),
'server_version_num',current_setting('server_version_num'),'read_only',current_setting('transaction_read_only'),
'isolation',current_setting('transaction_isolation'),'revision',(SELECT jsonb_agg(version_num ORDER BY version_num) FROM alembic_version),
'app_role_flags',(SELECT jsonb_build_array(rolsuper,rolbypassrls) FROM pg_roles WHERE rolname='enterprise_benchmark'),
""" + ",\n".join(f"'{key}',(SELECT COALESCE(jsonb_agg(row),'[]'::jsonb) FROM ({selector}) population)" for key, selector in _SELECTORS.items()) + ");\nROLLBACK;\n"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def decode(raw: bytes) -> dict[str, Any]:
    require(0 < len(raw) <= 8 * 1024 * 1024, "Bounded original native export required")
    value = json.loads(raw, object_pairs_hook=_unique,
                       parse_float=lambda _: (_ for _ in ()).throw(ValueError("No floating-point financial evidence")),
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON evidence")))
    require(type(value) is dict, "Native export must be an object")
    return value


def load(path: Path) -> dict[str, Any]:
    return decode(_raw(path))


def _raw(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    require(0 < len(raw) <= 8 * 1024 * 1024, "Native export size exceeds bound")
    return raw


def _one(packet: dict[str, Any], key: str) -> dict[str, Any]:
    rows = packet[key]
    require(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict, "Exact one native " + key + " required")
    return rows[0]


def _text(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= 500 and all(ord(char) >= 32 and ord(char) != 127 for char in value)


def verify_export(packet: dict[str, Any], *, expected_validation_digest: str | None = None,
                  expected_revision: str | None = None) -> dict[str, Any]:
    require(set(packet) == set(_SELECTORS) | {"schema_version", "database", "server_version_num", "read_only", "isolation", "revision", "app_role_flags"},
            "Closed native export schema required")
    require(packet["schema_version"] == CONTRACT and packet["database"] == "postgres"
            and packet["server_version_num"] == "170011" and packet["read_only"] == "on"
            and packet["isolation"] == "repeatable read", "Native read-only PostgreSQL17.11 subject differs")
    require(packet["app_role_flags"] == [False, False] and all(type(flag) is bool for flag in packet["app_role_flags"]),
            "Native application role must remain restricted")
    require(type(packet["revision"]) is list and len(packet["revision"]) == 1 and packet["revision"][0] in REVISIONS,
            "Known exact runtime revision required")
    if expected_revision is not None:
        require(expected_revision in REVISIONS and packet["revision"] == [expected_revision], "Trusted runtime revision differs")
    header, effect = _one(packet, "headers"), _one(packet, "effects")
    require(set(effect) == {"tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "entry_id", "source_kind",
        "source_id", "purpose", "reverses_effect_id", "validation_digest", "validation_contract_version", "currency_code", "currency_precision",
        "currency_rounding_policy", "currency_registry_version", "currency_registry_digest", "snapshot_json", "posted_actor_id", "posted_at",
        "reason", "audit_event_id", "outbox_event_id"}, "Closed original native publication effect required")
    require(_text(effect["posted_at"]), "Original publication timestamp required")
    posted_at = datetime.fromisoformat(effect["posted_at"])
    require(posted_at.tzinfo is not None and posted_at.utcoffset() == timedelta(0), "Publication timestamp must retain UTC")
    tenant, entry = header["tenant_id"], header["id"]
    require(_text(tenant) and _text(entry) and _text(effect["id"]), "Native source identities required")
    require(header["entry_number"] == NUMBER and header["organization_code"] == "ORG" and header["entity_code"] == "ENTITY"
            and header["workspace_id"] == "work" and header["period_id"] == "period" and header["posting_date"] == "2026-10-08"
            and header["description"] == "Independent alternating dimensional snapshot benchmark"
            and header["external_reference"] == "" and header["source_type"] == "Manual" and header["status"] == "Validated"
            and header["reverses_posting_id"] is None, "Original reviewed synthetic header differs")
    require(header["preparer_actor_id"] == "erp-maker" and header["validator_actor_id"] == "erp-checker"
            and effect["posted_actor_id"] == "erp-poster" and header["validation_contract_version"] == REVIEW,
            "Three exact independent native actors required")
    policy = {key: header[key] for key in ("currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")}
    require(policy["currency_code"] == "USD" and type(policy["currency_precision"]) is int and policy["currency_precision"] == 2
            and policy["currency_rounding_policy"] == "ROUND_HALF_UP" and _text(policy["currency_registry_version"])
            and re.fullmatch(r"[0-9a-f]{64}", policy["currency_registry_digest"]), "Exact USD minor-unit policy required")
    scope = {"tenant_id": tenant, "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    require(all(effect[key] == value for key, value in scope.items()) and effect["entry_id"] == entry
            and effect["source_id"] == entry and effect["source_kind"] == "Manual" and effect["purpose"] == "operational_posting"
            and effect["reverses_effect_id"] is None and effect["validation_contract_version"] == REVIEW
            and effect["reason"] == "Independent dimensional benchmark posting"
            and all(effect[key] == value for key, value in policy.items()), "Original source-owned native effect differs")
    for table in _SELECTORS:
        require(type(packet[table]) is list and all(type(row) is dict and row.get("tenant_id") == tenant for row in packet[table]),
                "Original row tenant mismatch: " + table)
    masters = {key: _one(packet, key) for key in ("journals", "charts", "periods", "organizations", "entities", "registries", "audit", "outbox", "commands")}
    journal, chart, period, organization, entity = (masters[key] for key in ("journals", "charts", "periods", "organizations", "entities"))
    require(journal["id"] == header["journal_id"] and journal["workspace_id"] == "work" and journal["organization_code"] == "ORG"
            and journal["journal_code"] == "STOCK" and journal["currency_code"] == "USD" and journal["active"] is True
            and journal["chart_id"] == chart["id"] and chart["chart_code"] == "DEFAULT" and chart["workspace_id"] == "work"
            and chart["organization_code"] == "ORG" and chart["active"] is True, "Journal/chart source scope differs")
    require(period["id"] == "period" and period["application_workspace_id"] == "work" and period["status"] == "Open"
            and period["start_date"] <= "2026-10-08" <= period["end_date"]
            and organization["id"] == "org" and organization["organization_code"] == "ORG"
            and organization["application_workspace_id"] == "work" and organization["base_currency"] == "USD" and organization["active"] is True
            and entity["id"] == "entity" and entity["organization_id"] == "org" and entity["entity_code"] == "ENTITY"
            and entity["currency_code"] == "USD" and entity["active"] is True, "Native entity/period/organization context differs")
    accounts = {row["id"]: row for row in packet["accounts"]}
    require(len(accounts) == len(packet["accounts"]) == 2 and {row["account_code"] for row in accounts.values()} == {"CASH", "EQUITY"},
            "Exactly two distinct native account masters required")
    require(all(row["workspace_id"] == "work" and row["chart_id"] == chart["id"] and row["active"] is True
                and row["allow_posting"] is True and row["allow_manual_posting"] is True
                and row["account_type"] == ("Asset" if row["account_code"] == "CASH" else "Equity")
                and row["normal_balance"] == ("Debit" if row["account_code"] == "CASH" else "Credit") for row in accounts.values()),
            "Native account policy/scope differs")
    dimensions = {row["id"]: row for row in packet["dimensions"]}
    values = {row["id"]: row for row in packet["dimension_values"]}
    require(len(dimensions) == len(packet["dimensions"]) == len(values) == len(packet["dimension_values"]) == 2
            and {row["dimension_code"] for row in dimensions.values()} == {"BENCH_A", "BENCH_B"}, "Exact dimension master population required")
    require(all(row["workspace_id"] == "work" and row["organization_code"] == "ORG" and row["active"] is True
                and row["required_on_entries"] is False for row in dimensions.values())
            and all(row["workspace_id"] == "work" and row["dimension_id"] in dimensions and row["value_code"] == "SYNTHETIC"
                    and row["active"] is True for row in values.values())
            and {row["dimension_id"] for row in values.values()} == set(dimensions), "Native dimension value scope differs")
    lines = packet["lines"]
    require(len(lines) == 1000 and [row["line_number"] for row in lines] == list(range(1, 1001))
            and all(type(row["line_number"]) is int for row in lines)
            and len({row["id"] for row in lines}) == 1000 and all(_text(row["id"]) for row in lines), "Exact ordered unique native line population required")
    by_id = {row["id"]: row for row in lines}
    links = packet["dimension_links"]
    require(len(links) == 668 and [(row["entry_line_id"], row["dimension_id"]) for row in links]
            == sorted({(row["entry_line_id"], row["dimension_id"]) for row in links}), "Exact ordered unique native dimension links required")
    attached: dict[str, dict[str, str]] = {identifier: {} for identifier in by_id}
    for link in links:
        line_id, dimension_id, value_id = (link[key] for key in ("entry_line_id", "dimension_id", "dimension_value_id"))
        require(line_id in by_id and dimension_id in dimensions and value_id in values
                and values[value_id]["dimension_id"] == dimension_id, "Native dimension foreign source differs")
        attached[line_id][dimension_id] = value_id
    sealed_lines = []
    debit = credit = 0
    for index, line in enumerate(lines):
        require(line["entry_id"] == entry and line["currency_code"] == "USD" and line["description"] == ""
                and line["account_id"] in accounts, "Native line context differs")
        require(type(line["debit_minor"]) is int and type(line["credit_minor"]) is int
                and (line["debit_minor"], line["credit_minor"]) == ((1, 0) if index % 2 == 0 else (0, 1))
                and accounts[line["account_id"]]["account_code"] == ("CASH" if index % 2 == 0 else "EQUITY"), "Independent alternating integer money/account oracle failed")
        actual_dimensions = attached[line["id"]]
        require(({dimensions[key]["dimension_code"]: values[value]["value_code"] for key, value in actual_dimensions.items()}
                 == ({"BENCH_A": "SYNTHETIC", "BENCH_B": "SYNTHETIC"} if index % 3 == 0 else {})), "Independent every-third-line dimension oracle failed")
        sealed_lines.append({key: actual_dimensions if key == "dimensions" else line[key] for key in LINE_KEYS})
        debit += line["debit_minor"]
        credit += line["credit_minor"]
    require(debit == credit == 500 and type(header["total_debit_minor"]) is int and type(header["total_credit_minor"]) is int
            and header["total_debit_minor"] == header["total_credit_minor"] == 500, "Independent total/header money differs")
    native_header = {key: ("org" if key == "organization_id" else "entity" if key == "legal_entity_id" else header[key]) for key in HEADER_KEYS}
    snapshot = {"schema_version": REVIEW, "entry": native_header, "lines": sealed_lines}
    seal = digest(snapshot)
    require(effect["snapshot_json"] == snapshot and effect["validation_digest"] == header["validation_digest"] == seal,
            "Original native snapshot/review SHA256 differs")
    if expected_validation_digest is not None:
        require(type(expected_validation_digest) is str and re.fullmatch(r"[0-9a-f]{64}", expected_validation_digest)
                and seal == expected_validation_digest, "Trusted original harness review seal differs")
    registry = masters["registries"]
    registry_snapshot = registry["snapshot_json"]
    require(type(registry_snapshot) is dict and registry["registry_digest"] == policy["currency_registry_digest"]
            and registry["registry_version"] == policy["currency_registry_version"] == registry_snapshot["registry_version"]
            and registry_snapshot["digest"] == registry["registry_digest"]
            and digest({key: value for key, value in registry_snapshot.items() if key != "digest"}) == registry["registry_digest"],
            "Retained registry source SHA256 differs")
    usd = [row for row in registry_snapshot["currencies"] if row["code"] == "USD"]
    require(len(usd) == 1 and type(usd[0]["minor_units"]) is int and usd[0]["minor_units"] == 2
            and usd[0]["rounding_policy"] == "ROUND_HALF_UP", "Registry USD precision/source rule differs")
    audit, outbox, command = (masters[key] for key in ("audit", "outbox", "commands"))
    metadata = {"entry_id": entry, "content_digest": seal}
    require(audit["id"] == effect["audit_event_id"] and audit["actor_user_id"] == "erp-poster" and audit["object_type"] == "finance_posting"
            and audit["object_id"] == effect["id"] and audit["action"] == "finance_entry_posted" and audit["metadata_json"] == metadata
            and outbox["event_id"] == effect["outbox_event_id"] and outbox["event_type"] == "finance_entry_posted"
            and outbox["aggregate_type"] == "finance_posting" and outbox["aggregate_id"] == effect["id"]
            and outbox["payload"] == {**metadata, "audit_event_id": audit["id"]}
            and all(outbox[key] == value for key, value in scope.items()), "Original audit/outbox source custody differs")
    request = {"operation": "post", "actor_id": "erp-poster", "workspace_id": "work", "entry_id": entry,
               "expected_validation_digest": seal, "reason": "Independent dimensional benchmark posting"}
    response = {key: value for key, value in effect.items() if key not in {"tenant_id", "snapshot_json"}}
    response["snapshot"] = snapshot
    require(command["command_id"] == "benchmark-snapshot-post" and command["operation"] == "post"
            and command["actor_id"] == "erp-poster" and command["request_digest"] == digest(request)
            and command["result_json"] == response and all(command[key] == value for key, value in scope.items()),
            "Original posting command acknowledgement differs")
    return {"status": "passed", "schema_version": CONTRACT, "tenant_id": tenant, "entry_id": entry, "effect_id": effect["id"],
            "validation_digest": seal, "revision": packet["revision"][0], "line_count": 1000, "dimension_links": 668,
            "debit_minor": debit, "credit_minor": credit, "native_publication_proved": True,
            "external_report_anchor": expected_validation_digest is not None and expected_revision is not None,
            "performance_comparison_accepted": False, "audit_chain_recomputed": False}


def capture(*, container_id: str, run: Any, output: Path, source_process: dict[str, Any]) -> dict[str, Any]:
    require(type(container_id) is str and re.fullmatch(r"[0-9a-f]{64}", container_id), "Acknowledged full immutable container ID required")
    require(type(source_process) is dict and set(source_process) == {"pid", "start_ticks", "executable", "session", "process_group"}
            and all(type(source_process[key]) is int and source_process[key] > 0 for key in ("pid", "start_ticks", "session", "process_group"))
            and source_process["pid"] == source_process["session"] == source_process["process_group"] and _text(source_process["executable"]),
            "Admitted source process identity required")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    raw_path, metadata_path = output / "large-journal-ledger.raw.json", output / "large-journal-ledger-capture.json"
    require(not raw_path.exists() and not metadata_path.exists(), "Original ledger export must never be replaced")
    argv = ["docker", "exec", "--interactive", container_id, "psql", "--username", "postgres", "--dbname", "postgres",
            "--no-psqlrc", "--quiet", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1"]
    result = run(argv, input=SQL.encode(), capture_output=True, timeout=30, check=False)
    raw = result.stdout if type(result.stdout) is bytes else result.stdout.encode()
    stderr = result.stderr if type(result.stderr) is bytes else result.stderr.encode()
    require(len(raw) <= 8 * 1024 * 1024 and len(stderr) <= 1024 * 1024, "Bounded original SQL export required")
    with raw_path.open("xb") as stream:
        stream.write(raw)
    evidence: dict[str, Any] = {"status": "failed", "container_id": container_id, "source_process": source_process,
        "sql_sha256": hashlib.sha256(SQL.encode()).hexdigest(), "command_sha256": digest(argv), "command": argv,
        "stdout_bytes": len(raw), "stdout_sha256": hashlib.sha256(raw).hexdigest(), "stderr_bytes": len(stderr),
        "raw_bytes": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(), "returncode": result.returncode,
        "credentials_or_environment_captured": False, "performance_comparison_accepted": False}
    try:
        require(type(result.returncode) is int and result.returncode == 0 and not stderr, "Original readonly SQL export failed")
        verification = verify_export(decode(raw))
        evidence.update(status="passed", verification=verification)
        return verification
    except Exception as exc:
        evidence["failure_type"] = type(exc).__name__
        raise
    finally:
        with metadata_path.open("xb") as stream:
            stream.write(json.dumps(evidence, indent=2, allow_nan=False).encode() + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--expected-validation-digest", required=True)
    parser.add_argument("--expected-export-sha256", required=True, help="Separately trusted original raw member SHA256")
    parser.add_argument("--expected-revision", required=True, choices=sorted(REVISIONS))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = _raw(args.ledger)
    raw_sha = hashlib.sha256(raw).hexdigest()
    require(re.fullmatch(r"[0-9a-f]{64}", args.expected_export_sha256) is not None and raw_sha == args.expected_export_sha256,
            "Separately trusted original raw export SHA256 differs")
    report = verify_export(decode(raw), expected_validation_digest=args.expected_validation_digest, expected_revision=args.expected_revision)
    report.update(raw_export_sha256=raw_sha, raw_export_anchor=True)
    with args.output.open("xb") as stream:
        stream.write(json.dumps(report, indent=2).encode() + b"\n")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
