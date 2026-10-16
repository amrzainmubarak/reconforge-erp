"""Private monetary browser custody and isolated independent-reader execution.

No financial arithmetic is implemented here. A complete hash-pinned C proof is
mandatory; decoding a raw packet or running an incomplete reader cannot pass.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess  # nosec B404
import sys
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from reconforge.io.structured import StructuredDocumentPolicy, parse_json_document
from tests import customer_partial_return_browser_reader as common
from tests import customer_partial_return_remainder_browser_reader as custody
from tests.customer_partial_return_monetary_posted_oracle import MAX_CAPTURE_ENVELOPE_BYTES, MAX_ROW_BYTES, TABLES

FAMILY = "native-customer-partial-return-monetary-originals"
OBSERVATIONS = "native-customer-partial-return-monetary-observation-originals"
EXECUTIONS = "independent-customer-partial-return-monetary-row-verification"
PACKET, RESTORE, OBSERVATION_PACKET = "posted-cycle-input.json", "posted-cycle-restored-input.json", "observations-input.json"
REFUSED_REQUEST = "active-valuation-refused-request.json"
READER = Path(__file__).resolve().with_name("customer_partial_return_monetary_posted_oracle.py")
READER_SHA256 = "72ac6163d886d6527010a3eadd2827d39461e4242a3c5581718c3eb6bc2c7ddb"
VERSIONS = {"identity": (0, 0, 0, 1, 2, 3, 4, 5, 6, 7), "foreign": (0, 0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7)}
EXPECTED_TOTALS = {"identity": (12, 28, "71800"), "foreign": (14, 37, "81605")}
MAX_CAPTURE, MAX_PACKET, MAX_TOTAL, MAX_PROOF = MAX_CAPTURE_ENVELOPE_BYTES, 64 * 1024 * 1024, 192 * 1024 * 1024, 128 * 1024
POLICY = StructuredDocumentPolicy(max_file_bytes=MAX_PACKET, max_nodes=100_000, max_depth=12,
                                  max_collection_items=20_000, max_scalar_characters=MAX_ROW_BYTES)
_require, _same_typed, _encode, _regular, _file = common._require, common._same_typed, common._encode, custody._regular, custody._file
EXECUTION_NAMES = common.EXECUTION_NAMES


def _decode(original: bytes) -> dict[str, Any]:
    value = parse_json_document(original.decode("utf-8"), policy=POLICY, reject_fractional_numbers=True)
    _require(type(value) is dict)
    return cast(dict[str, Any], value)


def _case(case: str) -> tuple[int, ...]:
    _require(type(case) is str and case in VERSIONS)
    return VERSIONS[case]


def _text(value: Any, maximum: int = 160) -> None:
    _require(type(value) is str and 0 < len(value) <= maximum and value == value.strip()
             and all(ord(char) >= 32 and ord(char) != 127 for char in value))


def _tables(value: Any) -> None:
    _require(type(value) is dict and set(value) == set(TABLES))
    for rows in value.values():
        _require(type(rows) is list and len(rows) <= 4096 and all(type(row) is str and len(row.encode()) <= 256 * 1024 for row in rows)
                 and rows == sorted(rows) and len(rows) == len(set(rows)))


def _family(private: Path, *, case: str, require_restore: bool) -> dict[str, Any]:
    versions = _case(case)
    _require(type(require_restore) is bool)
    _regular(private, directory=True)
    _require(not (private / "native-customer-partial-return-monetary-failed-observation-originals").exists())
    roots = (private / FAMILY, private / OBSERVATIONS)
    for root in roots:
        _regular(root, directory=True)
        _require({path.name for path in root.iterdir()} == {case})
    data, observations = roots[0] / case, roots[1] / case
    _regular(data, directory=True)
    _regular(observations, directory=True)
    names = {f"committed-capture-{index}.json" for index in range(len(versions))} | {PACKET} | ({RESTORE} if require_restore else set())
    kinds = {"RetainedReplay": "retained-replay.json", "ScopeRefusal": "scope-refusal.json", "FinalRead": "final-observation.json"}
    if case == "foreign":
        kinds = {"ActiveValuationRefusal": "active-valuation-refusal.json", **kinds}
    observation_names = {*kinds.values(), OBSERVATION_PACKET} | ({REFUSED_REQUEST} if case == "foreign" else set())
    _require({path.name for path in data.iterdir()} == names and {path.name for path in observations.iterdir()} == observation_names)
    originals, identities, total = {}, [], 0
    for folder, members in ((data, names), (observations, observation_names)):
        for name in sorted(members):
            maximum = MAX_PACKET if name in {PACKET, OBSERVATION_PACKET} else 8192 if name == REFUSED_REQUEST else MAX_CAPTURE + 4096
            original, identity = _file(folder / name, maximum)
            total += len(original)
            _require(total <= MAX_TOTAL)
            relative = (folder / name).relative_to(private).as_posix()
            identities.append({"relative_path": relative, **identity})
            originals[relative] = original
    packet = _decode(originals[(data / PACKET).relative_to(private).as_posix()])
    _require(set(packet) == {"schema_version", "tenant_id", "source_order_id", "captures"}
             and packet["schema_version"] == "customer-partial-return-monetary-posted-cycle-input-v1"
             and type(packet["captures"]) is list and len(packet["captures"]) == len(versions))
    _text(packet["tenant_id"])
    _text(packet["source_order_id"])
    for index, child in enumerate(packet["captures"]):
        _require(type(child) is dict and set(child) == {"capture", "tables"} and type(child["capture"]) is int and child["capture"] == index)
        _tables(child["tables"])
        raw = originals[(data / f"committed-capture-{index}.json").relative_to(private).as_posix()]
        _require(_same_typed(_decode(raw), child))
    envelope = _decode(originals[(observations / OBSERVATION_PACKET).relative_to(private).as_posix()])
    _require(set(envelope) == {"schema_version", "tenant_id", "source_order_id", "observations"}
             and envelope["schema_version"] == "customer-partial-return-monetary-posted-observations-input-v1"
             and envelope["tenant_id"] == packet["tenant_id"] and envelope["source_order_id"] == packet["source_order_id"]
             and type(envelope["observations"]) is list and len(envelope["observations"]) == len(kinds))
    for child, (kind, name) in zip(envelope["observations"], kinds.items(), strict=True):
        raw = originals[(observations / name).relative_to(private).as_posix()]
        _require(_same_typed(_decode(raw), child) and type(child) is dict
                 and set(child) == {"schema_version", "kind", "tenant_id", "source_order_id", "capture", "history_version", "plan_id", "plan_digest", "tables", "refusal"}
                 and child["schema_version"] == "customer-partial-return-monetary-browser-observation-v1"
                 and child["kind"] == kind and child["tenant_id"] == packet["tenant_id"] and child["source_order_id"] == packet["source_order_id"])
        index = 5 if kind == "ActiveValuationRefusal" else len(versions) - (3 if kind == "RetainedReplay" else 1)
        _require(type(child["capture"]) is int and child["capture"] == index
                 and type(child["history_version"]) is int and child["history_version"] == versions[index])
        _tables(child["tables"])
        if kind in {"RetainedReplay", "ActiveValuationRefusal"}:
            prefix = "FX1" if kind == "ActiveValuationRefusal" else "CRF3"
            _require(type(child["plan_id"]) is str and re.fullmatch(prefix + r"-[0-9a-f]{32}", child["plan_id"]) is not None
                     and type(child["plan_digest"]) is str and re.fullmatch(r"[0-9a-f]{64}", child["plan_digest"]) is not None)
        else:
            _require(child["plan_id"] is None and child["plan_digest"] is None)
        if kind in {"ActiveValuationRefusal", "ScopeRefusal"}:
            refusal = child["refusal"]
            _require(type(refusal) is dict and set(refusal) == {"operation", "status", "code"}
                     and refusal["operation"] == ("PrepareReturn" if kind == "ActiveValuationRefusal" else "ReadSource")
                     and type(refusal["status"]) is int and refusal["status"] == (409 if kind == "ActiveValuationRefusal" else 403)
                     and type(refusal["code"]) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", refusal["code"]) is not None)
            if kind == "ActiveValuationRefusal":
                _require(refusal["code"] == "monetary_return_state_conflict")
        else:
            _require(child["refusal"] is None)
    if case == "foreign":
        request = _decode(originals[(observations / REFUSED_REQUEST).relative_to(private).as_posix()])
        _require(set(request) == {"method", "route", "body"} and request["method"] == "POST" and request["route"] == "/api/v3/customer-partial-returns/plans")
        body = request["body"]
        _require(type(body) is dict and set(body) == {"command_id", "source_order_id", "quantity_scaled", "period_id", "posting_date", "reason", "expected_history_version"}
                 and body["source_order_id"] == packet["source_order_id"] and body["quantity_scaled"] == "4"
                 and type(body["expected_history_version"]) is int and body["expected_history_version"] == 2)
        for key, maximum in (("command_id", 140), ("period_id", 160), ("posting_date", 10), ("reason", 500)):
            _text(body[key], maximum)
        _require(date.fromisoformat(body["posting_date"]).isoformat() == body["posting_date"])
    if require_restore:
        restored = _decode(originals[(data / RESTORE).relative_to(private).as_posix()])
        _require(set(restored) == {"schema_version", "tenant_id", "source_order_id", "tables"}
                 and restored["schema_version"] == "customer-partial-return-monetary-posted-restored-input-v1"
                 and restored["tenant_id"] == packet["tenant_id"] and restored["source_order_id"] == packet["source_order_id"]
                 and _same_typed(restored["tables"], envelope["observations"][-1]["tables"]))
    source, source_identity = _file(READER, 2 * 1024 * 1024)
    _require(hashlib.sha256(source).hexdigest() == READER_SHA256)
    return {"case": case, "require_restore": require_restore, "identities": identities, "source": source_identity,
            "input_set_sha256": hashlib.sha256(_encode(identities)).hexdigest(),
            "input_sha256": hashlib.sha256(originals[(data / PACKET).relative_to(private).as_posix()]).hexdigest(),
            "observations_input_sha256": hashlib.sha256(originals[(observations / OBSERVATION_PACKET).relative_to(private).as_posix()]).hexdigest(),
            "restore_input_sha256": hashlib.sha256(originals[(data / RESTORE).relative_to(private).as_posix()]).hexdigest() if require_restore else None}


def _proof(original: bytes, inputs: dict[str, Any]) -> dict[str, Any]:
    proof = _decode(original)
    required = {"schema_version", "status", "case", "captures", "tables", "monetary_events", "final_posting_effects", "final_posted_lines",
        "final_debits_minor", "final_credits_minor", "zero_financial_entries_omitted", "original_rows_immutable", "active_prefix_witnesses",
        "posted_journals_bound", "physical_restorations_bound", "closing_valuations_bound", "audit_chain_valid", "audit_original_prefix_equal",
        "observations", "observation_business_tables", "observation_business_original_rows_equal", "observation_audit_actions_bound", "observation_chronology_bound",
        "populated_restore_original_rows_equal", "restored_tables", "restored_rows", "input_sha256", "observations_input_sha256", "restore_input_sha256",
        "oracle_source_sha256", "current_authorization_proven"}
    _require(set(proof) == required and proof["schema_version"] == "independent-monetary-posted-cycle-proof-v1" and proof["status"] == "passed"
             and proof["case"] == inputs["case"] and proof["current_authorization_proven"] is False)
    expected = {"captures": len(_case(inputs["case"])), "tables": 91, "monetary_events": 7,
                "observations": 4 if inputs["case"] == "foreign" else 3, "observation_business_tables": 89}
    _require(all(type(proof[key]) is int and proof[key] == value for key, value in expected.items()))
    for key in ("zero_financial_entries_omitted", "original_rows_immutable", "active_prefix_witnesses", "posted_journals_bound", "physical_restorations_bound",
                "closing_valuations_bound", "audit_chain_valid", "audit_original_prefix_equal", "observation_business_original_rows_equal", "observation_audit_actions_bound", "observation_chronology_bound"):
        _require(proof[key] is True)
    for key in ("final_posting_effects", "final_posted_lines", "restored_tables", "restored_rows"):
        _require(type(proof[key]) is int and 0 <= proof[key] <= 1_000_000)
    for key in ("final_debits_minor", "final_credits_minor"):
        _require(type(proof[key]) is str and re.fullmatch(r"[1-9][0-9]{0,24}", proof[key]) is not None)
    _require(proof["final_debits_minor"] == proof["final_credits_minor"] and proof["final_posting_effects"] > 0 and proof["final_posted_lines"] > 0
             and proof["oracle_source_sha256"] == READER_SHA256)
    # The independent reader derives actual totals first. This adapter then
    # binds its proof to the fixed mandatory browser fixture, not caller math.
    _require((proof["final_posting_effects"], proof["final_posted_lines"], proof["final_debits_minor"]) == EXPECTED_TOTALS[inputs["case"]])
    _require(all(_same_typed(proof[key], inputs[key]) for key in ("input_sha256", "observations_input_sha256", "restore_input_sha256")))
    _require(proof["populated_restore_original_rows_equal"] is inputs["require_restore"]
             and proof["restored_tables"] == (91 if inputs["require_restore"] else 0)
             and (proof["restored_rows"] > 0) == inputs["require_restore"])
    return proof


def _public(inputs: dict[str, Any], proof: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return {**proof, "schema_version": "customer-partial-return-monetary-browser-original-proof-v1",
            "isolated_modes_byte_equal": True, "I_proof_sha256": identity["sha256"], "IO_proof_sha256": identity["sha256"],
            "input_set_sha256": inputs["input_set_sha256"], "raw_financial_rows_published": False}


def _outcome(mode: str, code: int | None, *, timed_out: bool = False, launch_failed: bool = False) -> dict[str, Any]:
    return {"schema_version": "customer-partial-return-monetary-reader-execution-v1", "mode": mode, "isolated": True,
            "optimized": mode == "IO", "exit_code": code, "timed_out": timed_out, "launch_failed": launch_failed}


def verify_monetary_original_rows(private: Path, *, case: str, require_restore: bool) -> dict[str, Any]:
    inputs = _family(private, case=case, require_restore=require_restore)
    root = private / EXECUTIONS
    _require(not root.exists())
    # Reuse the existing path/reparse guard on a future directory before write.
    from tests.customer_partial_return_remainder_browser import _regular_path
    _regular_path(root, directory=True)
    root.mkdir()
    execution = root / uuid4().hex
    execution.mkdir()
    records: list[dict[str, Any]] = []
    proofs: list[bytes] = []
    qualified: dict[str, Any] = {}
    for mode, flags in (("I", ["-I"]), ("IO", ["-I", "-O"])):
        argv = [sys.executable, *flags, str(READER), "--input", str(private / FAMILY / case / PACKET),
                "--observations-input", str(private / OBSERVATIONS / case / OBSERVATION_PACKET), "--output", str(execution / (mode + ".json"))]
        if require_restore:
            argv.extend(("--restore-input", str(private / FAMILY / case / RESTORE)))
        outcome = _outcome(mode, None)
        with (execution / (mode + ".stdout")).open("xb") as stdout, (execution / (mode + ".stderr")).open("xb") as stderr:
            try:
                environment = {key: value for key, value in os.environ.items() if key in {"SYSTEMROOT", "SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"}}
                completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=60, check=False, env=environment)  # nosec B603
                outcome = _outcome(mode, completed.returncode)
            except subprocess.TimeoutExpired:
                outcome = _outcome(mode, None, timed_out=True)
            except OSError:
                outcome = _outcome(mode, None, launch_failed=True)
        common._write(execution / (mode + ".result.json"), outcome)
        _require(_same_typed(outcome, _outcome(mode, 0)))
        original, identity = _file(execution / (mode + ".json"), MAX_PROOF)
        qualified = _proof(original, inputs)
        streams = []
        for suffix in ("stdout", "stderr"):
            raw, metadata = _file(execution / (mode + "." + suffix), 64 * 1024)
            _require(raw == b"")
            streams.append(metadata)
        _, result_identity = _file(execution / (mode + ".result.json"), MAX_PROOF)
        records.append({"mode": mode, "proof": identity, "streams": streams, "result": result_identity})
        proofs.append(original)
        _require(_same_typed(_family(private, case=case, require_restore=require_restore), inputs))
    _require(proofs[0] == proofs[1])
    core = _public(inputs, qualified, records[0]["proof"])
    common._write(execution / "reader-custody.json", {"schema_version": "monetary-reader-custody-v1", "inputs": inputs, "executions": records, "public_core": core})
    _, identity = _file(execution / "reader-custody.json", MAX_PROOF)
    result = {**core, "execution_receipt_sha256": identity["sha256"]}
    require_monetary_original_binding(private, result, case=case, require_restore=require_restore)
    return result


def require_monetary_original_binding(private: Path, proof: dict[str, Any], *, case: str, require_restore: bool) -> None:
    inputs = _family(private, case=case, require_restore=require_restore)
    root = private / EXECUTIONS
    _regular(root, directory=True)
    paths = list(root.iterdir())
    _require(len(paths) == 1 and re.fullmatch(r"[0-9a-f]{32}", paths[0].name) is not None)
    execution = paths[0]
    _regular(execution, directory=True)
    _require({path.name for path in execution.iterdir()} == EXECUTION_NAMES)
    data, identity = _file(execution / "reader-custody.json", MAX_PROOF)
    _require(type(proof) is dict and proof.get("execution_receipt_sha256") == identity["sha256"])
    receipt = _decode(data)
    _require(set(receipt) == {"schema_version", "inputs", "executions", "public_core"} and receipt["schema_version"] == "monetary-reader-custody-v1"
             and _same_typed(receipt["inputs"], inputs) and type(receipt["executions"]) is list and len(receipt["executions"]) == 2)
    proofs, qualified = [], {}
    for row, mode in zip(receipt["executions"], ("I", "IO"), strict=True):
        _require(type(row) is dict and set(row) == {"mode", "proof", "streams", "result"} and row["mode"] == mode)
        original, identity = _file(execution / (mode + ".json"), MAX_PROOF)
        _require(_same_typed(identity, row["proof"]))
        proofs.append(original)
        qualified = _proof(original, inputs)
        streams = []
        for suffix in ("stdout", "stderr"):
            raw, metadata = _file(execution / (mode + "." + suffix), 64 * 1024)
            _require(raw == b"")
            streams.append(metadata)
        _require(_same_typed(streams, row["streams"]))
        raw, metadata = _file(execution / (mode + ".result.json"), MAX_PROOF)
        _require(_same_typed(metadata, row["result"]) and _same_typed(_decode(raw), _outcome(mode, 0)))
    _require(proofs[0] == proofs[1])
    core = _public(inputs, qualified, receipt["executions"][0]["proof"])
    _require(_same_typed(core, receipt["public_core"]) and _same_typed(proof, {**core, "execution_receipt_sha256": hashlib.sha256(data).hexdigest()}))
