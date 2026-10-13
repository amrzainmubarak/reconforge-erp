"""Governed native fixture for a strictly read-only Project browser surface.

Employees/time/prices/wage/invoice/cash are provisioned by existing source owner
commands with three distinct synthetic humans. Browser financial writes are not
claimed; its task is reading and downloading this exact original source pair.
"""

import hashlib
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from reconforge.application.accrual_deferral_evidence import evidence_chunks, evidence_digest
from reconforge.domain.project_source_reconciliation import ProjectSourceSelection
from reconforge.infrastructure.postgres_project_source_reconciliation import (
    PostgresProjectSourceReconciliationRepository,
)
from tests.people_project_payroll_browser import private_runtime
from tests.project_time_billing_browser import PROJECT_TIME_BILLING_TABLES, seed_project_time_billing_browser
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_people_project_payroll import SCOPE
from tests.test_postgres_project_source_reconciliation import completed_pair

PROJECT_SOURCE_RECONCILIATION_TABLES = tuple(
    dict.fromkeys(
        (
            *PROJECT_TIME_BILLING_TABLES,
            "hc_payruns",
            "hc_payments",
            "hc_claim_heads",
            "hc_claim_events",
            "finance_posting_commands",
            "finance_dimensions",
            "finance_dimension_values",
        )
    )
)
PROJECT_SOURCE_RECONCILIATION_WORKSPACE_PROBE_TABLES = tuple(
    name for name in PROJECT_SOURCE_RECONCILIATION_TABLES if name != "domain_audit_events"
)
PROJECT_SOURCE_RECONCILIATION_TAMPER = (
    "UPDATE reconforge.hc_payruns SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
    "UPDATE reconforge.pb_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
    "DELETE FROM reconforge.pb_time_claims WHERE tenant_id=%s",
)
_ORIGINALS: dict[str, tuple[tuple[str, str, str], str]] = {}
_ORIGINAL_CAPTURE: dict[str, bytes] = {}


def source_evidence(base: ReceiptRuntime) -> dict[str, Any]:
    pair, _ = _ORIGINALS[base.tenant]
    with private_runtime(base).actor("maker", private=False) as (connection, _, actor):
        return PostgresProjectSourceReconciliationRepository(connection, base.tenant).report(
            ProjectSourceSelection(SCOPE, pair[2], "period", pair[0], pair[1]), actor=actor
        )


def immutable_source_digest(proof: dict[str, Any]) -> str:
    raw = {key: value for key, value in proof["original_rows"].items() if key not in {"captured_at", "outbox"}}
    # Delivery leasing is legitimately mutable. Only the original event tuple
    # participates in this fixture's preserved source-history comparison.
    raw["outbox"] = [
        {
            key: event[key]
            for key in (
                "tenant_id",
                "event_id",
                "event_type",
                "aggregate_type",
                "aggregate_id",
                "workspace_id",
                "organization_id",
                "legal_entity_id",
                "payload",
                "created_at",
            )
        }
        for event in proof["original_rows"]["outbox"]
    ]
    return evidence_digest(raw)


def seed_project_source_reconciliation_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = seed_project_time_billing_browser(admin_dsn, app_dsn)
    pair = completed_pair(private_runtime(base))
    _ORIGINALS[base.tenant] = (pair, "")
    original = source_evidence(base)
    _ORIGINALS[base.tenant] = (pair, immutable_source_digest(original))
    _ORIGINAL_CAPTURE[base.tenant] = b"".join(evidence_chunks(original))
    return base


@contextmanager
def project_source_reconciliation_restore_tamper_actor(base: ReceiptRuntime):
    with private_runtime(base).actor("poster", private=False) as values:
        yield values


def verify_project_source_reconciliation_browser(base: ReceiptRuntime) -> dict[str, Any]:
    proof = source_evidence(base)
    if immutable_source_digest(proof) != _ORIGINALS[base.tenant][1]:
        raise ValueError("Read or restore changed the original immutable financial source population")
    if proof["report"]["project_totals"] != {
        "wage_cost_minor": "1268",
        "revenue_minor": "2535",
        "source_margin_minor": "1267",
    }:
        raise ValueError("Original Project allocation differs")
    script = Path(__file__).resolve().parents[1] / ".github/scripts/verify_project_source_reconciliation.py"
    spec = importlib.util.spec_from_file_location("project_source_browser_independent", script)
    if spec is None or spec.loader is None:
        raise ValueError("Independent original oracle is absent")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    current_independent = oracle.verify(proof)
    if current_independent["source_effect_count"] != 6:
        raise ValueError("Exactly six original native effects are required")
    fresh_raw = b"".join(evidence_chunks(proof))
    directory = Path(__file__).resolve().parents[1] / "output/project-source-browser-native-captures"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ("fresh-original-" + uuid4().hex + ".json")).open("xb") as handle:
        handle.write(fresh_raw)
    raw = _ORIGINAL_CAPTURE[base.tenant]
    seeded = json.loads(raw)
    independent = oracle.verify(seeded)
    if seeded["report"] != proof["report"]:
        raise ValueError("Current verified source summary differs from the original seed capture")
    return {
        "schema_version": "project-source-browser-read-verification-v1",
        "original_evidence": seeded,
        "original_evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "original_evidence_bytes": len(raw),
        "immutable_source_sha256": immutable_source_digest(proof),
        "oracle_source_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "independent_oracle": independent,
        "native_effect_count": 6,
        "browser_financial_writes": False,
        "financial_sources_provisioned_by": "existing-owner-commands-three-distinct-synthetic-humans",
        "capture_timestamp_is_dynamic": True,
        "original_evidence_subject": "exact-original-canonical-seed-capture-retained-before-browser",
        "fresh_current_captures": "separately-retained-unaltered-output/project-source-browser-native-captures",
        "private_personnel_rows_exported": False,
        "full_native_catalog_equality_by_this_helper": False,
        "country_statutory_packs": 0,
        "bank_execution_proven": False,
        "performance_comparison_accepted": False,
    }
