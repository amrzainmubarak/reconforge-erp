"""Owned PostgreSQL 17 + normal HTTPS expansion cycles and populated native recovery gate.

Requires a built apps/web/dist, installed web dev dependencies and Playwright
Chromium. Fixtures are synthetic; credentials stay in memory and child environment.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests import browser_diagnostic_redaction as diagnostic_redaction  # noqa: E402
from tests.erp_expansion_browser_restore import (  # noqa: E402
    EXPANSION_TABLES,
    verify_expansion_cycles,
    verify_expansion_native_restore,
)
from tests.erp_expansion_browser_seed import seed_expansion_browser  # noqa: E402
from tests.inventory_transfer_original_publication import publish_inventory_transfer_originals  # noqa: E402
from tests.original_browser_download_verification import canonical as original_verification_json_bytes  # noqa: E402
from tests.original_browser_download_verification import verify_original_browser_downloads  # noqa: E402

IMAGE = "postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3"
PUBLIC_ORIGINAL_JSON = re.compile(
    r"(?:\.last-run|"
    r"cashflow-(?:view|original|original-wire|browser-read-boundary)|"
    r"group-diagnostic-(?:view|original|original-wire|browser-read-boundary|source-capture-reads)|"
    r"project-source-(?:view|original|close-view|close-original|browser-boundary)|"
    r"inventory-transfer-(?:browser-wire|ar-mobile-read-boundary|IT1-S-[0-9a-f]{32}-evidence)|"
    r"(?:fx-proof|ic-proof|fixed-asset-proof)-[a-z0-9-]+|ic-group-report|"
    r"intercompany-fx-(?:stage-[0-9]+|management-report|report-download|proof-ar-mobile)|"
    r"accrual-deferral-native-proof-en|manufacturing-supply-original-replay-custody|"
    r"(?:hc1|pb1)-original-native-financial-evidence(?:-[a-z0-9]+)?|"
    r"wire-request-timings(?:-[a-z0-9]+)?|snapshot-mobile-overflow-(?:ar|en)(?:-[a-z0-9]+)?|"
    r"captured-statements-(?:ar-rtl|en)-390px(?:-[a-z0-9]+)?|"
    r"native-financial-snapshot-oracle(?:-[a-z0-9]+)?)\.json",
    re.IGNORECASE,
)


def private_diagnostics_directory(output: Path) -> Path:
    """Fresh private run, outside the exact public browser artifact directory."""
    sibling = output.parent / (output.name + "-private-diagnostics")
    if sibling.is_symlink():
        raise ValueError("Private browser diagnostic storage cannot be a symlink.")
    sibling.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = sibling / uuid4().hex
    private.mkdir(mode=0o700)
    return private


def _public_diagnostic_paths(output: Path) -> list[Path]:
    paths = [output / name for name in ("browser.log", "playwright.json")]
    artifacts = output / "playwright-artifacts"
    if artifacts.is_symlink():
        raise ValueError("Public browser artifact storage cannot be a symlink.")
    if artifacts.is_dir():
        # A reused output must not leave an old trace/network container in the
        # upload directory merely because the current child writes privately.
        paths.extend(path for path in sorted(artifacts.rglob("*"))
            if path.is_symlink() or path.is_file() and (path.name == "error-context.md"
                or not _unchanged_original_artifact_name(path)))
    return [path for path in paths if path.exists() or path.is_symlink()]


def _unchanged_original_artifact_name(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".sql"} or PUBLIC_ORIGINAL_JSON.fullmatch(path.name) is not None


def _quarantine_public_diagnostics(output: Path, private: Path) -> dict[str, Path]:
    retained = {}
    for path in _public_diagnostic_paths(output):
        relative = path.relative_to(output).as_posix()
        destination = private / "public-originals" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise ValueError("An original browser diagnostic cannot be overwritten.")
        path.rename(destination)  # Same parent filesystem; preserve original bytes before publication.
        retained[relative] = destination
    return retained


def _quarantine_public_output(output: Path, private: Path) -> None:
    # Last resort for a failed individual move. Verify the exact selected output
    # and sibling target before moving a populated directory; never move a repo.
    selected, target = output.resolve(), (private / "quarantined-public-output").resolve()
    if (selected == ROOT.resolve() or ROOT.resolve().is_relative_to(selected)
            or not target.is_relative_to(selected.parent) or target.is_relative_to(selected)
            or target.exists() or output.is_symlink()):
        raise RuntimeError("Public browser diagnostic quarantine target is refused.")
    output.rename(target)
    output.mkdir()


def _file_identity(path: Path) -> dict[str, Any]:
    digest, length = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(65_536):
            digest.update(chunk)
            length += len(chunk)
    return {"bytes": length, "sha256": digest.hexdigest()}


def _stage_original_browser_artifacts(output: Path, private: Path, known_private_values: list[str]) -> tuple[list[tuple[Path, Path]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Mirror original attachments byte-for-byte, without a financial parser."""
    artifacts = private / "playwright-artifacts"
    if artifacts.is_symlink():
        raise ValueError("Private browser artifact storage cannot be a symlink.")
    staged: list[tuple[Path, Path]] = []
    receipts = []
    private_receipts: list[dict[str, Any]] = []
    for source in sorted(artifacts.rglob("*")):
        if source.is_symlink():
            raise ValueError("A browser artifact cannot traverse a symbolic link.")
        if not source.is_file() or source.name == "error-context.md":
            continue
        # Trace/HAR/network containers can retain authentication headers. They
        # remain original private files, even when a future config enables them.
        suffix, basename = source.suffix.lower(), source.name.lower()
        if (suffix in {".zip", ".har", ".network", ".trace", ".webm", ".mp4"}
                or basename in {"trace.json", "network.json"}):
            private_receipts.append({"artifact_index": len(private_receipts),
                "kind": "private-browser-diagnostic-container", "original": _file_identity(source), "published": False})
            continue
        if not _unchanged_original_artifact_name(source):
            raise ValueError("Browser attachment is outside the unchanged-original publication allowlist.")
        name = "playwright-artifacts/" + source.relative_to(artifacts).as_posix()
        if diagnostic_redaction.redact_browser_text(name, known_private_values) != name:
            raise ValueError("An original browser artifact path cannot be published safely.")
        destination = output / name
        if destination.is_symlink() or not destination.resolve().is_relative_to(output.resolve()):
            raise ValueError("An original browser artifact destination escapes its output.")
        identity = _file_identity(source)
        if destination.exists():
            if not destination.is_file() or _file_identity(destination) != identity:
                raise ValueError("An existing original browser artifact cannot be overwritten.")
        else:
            copy = private / "unchanged-public" / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as original, copy.open("xb") as target:
                shutil.copyfileobj(original, target, length=65_536)
            if _file_identity(copy) != identity or _file_identity(source) != identity:
                raise ValueError("An original browser artifact changed during byte-preserving capture.")
            staged.append((copy, destination))
        receipts.append({"relative_path": name, "original": identity, "public_copy": identity, "content_transform": False})
    return staged, receipts, private_receipts


