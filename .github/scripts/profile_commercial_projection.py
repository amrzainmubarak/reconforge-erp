"""Small owned EXPLAIN comparison over a real governed partial AR collection.

Run with verify_commercial_collections.py .github/scripts/profile_commercial_projection.py.
Neither projection changes financial source, ledger, receipt or closure history.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any

from reconforge.domain.finance_posting import canonical_json
from tests.test_postgres_commercial_collections import complete, invoiced, prepare
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_stock_commerce import repository
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database


def candidate_projection(body: str) -> str:
    native_sum = "(SELECT sum(amount_minor) FROM reconforge.ar_receipt_allocations WHERE tenant_id=s.tenant_id AND invoice_id=s.invoice_id)"
    if body.count(native_sum) != 3:
        raise AssertionError("Expected the retained three identical native allocation aggregates")
    body = body.replace(native_sum, "cash.allocated")
    join = "FROM reconforge.stock_commerce_tranches t JOIN reconforge.stock_sales_orders s ON s.tenant_id=t.tenant_id AND s.id=t.stock_order_id"
    if body.count(join) != 1:
        raise AssertionError("Expected the retained native tranche membership")
    return body.replace(join, join + " LEFT JOIN LATERAL (SELECT sum(amount_minor) allocated FROM reconforge.ar_receipt_allocations WHERE tenant_id=s.tenant_id AND workspace_id=s.workspace_id AND invoice_id=s.invoice_id) cash ON TRUE")


def allocation_scans(node: dict[str, Any]) -> int:
    return (int(node.get("Actual Loops", 0)) if node.get("Relation Name") == "ar_receipt_allocations" else 0) + sum(
        allocation_scans(child) for child in node.get("Plans", []))


def test_profile_real_collection_projection(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    order, invoice_id = invoiced(runtime)
    complete(runtime, prepare(runtime, invoice_id, 10000), "PROFILE")
    with runtime.actor("maker") as (connection, _, actor):
        expected = repository(connection, runtime).get(order["id"], actor=actor)
        definition = connection.execute("SELECT pg_get_functiondef('reconforge.stock_commerce_public(reconforge.stock_commerce_orders)'::regprocedure) d").fetchone()["d"]
        body = definition.split("AS $function$", 1)[1].rsplit("$function$", 1)[0].strip().rstrip(";")
        candidate = candidate_projection(body)
        tail = " FROM reconforge.stock_commerce_orders d WHERE d.tenant_id=%s AND d.id=%s"
        arguments = (runtime.tenant, order["id"])
        for query in (body, candidate):
            assert connection.execute(query + tail, arguments).fetchone()["jsonb_build_object"] == expected
        plans: dict[str, list[dict[str, Any]]] = {"baseline": [], "candidate": []}
        # Alternating order balances warm-cache and scheduling effects.
        for repeat in range(25):
            labels = ("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")
            for label in labels:
                query = body if label == "baseline" else candidate
                plan = connection.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query + tail, arguments).fetchone()["QUERY PLAN"][0]
                plans[label].append(plan)
        baseline_scans = allocation_scans(plans["baseline"][0]["Plan"])
        candidate_scans = allocation_scans(plans["candidate"][0]["Plan"])
        assert baseline_scans == 3 and candidate_scans == 1
        measured = {label: {"execution_ms": [plan["Execution Time"] for plan in group],
                           "planning_ms": [plan["Planning Time"] for plan in group],
                           "median_execution_ms": statistics.median(plan["Execution Time"] for plan in group),
                           "allocation_scan_loops": allocation_scans(group[0]["Plan"]), "first_plan": group[0]}
                    for label, group in plans.items()}
        root = Path(__file__).resolve().parents[2]
        output = root / "output/global-operating-platform-20261009/commercial" / ("projection-" + str(time.time_ns()) + ".json")
        packet = {"scope": "single native invoice with one actual reviewed partial receipt; projection only",
                  "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),  # nosec B603 B607
                  "platform": platform.platform(), "python": platform.python_version(), "logical_cpus": os.cpu_count(),
                  "postgres_version": connection.execute("SHOW server_version").fetchone()["server_version"],
                  "dataset": {"lines": 1, "tranches": 1, "collection_plans": 1, "invoice_minor": "45000", "collection_minor": "10000"},
                  "projection_sha256": hashlib.sha256(canonical_json(expected).encode()).hexdigest(),
                  "baseline_sql": body, "candidate_sql": candidate, "measurements": measured,
                  "projection_identical": True, "financial_source_unchanged": True}
        output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"evidence": str(output), "baseline_ms": measured["baseline"]["median_execution_ms"],
                          "candidate_ms": measured["candidate"]["median_execution_ms"], "scans": [baseline_scans, candidate_scans]}))
