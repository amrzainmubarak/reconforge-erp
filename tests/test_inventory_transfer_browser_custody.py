"""Original subprocess custody, public configuration and restore anchor regressions."""
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.inventory_transfer_browser as helper


def test_genuine_original_callback_keeps_argv_stdout_stderr_and_refuses_restore_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = gzip.decompress((Path(__file__).parent / "fixtures/inventory-transfer-original-v1.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == "6c6bc9c46cd8314fe372080fed5393e4eaeb1cd4ad21138ccb4159c77604544e"
    original = json.loads(raw)
    runtime = SimpleNamespace(tenant=original["tenant_id"], password="PRIVATE-UNIT-INPUT")
    monkeypatch.setattr(helper, "_ORIGINAL_EXPORT_SHA256", {})
    monkeypatch.setattr(helper, "_ORIGINAL_VERIFIED_RESULTS", {})
    monkeypatch.setattr(helper, "inventory_transfer_proof", lambda *args, **kwargs: json.loads(raw))
    monkeypatch.setenv("RECONFORGE_IT1_ORACLE_CUSTODY_DIR", str(tmp_path))
    config = helper.inventory_transfer_browser_configuration(runtime)
    assert runtime.password not in json.dumps(config) and "password" not in config
    first = helper.verify_inventory_transfer_browser(runtime, actor_name="poster")
    second = helper.verify_inventory_transfer_browser(runtime, actor_name="poster")
    manifest = first["original_oracle_manifest"]
    assert second["original_oracle_manifest"]["restore_original_sha256"] == manifest["original_file_sha256"]
    assert first == second
    assert len(list(tmp_path.glob("capture-*"))) == 2
    packet = Path(first["original_oracle_packet"])
    assert len(manifest["members"]) == 6 and first["restore_rebaseline_allowed"] is False
    for member in manifest["members"]:
        content = (packet / member["name"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == member["sha256"] and len(content) == member["bytes"]
    assert (packet / "stdout-I.json").read_bytes() == (packet / "stdout-I-O.json").read_bytes()
    assert not (packet / "stderr-I.log").read_bytes() and not (packet / "stderr-I-O.log").read_bytes()
    changed = json.loads(raw)
    changed["populations"]["inventory_transfer_events"][0]["audit_event_id"] = "DETACHED"
    monkeypatch.setattr(helper, "inventory_transfer_proof", lambda *args, **kwargs: changed)
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="Restored transfer originals differ"):
        helper.verify_inventory_transfer_browser(runtime, actor_name="poster")
    assert set(tmp_path.iterdir()) == before and helper._ORIGINAL_EXPORT_SHA256[runtime.tenant] == manifest["original_file_sha256"]
    assert hashlib.sha256((packet / "trusted-original-manifest.json").read_bytes()).hexdigest() == first["original_oracle_manifest_sha256"]


@pytest.mark.parametrize("late", ["raw", "manifest", "earlier-stdout", "earlier-argv", "during-next-cli"])
def test_original_cached_callback_rechecks_all_earlier_members_without_rebaseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, late: str) -> None:
    raw = gzip.decompress((Path(__file__).parent / "fixtures/inventory-transfer-original-v1.json.gz").read_bytes())
    original = json.loads(raw)
    runtime = SimpleNamespace(tenant=original["tenant_id"], password="PRIVATE-UNIT-INPUT")
    monkeypatch.setattr(helper, "_ORIGINAL_EXPORT_SHA256", {})
    monkeypatch.setattr(helper, "_ORIGINAL_VERIFIED_RESULTS", {})
    monkeypatch.setattr(helper, "inventory_transfer_proof", lambda *args, **kwargs: json.loads(raw))
    monkeypatch.setenv("RECONFORGE_IT1_ORACLE_CUSTODY_DIR", str(tmp_path / "unused-environment-custody"))
    explicit = tmp_path / "explicit-custody"
    first = helper.verify_inventory_transfer_browser(runtime, actor_name="poster", custody_root=explicit)
    packet = Path(first["original_oracle_packet"])
    assert packet.parent == explicit.resolve() and not (tmp_path / "unused-environment-custody").exists()
    if late == "during-next-cli":
        run = helper.subprocess.run

        def mutate_earlier(*args, **kwargs):
            result = run(*args, **kwargs)
            (packet / "stdout-I.json").write_bytes(b"late earlier output mutation")
            return result

        monkeypatch.setattr(helper.subprocess, "run", mutate_earlier)
    else:
        name = {"raw": "inventory-transfer-original.json", "manifest": "trusted-original-manifest.json", "earlier-stdout": "stdout-I.json", "earlier-argv": "argv-I.json"}[late]
        (packet / name).write_bytes(b"late original member mutation")
    with pytest.raises(ValueError, match="WRITE-time identity"):
        helper.verify_inventory_transfer_browser(runtime, actor_name="poster", custody_root=explicit)
    assert helper._ORIGINAL_VERIFIED_RESULTS[runtime.tenant]["original_oracle_manifest_sha256"] == first["original_oracle_manifest_sha256"]