def publish_browser_diagnostics(output: Path, private: Path, known_private_values: list[str]) -> dict[str, Any]:
    """Publish only complete derived diagnostics; financial bytes are excluded."""
    helper_source = Path(diagnostic_redaction.__file__).read_bytes()
    helper_sha = hashlib.sha256(helper_source).hexdigest()
    writer_source = Path(__file__).read_bytes()
    receipt: dict[str, Any] = {"schema_version": "browser-diagnostic-publication-v1",
        "sanitizer": {"version": diagnostic_redaction.SANITIZER_VERSION, "source_sha256": helper_sha, "source_bytes": len(helper_source)},
        "writer": {"source_sha256": hashlib.sha256(writer_source).hexdigest(), "source_bytes": len(writer_source)},
        "private_storage": "sibling-outside-public-browser-artifact-directory", "private_run_id": private.name,
        "financial_artifacts_sanitized": False, "artifacts": [], "original_custody": [],
        "unchanged_browser_artifacts": [], "private_browser_artifacts": [], "status": "quarantined"}
    try:
        quarantined = _quarantine_public_diagnostics(output, private)
        inputs = {name: private / name for name in ("browser.log", "playwright.json") if (private / name).exists()}
        inputs.update({name: path for name, path in quarantined.items() if name.startswith("playwright-artifacts/")})
        if (private / "playwright-artifacts").is_symlink():
            raise ValueError("Private browser artifact storage cannot be a symlink.")
        inputs.update({path.relative_to(private).as_posix(): path
            for path in sorted((private / "playwright-artifacts").rglob("error-context.md"))})
        staged = []
        for name, path in sorted(inputs.items()):
            if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(private.resolve())
                    or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(private))):
                raise ValueError("An original browser diagnostic must be a regular owned file.")
            with path.open("rb") as stream:
                raw = stream.read(diagnostic_redaction.MAX_DIAGNOSTIC_BYTES + 1)
            receipt["original_custody"].append({"artifact_index": len(receipt["original_custody"]),
                "original_bytes": path.stat().st_size,
                "original_sha256": hashlib.sha256(raw).hexdigest() if len(raw) <= diagnostic_redaction.MAX_DIAGNOSTIC_BYTES else None})
            derived = diagnostic_redaction.derive_browser_diagnostic(name, raw,
                sanitizer_source_sha256=helper_sha, known_private_values=known_private_values)
            destination = private / "derived-public" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(derived.content)
            staged.append((destination, output / name))
            receipt["artifacts"].append(derived.receipt)
        unchanged_staged, unchanged_receipts, private_receipts = _stage_original_browser_artifacts(output, private, known_private_values)
        receipt["private_browser_artifacts"] = private_receipts
        staged.extend(unchanged_staged)
        # Every sanitizer completed before the first public diagnostic appears.
        for source, destination in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise ValueError("A public browser diagnostic appeared during publication.")
            source.rename(destination)
        receipt["status"] = "published"
        receipt["unchanged_browser_artifacts"] = unchanged_receipts
    except Exception:
        # Never echo the exception; it may contain a private value or header.
        try:
            _quarantine_public_diagnostics(output, private / "failed-publication")
        except Exception:
            _quarantine_public_output(output, private)
        receipt["artifacts"] = []
    receipt["public_custody_file"] = "browser-diagnostic-custody-" + private.name + ".json"
    with (output / receipt["public_custody_file"]).open("x", encoding="utf8") as stream:
        json.dump(receipt, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return receipt


def run_browser_process(argv: list[str], *, environment: dict[str, str], private: Path) -> subprocess.CompletedProcess[bytes]:
    """Keep exact stdout/stderr bytes private, including an interrupted process."""
    try:
        result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, timeout=600)  # nosec B603
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode("utf8")
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr or "").encode("utf8")
        with (private / "browser.log").open("xb") as stream:
            stream.write(stdout + stderr)
        raise RuntimeError("Owned browser execution timed out; private diagnostics retained.") from None
    with (private / "browser.log").open("xb") as stream:
        stream.write(result.stdout + result.stderr)
    return result


def source_digest(directory: Path = ROOT) -> str:
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=directory).decode().split("\0")  # nosec B603 B607
    digest = hashlib.sha256()
    for name in sorted(filter(None, files)):
        digest.update(name.encode())
        digest.update(hashlib.sha256((directory / name).read_bytes()).digest())
    return digest.hexdigest()


def built_web_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def tracked_status(directory: Path) -> str:
    """Retain dirty paths as evidence without exporting their file contents."""
    return subprocess.check_output(  # nosec B603 B607
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=directory, text=True,
    )


def require_browser_acceptance(stats: object, *, required_cases: int = 1) -> None:
    """An exit-zero process cannot replace execution of the required wire cycle."""
    if not isinstance(stats, dict):
        raise RuntimeError("Required browser execution statistics are missing")
    if type(required_cases) is not int or required_cases not in {1, 3}:
        raise RuntimeError("Required browser scenario case count is invalid")
    for name, required in (("expected", required_cases), ("skipped", 0), ("unexpected", 0), ("flaky", 0)):
        if type(stats.get(name)) is not int or stats[name] != required:
            raise RuntimeError(f"Required browser outcome count refused: {name}")


