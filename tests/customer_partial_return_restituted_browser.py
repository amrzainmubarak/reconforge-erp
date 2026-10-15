"""Private, serial-fixture originals for zero-cost Stock resale and return.

Four immutable checkpoints span two real Stock sources. The separate reader
owns financial interpretation; this observer never supplies a posting endpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.io.structured import parse_json_document
from tests.customer_partial_return_remainder_browser import (
    LOAD_POLICY,
    MAX_CAPTURE_BYTES,
    MAX_OBSERVATION_BYTES,
    MAX_PACKET_BYTES,
    ReceiptRuntime,
    _bytes,
    _read,
    _regular_path,
    _retain,
    _snapshot,
    _storage,
    _tables,
    _text,
    require,
    seed_remainder_browser,
)

FAMILY = "native-customer-partial-return-restituted-originals"
OBSERVATIONS = "native-customer-partial-return-restituted-observation-originals"
REFUSED = "native-customer-partial-return-restituted-failed-observation-originals"
CHECKPOINTS = ("Original", "ZeroReturn", "ResaleInvoiced", "ResaleReturned")
KINDS = ("RetainedReplay", "DependencyRefusal", "FinalRead")
PACKET = "posted-cycle-input.json"
RESTORE = "posted-cycle-restored-input.json"
OBSERVATION_PACKET = "posted-cycle-observations-input.json"
OBSERVATION_SCHEMA = "customer-partial-return-restituted-browser-observation-v1"
OBSERVATION_FIELDS = {"schema_version", "tenant_id", "original_source_order_id", "resale_source_order_id",
                      "kind", "posted_plan_id", "plan_digest", "tables", "refusal"}


def _root(root: Path) -> Path:
    require(root.name == FAMILY)
    return _storage(root)


def _files(root: Path) -> list[Path]:
    files = []
    for path in root.iterdir():
        _regular_path(path)
        require(path.name in {PACKET, RESTORE, *(f"checkpoint-{n}.json" for n in range(4))})
        if path.name.startswith("checkpoint-"):
            files.append(path)
    files.sort(key=lambda path: path.name)
    require([path.name for path in files] == [f"checkpoint-{n}.json" for n in range(len(files))])
    return files


def _load(path: Path, *, checkpoint: str | None = None, kind: str | None = None) -> dict[str, Any]:
    _regular_path(path)
    value = parse_json_document(_read(path, MAX_OBSERVATION_BYTES).decode("utf-8"),
                                policy=LOAD_POLICY, reject_fractional_numbers=True)
    require(type(value) is dict)
    result = cast(dict[str, Any], value)
    if checkpoint is not None:
        require(kind is None and checkpoint in CHECKPOINTS and set(result) == {"checkpoint", "tables"}
                and result["checkpoint"] == checkpoint)
    else:
        require(kind in KINDS and set(result) == OBSERVATION_FIELDS and result["schema_version"] == OBSERVATION_SCHEMA
                and result["kind"] == kind)
        for key in ("tenant_id", "original_source_order_id", "resale_source_order_id"):
            _text(result[key])
        _plan_pin(result["posted_plan_id"], result["plan_digest"])
        _refusal(result["refusal"], kind=kind, original_plan=result["posted_plan_id"])
    _tables(result["tables"])
    return result


def _plan_pin(plan: Any, digest: Any) -> None:
    require(type(plan) is str and re.fullmatch(r"CR2-[a-f0-9]{32}", plan) is not None)
    require(type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest) is not None)


def _refusal(value: Any, *, kind: str | None, original_plan: str) -> None:
    if kind != "DependencyRefusal":
        require(value is None)
        return
    require(type(value) is dict and set(value) == {"method", "route", "status", "code"}
            and value["method"] == "POST" and type(value["status"]) is int and value["status"] == 409
            and value["code"] == "customer_partial_return_reversal_dependency"
            and value["route"] == f"/api/v2/customer-partial-returns/plans/{original_plan}/reversals")


def _audit(before: dict[str, list[str]], after: dict[str, list[str]], tenant: str) -> None:
    from tests.customer_partial_return_restituted_cycle_oracle import verify_audit_only_transition
    verify_audit_only_transition(before, after, tenant_id=tenant)


def _observe(root: Path, *, runtime: ReceiptRuntime, original: str, resale: str,
             kind: str, plan_id: str, plan_digest: str, tables: dict[str, list[str]],
             refusal: dict[str, Any] | None) -> None:
    _plan_pin(plan_id, plan_digest)
    require(kind in KINDS and original != resale)
    _refusal(refusal, kind=kind, original_plan=plan_id)
    baseline = _load(root / "checkpoint-3.json", checkpoint="ResaleReturned")
    folder = _storage(root.parent / OBSERVATIONS)
    candidate = {"schema_version": OBSERVATION_SCHEMA, "tenant_id": runtime.tenant,
                 "original_source_order_id": original, "resale_source_order_id": resale, "kind": kind,
                 "posted_plan_id": plan_id, "plan_digest": plan_digest, "tables": _tables(tables), "refusal": refusal}
    try:
        require({path.name for path in folder.iterdir()} <= {OBSERVATION_PACKET, *(name + ".json" for name in KINDS)})
        for path in folder.iterdir():
            _regular_path(path)
        _audit(baseline["tables"], tables, runtime.tenant)
        _retain(folder / (kind + ".json"), _bytes(candidate, MAX_OBSERVATION_BYTES), same_allowed=True)
    except (ValueError, TypeError, KeyError):
        refused = _storage(root.parent / REFUSED)
        require(len(list(refused.iterdir())) < 16)
        failure = {"schema_version": "customer-partial-return-restituted-refused-observation-v1",
                   "reason_code": "audit_only_transition_refused", "candidate": candidate,
                   "retained_original_sha256": hashlib.sha256(_read(root / "checkpoint-3.json", MAX_CAPTURE_BYTES)).hexdigest()}
        _retain(refused / ("refused-observation-" + uuid4().hex + ".json"), _bytes(failure, MAX_OBSERVATION_BYTES))
        raise ValueError("Restituted browser observation refused.") from None


def capture_restituted_browser(runtime: ReceiptRuntime, original: str, root: Path, *, checkpoint: str,
                               resale: str | None = None, posted_plan_id: str | None = None,
                               plan_digest: str | None = None, observation: str | None = None,
                               refusal: dict[str, Any] | None = None) -> dict[str, Any]:
    root = _root(root)
    files = _files(root)
    require(checkpoint in CHECKPOINTS and (observation is None or observation in KINDS))
    index = CHECKPOINTS.index(checkpoint)
    require(index < 2 or (resale is not None and _text(resale) != _text(original)))
    require(index >= 2 or resale is None)
    for n, path in enumerate(files):
        _load(path, checkpoint=CHECKPOINTS[n])
    source = original if index < 2 or observation == "DependencyRefusal" else _text(resale)
    version, tables, last = _snapshot(runtime, source, "zero")
    require(version == (0 if index in {0, 2} else 1))
    if index in {0, 2}:
        require(last is None and posted_plan_id is None and plan_digest is None)
    else:
        _plan_pin(posted_plan_id, plan_digest)
        require(last is not None and last["phase"] == 2 and (last["plan_id"], last["plan_digest"]) == (posted_plan_id, plan_digest))
    require(index == len(files) or (index == 3 and len(files) == 4))
    if index == len(files):
        require(observation is None and refusal is None)
        _retain(root / f"checkpoint-{index}.json", _bytes({"checkpoint": checkpoint, "tables": tables}, MAX_CAPTURE_BYTES))
        if index == 3:
            assemble_restituted_browser(root, tenant=runtime.tenant, original=original, resale=_text(resale))
    else:
        require(checkpoint == "ResaleReturned" and observation in KINDS and resale is not None)
        _observe(root, runtime=runtime, original=original, resale=_text(resale), kind=str(observation),
                 plan_id=str(posted_plan_id), plan_digest=str(plan_digest), tables=tables, refusal=refusal)
    return {"checkpoints": len(_files(root)), "tables": 79, "raw_financial_rows_published": False}


def assemble_restituted_browser(root: Path, *, tenant: str, original: str, resale: str) -> dict[str, Any]:
    root = _root(root)
    require(len(_files(root)) == 4 and _text(original) != _text(resale))
    packet = {"schema_version": "customer-partial-return-restituted-cycle-input-v1", "tenant_id": _text(tenant),
              "original_source_order_id": original, "resale_source_order_id": resale,
              "captures": [_load(root / f"checkpoint-{index}.json", checkpoint=name) for index, name in enumerate(CHECKPOINTS)]}
    _retain(root / PACKET, _bytes(packet, MAX_PACKET_BYTES), same_allowed=True)
    return packet


def seed_restituted_browser(admin_dsn: str, app_dsn: str) -> tuple[ReceiptRuntime, str]:
    return seed_remainder_browser(admin_dsn, app_dsn, case="zero")


def verify_seeded_restituted_browser(runtime: ReceiptRuntime, *, custody_root: Path, original: str,
                                    original_app_dsn: str) -> dict[str, Any]:
    """Use the real browser's sealed resale identity, never a guessed identifier."""
    root = _root(custody_root)
    _regular_path(root / PACKET)
    value = parse_json_document(_read(root / PACKET, MAX_PACKET_BYTES).decode("utf-8"),
                                policy=LOAD_POLICY, reject_fractional_numbers=True)
    require(type(value) is dict)
    packet = cast(dict[str, Any], value)
    require(set(packet) == {"schema_version", "tenant_id", "original_source_order_id", "resale_source_order_id", "captures"}
            and packet["schema_version"] == "customer-partial-return-restituted-cycle-input-v1"
            and packet["tenant_id"] == runtime.tenant and packet["original_source_order_id"] == original)
    resale = _text(packet["resale_source_order_id"])
    require(packet == assemble_restituted_browser(root, tenant=runtime.tenant, original=original, resale=resale))
    return verify_restituted_browser(runtime, custody_root=root, original=original, resale=resale, original_app_dsn=original_app_dsn)


