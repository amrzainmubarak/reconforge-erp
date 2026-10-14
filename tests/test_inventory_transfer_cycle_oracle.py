"""Independent custody/adversarial verification of a genuine native original."""
from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/verify_inventory_transfer_cycle_oracle.py"
FIXTURE = ROOT / "tests/fixtures/inventory-transfer-original-v1.json.gz"
ORIGINAL_SHA256 = "6c6bc9c46cd8314fe372080fed5393e4eaeb1cd4ad21138ccb4159c77604544e"
GZIP_SHA256 = "01d11cb24e8177530eb60a68a422da89ea0e30c5b08a6c4a893d890be2b1aef4"


@pytest.fixture(scope="module")
def oracle():
    spec = importlib.util.spec_from_file_location("independent_transfer_oracle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def raw() -> bytes:
    compressed = FIXTURE.read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == GZIP_SHA256
    original = gzip.decompress(compressed)
    assert len(original) == 653318 and hashlib.sha256(original).hexdigest() == ORIGINAL_SHA256
    return original


def run_cli(original: Path, expected: str, *extra: str, optimized: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []), str(SCRIPT), str(original),
        "--expected-export-sha256", expected, *extra], capture_output=True, text=True, timeout=15)


def test_actual_original_cli_normal_and_optimized_are_exact_and_anchored(raw: bytes, tmp_path: Path) -> None:
    original = tmp_path / "original.json"
    original.write_bytes(raw)
    normal, optimized = [run_cli(original, ORIGINAL_SHA256, optimized=mode) for mode in (False, True)]
    assert normal.returncode == optimized.returncode == 0 and normal.stdout == optimized.stdout
    result = json.loads(normal.stdout)
    assert result["original_file_sha256"] == ORIGINAL_SHA256 and result["verifier_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert {key: result[key] for key in ("opening_quantity_scaled", "forward_quantity_scaled", "restored_quantity_scaled", "destination_quantity_scaled", "pooled_value_minor")} == {
        "opening_quantity_scaled": "3", "forward_quantity_scaled": "1", "restored_quantity_scaled": "3", "destination_quantity_scaled": "0", "pooled_value_minor": "3600"}
    assert result["new_gl_effects"] == result["new_valuation_effects"] == 0 and result["independent_human_commands"] == 6


@pytest.mark.parametrize("mutation", ["detached-native-line", "duplicate-native-line", "detached-audit", "detached-outbox", "changed-outbox-payload",
    "changed-outbox-scope", "changed-audit-actor", "duplicate-command-key", "wrong-historical-phase", "wrong-historical-native",
    "wrong-historical-cost", "bool-event-version", "float-cost", "changed-original-gl", "extra-original-gl", "changed-core-namespace",
    "changed-core-quantity", "changed-release-subject", "changed-child-custody", "changed-receipt-seal", "changed-review-seal", "omitted-original-line",
    "extra-correction-owner", "duplicate-cost-source", "omitted-native-outbox"])
def test_original_independent_adversaries_refuse_after_valid_positive(oracle, raw: bytes, mutation: str) -> None:
    original = json.loads(raw)
    assert oracle.verify(original)["pooled_value_minor"] == "3600"
    proof = deepcopy(original)
    tables = proof["populations"]
    source = tables["inventory_transfer_sources"][0]
    event = tables["inventory_transfer_events"][0]
    command = tables["inventory_transfer_commands"][0]
    outbox = next(row for row in tables["outbox_events"] if row["event_id"] == event["outbox_event_id"])
    audit = next(row for row in tables["domain_audit_events"] if row["id"] == event["audit_event_id"])
    cost = source["payload"]["cost_snapshot"]["sources"][0]
    if mutation in {"detached-native-line", "duplicate-native-line"}:
        line = deepcopy(tables["inventory_movement_lines"][0])
        if mutation == "detached-native-line":
            line.update(id="FOREIGN-LINE", movement_id="FOREIGN-MOVEMENT")
        tables["inventory_movement_lines"].append(line)
    elif mutation == "detached-audit":
        event["audit_event_id"] = "DETACHED-AUDIT"
    elif mutation == "detached-outbox":
        event["outbox_event_id"] = "DETACHED-OUTBOX"
    elif mutation == "changed-outbox-payload":
        outbox["payload"]["reason"] = "Detached immutable body"
    elif mutation == "changed-outbox-scope":
        outbox["legal_entity_id"] = "OTHER-ENTITY"
    elif mutation == "changed-audit-actor":
        audit["actor_user_id"] = "FOREIGN-ACTOR"
    elif mutation == "duplicate-command-key":
        tables["inventory_transfer_commands"][1]["command_id"] = command["command_id"]
    elif mutation == "wrong-historical-phase":
        command["response_json"]["source"]["phase"] = 3
    elif mutation == "wrong-historical-native":
        command["response_json"]["native_response"]["head"]["source_reference"] = "FOREIGN-SOURCE"
    elif mutation == "wrong-historical-cost":
        command["response_json"]["source"]["cost_snapshot"]["remaining_value_minor"] = 1200
    elif mutation == "bool-event-version":
        next(row for row in tables["inventory_transfer_events"] if row["version"] == 1)["version"] = True
    elif mutation == "float-cost":
        cost["layer"]["original_value_minor"] = 3600.0
    elif mutation == "changed-original-gl":
        tables["finance_entry_lines"][0]["debit_minor"] += 1
    elif mutation == "extra-original-gl":
        extra = deepcopy(tables["finance_entries"][0])
        extra["id"] = "EXTRA-GL"
        tables["finance_entries"].append(extra)
    elif mutation == "changed-core-namespace":
        tables["inventory_quantity_source_guards"][0]["owner_namespace"] = "MSP1"
    elif mutation == "changed-core-quantity":
        tables["inventory_quantity_source_guards"][0]["quantity_scaled"] += 1
    elif mutation == "changed-release-subject":
        tables["inventory_transfer_releases"][0]["target_movement_id"] = "FOREIGN-MOVEMENT"
    elif mutation == "changed-child-custody":
        child = next(row for row in tables["inventory_transfer_sources"] if row["original_transfer_id"] is not None)
        child["from_location_id"] = child["to_location_id"]
    elif mutation == "changed-receipt-seal":
        tables["inventory_receipt_plans"][0]["plan_json"]["plan_digest"] = "a" * 64
    elif mutation == "changed-review-seal":
        tables["inventory_receipt_reviews"][0]["review_json"]["review_digest"] = "a" * 64
    elif mutation == "omitted-original-line":
        tables["inventory_movement_lines"].pop()
    elif mutation == "extra-correction-owner":
        tables["inventory_valuation_reversal_effects"].append({"tenant_id": proof["tenant_id"], "id": "EXTRA-CORRECTION"})
    elif mutation == "duplicate-cost-source":
        source["payload"]["cost_snapshot"]["sources"].append(deepcopy(cost))
    elif mutation == "omitted-native-outbox":
        native_id = source["native_movement_id"]
        tables["outbox_events"] = [row for row in tables["outbox_events"] if row["aggregate_id"] != native_id]
    else:
        pytest.fail("Unrecognized finite original adversary")
    with pytest.raises((ValueError, KeyError, StopIteration)):
        oracle.verify(proof)


