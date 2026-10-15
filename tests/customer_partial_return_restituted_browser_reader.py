"""Private input custody and isolated C-reader binding for the fourth M7 case.

The five pinned independent reader files derive financial facts. This adapter
only joins opaque originals and admits their finite verified proof projection.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from tests import customer_partial_return_browser_reader as common
from tests import customer_partial_return_remainder_browser_reader as shared

FAMILY = "native-customer-partial-return-restituted-originals"
OBSERVATIONS = "native-customer-partial-return-restituted-observation-originals"
EXECUTIONS = "independent-customer-partial-return-restituted-row-verification"
PACKET = "posted-cycle-input.json"
RESTORE = "posted-cycle-restored-input.json"
OBSERVATIONS_PACKET = "posted-cycle-observations-input.json"
CHECKPOINTS = ("Original", "ZeroReturn", "ResaleInvoiced", "ResaleReturned")
KINDS = ("RetainedReplay", "DependencyRefusal", "FinalRead")
READER = Path(__file__).resolve().with_name("customer_partial_return_restituted_cycle_oracle.py")
SOURCE_HASHES = {
    "customer_partial_return_restituted_cycle_oracle.py": "fe2ede4c586014f1d63fc4ae639ea28c19740bdf21139f33ee7a7d7402459c35",
    "customer_partial_return_restituted_source_oracle.py": "77689aeb529ebc886a658120e824f5842f07e1c6e9fb302f5836356962f7bd40",
    "customer_partial_return_remainder_posted_oracle.py": "833b37ff15666b53504aea41c244d55ada3169df97f7f72bf7783d224b6e9c8d",
    "customer_partial_return_remainder_oracle.py": "e47d3900bb50e77bc4186eb91a5556fa495fdbb4c07cb408f5e89ac20f545510",
    "customer_partial_return_posted_cycle_oracle.py": "be85ca58d3dec5873527ae9654f9208c87b6a61e171cd2215b9d2da97346544e",
}
TABLES = shared.TABLES
EXECUTION_NAMES = common.EXECUTION_NAMES
MAX_CAPTURE_BYTES = common.MAX_CAPTURE_BYTES
MAX_OBSERVATION_BYTES = common.MAX_OBSERVATION_BYTES
MAX_PACKET_BYTES = common.MAX_PACKET_BYTES
MAX_TOTAL_BYTES = common.MAX_TOTAL_BYTES
MAX_PROOF_BYTES = common.MAX_PROOF_BYTES
MAX_STREAM_BYTES = common.MAX_STREAM_BYTES
_encode, _decode, _same_typed = common._encode, common._decode, common._same_typed
_require, _text = common._require, common._text
_regular, _file, _tables = shared._regular, shared._file, shared._tables
RestitutedOriginalRefusal = common.CustomerPartialReturnOriginalRefusal


def _sources() -> list[dict[str, Any]]:
    result = []
    for name, expected in SOURCE_HASHES.items():
        original, identity = _file(READER.with_name(name), MAX_PROOF_BYTES)
        _require(hashlib.sha256(original).hexdigest() == expected)
        result.append(identity)
    return result


def _family(private: Path, *, require_restore: bool) -> dict[str, Any]:
    _require(type(require_restore) is bool)
    _regular(private, directory=True)
    root, observation_root = private / FAMILY, private / OBSERVATIONS
    _regular(root, directory=True)
    _regular(observation_root, directory=True)
    captures = tuple(f"checkpoint-{number}.json" for number in range(4))
    names = {*captures, PACKET} | ({RESTORE} if require_restore else set())
    observation_names = {OBSERVATIONS_PACKET, *(kind + ".json" for kind in KINDS)}
    _require({path.name for path in root.iterdir()} == names and {path.name for path in observation_root.iterdir()} == observation_names)
    originals, identities = {}, []
    for folder, members in ((root, names), (observation_root, observation_names)):
        for name in sorted(members):
            maximum = MAX_PACKET_BYTES if name in {PACKET, OBSERVATIONS_PACKET} else MAX_OBSERVATION_BYTES if folder == observation_root else MAX_CAPTURE_BYTES
            data, identity = _file(folder / name, maximum)
            originals[name] = data
            identities.append({**identity, "member": (folder / name).relative_to(private).as_posix()})
    _require(sum(len(value) for value in originals.values()) <= MAX_TOTAL_BYTES)
    packet = _decode(originals[PACKET])
    identity_fields = ("tenant_id", "original_source_order_id", "resale_source_order_id")
    _require(set(packet) == {"schema_version", *identity_fields, "captures"}
             and packet["schema_version"] == "customer-partial-return-restituted-cycle-input-v1"
             and type(packet["captures"]) is list and len(packet["captures"]) == 4)
    for key in identity_fields:
        _text(packet[key])
    _require(packet["original_source_order_id"] != packet["resale_source_order_id"])
    for index, (name, checkpoint) in enumerate(zip(captures, CHECKPOINTS, strict=True)):
        value = _decode(originals[name])
        _require(set(value) == {"checkpoint", "tables"} and value["checkpoint"] == checkpoint)
        _tables(value["tables"])
        _require(_same_typed(value, packet["captures"][index]))
    observations = _decode(originals[OBSERVATIONS_PACKET])
    _require(set(observations) == {"schema_version", *identity_fields, "observations"}
             and observations["schema_version"] == "customer-partial-return-restituted-observations-input-v1"
             and all(observations[key] == packet[key] for key in identity_fields)
             and type(observations["observations"]) is list and len(observations["observations"]) == 3)
    values = []
    for index, kind in enumerate(KINDS):
        value = _decode(originals[kind + ".json"])
        _require(set(value) == {"schema_version", *identity_fields, "kind", "posted_plan_id", "plan_digest", "tables", "refusal"}
                 and value["schema_version"] == "customer-partial-return-restituted-browser-observation-v1" and value["kind"] == kind
                 and all(value[key] == packet[key] for key in identity_fields))
        _require(type(value["posted_plan_id"]) is str and re.fullmatch(r"CR2-[a-f0-9]{32}", value["posted_plan_id"]) is not None
                 and type(value["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["plan_digest"]) is not None)
        if kind == "DependencyRefusal":
            refused = value["refusal"]
            _require(type(refused) is dict and set(refused) == {"method", "route", "status", "code"}
                     and refused["method"] == "POST" and type(refused["status"]) is int and refused["status"] == 409
                     and refused["code"] == "customer_partial_return_reversal_dependency"
                     and refused["route"] == f"/api/v2/customer-partial-returns/plans/{value['posted_plan_id']}/reversals")
        else:
            _require(value["refusal"] is None)
        _tables(value["tables"])
        _require(_same_typed(value, observations["observations"][index]))
        values.append(value)
    _require((values[0]["posted_plan_id"], values[0]["plan_digest"]) == (values[2]["posted_plan_id"], values[2]["plan_digest"])
             and values[1]["posted_plan_id"] != values[0]["posted_plan_id"])
    final = values[-1]["tables"]
    if require_restore:
        restored = _decode(originals[RESTORE])
        _require(set(restored) == {"schema_version", *identity_fields, "tables"}
                 and restored["schema_version"] == "customer-partial-return-restituted-restored-input-v1"
                 and all(restored[key] == packet[key] for key in identity_fields)
                 and _same_typed(_tables(restored["tables"]), final))
    return {"require_restore": require_restore, "input_files": identities, "sources": _sources(),
            "input_set_sha256": hashlib.sha256(_encode(identities)).hexdigest(),
            "input_sha256": {"input": hashlib.sha256(originals[PACKET]).hexdigest(),
                             "observations_input": hashlib.sha256(originals[OBSERVATIONS_PACKET]).hexdigest(),
                             **({"restore_input": hashlib.sha256(originals[RESTORE]).hexdigest()} if require_restore else {})},
            "final_rows": sum(len(rows) for rows in final.values())}


def _expected(inputs: dict[str, Any], appended: int, admission_digest: str) -> dict[str, Any]:
    value = {"schema_version": "independent-restituted-cycle-proof-v1", "status": "passed", "checkpoints": 4, "tables": 79,
             "sources": 2, "governed_returns": 2, "original_cost_admission": {
                 "schema_version": "independent-finite-restituted-original-v1", "explicit_original_cost_admission": True,
                 "original_cost_admission_sha256": admission_digest, "original_cogs_effect_absent": True,
                 "original_quantity_scaled": 1, "original_gross_minor": 100, "original_cost_minor": 0,
                 "prior_zero_physical_quantity_scaled": 1, "prior_zero_physical_value_minor": 0,
                 "current_authorization_proven": False, "native_execution_proven": False},
             "final_actual_posting_effects": 5, "final_actual_posted_lines": 10, "final_debits_minor": 203, "final_credits_minor": 203,
             "final_account_minor_balances": {"AR": 1, "CASH": 0, "CLEARING": -1, "COGS": 1, "INVENTORY": 0, "REFUND": 0, "REVENUE": -1},
             "old_return_credit_minor": 0, "resale_revenue_minor": 100, "resale_original_cogs_absent": True,
             "new_return_credit_minor": 100, "new_return_cost_minor": 0, "no_fake_zero_financial_entries": True,
             "final_layer_quantity_scaled": 1, "final_layer_value_minor": 0,
             "old_return_later_immutable_consumption_dependency": True, "three_distinct_humans": True,
             "dependency_refusal_http_proven": True, "populated_restore_proven": inputs["require_restore"],
             "current_authorization_proven": False, "benchmark": False,
             "observations": 3, "observation_tables": 79, "observation_business_tables": 77, "observation_chronology_bound": True,
             "audit_actions_bound": True, "audit_chain_valid": True, "audit_original_prefix_equal": True,
             "business_original_rows_equal": True, "appended_audit_events": appended,
             "input_sha256": inputs["input_sha256"], "reader_source_sha256": dict(SOURCE_HASHES)}
    if inputs["require_restore"]:
        value.update(restored_tables=79, restored_rows=inputs["final_rows"], restore_target_final_observation=True)
    return value


def _proof(original: bytes, inputs: dict[str, Any]) -> dict[str, Any]:
    value = _decode(original)
    appended, admission = value.get("appended_audit_events"), value.get("original_cost_admission")
    _require(type(appended) is int and 2 <= appended <= 8192 and type(admission) is dict)
    admission_digest = cast(dict[str, Any], admission).get("original_cost_admission_sha256")
    _require(type(admission_digest) is str and re.fullmatch(r"[a-f0-9]{64}", admission_digest) is not None)
    _require(_same_typed(value, _expected(inputs, cast(int, appended), cast(str, admission_digest))))
    return value


def _public(inputs: dict[str, Any], proof_identity: dict[str, Any], appended: int, admission_digest: str) -> dict[str, Any]:
    return {**_expected(inputs, appended, admission_digest), "schema_version": "customer-partial-return-restituted-browser-original-proof-v1",
            "restored": inputs["require_restore"], "input_set_sha256": inputs["input_set_sha256"],
            "isolated_modes_byte_equal": True, "I_proof_sha256": proof_identity["sha256"], "IO_proof_sha256": proof_identity["sha256"],
            "raw_financial_rows_published": False}


def _outcome(mode: str, *, exit_code: int | None, timed_out: bool = False, launch_failed: bool = False) -> dict[str, Any]:
    return {"schema_version": "customer-partial-return-restituted-reader-execution-v1", "mode": mode,
            "exit_code": exit_code, "isolated": True, "optimized": mode == "IO", "timed_out": timed_out, "launch_failed": launch_failed}


def verify_restituted_original_rows(private: Path, *, require_restore: bool) -> dict[str, Any]:
    inputs = _family(private, require_restore=require_restore)
    root = private / EXECUTIONS
    _require(not root.exists())
    for ancestor in (root, *root.parents):
        _require(not ancestor.is_symlink() and not getattr(ancestor, "is_junction", lambda: False)())
        if ancestor.exists():
            _require(not getattr(ancestor.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    root.mkdir(parents=True)
    execution = root / uuid4().hex
    execution.mkdir()
    _regular(execution, directory=True)
    records: list[dict[str, Any]] = []
    proofs: list[bytes] = []
    qualified: dict[str, Any] = {}
    for mode, flags in (("I", ["-I"]), ("IO", ["-I", "-O"])):
        argv = [sys.executable, *flags, str(READER), "--input", str(private / FAMILY / PACKET),
                "--observations-input", str(private / OBSERVATIONS / OBSERVATIONS_PACKET), "--output", str(execution / (mode + ".json"))]
        if require_restore:
            argv.extend(("--restore-input", str(private / FAMILY / RESTORE)))
        outcome = _outcome(mode, exit_code=None)
        with (execution / (mode + ".stdout")).open("xb") as stdout, (execution / (mode + ".stderr")).open("xb") as stderr:
            try:
                environment = {key: value for key, value in os.environ.items() if key in {"SYSTEMROOT", "SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"}}
                result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=60,
                                        check=False, env=environment)  # nosec B603
                outcome = _outcome(mode, exit_code=result.returncode)
            except subprocess.TimeoutExpired:
                outcome = _outcome(mode, exit_code=None, timed_out=True)
            except OSError:
                outcome = _outcome(mode, exit_code=None, launch_failed=True)
        common._write(execution / (mode + ".result.json"), outcome)
        _require(_same_typed(outcome, _outcome(mode, exit_code=0)))
        original, identity = _file(execution / (mode + ".json"), MAX_PROOF_BYTES)
        qualified = _proof(original, inputs)
        streams = []
        for suffix in ("stdout", "stderr"):
            data, metadata = _file(execution / (mode + "." + suffix), MAX_STREAM_BYTES)
            _require(data == b"")
            streams.append(metadata)
        _, outcome_identity = _file(execution / (mode + ".result.json"), MAX_PROOF_BYTES)
        records.append({"mode": mode, "proof": identity, "streams": streams, "result": outcome_identity})
        proofs.append(original)
        _require(_same_typed(_family(private, require_restore=require_restore), inputs))
    _require(proofs[0] == proofs[1])
    core = _public(inputs, records[0]["proof"], qualified["appended_audit_events"], qualified["original_cost_admission"]["original_cost_admission_sha256"])
    receipt = {"schema_version": "customer-partial-return-restituted-reader-custody-v1", "inputs": inputs, "executions": records, "public_core": core}
    common._write(execution / "reader-custody.json", receipt)
    _, identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    verified = {**core, "execution_receipt_sha256": identity["sha256"]}
    require_restituted_original_binding(private, verified, require_restore=require_restore)
    return verified


def require_restituted_original_binding(private: Path, proof: dict[str, Any], *, require_restore: bool) -> None:
    inputs = _family(private, require_restore=require_restore)
    root = private / EXECUTIONS
    _regular(root, directory=True)
    directories = list(root.iterdir())
    _require(len(directories) == 1 and re.fullmatch(r"[a-f0-9]{32}", directories[0].name) is not None)
    execution = directories[0]
    _regular(execution, directory=True)
    _require({path.name for path in execution.iterdir()} == EXECUTION_NAMES)
    data, identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    _require(type(proof) is dict and proof.get("execution_receipt_sha256") == identity["sha256"])
    receipt = _decode(data)
    _require(set(receipt) == {"schema_version", "inputs", "executions", "public_core"}
             and receipt["schema_version"] == "customer-partial-return-restituted-reader-custody-v1"
             and _same_typed(receipt["inputs"], inputs) and type(receipt["executions"]) is list and len(receipt["executions"]) == 2)
    originals = []
    qualified: dict[str, Any] = {}
    for row, mode in zip(receipt["executions"], ("I", "IO"), strict=True):
        _require(type(row) is dict and set(row) == {"mode", "proof", "streams", "result"} and row["mode"] == mode)
        data, identity = _file(execution / (mode + ".json"), MAX_PROOF_BYTES)
        _require(_same_typed(identity, row["proof"]))
        originals.append(data)
        qualified = _proof(data, inputs)
        streams = []
        for suffix in ("stdout", "stderr"):
            data, metadata = _file(execution / (mode + "." + suffix), MAX_STREAM_BYTES)
            _require(data == b"")
            streams.append(metadata)
        _require(_same_typed(streams, row["streams"]))
        data, identity = _file(execution / (mode + ".result.json"), MAX_PROOF_BYTES)
        _require(_same_typed(identity, row["result"]) and _same_typed(_decode(data), _outcome(mode, exit_code=0)))
    _require(originals[0] == originals[1])
    core = _public(inputs, receipt["executions"][0]["proof"], qualified["appended_audit_events"], qualified["original_cost_admission"]["original_cost_admission_sha256"])
    _, identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    _require(_same_typed(receipt["public_core"], core) and _same_typed(proof, {**core, "execution_receipt_sha256": identity["sha256"]}))
    _require(_same_typed(_family(private, require_restore=require_restore), inputs))
