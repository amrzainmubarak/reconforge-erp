"""Independent synthetic native export mutations; no application/DB imports."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_wave5_large_journal.py"
spec = importlib.util.spec_from_file_location("large_native_journal_oracle", SCRIPT)
assert spec is not None and spec.loader is not None
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)


def fixture() -> dict:
    scope = {"tenant_id": "synthetic-large-tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    registry = {"schema_version": 1, "registry_version": "synthetic-v1", "source": "Synthetic test", "source_url": "",
                "published_at": "2026-10-01", "currencies": [{"code": "USD", "minor_units": 2, "rounding_policy": "ROUND_HALF_UP"}]}
    registry["digest"] = hashlib.sha256(json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    policy = {"currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP",
              "currency_registry_version": "synthetic-v1", "currency_registry_digest": registry["digest"]}
    header = {"tenant_id": scope["tenant_id"], "id": "entry-large", "workspace_id": "work", "journal_id": "journal-stock",
              "organization_code": "ORG", "entity_code": "ENTITY", "period_id": "period", "entry_number": "BENCH-SNAPSHOT-DIMENSIONS",
              "posting_date": "2026-10-08", "description": "Independent alternating dimensional snapshot benchmark",
              "external_reference": "", "source_type": "Manual", "status": "Validated", "reverses_posting_id": None,
              "preparer_actor_id": "erp-maker", "validator_actor_id": "erp-checker", "validation_contract_version": "finance-entry-review-v1",
              "total_debit_minor": 500, "total_credit_minor": 500, **policy}
    lines = [{"tenant_id": scope["tenant_id"], "id": f"line-{index + 1:04}", "entry_id": header["id"], "line_number": index + 1,
              "account_id": "account-cash" if index % 2 == 0 else "account-equity", "description": "", "currency_code": "USD",
              "debit_minor": 1 if index % 2 == 0 else 0, "credit_minor": 0 if index % 2 == 0 else 1} for index in range(1000)]
    links = [{"tenant_id": scope["tenant_id"], "entry_line_id": row["id"], "dimension_id": f"dimension-{label}", "dimension_value_id": f"value-{label}"}
             for row in lines if (row["line_number"] - 1) % 3 == 0 for label in ("A", "B")]
    sealed_lines = [{"line_number": row["line_number"], "account_id": row["account_id"], "description": "",
                     "debit_minor": row["debit_minor"], "credit_minor": row["credit_minor"],
                     "dimensions": {"dimension-A": "value-A", "dimension-B": "value-B"} if (row["line_number"] - 1) % 3 == 0 else {}} for row in lines]
    sealed_header = {key: value for key, value in header.items() if key in o.HEADER_KEYS}
    sealed_header.update(organization_id="org", legal_entity_id="entity")
    snapshot = {"schema_version": "finance-entry-review-v1", "entry": sealed_header, "lines": sealed_lines}
    seal = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    header["validation_digest"] = seal
    effect = {**scope, "id": "effect-large", "entry_id": header["id"], "source_kind": "Manual", "source_id": header["id"],
              "purpose": "operational_posting", "reverses_effect_id": None, "validation_digest": seal,
              "validation_contract_version": "finance-entry-review-v1", **policy, "snapshot_json": snapshot,
              "posted_actor_id": "erp-poster", "posted_at": "2026-10-12T00:00:00Z",
              "reason": "Independent dimensional benchmark posting", "audit_event_id": "audit-large", "outbox_event_id": "outbox-large"}
    result = {key: value for key, value in effect.items() if key not in {"tenant_id", "snapshot_json"}}
    result["snapshot"] = snapshot
    request = {"operation": "post", "actor_id": "erp-poster", "workspace_id": "work", "entry_id": header["id"],
               "expected_validation_digest": seal, "reason": effect["reason"]}
    masters = {"tenant_id": scope["tenant_id"], "workspace_id": "work", "active": True}
    return {"schema_version": "wave5-large-native-journal-export-v1", "database": "postgres", "server_version_num": "170011",
            "read_only": "on", "isolation": "repeatable read", "revision": ["0137_pg_intercompany_projection"], "app_role_flags": [False, False],
            "headers": [header], "effects": [effect], "lines": lines, "dimension_links": links,
            "accounts": [{**masters, "id": "account-cash", "account_code": "CASH", "chart_id": "chart-default", "account_type": "Asset",
                          "normal_balance": "Debit", "allow_posting": True, "allow_manual_posting": True},
                         {**masters, "id": "account-equity", "account_code": "EQUITY", "chart_id": "chart-default", "account_type": "Equity",
                          "normal_balance": "Credit", "allow_posting": True, "allow_manual_posting": True}],
            "dimensions": [{**masters, "id": f"dimension-{label}", "organization_code": "ORG", "dimension_code": f"BENCH_{label}",
                            "required_on_entries": False} for label in ("A", "B")],
            "dimension_values": [{**masters, "id": f"value-{label}", "dimension_id": f"dimension-{label}", "value_code": "SYNTHETIC"} for label in ("A", "B")],
            "journals": [{**masters, "id": "journal-stock", "organization_code": "ORG", "journal_code": "STOCK", "currency_code": "USD", "chart_id": "chart-default"}],
            "charts": [{**masters, "id": "chart-default", "chart_code": "DEFAULT", "organization_code": "ORG"}],
            "periods": [{"tenant_id": scope["tenant_id"], "id": "period", "application_workspace_id": "work", "status": "Open", "start_date": "2026-10-01", "end_date": "2026-10-31"}],
            "organizations": [{"tenant_id": scope["tenant_id"], "id": "org", "organization_code": "ORG", "application_workspace_id": "work", "base_currency": "USD", "active": True}],
            "entities": [{"tenant_id": scope["tenant_id"], "id": "entity", "organization_id": "org", "entity_code": "ENTITY", "currency_code": "USD", "active": True}],
            "registries": [{"tenant_id": scope["tenant_id"], "registry_version": "synthetic-v1", "registry_digest": registry["digest"], "snapshot_json": registry}],
            "audit": [{"tenant_id": scope["tenant_id"], "id": "audit-large", "actor_user_id": "erp-poster", "object_type": "finance_posting", "object_id": effect["id"],
                       "action": "finance_entry_posted", "metadata_json": {"entry_id": header["id"], "content_digest": seal}}],
            "outbox": [{**scope, "event_id": "outbox-large", "event_type": "finance_entry_posted", "aggregate_type": "finance_posting", "aggregate_id": effect["id"],
                        "payload": {"entry_id": header["id"], "content_digest": seal, "audit_event_id": "audit-large"}}],
            "commands": [{**scope, "command_id": "benchmark-snapshot-post", "operation": "post", "actor_id": "erp-poster",
                          "request_digest": hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "result_json": result}]}


@pytest.mark.parametrize("revision", sorted(o.REVISIONS))
def test_fixed_independent_1000_line_668_dimension_500_minor_native_source(revision: str) -> None:
    ledger = fixture()
    ledger["revision"] = [revision]
    report = o.verify_export(ledger, expected_validation_digest=ledger["headers"][0]["validation_digest"], expected_revision=revision)
    assert report["line_count"] == 1000 and report["dimension_links"] == 668
    assert report["debit_minor"] == report["credit_minor"] == 500
    assert report["entry_id"] == "entry-large" and report["effect_id"] == "effect-large"
    assert report["external_report_anchor"] is True and report["native_publication_proved"] is True
    assert report["performance_comparison_accepted"] is False


@pytest.mark.parametrize(("path", "value"), [
    (("database",), "enterprise_benchmark"), (("server_version_num",), "170010"), (("read_only",), "off"), (("isolation",), "read committed"),
    (("revision",), ["0138_unreviewed"]), (("revision",), []), (("app_role_flags",), [0, 0]), (("app_role_flags",), [False, True]),
    (("headers", 0, "status"), "Posted"), (("headers", 0, "tenant_id"), "foreign"), (("headers", 0, "workspace_id"), "foreign"),
    (("headers", 0, "entity_code"), "BUYER"), (("headers", 0, "source_type"), "Generated"), (("headers", 0, "currency_code"), "EUR"),
    (("headers", 0, "currency_precision"), 2.0), (("headers", 0, "preparer_actor_id"), "erp-poster"), (("headers", 0, "total_debit_minor"), 500.0),
    (("headers", 0, "validation_digest"), "0" * 64), (("effects", 0, "entry_id"), "foreign"), (("effects", 0, "source_id"), "foreign"),
    (("effects", 0, "purpose"), "fake"), (("effects", 0, "source_kind"), "Reversal"), (("effects", 0, "posted_actor_id"), "erp-checker"),
    (("effects", 0, "currency_registry_version"), "unreviewed"), (("lines", 0, "debit_minor"), True), (("lines", 0, "debit_minor"), 2),
    (("effects", 0, "posted_at"), "2026-10-12T00:00:00"), (("effects", 0, "posted_at"), "2026-10-12T00:00:00+03:00"),
    (("lines", 0, "credit_minor"), 1), (("lines", 0, "account_id"), "account-equity"), (("lines", 0, "entry_id"), "foreign"),
    (("lines", 1, "tenant_id"), "foreign"), (("lines", 0, "currency_code"), "EUR"), (("lines", 0, "line_number"), True),
    (("lines", 999, "id"), "line-0001"), (("dimension_links", 0, "dimension_value_id"), "value-B"),
    (("dimension_links", 0, "entry_line_id"), "line-0002"), (("dimension_links", 0, "tenant_id"), "foreign"),
    (("dimensions", 0, "dimension_code"), "WRONG"), (("dimension_values", 0, "value_code"), "REAL"),
    (("dimension_values", 0, "workspace_id"), "foreign"), (("accounts", 0, "allow_posting"), False),
    (("accounts", 0, "chart_id"), "foreign"), (("periods", 0, "status"), "Closed"), (("journals", 0, "currency_code"), "EUR"),
    (("charts", 0, "organization_code"), "foreign"), (("organizations", 0, "base_currency"), "EUR"), (("entities", 0, "active"), False),
    (("audit", 0, "object_id"), "foreign"), (("outbox", 0, "payload", "content_digest"), "0" * 64),
    (("commands", 0, "request_digest"), "0" * 64), (("commands", 0, "result_json", "id"), "foreign"),
    (("registries", 0, "snapshot_json", "currencies", 0, "minor_units"), 3),
])
def test_native_money_dimension_scope_status_source_and_evidence_tamper_refused(path: tuple, value: object) -> None:
    ledger = fixture()
    target = ledger
    for member in path[:-1]:
        target = target[member]
    target[path[-1]] = value
    with pytest.raises((ValueError, KeyError, TypeError)):
        o.verify_export(ledger)


@pytest.mark.parametrize("table", ["headers", "effects", "lines", "dimension_links", "accounts", "dimensions", "dimension_values", "commands", "audit", "outbox"])
@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_population_omission_extra_or_duplicate_is_refused(table: str, mutation: str) -> None:
    ledger = fixture()
    if mutation == "missing":
        ledger[table].pop()
    elif mutation == "extra":
        row = copy.deepcopy(ledger[table][0])
        row["id"] = "extra"
        ledger[table].append(row)
    else:
        ledger[table].append(copy.deepcopy(ledger[table][0]))
    with pytest.raises((ValueError, KeyError, TypeError)):
        o.verify_export(ledger)


def test_balanced_total_tamper_does_not_pass_per_line_independent_oracle() -> None:
    ledger = fixture()
    ledger["lines"][0]["debit_minor"], ledger["lines"][2]["debit_minor"] = 0, 2
    assert sum(row["debit_minor"] for row in ledger["lines"]) == 500
    with pytest.raises(ValueError, match="alternating"):
        o.verify_export(ledger)


def test_trusted_harness_seal_and_exact_revision_are_both_required_for_final_anchor() -> None:
    ledger = fixture()
    assert o.verify_export(ledger)["external_report_anchor"] is False
    assert o.verify_export(ledger, expected_validation_digest=ledger["headers"][0]["validation_digest"])["external_report_anchor"] is False
    with pytest.raises(ValueError, match="Trusted original"):
        o.verify_export(ledger, expected_validation_digest="0" * 64)
    with pytest.raises(ValueError, match="Trusted runtime"):
        o.verify_export(ledger, expected_revision="0136_pg_inventory_scope")


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}', b'[]', b'{} {}'])
def test_strict_json_duplicate_float_nonfinite_and_extra_document_refusal(raw: bytes) -> None:
    with pytest.raises(ValueError):
        o.decode(raw)


def process() -> dict:
    return {"pid": 42, "start_ticks": 7, "executable": "/synthetic/python", "session": 42, "process_group": 42}


def test_original_readonly_capture_retains_raw_bytes_and_exact_cid_not_credentials(tmp_path: Path) -> None:
    raw = json.dumps(fixture()).encode() + b"\n"
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=raw, stderr=b""))
    result = o.capture(container_id="a" * 64, run=run, output=tmp_path, source_process=process())
    assert result["status"] == "passed" and result["external_report_anchor"] is False
    assert (tmp_path / "large-journal-ledger.raw.json").read_bytes() == raw
    meta = json.loads((tmp_path / "large-journal-ledger-capture.json").read_bytes())
    assert meta["container_id"] == "a" * 64 and meta["source_process"] == process()
    assert meta["raw_sha256"] == hashlib.sha256(raw).hexdigest() and meta["raw_bytes"] == len(raw)
    assert meta["credentials_or_environment_captured"] is False
    command = run.call_args.args[0]
    assert command[:4] == ["docker", "exec", "--interactive", "a" * 64]
    assert command[command.index("--dbname") + 1] == "postgres" and run.call_args.kwargs["input"] == o.SQL.encode()
    assert "env" not in run.call_args.kwargs and "password" not in " ".join(command).lower()
    with pytest.raises(ValueError, match="never be replaced"):
        o.capture(container_id="a" * 64, run=run, output=tmp_path, source_process=process())
    assert run.call_count == 1


@pytest.mark.parametrize(("cid", "identity"), [("short", process()), ("A" * 64, process()), ("a" * 64, {**process(), "pid": True}),
                                              ("a" * 64, {**process(), "session": 43}), ("a" * 64, {**process(), "password": "do-not-capture"})])
def test_unacknowledged_identity_cannot_execute_even_readonly_sql(tmp_path: Path, cid: str, identity: dict) -> None:
    run = Mock()
    with pytest.raises(ValueError):
        o.capture(container_id=cid, run=run, output=tmp_path, source_process=identity)
    run.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_failed_raw_export_remains_failed_and_unmodified_for_caller_cleanup(tmp_path: Path) -> None:
    raw = b'{"failed":"original-synthetic"}\n'
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout=raw, stderr=b"synthetic failure"))
    with pytest.raises(ValueError, match="export failed"):
        o.capture(container_id="a" * 64, run=run, output=tmp_path, source_process=process())
    assert (tmp_path / "large-journal-ledger.raw.json").read_bytes() == raw
    metadata = json.loads((tmp_path / "large-journal-ledger-capture.json").read_bytes())
    assert metadata["status"] == "failed" and metadata["returncode"] == 1
    assert metadata["stderr_sha256"] == hashlib.sha256(b"synthetic failure").hexdigest()
    assert "synthetic failure" not in json.dumps(metadata)


def test_fixed_export_is_readonly_and_oracle_has_only_stdlib_imports() -> None:
    source = ast.parse(SCRIPT.read_text())
    imports = {node.module.split(".")[0] for node in ast.walk(source) if isinstance(node, ast.ImportFrom) and node.module}
    imports |= {alias.name.split(".")[0] for node in ast.walk(source) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {"__future__", "argparse", "hashlib", "json", "re", "pathlib", "typing", "datetime"}
    assert "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in o.SQL and o.SQL.endswith("ROLLBACK;\n")
    for word in ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "CREATE", "COPY", "GRANT"):
        assert word not in o.SQL.upper().split()
    assert "identity_users" not in o.SQL and "password" not in o.SQL.lower()


def test_standalone_isolated_and_optimized_cli_proofs_are_identical(tmp_path: Path) -> None:
    ledger = fixture()
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger))
    outputs = []
    for flags, name in ((["-I"], "normal"), (["-I", "-O"], "optimized")):
        result = subprocess.run([sys.executable, *flags, str(SCRIPT), "--ledger", str(path), "--expected-validation-digest",
                                 ledger["headers"][0]["validation_digest"], "--expected-revision", ledger["revision"][0],
                                 "--expected-export-sha256", hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "--output", str(tmp_path / (name + ".json"))], capture_output=True, check=False, timeout=10)
        assert result.returncode == 0
        outputs.append((tmp_path / (name + ".json")).read_bytes())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["external_report_anchor"] is True and json.loads(outputs[0])["raw_export_anchor"] is True


@pytest.mark.parametrize("flags", [["-I"], ["-I", "-O"]])
def test_coordinated_tenant_swap_keeps_financial_seal_but_refuses_trusted_original_raw_hash(tmp_path: Path, flags: list[str]) -> None:
    original = fixture()
    trusted = json.dumps(original).encode()
    changed = json.loads(trusted)

    def change(value: object) -> None:
        if type(value) is dict:
            for key, member in value.items():
                if key == "tenant_id":
                    value[key] = "different-consistent-tenant"
                else:
                    change(member)
        elif type(value) is list:
            for member in value:
                change(member)

    change(changed)
    # The public review snapshot omits tenant_id. Source custody therefore
    # requires a separate original-byte anchor, not just the financial seal.
    assert o.verify_export(changed, expected_validation_digest=original["headers"][0]["validation_digest"],
                           expected_revision=original["revision"][0])["external_report_anchor"] is True
    path, output = tmp_path / "swapped.json", tmp_path / "must-not-exist.json"
    path.write_text(json.dumps(changed))
    result = subprocess.run([sys.executable, *flags, str(SCRIPT), "--ledger", str(path), "--expected-validation-digest",
                             original["headers"][0]["validation_digest"], "--expected-revision", original["revision"][0],
                             "--expected-export-sha256", hashlib.sha256(trusted).hexdigest(), "--output", str(output)],
                            capture_output=True, check=False, timeout=10)
    assert result.returncode != 0 and b"trusted original raw export" in result.stderr
    assert not output.exists()
