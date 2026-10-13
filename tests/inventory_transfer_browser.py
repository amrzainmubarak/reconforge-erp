"""Original transfer rows, genuine approved starting inputs and restore probes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.test_postgres_inventory_transfer import TABLES, transfer_runtime

ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_EXPORT_SHA256: dict[str, str] = {}
INVENTORY_TRANSFER_TABLES = (*TABLES, "inventory_quantity_source_guards", "inventory_quantity_source_releases", "inventory_quantity_claim_gates",
    "inventory_units_of_measure", "inventory_items", "inventory_locations", "inventory_warehouses", "inventory_movements", "inventory_movement_lines",
    "inventory_valuation_documents", "inventory_valuation_lines", "inventory_valuation_input_costs", "inventory_cost_layers", "inventory_layer_consumptions",
    "inventory_valuation_reversals", "inventory_valuation_reversal_effects", "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links",
    "inventory_receipt_commands", "finance_entries", "finance_entry_lines", "finance_posting_effects", "domain_audit_events", "outbox_events")
INVENTORY_TRANSFER_WORKSPACE_PROBE_TABLES = tuple(name for name in INVENTORY_TRANSFER_TABLES if name != "domain_audit_events")
INVENTORY_TRANSFER_TAMPER = (
    "UPDATE reconforge.inventory_transfer_sources SET quantity_scaled=quantity_scaled+1 WHERE tenant_id=%s",
    "DELETE FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s AND owner_namespace='IT1'",
    "DELETE FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s AND operation='post'",
)


def inventory_transfer_proof(runtime: Any, *, actor_name: str = "browser-poster") -> dict[str, Any]:
    """Export authorized original rows, with no arithmetic or credentials."""
    from psycopg import sql

    with runtime.actor(actor_name) as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        owner.list_transfers({"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}, actor=actor)
        role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        if dict(role) != {"rolsuper": False, "rolbypassrls": False}:
            raise ValueError("Original transfer export requires an ordinary tenant role")
        populations = {}
        for name in INVENTORY_TRANSFER_TABLES:
            populations[name] = [row["original"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) original FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (runtime.tenant,))]
    paths = ("reconforge/domain/inventory_transfer.py", "reconforge/infrastructure/postgres_inventory_transfer.py",
        "reconforge/infrastructure/postgres_inventory_transfer_schema.py", "reconforge/infrastructure/postgres_inventory_transfer_integration.py",
        "reconforge/infrastructure/postgres_inventory_quantity_source_ownership.py", "alembic/versions/0146_postgres_inventory_transfer.py",
        "tests/inventory_transfer_browser.py", ".github/scripts/verify_inventory_transfer_cycle_oracle.py")
    return {"schema_version": "inventory-transfer-proof-v1", "tenant_id": runtime.tenant,
        "capture": {"role_superuser": False, "role_bypassrls": False,
            "source_files_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}}, "populations": populations}


def export_inventory_transfer_proof(runtime: Any, *, actor_name: str = "poster") -> None:
    if directory := os.environ.get("RECONFORGE_IT1_NATIVE_PROOF_DIR"):
        destination = Path(directory) / "native-transfer-original-populations.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8", newline="\n") as target:
            json.dump(inventory_transfer_proof(runtime, actor_name=actor_name), target, indent=2, sort_keys=True, allow_nan=False)
            target.write("\n")


def seed_inventory_transfer_browser(admin_dsn: str, app_dsn: str) -> Any:
    """Approved native IRP stock and masters only; browser creates every transfer."""
    runtime = transfer_runtime((admin_dsn, app_dsn))
    from psycopg import sql

    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        for name in TABLES:
            if connection.execute(sql.SQL("SELECT count(*) n FROM reconforge.{} WHERE tenant_id=%s").format(sql.Identifier(name)), (runtime.tenant,)).fetchone()["n"] != 0:
                raise ValueError("A browser fixture cannot contain completed transfer documents")
    seed_erp_browser_principals(runtime)
    return runtime


def inventory_transfer_browser_configuration(runtime: Any) -> dict[str, Any]:
    return {"schema_version": "inventory-transfer-browser-v1", "tenant_id": runtime.tenant,
        "username": "browser-maker", "checker_username": "browser-checker", "poster_username": "browser-poster",
        "scope": {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"},
        "transfer": {"number": "TRANSFER-BROWSER", "item_code": "ITEM", "quantity": "1", "from_location": "MAIN/STOCK", "to_location": "SECOND/STOCK",
            "period_id": "period", "posting_date": "2026-10-14", "reason": "Actual same-entity warehouse transfer"}}


def verify_inventory_transfer_browser(runtime: Any, *, actor_name: str = "browser-poster") -> dict[str, Any]:
    """Retain original capture, execute isolated normal/optimized oracle and pin restore bytes."""
    proof = inventory_transfer_proof(runtime, actor_name=actor_name)
    raw = (json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    retained = _ORIGINAL_EXPORT_SHA256.get(runtime.tenant)
    if retained is not None and retained != digest:
        raise ValueError("Restored transfer originals differ from their retained successful capture")
    base = Path(os.environ.get("RECONFORGE_IT1_ORACLE_CUSTODY_DIR", str(ROOT / "output/inventory-transfer-original-custody")))
    base.mkdir(parents=True, exist_ok=True)
    packet = base / ("capture-" + uuid4().hex)
    packet.mkdir(exist_ok=False)
    original, verifier = packet / "inventory-transfer-original.json", ROOT / ".github/scripts/verify_inventory_transfer_cycle_oracle.py"
    with original.open("xb") as target:
        target.write(raw)
    verifier_digest = hashlib.sha256(verifier.read_bytes()).hexdigest()
    results, members = [], []
    for name, flags in (("I", ["-I"]), ("I-O", ["-I", "-O"])):
        argv = [sys.executable, *flags, str(verifier), str(original), "--expected-export-sha256", digest]
        process = subprocess.run(argv, capture_output=True, timeout=15, check=False)
        records = {"argv-" + name + ".json": (json.dumps(argv, ensure_ascii=False) + "\n").encode(),
            "stdout-" + name + ".json": process.stdout, "stderr-" + name + ".log": process.stderr}
        for filename, content in records.items():
            with (packet / filename).open("xb") as target:
                target.write(content)
            members.append({"name": filename, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        if process.returncode != 0:
            raise ValueError("Independent original transfer oracle refused its retained byte capture")
        results.append(json.loads(process.stdout))
    if results[0] != results[1] or original.read_bytes() != raw or hashlib.sha256(verifier.read_bytes()).hexdigest() != verifier_digest:
        raise ValueError("Normal/optimized original verification or frozen source custody differs")
    result = results[0]
    if result["original_file_sha256"] != digest or result["verifier_sha256"] != verifier_digest:
        raise ValueError("Independent receipt does not bind the exact captured original and verifier bytes")
    events = proof["populations"]["inventory_transfer_events"]
    expected = {"create": "erp-maker", "inverse-create": "erp-maker", "review": "erp-checker", "post": "erp-poster"}
    if actor_name == "browser-poster" and any(event["actor_id"] != expected[event["operation"]] for event in events):
        raise ValueError("Actual browser transfer commands require the original three distinct ERP humans")
    manifest = {"schema_version": "inventory-transfer-original-oracle-custody-v1", "original_file": original.name,
        "original_file_sha256": digest, "original_bytes": len(raw), "verifier_sha256": verifier_digest,
        "source_files_sha256": proof["capture"]["source_files_sha256"], "members": members,
        "normal_optimized_receipts_equal": True, "restore_original_sha256": retained or digest,
        "independent_oracle": result}
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with (packet / "trusted-original-manifest.json").open("xb") as target:
        target.write(manifest_raw)
    _ORIGINAL_EXPORT_SHA256.setdefault(runtime.tenant, digest)
    return {"schema_version": "inventory-transfer-browser-native-verification-v1", "independent_financial_proof": proof,
        "independent_oracle": result, "original_oracle_packet": str(packet), "original_oracle_manifest": manifest,
        "original_oracle_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(), "browser_inventory_writes": True,
        "transfer_new_gl_effects": 0, "originals_preserved": True, "restore_rebaseline_allowed": False}
