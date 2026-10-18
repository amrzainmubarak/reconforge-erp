"""Private original custody and isolated execution for three v2 HTTPS cases.

Financial expectations stay in three byte-pinned stdlib readers. This bridge
joins separately retained capture/observation/restore originals, retains both
real child executions, and rebinds every input and proof around publication.
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

FAMILY = "native-customer-partial-return-remainder-originals"
OBSERVATIONS = "native-customer-partial-return-remainder-observation-originals"
EXECUTIONS = "independent-customer-partial-return-remainder-row-verification"
PACKET = "posted-cycle-input.json"
RESTORE = "posted-cycle-restored-input.json"
OBSERVATIONS_PACKET = "posted-cycle-observations-input.json"
EVENTS = {"ordinary": 3, "zero": 7, "refund": 6}
REPLAY = {"ordinary": 1, "zero": 1, "refund": 4}
READER = Path(__file__).resolve().with_name("customer_partial_return_remainder_posted_oracle.py")
SOURCE_HASHES = {
    "customer_partial_return_remainder_posted_oracle.py": "833b37ff15666b53504aea41c244d55ada3169df97f7f72bf7783d224b6e9c8d",
    "customer_partial_return_remainder_oracle.py": "e47d3900bb50e77bc4186eb91a5556fa495fdbb4c07cb408f5e89ac20f545510",
    "customer_partial_return_posted_cycle_oracle.py": "be85ca58d3dec5873527ae9654f9208c87b6a61e171cd2215b9d2da97346544e",
}
TABLES = (*common.TABLES, "customer_partial_return_allocation_witnesses")
EXECUTION_NAMES = common.EXECUTION_NAMES
MAX_CAPTURE_BYTES = common.MAX_CAPTURE_BYTES
MAX_OBSERVATION_BYTES = common.MAX_OBSERVATION_BYTES
MAX_PACKET_BYTES = common.MAX_PACKET_BYTES
MAX_TOTAL_BYTES = common.MAX_TOTAL_BYTES
MAX_PROOF_BYTES = common.MAX_PROOF_BYTES
MAX_STREAM_BYTES = common.MAX_STREAM_BYTES

_encode = common._encode
_decode = common._decode
_same_typed = common._same_typed
_require = common._require
_text = common._text
RemainderOriginalRefusal = common.CustomerPartialReturnOriginalRefusal


def _regular(path: Path, *, directory: bool = False) -> None:
    _require(path.is_absolute() and ".." not in path.parts)
    for item in (path, *path.parents):
        _require(not item.is_symlink())
        if item.exists():
            _require(not getattr(item.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    _require(path.is_dir() if directory else path.is_file())


def _file(path: Path, maximum: int) -> tuple[bytes, dict[str, Any]]:
    _regular(path)
    data, identity = common._file(path, maximum)
    _regular(path)
    return data, identity


def _case(case: str) -> int:
    _require(type(case) is str and case in EVENTS)
    return EVENTS[case]


def _tables(value: Any) -> dict[str, list[str]]:
    _require(type(value) is dict and set(value) == set(TABLES))
    for rows in value.values():
        _require(type(rows) is list and len(rows) <= 4096 and all(type(row) is str for row in rows))
        _require(rows == sorted(rows) and len(rows) == len(set(rows)))
    return value


def _sources() -> list[dict[str, Any]]:
    identities = []
    for name, expected in SOURCE_HASHES.items():
        original, identity = _file(READER.with_name(name), MAX_PROOF_BYTES)
        _require(hashlib.sha256(original).hexdigest() == expected)
        identities.append(identity)
    return identities


def _family(private: Path, *, case: str, require_restore: bool) -> dict[str, Any]:
    count = _case(case)
    _require(type(require_restore) is bool)
    _regular(private, directory=True)
    root, observation_root = private / FAMILY / case, private / OBSERVATIONS / case
    _regular(root, directory=True)
    _regular(observation_root, directory=True)
    captures = tuple(f"committed-capture-{number}.json" for number in range(count + 1))
    observation_files = ((f"retained-replay-{REPLAY[case]}.json", "RetainedReplay", REPLAY[case]),
                         ("final-observation.json", "FinalRead", count))
    names = set(captures) | {PACKET} | ({RESTORE} if require_restore else set())
    _require({path.name for path in root.iterdir()} == names)
    observation_names = {row[0] for row in observation_files} | {OBSERVATIONS_PACKET}
    _require({path.name for path in observation_root.iterdir()} == observation_names)
    originals, identities = {}, []
    for folder, members in ((root, names), (observation_root, observation_names)):
        for name in sorted(members):
            maximum = MAX_PACKET_BYTES if name in {PACKET, OBSERVATIONS_PACKET} else MAX_OBSERVATION_BYTES if folder == observation_root else MAX_CAPTURE_BYTES
            data, identity = _file(folder / name, maximum)
            originals[name] = data
            identities.append({**identity, "member": (folder / name).relative_to(private).as_posix()})
    _require(sum(len(value) for value in originals.values()) <= MAX_TOTAL_BYTES)
    packet = _decode(originals[PACKET])
    _require(set(packet) == {"schema_version", "case", "tenant_id", "source_order_id", "captures"}
             and packet["schema_version"] == "customer-partial-return-remainder-posted-cycle-input-v1" and packet["case"] == case)
    for key in ("tenant_id", "source_order_id"):
        _text(packet[key])
    _require(type(packet["captures"]) is list and len(packet["captures"]) == count + 1)
    fields = {"schema_version", "tenant_id", "source_order_id", "history_version", "posted_plan_id", "plan_digest", "tables"}
    values = []
    for number, name in enumerate(captures):
        value = _decode(originals[name])
        _require(set(value) == fields and value["schema_version"] == "customer-partial-return-remainder-browser-capture-v1")
        _require(all(value[key] == packet[key] for key in ("tenant_id", "source_order_id"))
                 and type(value["history_version"]) is int and value["history_version"] == number)
        if number == 0:
            _require(value["posted_plan_id"] is None and value["plan_digest"] is None)
        else:
            _text(value["posted_plan_id"])
            _require(type(value["plan_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["plan_digest"]) is not None)
        _tables(value["tables"])
        _require(_same_typed(value, packet["captures"][number]))
        values.append(value)
    observations = _decode(originals[OBSERVATIONS_PACKET])
    _require(set(observations) == {"schema_version", "case", "tenant_id", "source_order_id", "observations"}
             and observations["schema_version"] == "customer-partial-return-remainder-posted-observations-input-v1"
             and all(observations[key] == packet[key] for key in ("case", "tenant_id", "source_order_id"))
             and type(observations["observations"]) is list and len(observations["observations"]) == 2)
    for index, (name, kind, version) in enumerate(observation_files):
        value = _decode(originals[name])
        _require(set(value) == fields | {"kind"}
                 and value["schema_version"] == "customer-partial-return-remainder-browser-observation-v1"
                 and value["kind"] == kind and type(value["history_version"]) is int and value["history_version"] == version)
        _require(all(value[key] == values[version][key] for key in ("tenant_id", "source_order_id", "posted_plan_id", "plan_digest")))
        _tables(value["tables"])
        _require(_same_typed(value, observations["observations"][index]))
    final = observations["observations"][-1]["tables"]
    if require_restore:
        restored = _decode(originals[RESTORE])
        _require(set(restored) == {"schema_version", "case", "tenant_id", "source_order_id", "tables"}
                 and restored["schema_version"] == "customer-partial-return-remainder-posted-restored-input-v1"
                 and all(restored[key] == packet[key] for key in ("case", "tenant_id", "source_order_id"))
                 and _same_typed(_tables(restored["tables"]), final))
    return {"case": case, "require_restore": require_restore, "input_files": identities, "sources": _sources(),
            "input_set_sha256": hashlib.sha256(_encode(identities)).hexdigest(),
            "input_sha256": {"input": hashlib.sha256(originals[PACKET]).hexdigest(),
                             "observations_input": hashlib.sha256(originals[OBSERVATIONS_PACKET]).hexdigest(),
                             **({"restore_input": hashlib.sha256(originals[RESTORE]).hexdigest()} if require_restore else {})},
            "final_rows": sum(len(rows) for rows in final.values())}


def _expected(inputs: dict[str, Any], appended: int) -> dict[str, Any]:
    case = inputs["case"]
    count = EVENTS[case]
    effects, lines, debit = {"ordinary": (6, 12, 4001), "zero": (4, 8, 4), "refund": (8, 17, 81000)}[case]
    value = {"status": "passed", "case": case, "events": count, "captures": count + 1, "tables": 79,
             "positive_original_consumptions": 1, "history_capacity": 256, "allocation_policy": "remaining-original-v1",
             "new_actual_posting_effects": effects, "new_actual_posted_lines": lines, "new_debits_minor": debit, "new_credits_minor": debit,
             "zero_financial_entries_omitted": True, "immutable_original_consumptions": True, "independent_active_prefix_witnesses": True,
             "three_distinct_humans": True, "original_zero_cost_admission": False, "benchmark": False,
             "observation_schema": "customer-partial-return-remainder-posted-observations-input-v1", "observations": 2,
             "observation_tables": 79, "observation_business_tables": 77, "observation_chronology_bound": True,
             "appended_audit_events": appended, "audit_original_prefix_equal": True, "audit_chain_valid": True,
             "audit_actions_bound": True, "business_original_rows_equal": True,
             "input_sha256": inputs["input_sha256"], "reader_source_sha256": dict(SOURCE_HASHES)}
    if inputs["require_restore"]:
        value.update(restored_tables=79, restored_rows=inputs["final_rows"], restored_original_rows_equal=True, restore_target_final_observation=True)
    return value


def _proof(original: bytes, inputs: dict[str, Any]) -> dict[str, Any]:
    value = _decode(original)
    appended = value.get("appended_audit_events")
    _require(type(appended) is int and 1 <= appended <= 8192)
    _require(_same_typed(value, _expected(inputs, cast(int, appended))))
    return value


def _public(inputs: dict[str, Any], proof_identity: dict[str, Any], appended: int) -> dict[str, Any]:
    # Finite metrics copied only after exact typed comparison to a real proof.
    return {"schema_version": "customer-partial-return-remainder-browser-original-proof-v1",
            **_expected(inputs, appended), "restored": inputs["require_restore"],
            "input_set_sha256": inputs["input_set_sha256"], "isolated_modes_byte_equal": True,
            "I_proof_sha256": proof_identity["sha256"], "IO_proof_sha256": proof_identity["sha256"],
            "raw_financial_rows_published": False}


def _outcome(mode: str, *, exit_code: int | None, timed_out: bool = False, launch_failed: bool = False) -> dict[str, Any]:
    return {"schema_version": "customer-partial-return-remainder-reader-execution-v1", "mode": mode,
            "exit_code": exit_code, "isolated": True, "optimized": mode == "IO", "timed_out": timed_out, "launch_failed": launch_failed}


def verify_remainder_original_rows(private: Path, *, case: str, require_restore: bool) -> dict[str, Any]:
    inputs = _family(private, case=case, require_restore=require_restore)
    root = private / EXECUTIONS / case
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
        argv = [sys.executable, *flags, str(READER), "--input", str(private / FAMILY / case / PACKET),
                "--observations-input", str(private / OBSERVATIONS / case / OBSERVATIONS_PACKET), "--output", str(execution / (mode + ".json"))]
        if require_restore:
            argv.extend(("--restore-input", str(private / FAMILY / case / RESTORE)))
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
        _require(_same_typed(_family(private, case=case, require_restore=require_restore), inputs))
    _require(proofs[0] == proofs[1])
    core = _public(inputs, records[0]["proof"], qualified["appended_audit_events"])
    receipt = {"schema_version": "customer-partial-return-remainder-reader-custody-v1", "inputs": inputs, "executions": records, "public_core": core}
    common._write(execution / "reader-custody.json", receipt)
    _, identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    verified = {**core, "execution_receipt_sha256": identity["sha256"]}
    require_remainder_original_binding(private, verified, case=case, require_restore=require_restore)
    return verified


def require_remainder_original_binding(private: Path, proof: dict[str, Any], *, case: str, require_restore: bool) -> None:
    inputs = _family(private, case=case, require_restore=require_restore)
    root = private / EXECUTIONS / case
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
             and receipt["schema_version"] == "customer-partial-return-remainder-reader-custody-v1"
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
    core = _public(inputs, receipt["executions"][0]["proof"], qualified["appended_audit_events"])
    _, identity = _file(execution / "reader-custody.json", MAX_PROOF_BYTES)
    _require(_same_typed(receipt["public_core"], core) and _same_typed(proof, {**core, "execution_receipt_sha256": identity["sha256"]}))
    _require(_same_typed(_family(private, case=case, require_restore=require_restore), inputs))