def test_original_delivery_state_changes_preserve_immutable_financial_facts(oracle, raw: bytes) -> None:
    proof = json.loads(raw)
    before = oracle.verify(proof)
    for row in proof["populations"]["outbox_events"]:
        row.update(status="Published", attempt_count=1, published_at="2026-10-14T00:00:00+00:00", claimed_at=None, claimed_by=None,
            lease_generation=1, available_at="2026-10-14T00:00:00+00:00", last_error=None)
    after = oracle.verify(proof)
    assert {key: value for key, value in after.items() if key != "original_digest"} == {key: value for key, value in before.items() if key != "original_digest"}


@pytest.mark.parametrize("case", ["changed-bytes", "duplicate-member", "floating-input", "nonfinite-input", "missing-anchor", "malformed-anchor"])
def test_raw_original_parser_refuses_exact_anchor_and_member_adversaries(raw: bytes, tmp_path: Path, case: str) -> None:
    changed = raw + b" " if case == "changed-bytes" else raw
    if case == "duplicate-member":
        changed = raw.replace(b"{", b'{"schema_version":"inventory-transfer-proof-v1",', 1)
    elif case == "floating-input":
        changed = raw.replace(b'"role_superuser": false', b'"role_superuser": 0.0', 1)
    elif case == "nonfinite-input":
        changed = raw.replace(b'"role_superuser": false', b'"role_superuser": NaN', 1)
    original = tmp_path / "original.json"
    original.write_bytes(changed)
    expected = ORIGINAL_SHA256 if case == "changed-bytes" else hashlib.sha256(changed).hexdigest()
    if case == "missing-anchor":
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(original)], capture_output=True, text=True, timeout=15)
    else:
        result = run_cli(original, "malformed" if case == "malformed-anchor" else expected, optimized=True)
    assert result.returncode != 0 and not result.stdout


def test_original_parser_performs_one_bounded_byte_read_before_decode(oracle) -> None:
    calls: list[int] = []

    class Original(io.BytesIO):
        def read(self, size=-1):
            calls.append(size)
            return b"x" * size

    class PathLike:
        def open(self, mode):
            assert mode == "rb"
            return Original()

    with pytest.raises(ValueError, match="finite byte budget"):
        oracle.read_original(PathLike(), "a" * 64)
    assert calls == [oracle.MAX_BYTES + 1]


def test_output_is_exclusive_and_does_not_replace_original_receipt(raw: bytes, tmp_path: Path) -> None:
    original, output = tmp_path / "original.json", tmp_path / "oracle.json"
    original.write_bytes(raw)
    output.write_bytes(b"retained-original-receipt")
    result = run_cli(original, ORIGINAL_SHA256, "--output", str(output))
    assert result.returncode != 0 and output.read_bytes() == b"retained-original-receipt" and original.read_bytes() == raw


def test_oracle_imports_only_stdlib_and_has_no_optimized_assert_admission() -> None:
    tree = ast.parse(SCRIPT.read_text())
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert modules <= {"__future__", "argparse", "hashlib", "json", "re", "collections", "fractions", "pathlib", "typing"}
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