def verify_restituted_browser(runtime: ReceiptRuntime, *, custody_root: Path, original: str, resale: str,
                              original_app_dsn: str) -> dict[str, Any]:
    root = _root(custody_root)
    assemble_restituted_browser(root, tenant=runtime.tenant, original=original, resale=resale)
    version, tables, last = _snapshot(runtime, resale, "zero")
    require(version == 1 and last is not None)
    if last is None:
        raise ValueError("Committed resale return is required.")
    require(last["phase"] == 2)
    if runtime.factory.settings.dsn == original_app_dsn:
        _observe(root, runtime=runtime, original=original, resale=resale, kind="FinalRead",
                 plan_id=last["plan_id"], plan_digest=last["plan_digest"], tables=tables, refusal=None)
    folder = _storage(root.parent / OBSERVATIONS)
    require({path.name for path in folder.iterdir()} in ({name + ".json" for name in KINDS},
            {OBSERVATION_PACKET, *(name + ".json" for name in KINDS)}))
    values = [_load(folder / (kind + ".json"), kind=kind) for kind in KINDS]
    baseline = _load(root / "checkpoint-3.json", checkpoint="ResaleReturned")
    for value in values:
        require((value["tenant_id"], value["original_source_order_id"], value["resale_source_order_id"]) == (runtime.tenant, original, resale))
        _audit(baseline["tables"], value["tables"], runtime.tenant)
    require(tables == values[-1]["tables"])
    packet = {"schema_version": "customer-partial-return-restituted-observations-input-v1", "tenant_id": runtime.tenant,
              "original_source_order_id": original, "resale_source_order_id": resale, "observations": values}
    _retain(folder / OBSERVATION_PACKET, _bytes(packet, MAX_PACKET_BYTES), same_allowed=True)
    if runtime.factory.settings.dsn != original_app_dsn:
        restored = {"schema_version": "customer-partial-return-restituted-restored-input-v1", "tenant_id": runtime.tenant,
                    "original_source_order_id": original, "resale_source_order_id": resale, "tables": tables}
        _retain(root / RESTORE, _bytes(restored, MAX_CAPTURE_BYTES), same_allowed=True)
    return {"schema_version": "customer-partial-return-restituted-browser-custody-proof-v1", "checkpoints": 4,
            "tables": [{"table": name, "rows": len(rows), "sha256": hashlib.sha256(_bytes(rows, MAX_CAPTURE_BYTES)).hexdigest()}
                       for name, rows in sorted(tables.items())], "raw_financial_rows_published": False,
            "independent_financial_verification_required": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture",))
    parser.parse_args()
    try:
        runtime = ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=os.environ["RECONFORGE_GFO_APP_DSN"], require_tls=False)),
                                 "", os.environ["RECONFORGE_ERP_TENANT"], os.environ["RECONFORGE_ERP_PASSWORD"])
        kind = os.environ.get("RECONFORGE_PARTIAL_RESTITUTED_OBSERVATION")
        refusal = None
        if kind == "DependencyRefusal":
            refusal = {"method": os.environ["RECONFORGE_PARTIAL_REFUSAL_METHOD"], "route": os.environ["RECONFORGE_PARTIAL_REFUSAL_ROUTE"],
                       "status": int(os.environ["RECONFORGE_PARTIAL_REFUSAL_STATUS"]), "code": os.environ["RECONFORGE_PARTIAL_REFUSAL_CODE"]}
        capture_restituted_browser(runtime, os.environ["RECONFORGE_CUSTOMER_PARTIAL_RETURN_SOURCE"],
            Path(os.environ["RECONFORGE_PARTIAL_RESTITUTED_CUSTODY_ROOT"]), checkpoint=os.environ["RECONFORGE_PARTIAL_RESTITUTED_CHECKPOINT"],
            resale=os.environ.get("RECONFORGE_PARTIAL_RESALE_SOURCE"), posted_plan_id=os.environ.get("RECONFORGE_PARTIAL_POSTED_PLAN"),
            plan_digest=os.environ.get("RECONFORGE_PARTIAL_POSTED_DIGEST"), observation=kind, refusal=refusal)
    except Exception:
        print("Committed restituted browser observation refused.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