def publish_original_oracle_custody(private: Path, output: Path, verified: dict[str, Any]) -> dict[str, Any]:
    """Keep isolated financial verifier bytes distinct from browser diagnostics."""
    source = private / "original-browser-download-verification"
    admitted = re.compile(r"(?:custody\.json|[1-2]-(?:I|IO)(?:(?:\.command|\.execution)?\.json|\.(?:stdout|stderr)\.log))")
    if source.is_symlink() or not source.is_dir() or not source.resolve().is_relative_to(private.resolve()):
        raise ValueError("Original oracle custody is outside its owned private directory")
    originals = sorted(source.iterdir())
    if not originals or len(originals) > 25 or any(not p.is_file() or p.is_symlink() or not admitted.fullmatch(p.name) for p in originals):
        raise ValueError("Original oracle custody has an unexpected member")
    expected: dict[str, dict[str, Any]] = {}
    records = list(verified["retained_execution_artifacts"])
    for artifact in verified["artifacts"]:
        records.extend((artifact["normal"], artifact["optimized"]))
    for record in records:
        name = record["path"]
        if (not isinstance(name, str) or not admitted.fullmatch(name) or name == "custody.json"
                or name in expected or type(record["bytes"]) is not int or record["bytes"] < 0
                or not isinstance(record["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None):
            raise ValueError("Original oracle custody has an invalid trusted member")
        expected[name] = {"bytes": record["bytes"], "sha256": record["sha256"]}
    custody_raw = original_verification_json_bytes(verified)
    expected["custody.json"] = {"bytes": len(custody_raw), "sha256": hashlib.sha256(custody_raw).hexdigest()}
    if set(expected) != {p.name for p in originals} or any(_file_identity(p) != expected[p.name] for p in originals):
        raise ValueError("Original oracle custody differs from the successful verification before publication")
    target = output / "original-browser-download-verification"
    target.mkdir(exist_ok=False)
    members = []
    try:
        for original in originals:
            identity = expected[original.name]
            destination = target / original.name
            with original.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=65_536)
            if _file_identity(original) != identity or _file_identity(destination) != identity:
                raise ValueError("Original oracle custody changed during byte-preserving publication")
            members.append({"name": original.name, **identity})
        if (set(expected) != {p.name for p in target.iterdir()}
                or any(_file_identity(p) != expected[p.name] or _file_identity(target / p.name) != expected[p.name] for p in originals)):
            raise ValueError("Original oracle custody changed before completed publication")
    except Exception:
        refused = private / ("refused-original-oracle-publication-" + uuid4().hex)
        if (target.is_symlink() or not target.resolve().is_relative_to(output.resolve())
                or not refused.resolve().is_relative_to(private.resolve()) or refused.exists()):
            raise RuntimeError("Owned refused oracle publication quarantine is invalid") from None
        target.rename(refused)
        raise
    return {"financial_bytes_transformed": False, "verified_against_original_custody": True, "members": members}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-native-restore", action="store_true")
    parser.add_argument("--scenario", choices=("expansion", "commerce", "procurement", "snapshots", "collections", "landed-cost", "fixed-assets", "procurement-commitments", "customer-returns", "supplier-returns", "operational-fx-tax", "manufacturing-execution", "manufacturing-execution-v2", "intercompany-operations", "intercompany-fx", "intercompany-source-cashflow", "intercompany-group-diagnostic", "people-project-payroll", "procurement-sourcing", "accrual-deferral", "project-time-billing", "project-source-reconciliation", "manufacturing-supply-plan", "inventory-transfer"), default="expansion")
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "output/erp-expansion-20261009/browser")
    parser.add_argument("--web-root", type=Path, default=ROOT / "apps/web/dist")
    args = parser.parse_args()
    seed: Callable[[str, str], Any] = seed_expansion_browser
    verify_cycles: Callable[[Any], dict[str, Any]] = verify_expansion_cycles
    configuration = "apps/web/live/erp-expansion.playwright.config.ts"
    extension_tables: tuple[str, ...] = EXPANSION_TABLES
    tamper_actor: Callable[..., Any] | None = None
    personnel_dsn: Callable[..., str] | None = None
    workspace_probe_tables: tuple[str, ...] | None = None
    tamper_statements = (
        "UPDATE reconforge.stock_sales_orders SET total_minor=total_minor+1,row_version=row_version+1 WHERE tenant_id=%s",
        "UPDATE reconforge.financial_installment_links SET posted_actor_id='maker' WHERE tenant_id=%s",
        "UPDATE reconforge.financial_opening_links SET posted_actor_id='maker' WHERE tenant_id=%s",
    )
    if args.scenario == "commerce":
        from tests.stock_commerce_browser_seed import seed_stock_commerce_browser, verify_stock_commerce_browser
        seed, verify_cycles = seed_stock_commerce_browser, verify_stock_commerce_browser
        configuration = "apps/web/live/stock-commerce.playwright.config.ts"
        extension_tables = EXPANSION_TABLES + ("stock_commerce_orders", "stock_commerce_lines", "stock_commerce_tranches", "stock_commerce_commands")
        tamper_statements = (
            "UPDATE reconforge.stock_commerce_orders SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.stock_commerce_lines SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.stock_commerce_tranches SET stock_order_id='forged' WHERE tenant_id=%s",
        )
    elif args.scenario == "procurement":
        from tests.erp_procurement_enterprise_browser import (
            PROCUREMENT_ENTERPRISE_TABLES,
            seed_procurement_enterprise_browser,
            verify_procurement_enterprise_browser,
        )
        seed, verify_cycles = seed_procurement_enterprise_browser, verify_procurement_enterprise_browser
        configuration = "apps/web/live/erp-procurement-enterprise.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROCUREMENT_ENTERPRISE_TABLES))
        tamper_statements = (
            "UPDATE reconforge.procurement_partial_orders SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.procurement_partial_order_lines SET quantity=quantity+1 WHERE tenant_id=%s",
            "UPDATE reconforge.financial_installment_links SET posted_actor_id='maker' WHERE tenant_id=%s",
        )
    elif args.scenario == "procurement-commitments":
        from tests.erp_procurement_commitments_browser import (
            PROCUREMENT_COMMITMENT_BROWSER_TABLES,
            seed_procurement_commitments_browser,
            verify_procurement_commitments_browser,
        )
        seed, verify_cycles = seed_procurement_commitments_browser, verify_procurement_commitments_browser
        configuration = "apps/web/live/erp-procurement-commitments.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROCUREMENT_COMMITMENT_BROWSER_TABLES))
        tamper_statements = (
            "UPDATE reconforge.procurement_commitment_plans SET plan_digest=repeat('0',64) WHERE tenant_id=%s",
            "DELETE FROM reconforge.procurement_commitment_commands WHERE tenant_id=%s",
            "UPDATE reconforge.procurement_partial_orders SET total_minor=total_minor+1 WHERE tenant_id=%s",
        )
    elif args.scenario == "manufacturing-execution":
        from tests.manufacturing_execution_browser import (
            MANUFACTURING_EXECUTION_TABLES,
            MANUFACTURING_EXECUTION_TAMPER,
            MANUFACTURING_EXECUTION_WORKSPACE_PROBE_TABLES,
            seed_manufacturing_execution_browser,
            verify_manufacturing_execution_browser,
        )
        seed, verify_cycles = seed_manufacturing_execution_browser, verify_manufacturing_execution_browser
        configuration = "apps/web/live/manufacturing-execution.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + MANUFACTURING_EXECUTION_TABLES))
        tamper_statements = MANUFACTURING_EXECUTION_TAMPER
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + MANUFACTURING_EXECUTION_WORKSPACE_PROBE_TABLES))
    elif args.scenario == "inventory-transfer":
        from tests.inventory_transfer_browser import (
            INVENTORY_TRANSFER_TABLES,
            INVENTORY_TRANSFER_TAMPER,
            INVENTORY_TRANSFER_WORKSPACE_PROBE_TABLES,
            seed_inventory_transfer_browser,
            verify_inventory_transfer_browser,
        )
        seed, verify_cycles = seed_inventory_transfer_browser, verify_inventory_transfer_browser
        configuration = "apps/web/live/inventory-transfer.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INVENTORY_TRANSFER_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INVENTORY_TRANSFER_WORKSPACE_PROBE_TABLES))
        tamper_statements = INVENTORY_TRANSFER_TAMPER
    elif args.scenario == "manufacturing-supply-plan":
        from tests.manufacturing_supply_browser import (
            MANUFACTURING_SUPPLY_TABLES,
            MANUFACTURING_SUPPLY_TAMPER,
            MANUFACTURING_SUPPLY_WORKSPACE_PROBE_TABLES,
            seed_manufacturing_supply_browser,
            verify_manufacturing_supply_browser,
        )
        seed, verify_cycles = seed_manufacturing_supply_browser, verify_manufacturing_supply_browser
        configuration = "apps/web/live/manufacturing-supply.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + MANUFACTURING_SUPPLY_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + MANUFACTURING_SUPPLY_WORKSPACE_PROBE_TABLES))
        tamper_statements = MANUFACTURING_SUPPLY_TAMPER
    elif args.scenario == "manufacturing-execution-v2":
        from tests.manufacturing_execution_v2_browser import (
            MANUFACTURING_EXECUTION_V2_TABLES,
            MANUFACTURING_EXECUTION_V2_TAMPER,
            MANUFACTURING_EXECUTION_V2_WORKSPACE_PROBE_TABLES,
            seed_manufacturing_execution_v2_browser,
            verify_manufacturing_execution_v2_browser,
        )
        seed, verify_cycles = seed_manufacturing_execution_v2_browser, verify_manufacturing_execution_v2_browser
        configuration = "apps/web/live/manufacturing-execution-v2.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + MANUFACTURING_EXECUTION_V2_TABLES))
        tamper_statements = MANUFACTURING_EXECUTION_V2_TAMPER
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + MANUFACTURING_EXECUTION_V2_WORKSPACE_PROBE_TABLES))
    elif args.scenario == "intercompany-operations":
        from tests.intercompany_operations_browser_seed import (
            INTERCOMPANY_BROWSER_TABLES,
            INTERCOMPANY_RESTORE_TAMPER,
            intercompany_restore_tamper_actor,
            seed_intercompany_browser,
            verify_intercompany_browser,
        )
        seed, verify_cycles = seed_intercompany_browser, verify_intercompany_browser
        configuration = "apps/web/live/intercompany-operations.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INTERCOMPANY_BROWSER_TABLES))
        tamper_statements = INTERCOMPANY_RESTORE_TAMPER
        tamper_actor = intercompany_restore_tamper_actor
    elif args.scenario == "intercompany-source-cashflow":
        from tests.intercompany_cashflow_browser import (
            INTERCOMPANY_CASHFLOW_BROWSER_TABLES,
            INTERCOMPANY_CASHFLOW_RESTORE_TAMPER,
            INTERCOMPANY_CASHFLOW_WORKSPACE_PROBE_TABLES,
            intercompany_cashflow_restore_tamper_actor,
            seed_intercompany_cashflow_browser,
            verify_intercompany_cashflow_browser,
        )
        seed, verify_cycles = seed_intercompany_cashflow_browser, verify_intercompany_cashflow_browser
        configuration = "apps/web/live/intercompany-cashflow.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INTERCOMPANY_CASHFLOW_BROWSER_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INTERCOMPANY_CASHFLOW_WORKSPACE_PROBE_TABLES))
        tamper_statements = INTERCOMPANY_CASHFLOW_RESTORE_TAMPER
        tamper_actor = intercompany_cashflow_restore_tamper_actor
    elif args.scenario == "intercompany-group-diagnostic":
        from tests.intercompany_group_diagnostic_browser import (
            INTERCOMPANY_GROUP_DIAGNOSTIC_BROWSER_TABLES,
            INTERCOMPANY_GROUP_DIAGNOSTIC_RESTORE_TAMPER,
            INTERCOMPANY_GROUP_DIAGNOSTIC_WORKSPACE_PROBE_TABLES,
            intercompany_group_diagnostic_restore_tamper_actor,
            seed_intercompany_group_diagnostic_browser,
            verify_intercompany_group_diagnostic_browser,
        )
        seed, verify_cycles = seed_intercompany_group_diagnostic_browser, verify_intercompany_group_diagnostic_browser
        configuration = "apps/web/live/intercompany-group-diagnostic.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INTERCOMPANY_GROUP_DIAGNOSTIC_BROWSER_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INTERCOMPANY_GROUP_DIAGNOSTIC_WORKSPACE_PROBE_TABLES))
        tamper_statements = INTERCOMPANY_GROUP_DIAGNOSTIC_RESTORE_TAMPER
        tamper_actor = intercompany_group_diagnostic_restore_tamper_actor
    elif args.scenario == "intercompany-fx":
        from tests.intercompany_fx_browser_seed import (
            INTERCOMPANY_FX_BROWSER_TABLES,
            INTERCOMPANY_FX_RESTORE_TAMPER,
            intercompany_fx_restore_tamper_actor,
            seed_intercompany_fx_browser,
            verify_intercompany_fx_browser,
        )
        seed, verify_cycles = seed_intercompany_fx_browser, verify_intercompany_fx_browser
        configuration = "apps/web/live/intercompany-fx.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + INTERCOMPANY_FX_BROWSER_TABLES))
        tamper_statements = INTERCOMPANY_FX_RESTORE_TAMPER
        tamper_actor = intercompany_fx_restore_tamper_actor
    elif args.scenario == "people-project-payroll":
        from tests.people_project_payroll_browser import (
            PEOPLE_PROJECT_PAYROLL_TABLES,
            PEOPLE_PROJECT_PAYROLL_TAMPER,
            PEOPLE_PROJECT_PAYROLL_WORKSPACE_PROBE_TABLES,
            people_project_payroll_restore_tamper_actor,
            personnel_browser_dsn,
            seed_people_project_payroll_browser,
            verify_people_project_payroll_browser,
        )
        seed, verify_cycles = seed_people_project_payroll_browser, verify_people_project_payroll_browser
        configuration = "apps/web/live/people-project-payroll.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PEOPLE_PROJECT_PAYROLL_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PEOPLE_PROJECT_PAYROLL_WORKSPACE_PROBE_TABLES))
        tamper_statements = PEOPLE_PROJECT_PAYROLL_TAMPER
        tamper_actor = people_project_payroll_restore_tamper_actor
        personnel_dsn = personnel_browser_dsn
    elif args.scenario == "accrual-deferral":
        from tests.accrual_deferral_browser import (
            ACCRUAL_DEFERRAL_BROWSER_TABLES,
            ACCRUAL_DEFERRAL_RESTORE_TAMPER,
            ACCRUAL_DEFERRAL_WORKSPACE_PROBE_TABLES,
            accrual_deferral_restore_tamper_actor,
            seed_accrual_deferral_browser,
            verify_accrual_deferral_browser,
        )
        seed, verify_cycles = seed_accrual_deferral_browser, verify_accrual_deferral_browser
        configuration = "apps/web/live/accrual-deferral.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + ACCRUAL_DEFERRAL_BROWSER_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + ACCRUAL_DEFERRAL_WORKSPACE_PROBE_TABLES))
        tamper_statements = ACCRUAL_DEFERRAL_RESTORE_TAMPER
        tamper_actor = accrual_deferral_restore_tamper_actor
    elif args.scenario == "project-source-reconciliation":
        from tests.project_source_reconciliation_browser import (
            PROJECT_SOURCE_RECONCILIATION_TABLES,
            PROJECT_SOURCE_RECONCILIATION_TAMPER,
            PROJECT_SOURCE_RECONCILIATION_WORKSPACE_PROBE_TABLES,
            project_source_reconciliation_restore_tamper_actor,
            seed_project_source_reconciliation_browser,
            verify_project_source_reconciliation_browser,
        )
        seed, verify_cycles = seed_project_source_reconciliation_browser, verify_project_source_reconciliation_browser
        configuration = "apps/web/live/project-source-reconciliation.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROJECT_SOURCE_RECONCILIATION_TABLES))
        workspace_probe_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROJECT_SOURCE_RECONCILIATION_WORKSPACE_PROBE_TABLES))
        tamper_statements = PROJECT_SOURCE_RECONCILIATION_TAMPER
        tamper_actor = project_source_reconciliation_restore_tamper_actor
    elif args.scenario == "project-time-billing":
        from tests.project_time_billing_browser import (
            PROJECT_TIME_BILLING_TABLES,
            PROJECT_TIME_BILLING_TAMPER,
            personnel_browser_dsn,
            project_time_billing_restore_tamper_actor,
            seed_project_time_billing_browser,
            verify_project_time_billing_browser,
        )
        seed, verify_cycles = seed_project_time_billing_browser, verify_project_time_billing_browser
        configuration = "apps/web/live/project-time-billing.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROJECT_TIME_BILLING_TABLES))
        # The financial/time input relations require the same workspace probe
        # as the owned billing relations; only the tenant audit chain is global.
        workspace_probe_tables = tuple(name for name in extension_tables if name != "domain_audit_events")
        tamper_statements = PROJECT_TIME_BILLING_TAMPER
        tamper_actor = project_time_billing_restore_tamper_actor
        personnel_dsn = personnel_browser_dsn
    elif args.scenario == "procurement-sourcing":
        from tests.procurement_sourcing_browser import (
            PROCUREMENT_SOURCING_BROWSER_TABLES,
            seed_procurement_sourcing_browser,
            verify_procurement_sourcing_browser,
        )
        seed, verify_cycles = seed_procurement_sourcing_browser, verify_procurement_sourcing_browser
        configuration = "apps/web/live/procurement-sourcing.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROCUREMENT_SOURCING_BROWSER_TABLES))
        tamper_statements = (
            "UPDATE reconforge.procurement_sourcing_requisitions SET payload=jsonb_set(payload,'{reason}','\"forged\"') WHERE tenant_id=%s",
            "UPDATE reconforge.procurement_sourcing_quotes SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.procurement_sourcing_commands SET response_json='{}'::jsonb WHERE tenant_id=%s",
        )
    elif args.scenario == "supplier-returns":
        from tests.erp_supplier_returns_browser import (
            SUPPLIER_RETURN_BROWSER_TABLES,
            seed_supplier_returns_browser,
            verify_supplier_returns_browser,
        )
        seed, verify_cycles = seed_supplier_returns_browser, verify_supplier_returns_browser
        configuration = "apps/web/live/erp-supplier-returns.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + SUPPLIER_RETURN_BROWSER_TABLES))
        tamper_statements = (
            "UPDATE reconforge.supplier_return_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
            "DELETE FROM reconforge.supplier_return_commands WHERE tenant_id=%s",
            "DELETE FROM reconforge.ap_supplier_invoice_credits WHERE tenant_id=%s",
        )
    elif args.scenario == "customer-returns":
        from tests.customer_returns_browser import (
            CUSTOMER_RETURN_TABLES,
            seed_customer_returns_browser,
            verify_customer_returns_browser,
        )
        seed, verify_cycles = seed_customer_returns_browser, verify_customer_returns_browser
        configuration = "apps/web/live/customer-returns.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + CUSTOMER_RETURN_TABLES))
        tamper_statements = (
            "UPDATE reconforge.customer_return_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
            "DELETE FROM reconforge.customer_return_commands WHERE tenant_id=%s",
            "DELETE FROM reconforge.customer_return_events WHERE tenant_id=%s",
        )
    elif args.scenario == "operational-fx-tax":
        from tests.operational_fx_tax_browser_seed import (
            OPERATIONAL_FX_TABLES,
            seed_operational_fx_browser,
            verify_operational_fx_browser,
        )
        seed, verify_cycles = seed_operational_fx_browser, verify_operational_fx_browser
        configuration = "apps/web/live/operational-fx-tax.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + OPERATIONAL_FX_TABLES))
        tamper_statements = (
            "UPDATE reconforge.operational_fx_sources SET payload=jsonb_set(payload,'{foreign_gross_minor}',to_jsonb((payload->>'foreign_gross_minor')::bigint+1)) WHERE tenant_id=%s",
            "UPDATE reconforge.operational_fx_reviews SET reviewer_actor_id='erp-maker' WHERE tenant_id=%s",
            "UPDATE reconforge.operational_fx_commands SET response_json='{}'::jsonb WHERE tenant_id=%s",
        )
    elif args.scenario == "snapshots":
        from tests.enterprise_financial_snapshot_browser import (
            seed_financial_snapshot_browser,
            verify_financial_snapshot_browser,
        )
        seed, verify_cycles = seed_financial_snapshot_browser, verify_financial_snapshot_browser
        configuration = "apps/web/live/financial-snapshots.playwright.config.ts"
        extension_tables = EXPANSION_TABLES + ("financial_report_captures", "financial_report_members", "financial_report_snapshots")
        tamper_statements = (
            "UPDATE reconforge.financial_report_captures SET membership_sealed=false WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_report_members WHERE tenant_id=%s",
            "UPDATE reconforge.financial_report_snapshots SET report_digest=repeat('0',64) WHERE tenant_id=%s",
        )
    elif args.scenario == "collections":
        from tests.commercial_collections_browser import (
            COLLECTION_TABLES,
            seed_commercial_collections_browser,
            verify_commercial_collections_browser,
        )
        seed, verify_cycles = seed_commercial_collections_browser, verify_commercial_collections_browser
        configuration = "apps/web/live/commercial-collections.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + COLLECTION_TABLES))
        tamper_statements = (
            "UPDATE reconforge.commercial_collection_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.commercial_collection_links SET posted_actor_id='maker' WHERE tenant_id=%s",
            "DELETE FROM reconforge.commercial_collection_commands WHERE tenant_id=%s",
        )
    elif args.scenario == "landed-cost":
        from tests.erp_landed_cost_browser import (
            LANDED_COST_BROWSER_TABLES,
            seed_landed_cost_browser,
            verify_landed_cost_browser,
        )
        seed, verify_cycles = seed_landed_cost_browser, verify_landed_cost_browser
        configuration = "apps/web/live/erp-landed-cost.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + LANDED_COST_BROWSER_TABLES))
        tamper_statements = (
            "UPDATE reconforge.landed_cost_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.landed_cost_allocations SET freight_minor=freight_minor+1 WHERE tenant_id=%s",
            "DELETE FROM reconforge.landed_cost_commands WHERE tenant_id=%s",
        )
    elif args.scenario == "fixed-assets":
        from tests.fixed_assets_browser_seed import (
            FIXED_ASSET_TABLES,
            seed_fixed_assets_browser,
            verify_fixed_assets_browser,
        )
        seed, verify_cycles = seed_fixed_assets_browser, verify_fixed_assets_browser
        configuration = "apps/web/live/fixed-assets.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + FIXED_ASSET_TABLES))
        tamper_statements = (
            "UPDATE reconforge.fixed_assets SET payload=payload||jsonb_build_object('cost_minor',1) WHERE tenant_id=%s",
            "UPDATE reconforge.fixed_asset_links SET posted_actor_id='maker' WHERE tenant_id=%s",
            "DELETE FROM reconforge.fixed_asset_commands WHERE tenant_id=%s",
        )
    runtime_root = args.runtime_root.resolve()
    if runtime_root != ROOT.resolve():
        raise ValueError("Run the expansion harness from its exact integrated runtime checkout.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    private_diagnostics = private_diagnostics_directory(output)
    if args.scenario == "inventory-transfer":
        from tests.inventory_transfer_browser import verify_inventory_transfer_browser
        verify_cycles = partial(verify_inventory_transfer_browser,
            custody_root=private_diagnostics / "inventory-transfer-oracle-custody")
    if not (args.web_root / "index.html").is_file():
        raise ValueError("Build the integrated Studio before running browser acceptance.")
    name = "reconforge-erp-expansion-browser-" + uuid4().hex[:12]
    admin_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
    secret_values = [admin_password, app_password]
    container = ""
    server = None
    status_before = tracked_status(runtime_root)
    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(), "image": IMAGE,
        "container_resource_bounds": {"cpus": "2", "memory_bytes": 1073741824},
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=runtime_root, text=True).strip(),  # nosec B603 B607
        "source_sha256": source_digest(runtime_root), "runtime_root": str(runtime_root),
        "tooling_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "built_web_sha256": built_web_digest(args.web_root.resolve()), "status": "failed",
        "tracked_status_before": status_before,
        "tracked_clean_before": not status_before,
        "scenario": args.scenario, "configuration": configuration,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    module_origins = {}
    for module_name in (
        "reconforge.api.app", "reconforge.infrastructure.postgres_stock_sales",
        "reconforge.infrastructure.postgres_procurement_partial", "reconforge.infrastructure.postgres_financial_installments",
        "reconforge.infrastructure.postgres_financial_reporting", "tests.erp_expansion_browser_seed",
        "reconforge.infrastructure.postgres_commercial_collections", "reconforge.infrastructure.postgres_landed_cost",
        "reconforge.infrastructure.postgres_fixed_assets",
        "tests.erp_expansion_browser_restore",
        "tests.browser_diagnostic_redaction",
    ):
        origin_file = importlib.import_module(module_name).__file__
        if origin_file is None:
            raise ValueError("Expansion module has no captured source file.")
        origin = Path(origin_file).resolve()
        if not origin.is_relative_to(runtime_root):
            raise ValueError("Expansion module origin is outside the integrated runtime checkout.")
        module_origins[module_name] = {"path": str(origin), "sha256": hashlib.sha256(origin.read_bytes()).hexdigest()}
    if args.scenario in {"manufacturing-execution", "manufacturing-execution-v2", "intercompany-operations", "intercompany-fx", "intercompany-source-cashflow", "intercompany-group-diagnostic", "people-project-payroll", "procurement-sourcing", "accrual-deferral", "project-time-billing", "project-source-reconciliation", "manufacturing-supply-plan", "inventory-transfer"}:
        owner_module = "reconforge.infrastructure.postgres_intercompany_cashflow" if args.scenario == "intercompany-source-cashflow" else "reconforge.infrastructure.postgres_" + args.scenario.replace("-", "_")
        verification_module = (verify_cycles.func.__module__ if isinstance(verify_cycles, partial)
                               else verify_cycles.__module__)
        for module_name in dict.fromkeys((owner_module, seed.__module__, verification_module)):
            origin_file = importlib.import_module(module_name).__file__
            if origin_file is None:
                raise ValueError("New enterprise module has no captured source file.")
            origin = Path(origin_file).resolve()
            if not origin.is_relative_to(runtime_root):
                raise ValueError("New enterprise module origin is outside the integrated runtime checkout.")
            module_origins[module_name] = {"path": str(origin), "sha256": hashlib.sha256(origin.read_bytes()).hexdigest()}
    report["module_origins"] = module_origins
    started = time.monotonic()
    def run(argv: list[str], *, environment: dict[str, str] | None = None, check: bool = True, directory: Path = ROOT) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(argv, cwd=directory, env=environment, capture_output=True, text=True, timeout=600)  # nosec B603
        if check and result.returncode:
            diagnostic = result.stdout + result.stderr
            for value in secret_values:
                diagnostic = diagnostic.replace(value, "[redacted]")
            raise RuntimeError(diagnostic)
        return result
    try:
        environment = os.environ.copy()
        environment["POSTGRES_PASSWORD"] = admin_password
        container = run(["docker", "run", "--detach", "--rm", "--name", name,
                         "--label", "reconforge.owner=erp-expansion-browser", "--cpus", "2", "--memory", "1g", "-e", "POSTGRES_PASSWORD",
                         "-p", "127.0.0.1::5432", IMAGE], environment=environment).stdout.strip()
        port = run(["docker", "port", container, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1]
        admin_dsn = f"postgresql://postgres:{admin_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        app_dsn = f"postgresql://gfo_browser_app:{app_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        secret_values.extend((admin_dsn, app_dsn))
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(admin_dsn, autocommit=True) as admin:
                    admin.execute(sql.SQL("CREATE ROLE gfo_browser_app LOGIN PASSWORD {}").format(sql.Literal(app_password)))
                    version_row = admin.execute("SHOW server_version").fetchone()
                    assert version_row is not None
                    report["postgres_version"] = version_row[0]
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
        environment["RECONFORGE_POSTGRES_DSN"] = admin_dsn
        migration = run([sys.executable, "-m", "alembic", "upgrade", "head"], environment=environment, directory=runtime_root)
        (output / "migration.log").write_text(migration.stdout + migration.stderr, encoding="utf-8")
        with psycopg.connect(admin_dsn) as admin:
            admin.execute("GRANT USAGE ON SCHEMA reconforge TO gfo_browser_app")
            admin.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO gfo_browser_app")
            admin.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO gfo_browser_app")
            revision_row = admin.execute("SELECT version_num FROM alembic_version").fetchone()
            assert revision_row is not None
            report["revision"] = revision_row[0]
        with psycopg.connect(app_dsn) as connection:
            role_row = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            assert role_row is not None
            role_flags = list(role_row)
            assert role_flags == [False, False]
            report["role_privileges"] = role_flags
        runtime = seed(admin_dsn, app_dsn)
        secret_values.append(runtime.password)
        # Chromium blocks several OS-assigned low ephemeral ports. Bind an
        # available dynamic/private port without relaxing browser port policy.
        for _ in range(64):
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", 49152 + secrets.randbelow(16383)))
                except OSError:
                    continue
                https_port = listener.getsockname()[1]
                break
        else:
            raise RuntimeError("No owned dynamic HTTPS port is available.")
        url = f"https://localhost:{https_port}"
        environment.update(RECONFORGE_ERP_LIVE_URL=url, RECONFORGE_ERP_TENANT=runtime.tenant,
            RECONFORGE_ERP_PASSWORD=runtime.password, RECONFORGE_ERP_BROWSER_REPORT=str(private_diagnostics / "playwright.json"),
            RECONFORGE_ERP_BROWSER_ARTIFACTS=str(private_diagnostics / "playwright-artifacts"),
            RECONFORGE_GFO_APP_DSN=app_dsn, RECONFORGE_GFO_WEB_ROOT=str(args.web_root.resolve()),
            RECONFORGE_GFO_HTTPS_PORT=str(https_port))
        if personnel_dsn is not None:
            # The dedicated credential stays in the owned child's environment;
            # no public report or process argument carries it.
            personnel_connection = personnel_dsn(runtime)
            environment["RECONFORGE_PERSONNEL_POSTGRES_DSN"] = personnel_connection
            secret_values.append(personnel_connection)
            personnel_password = psycopg.conninfo.conninfo_to_dict(personnel_connection).get("password", "")
            if isinstance(personnel_password, str):
                secret_values.append(personnel_password)
        if args.scenario == "manufacturing-execution-v2":
            from tests.manufacturing_execution_v2_browser import manufacturing_execution_v2_browser_configuration
            environment["RECONFORGE_MANUFACTURING_V2_SOURCE"] = json.dumps(manufacturing_execution_v2_browser_configuration(runtime))
        if args.scenario == "manufacturing-supply-plan":
            from tests.manufacturing_supply_browser import manufacturing_supply_browser_configuration
            environment["RECONFORGE_MANUFACTURING_SUPPLY_SOURCE"] = json.dumps(manufacturing_supply_browser_configuration(runtime))
        if args.scenario == "inventory-transfer":
            from tests.inventory_transfer_browser import inventory_transfer_browser_configuration
            environment["RECONFORGE_INVENTORY_TRANSFER_SOURCE"] = json.dumps(inventory_transfer_browser_configuration(runtime))
        if args.scenario == "snapshots":
            from tests.enterprise_financial_snapshot_browser import financial_snapshot_oracle
            oracle_path = output / "financial-snapshot-oracle.json"
            oracle_path.write_text(json.dumps(financial_snapshot_oracle(), indent=2) + "\n", encoding="utf-8")
            environment["RECONFORGE_FINANCIAL_SNAPSHOT_ORACLE"] = str(oracle_path)
        elif args.scenario == "customer-returns":
            from tests.customer_returns_browser import customer_return_browser_source
            environment["RECONFORGE_CUSTOMER_RETURN_SOURCE"] = customer_return_browser_source(runtime)

        with (output / "https-runtime.log").open("w", encoding="utf-8") as log:
            runtime_command = "import sys; sys.path.insert(0, sys.argv[1]); from tests.gfo_browser_runtime import main; main()"
            server = subprocess.Popen([sys.executable, "-c", runtime_command, str(runtime_root)], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)  # nosec B603
            # Only the generated, owned localhost certificate is trusted here.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            deadline = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Owned HTTPS runtime exited; inspect https-runtime.log")
                try:
                    with urllib.request.urlopen(url + "/api/v1/health", context=context, timeout=1) as response:  # nosec B310
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Owned HTTPS readiness timeout") from None
                    time.sleep(.2)
            executable = "npx.cmd" if os.name == "nt" else "npx"
            browser = run_browser_process([executable, "--prefix", "apps/web", "playwright", "test", "--config", configuration],
                environment=environment, private=private_diagnostics)
            report["browser_exit_code"] = browser.returncode
        server.terminate()
        server.wait(timeout=15)
        report["owned_https_process_stopped"] = True
        if (private_diagnostics / "playwright.json").is_file():
            report["browser_counts"] = json.loads((private_diagnostics / "playwright.json").read_text(encoding="utf-8"))["stats"]
        if browser.returncode == 0:
            require_browser_acceptance(report.get("browser_counts"),
                required_cases=3 if args.scenario == "customer-returns" else 1)
            persisted_effects = verify_cycles(runtime)
            report["persisted_effects"] = persisted_effects
            if args.scenario in {"intercompany-source-cashflow", "intercompany-group-diagnostic", "project-source-reconciliation"}:
                downloaded_originals = verify_original_browser_downloads(
                    private_diagnostics, args.scenario, persisted_effects)
                report["downloaded_original_verification"] = downloaded_originals
                report["original_oracle_publication"] = publish_original_oracle_custody(private_diagnostics, output, downloaded_originals)
            if args.verify_native_restore:
                report["native_restore"] = verify_expansion_native_restore(runtime, container,
                    verify_cycles=verify_cycles, extension_tables=extension_tables, tamper_statements=tamper_statements,
                    tamper_actor=tamper_actor, workspace_probe_tables=workspace_probe_tables)
            if args.scenario == "inventory-transfer":
                # Fresh restore captures must still equal the first trusted
                # packet before any of its original bytes become public.
                report["original_oracle_publication"] = publish_inventory_transfer_originals(
                    private_diagnostics, output, persisted_effects)
        report["built_web_unchanged"] = built_web_digest(args.web_root.resolve()) == report["built_web_sha256"]
        report["source_unchanged"] = source_digest(runtime_root) == report["source_sha256"]
        report["source_commit_after"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=runtime_root, text=True).strip()
        status_after = tracked_status(runtime_root)
        report["tracked_status_after"] = status_after
        report["tracked_clean_after"] = not status_after
        report["source_unchanged"] = report["source_unchanged"] and report["source_commit_after"] == report["source_commit"]
        report["status"] = "passed" if browser.returncode == 0 and report["source_unchanged"] and report["built_web_unchanged"] and report["tracked_clean_before"] and report["tracked_clean_after"] else "failed"
        if status_before or status_after:
            report["error"] = "Tracked checkout is dirty; inspect tracked_status_before and tracked_status_after."
    except Exception as exc:
        with (private_diagnostics / "runner-error.txt").open("xb") as stream:
            stream.write(str(exc).encode("utf8"))
        report["error"] = "Owned acceptance failed; inspect retained private diagnostics and available derived browser diagnostics."
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            report["owned_https_process_stopped"] = True
        if container:
            assert run(["docker", "inspect", "--format", "{{.Id}}", name]).stdout.strip() == container
            run(["docker", "stop", "--time", "5", container])
            for _ in range(50):
                if not run(["docker", "ps", "-aq", "--filter", f"id={container}"]).stdout.strip():
                    report["owned_container_removed"] = True
                    break
                time.sleep(.1)
        report["wall_seconds"] = round(time.monotonic() - started, 3)
        publication = publish_browser_diagnostics(output, private_diagnostics, secret_values)
        report["browser_diagnostics"] = publication
        if publication["status"] != "published":
            report["status"] = "failed"
            report["error"] = "Browser diagnostic publication refused; private originals are quarantined."
        for filename in ("browser.log", "playwright.json", "https-runtime.log", "migration.log"):
            path = output / filename
            if path.exists():
                report[filename + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("status", "source_commit", "wall_seconds", "browser_counts", "error", "source_unchanged", "owned_container_removed") if key in report}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
