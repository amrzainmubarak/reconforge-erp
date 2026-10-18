"""Native browser inputs and source-qualified isolated original oracle custody."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from reconforge.domain.inventory_transfer import READ, TransferInversePreparation
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from tests.inventory_transfer_browser import (
    INVENTORY_TRANSFER_TABLES,
    INVENTORY_TRANSFER_TAMPER,
    inventory_transfer_browser_configuration,
    seed_inventory_transfer_browser,
    verify_inventory_transfer_browser,
)
from tests.test_postgres_inventory_transfer import baseline_receipt_database, phase, request, transfer_database

_ = (baseline_receipt_database, transfer_database)


def test_actual_browser_seed_approved_irp_three_units_usd3600_and_zero_transfer_documents(transfer_database: tuple[str, str]) -> None:
    runtime = seed_inventory_transfer_browser(*transfer_database)
    config = inventory_transfer_browser_configuration(runtime)
    assert config["schema_version"] == "inventory-transfer-browser-v1" and config["tenant_id"] == runtime.tenant
    assert runtime.password not in json.dumps(config) and "password" not in config
    assert len(INVENTORY_TRANSFER_TAMPER) == 3 and len(INVENTORY_TRANSFER_TABLES) == len(set(INVENTORY_TRANSFER_TABLES))
    actors = []
    for person in ("browser-maker", "browser-checker", "browser-poster"):
        with runtime.actor(person) as (connection, _, actor):
            actors.append(actor.user_id)
            assert PostgresIdentityRepository(connection).user_permissions(tenant_id=runtime.tenant, user_id=actor.user_id) >= READ
            assert PostgresInventoryTransferRepository(connection, runtime.tenant).list_transfers(config["scope"], actor=actor) == {"transfers": []}
            assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
            layer = connection.execute("SELECT original_quantity_scaled,remaining_quantity_scaled,original_value_minor,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
            assert dict(layer) == {"original_quantity_scaled": 3, "remaining_quantity_scaled": 3, "original_value_minor": 3600, "remaining_value_minor": 3600}
            assert connection.execute("SELECT count(*) n FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND original_plan_id IS NULL", (runtime.tenant,)).fetchone()["n"] == 1
            role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            assert dict(role) == {"rolsuper": False, "rolbypassrls": False}
    assert actors == ["erp-maker", "erp-checker", "erp-poster"]


def test_actual_browser_human_native_cycle_isolated_original_oracle_and_no_restore_rebaseline(transfer_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = seed_inventory_transfer_browser(*transfer_database)
    monkeypatch.setenv("RECONFORGE_IT1_ORACLE_CUSTODY_DIR", str(Path(os.environ.get("RECONFORGE_IT1_NATIVE_PROOF_DIR", str(tmp_path))) / "browser-oracle-originals"))
    with runtime.actor("browser-maker") as (connection, _, actor):
        created = PostgresInventoryTransferRepository(connection, runtime.tenant).create(request("TRANSFER-BROWSER"), command_id="browser-native-create", actor=actor)
    posted = phase(runtime, phase(runtime, created, "review", "browser-checker"), "post", "browser-poster")
    source = posted["source"]
    with runtime.actor("browser-maker") as (connection, _, actor):
        child = PostgresInventoryTransferRepository(connection, runtime.tenant).create_inverse(TransferInversePreparation(source["id"], source["source_digest"], 3,
            "TRANSFER-BROWSER-INVERSE", "period", "2026-10-14", "Actual independent compensation"), command_id="browser-native-inverse-create", actor=actor)
    phase(runtime, phase(runtime, child, "review", "browser-checker"), "post", "browser-poster")
    verified = verify_inventory_transfer_browser(runtime)
    manifest = verified["original_oracle_manifest"]
    packet = Path(verified["original_oracle_packet"])
    original = (packet / manifest["original_file"]).read_bytes()
    assert hashlib.sha256(original).hexdigest() == manifest["original_file_sha256"]
    assert len(original) == manifest["original_bytes"] and verified["browser_inventory_writes"] is True
    assert verified["transfer_new_gl_effects"] == 0 and verified["restore_rebaseline_allowed"] is False
    assert (packet / "stdout-I.json").read_bytes() == (packet / "stdout-I-O.json").read_bytes()
    assert not (packet / "stderr-I.log").read_bytes() and not (packet / "stderr-I-O.log").read_bytes()
    for member in manifest["members"]:
        content = (packet / member["name"]).read_bytes()
        assert len(content) == member["bytes"] and hashlib.sha256(content).hexdigest() == member["sha256"]
    assert json.loads((packet / "argv-I.json").read_bytes())[-2:] == ["--expected-export-sha256", manifest["original_file_sha256"]]
    assert verify_inventory_transfer_browser(runtime) == verified
    import tests.inventory_transfer_browser as helper

    capture = helper.inventory_transfer_proof

    def drift(*args, **kwargs):
        proof = capture(*args, **kwargs)
        proof["populations"]["inventory_transfer_commands"][0]["request_digest"] = "a" * 64
        return proof

    monkeypatch.setattr(helper, "inventory_transfer_proof", drift)
    with pytest.raises(ValueError, match="Restored transfer originals differ"):
        helper.verify_inventory_transfer_browser(runtime)
    assert (packet / manifest["original_file"]).read_bytes() == original
