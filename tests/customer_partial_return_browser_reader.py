"""Fail-closed isolated-reader binding for PRIVATE M7 browser SQL originals.

This does not calculate financial expectations. The pinned stdlib-only reader
derives actual ledger amounts; this gate admits the one declared synthetic
eight-event HTTPS cohort and exposes only its verified finite projection.
Subprocess execution uses a fixed interpreter and hash-pinned local reader,
without a shell, caller-selected executable or inherited financial credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from reconforge.io.structured import StructuredDocumentPolicy, parse_json_document
from tests.customer_partial_return_posted_cycle_oracle import TABLES

FAMILY = "native-customer-partial-return-originals"
EXECUTIONS = "independent-customer-partial-return-row-verification"
READER = Path(__file__).resolve().with_name("customer_partial_return_posted_cycle_oracle.py")
READER_SHA256 = "a255156f51f0030331f1fb9709445a6c234b9af342ea2d10ae5ebe9ab3d811ab"
PACKET = "posted-cycle-input.json"
RESTORE = "posted-cycle-restored-input.json"
CAPTURES = tuple(f"committed-capture-{number}.json" for number in range(9))
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_PACKET_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 72 * 1024 * 1024
MAX_PROOF_BYTES = 128 * 1024
MAX_STREAM_BYTES = 64 * 1024
POLICY = StructuredDocumentPolicy(max_file_bytes=MAX_PACKET_BYTES, max_nodes=100_000, max_depth=10,
                                  max_collection_items=4096, max_scalar_characters=MAX_CAPTURE_BYTES)
EXPECTED_ACCOUNTS = {"AR": 0, "CASH": 0, "CLEARING": -32000, "COGS": 0, "INVENTORY": 32000, "REFUND": 0, "REVENUE": 0}
READER_SCOPE = "Incremental GL amounts, original FIFO portions, layer deltas and history only; authority, RLS, recovery and API need separate native qualification."
EXPECTED_PROOF = {
    "schema_version": "customer-partial-return-posted-cycle-proof-v1", "captures": 9, "events": 8,
    "new_actual_posting_effects": 12, "new_actual_posted_lines": 25, "returned_quantity_scaled": 15,
    "receivable_minor": 0, "refund_liability_minor": 0, "original_consumptions_unchanged": True,
    "incremental_gl_fifo_layer_history_equal": True, "final_actual_posting_effects": 17,
    "final_actual_posted_entries": 17, "final_actual_posted_lines": 35, "final_total_debit_minor": 385000,
    "final_total_credit_minor": 385000, "final_account_minor_balances": EXPECTED_ACCOUNTS,
    "unposted_or_void_entries_excluded": True, "scope": READER_SCOPE,
}
EXECUTION_NAMES = frozenset({"I.json", "IO.json", "I.stdout", "I.stderr", "IO.stdout", "IO.stderr", "I.result.json", "IO.result.json", "reader-custody.json"})


class CustomerPartialReturnOriginalRefusal(ValueError):
    """A finite safe error never echoes financial data, paths or credentials."""


def _require(condition: bool) -> None:
    if not condition:
        raise CustomerPartialReturnOriginalRefusal("Independent partial-return browser originals refused.")


def _regular(path: Path, *, directory: bool = False) -> None:
    for item in (path, *path.parents):
        _require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)())
    _require(path.is_dir() if directory else path.is_file())


def _file(path: Path, maximum: int) -> tuple[bytes, dict[str, Any]]:
    _regular(path)
    before = path.stat()
    _require(before.st_size <= maximum)
    with path.open("rb") as stream:
        original = stream.read(maximum + 1)
    after = path.stat()
    _require(len(original) <= maximum and len(original) == before.st_size)
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
             == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
    return original, {"name": path.name, "bytes": len(original), "sha256": hashlib.sha256(original).hexdigest(),
                      "device": before.st_dev, "inode": before.st_ino, "mtime_ns": before.st_mtime_ns}


def _encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _decode(original: bytes) -> dict[str, Any]:
    value = parse_json_document(original.decode("utf-8"), policy=POLICY, reject_fractional_numbers=True)
    _require(type(value) is dict)
    return cast(dict[str, Any], value)


def _same_typed(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(_same_typed(actual[key], value) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_same_typed(left, right) for left, right in zip(actual, expected, strict=True))
    return bool(actual == expected)


def _text(value: Any) -> None:
    _require(type(value) is str and 0 < len(value) <= 200 and value == value.strip())


def _tables(value: Any) -> dict[str, list[str]]:
    _require(type(value) is dict and set(value) == set(TABLES))
    for rows in value.values():
        _require(type(rows) is list and len(rows) <= 4096 and all(type(row) is str for row in rows))
        _require(rows == sorted(rows) and len(rows) == len(set(rows)))
    return cast(dict[str, list[str]], value)


def _family(private: Path, *, require_restore: bool) -> dict[str, Any]:
    _require(type(require_restore) is bool)
    _regular(private, directory=True)
    root = private / FAMILY
    _regular(root, directory=True)
    names = set(CAPTURES) | {PACKET} | ({RESTORE} if require_restore else set())
    _require({path.name for path in root.iterdir()} == names)
    originals: dict[str, bytes] = {}
    identities = []
    for name in sorted(names):
        original, identity = _file(root / name, MAX_PACKET_BYTES if name == PACKET else MAX_CAPTURE_BYTES)
        originals[name] = original
        identities.append(identity)
    _require(sum(len(original) for original in originals.values()) <= MAX_TOTAL_BYTES)
    packet = _decode(originals[PACKET])
    _require(set(packet) == {"schema_version", "tenant_id", "source_order_id", "captures"}
             and packet["schema_version"] == "customer-partial-return-posted-cycle-input-v1")
    _text(packet["tenant_id"])
    _text(packet["source_order_id"])
    _require(type(packet["captures"]) is list and len(packet["captures"]) == 9)
    for number, name in enumerate(CAPTURES):
        capture = _decode(originals[name])
        _require(set(capture) == {"schema_version", "tenant_id", "source_order_id", "history_version", "posted_plan_id", "plan_digest", "tables"})
        _require(capture["schema_version"] == "customer-partial-return-browser-capture-v1"
                 and capture["tenant_id"] == packet["tenant_id"] and capture["source_order_id"] == packet["source_order_id"]
                 and type(capture["history_version"]) is int and capture["history_version"] == number)
        if number == 0:
            _require(capture["posted_plan_id"] is None and capture["plan_digest"] is None)
        else:
            _text(capture["posted_plan_id"])
            _require(type(capture["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", capture["plan_digest"]) is not None)
        _require(_same_typed(_tables(packet["captures"][number]), _tables(capture["tables"])))
    if require_restore:
        restored = _decode(originals[RESTORE])
        _require(set(restored) == {"schema_version", "tenant_id", "source_order_id", "capture"}
                 and restored["schema_version"] == "customer-partial-return-posted-restore-input-v1"
                 and restored["tenant_id"] == packet["tenant_id"] and restored["source_order_id"] == packet["source_order_id"])
        _require(_same_typed(_tables(restored["capture"]), _tables(packet["captures"][-1])))
    source, source_identity = _file(READER, MAX_PROOF_BYTES)
    _require(hashlib.sha256(source).hexdigest() == READER_SHA256)
    return {"input_files": identities, "source": source_identity, "input_set_sha256": hashlib.sha256(_encode(identities)).hexdigest(),
            "input_sha256": hashlib.sha256(originals[PACKET]).hexdigest(),
            "restore_input_sha256": hashlib.sha256(originals[RESTORE]).hexdigest() if require_restore else None,
            "final_rows": sum(len(rows) for rows in packet["captures"][-1].values()), "require_restore": require_restore}


def _proof(original: bytes, inputs: dict[str, Any]) -> dict[str, Any]:
    proof = _decode(original)
    expected = {**EXPECTED_PROOF, "input_sha256": inputs["input_sha256"], "oracle_source_sha256": READER_SHA256}
    if inputs["require_restore"]:
        expected.update(populated_restore_original_rows_equal=True, restored_tables=78, restored_rows=inputs["final_rows"],
                        restore_input_sha256=inputs["restore_input_sha256"])
    _require(_same_typed(proof, expected))
    return proof


def _write(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(_encode(value))


def _public(inputs: dict[str, Any], proof_identity: dict[str, Any]) -> dict[str, Any]:
    # Every financial value below is a literal admitted only after _proof's
    # exact typed comparison with the actual independently derived result.
    return {"schema_version": "customer-partial-return-browser-original-proof-v1", "status": "passed", "captures": 9,
            "events": 8, "tables": 78, "new_actual_posting_effects": 12, "new_actual_posted_lines": 25,
            "final_actual_posting_effects": 17, "final_actual_posted_entries": 17, "final_actual_posted_lines": 35,
            "final_total_debit_minor": 385000, "final_total_credit_minor": 385000,
            "final_account_minor_balances": dict(EXPECTED_ACCOUNTS), "returned_quantity_scaled": 15,
            "receivable_minor": 0, "refund_liability_minor": 0, "restored": inputs["require_restore"],
            "restored_tables": 78 if inputs["require_restore"] else 0,
            "restored_rows": inputs["final_rows"] if inputs["require_restore"] else 0,
            "input_sha256": inputs["input_sha256"], "restore_input_sha256": inputs["restore_input_sha256"],
            "input_set_sha256": inputs["input_set_sha256"], "oracle_source_sha256": READER_SHA256,
            "I_proof_sha256": proof_identity["sha256"], "IO_proof_sha256": proof_identity["sha256"],
            "isolated_modes_byte_equal": True, "raw_financial_rows_published": False}


def verify_customer_partial_return_original_rows(private: Path, *, require_restore: bool) -> dict[str, Any]:
    inputs = _family(private, require_restore=require_restore)
    execution_root = private / EXECUTIONS
    _require(not execution_root.exists() and not execution_root.is_symlink()
             and not getattr(execution_root, "is_junction", lambda: False)())
    execution_root.mkdir()
    execution = execution_root / uuid4().hex
    execution.mkdir()
    _regular(execution, directory=True)
    results: list[dict[str, Any]] = []
    proofs: list[bytes] = []
    for mode, flags in (("I", ["-I"]), ("IO", ["-I", "-O"])):
        argv = [sys.executable, *flags, str(READER), "--input", str(private / FAMILY / PACKET), "--output", str(execution / (mode + ".json"))]
        if require_restore:
            argv.extend(("--restore-input", str(private / FAMILY / RESTORE)))
        with (execution / (mode + ".stdout")).open("xb") as stdout, (execution / (mode + ".stderr")).open("xb") as stderr:
            try:
                environment = {key: value for key, value in os.environ.items() if key in {"SYSTEMROOT", "SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"}}
                result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=60,
                                        check=False, env=environment)  # nosec B603
            except subprocess.TimeoutExpired as exc:
                raise CustomerPartialReturnOriginalRefusal("Independent partial-return reader deadline refused.") from exc
        outcome = {"schema_version": "customer-partial-return-reader-execution-v1", "mode": mode,
                   "exit_code": result.returncode, "isolated": True, "optimized": mode == "IO"}
        _write(execution / (mode + ".result.json"), outcome)
        _require(type(result.returncode) is int and result.returncode == 0)
        original, proof_identity = _file(execution / (mode + ".json"), MAX_PROOF_BYTES)
        _proof(original, inputs)
        stream_identities = []
        for suffix in ("stdout", "stderr"):
            stream, identity = _file(execution / (mode + "." + suffix), MAX_STREAM_BYTES)
            _require(stream == b"")
            stream_identities.append(identity)
        _, result_identity = _file(execution / (mode + ".result.json"), MAX_PROOF_BYTES)
        proofs.append(original)
        results.append({"mode": mode, "proof": proof_identity, "streams": stream_identities, "result": result_identity})
        _require(_same_typed(_family(private, require_restore=require_restore), inputs))
    _require(proofs[0] == proofs[1])
    core = _public(inputs, results[0]["proof"])
    receipt = {"schema_version": "customer-partial-return-browser-reader-custody-v1", "inputs": inputs,
               "executions": results, "public_core": core}
    _write(execution / "reader-custody.json", receipt)
    _, receipt_identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    verified = {**core, "execution_receipt_sha256": receipt_identity["sha256"]}
    require_customer_partial_return_original_binding(private, verified)
    return verified


def require_customer_partial_return_original_binding(private: Path, verified: dict[str, Any]) -> None:
    _require(type(verified) is dict and type(verified.get("restored")) is bool)
    inputs = _family(private, require_restore=verified["restored"])
    root = private / EXECUTIONS
    _regular(root, directory=True)
    directories = list(root.iterdir())
    _require(len(directories) == 1 and re.fullmatch(r"[a-f0-9]{32}", directories[0].name) is not None)
    execution = directories[0]
    _regular(execution, directory=True)
    _require({path.name for path in execution.iterdir()} == EXECUTION_NAMES)
    raw_receipt, receipt_identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    _require(verified.get("execution_receipt_sha256") == receipt_identity["sha256"])
    receipt = _decode(raw_receipt)
    _require(set(receipt) == {"schema_version", "inputs", "executions", "public_core"}
             and receipt["schema_version"] == "customer-partial-return-browser-reader-custody-v1"
             and _same_typed(receipt["inputs"], inputs))
    _require(type(receipt["executions"]) is list and len(receipt["executions"]) == 2)
    proof_originals = []
    for row, mode in zip(receipt["executions"], ("I", "IO"), strict=True):
        _require(type(row) is dict and set(row) == {"mode", "proof", "streams", "result"} and row["mode"] == mode)
        proof, identity = _file(execution / (mode + ".json"), MAX_PROOF_BYTES)
        _require(_same_typed(identity, row["proof"]))
        _proof(proof, inputs)
        proof_originals.append(proof)
        streams = []
        for suffix in ("stdout", "stderr"):
            original, identity = _file(execution / (mode + "." + suffix), MAX_STREAM_BYTES)
            _require(original == b"")
            streams.append(identity)
        _require(_same_typed(streams, row["streams"]))
        original, identity = _file(execution / (mode + ".result.json"), MAX_PROOF_BYTES)
        _require(_same_typed(identity, row["result"]))
        _require(_same_typed(_decode(original), {"schema_version": "customer-partial-return-reader-execution-v1", "mode": mode,
                    "exit_code": 0, "isolated": True, "optimized": mode == "IO"}))
    _require(proof_originals[0] == proof_originals[1])
    core = _public(inputs, receipt["executions"][0]["proof"])
    _require(_same_typed(receipt["public_core"], core)
             and _same_typed(verified, {**core, "execution_receipt_sha256": receipt_identity["sha256"]}))
    _require(_same_typed(_family(private, require_restore=verified["restored"]), inputs))
