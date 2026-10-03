"""Verify the pinned 45-row AMLSim oracle through a real disposable PostgreSQL worker.

Requires RECONFORGE_TEST_POSTGRES_ADMIN_DSN and RECONFORGE_TEST_POSTGRES_DSN.
Creates, migrates and drops only a fresh reconforge_amlsim_<random> database.
The application role must already exist and pass the production runtime guard.
No source download, source installation, fake matcher or scope bypass is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reconforge.auth.policy import PolicyEvaluationContext  # noqa: E402
from reconforge.benchmark.amlsim_reconciliation import (  # noqa: E402
    AMLSimProfile,
    canonical_digest,
    load_amlsim_profile,
    parse_amlsim_sample,
    project_sides,
    run_amlsim_reconciliation,
)
from reconforge.deployment import WorkerPermissionManifest  # noqa: E402
from reconforge.infrastructure.postgres import (  # noqa: E402
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_reconciliation import (  # noqa: E402
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)
from reconforge.reconciliation.deterministic_engine import (  # noqa: E402
    LEGACY_CONSTRAINT_POLICY,
    STRICT_ONE_TO_ONE_CONSTRAINT_POLICY,
)
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY  # noqa: E402
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY  # noqa: E402
from reconforge.workers.postgres_reconciliation import (  # noqa: E402
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
)

TENANT = "amlsim-synthetic-a"
SIBLING = "amlsim-synthetic-b"
WORKER = "amlsim-oracle-worker"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_hashes() -> dict[str, str]:
    """Bind all Python runtime/migration source, including transitive installers."""
    paths = [*ROOT.joinpath("reconforge").rglob("*.py"), *ROOT.joinpath("alembic").rglob("*.py"), Path(__file__),
             ROOT / "docs/validation/amlsim-workload.v1.yaml", ROOT / "tests/fixtures/amlsim/tx.csv"]
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted(paths)
    }


def assert_oracle(results: list[dict[str, Any]], profile: AMLSimProfile, source_ids: set[str]) -> dict[str, Any]:
    """Assert fault-derived pairs and money/date constraints independently of scores."""
    matched = [row for row in results if row["status"] == "Matched"]
    left = {row["left_id"] for row in results if row["status"] == "Unmatched" and row["left_id"]}
    right = {row["right_id"] for row in results if row["status"] == "Unmatched" and row["right_id"]}
    expected_left = {"L-" + value for value in (profile.faults.missing_id, profile.faults.changed_amount_id, profile.faults.delayed_id)}
    fixed_right = {"R-" + value for value in (profile.faults.changed_amount_id, profile.faults.delayed_id)}
    duplicates = {"R-" + profile.faults.duplicate_id, "R-" + profile.faults.duplicate_id + "-duplicate"}
    require(len(results) == 48 and len(matched) == 42, "Fault oracle requires 42 pairs and 48 decisions.")
    require(left == expected_left, "Fault oracle unmatched left IDs differ.")
    require(len(right) == 3 and fixed_right <= right and len(right & duplicates) == 1, "Fault oracle unmatched right IDs differ.")
    require(len({row["left_id"] for row in matched}) == len({row["right_id"] for row in matched}) == 42, "Input reused by matching.")
    require({row["left_id"] for row in matched} == {"L-" + identity for identity in source_ids} - expected_left, "Matched set differs from the registered source IDs.")
    for row in matched:
        expected = "R-" + str(row["left_id"])[2:]
        require(row["right_id"] in (duplicates if expected in duplicates else {expected}), "Matched pair violates source identity.")
        require(Decimal(str(row["amount_difference"])) == 0 and row["date_difference_days"] == 0, "Matched pair violates exact money/date constraints.")
    return {"matched_pairs": 42, "unmatched_left_ids": sorted(left), "unmatched_right_ids": sorted(right), "oracle_passed": True}


def decision_projection(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude run IDs/timestamps; retain exact decisions and all engine lineage."""
    fields = ("left_id", "right_id", "match_type", "confidence", "explanation", "amount_difference", "date_difference_days", "status", "reason_code", "lineage_json")
    return json.loads(json.dumps([{key: row[key] for key in fields} for row in results], default=str))


def register(repository: PostgresReconciliationRepository, run_id: str, rule: dict[str, Any], sides: tuple[list[dict[str, Any]], list[dict[str, Any]]], input_hash: str) -> None:
    repository.create_run(
        tenant_id=TENANT, run_id=run_id, name="Pinned synthetic AMLSim oracle",
        left_source="AMLSim/tx.csv:projected-left", right_source="AMLSim/tx.csv:projected-right",
        algorithm_version="deterministic-global-v1", rule=rule, input_hash=input_hash,
        actor_id="synthetic-workload-registrar", idempotency_key=run_id,
    )
    for side, records in zip(("Left", "Right"), sides, strict=True):
        for record in records:
            repository.register_input(
                tenant_id=TENANT, run_id=run_id, side=side, source_id=record["id"],
                record_hash=canonical_digest(record), amount=record["amount"], amount_original=record["amount"],
                currency_code=record["currency"], date_value=record["date"], date_original=record["date"],
                reference_original=record["reference"], reference_normalized=record["reference"], attributes=record,
            )


def require_sealed_input_denied(repository: PostgresReconciliationRepository, run_id: str) -> None:
    """A new source identity must never extend a claimed or terminal manifest."""
    try:
        repository.register_input(
            tenant_id=TENANT, run_id=run_id, side="Left", source_id="L-after-sealing",
            record_hash="synthetic-sealed-input-probe", amount="1.00", currency_code="USD",
        )
    except PostgresReconciliationIntegrityError as exc:
        require("sealed" in str(exc), "New input failed for an unrelated reason.")
    else:
        raise ValueError("A new input was accepted after the manifest was sealed.")


def verify_registration_concurrency(factory: PostgresConnectionFactory) -> dict[str, Any]:
    """Observe actual backend lock waits and stale-snapshot admission behavior."""
    boundary = PostgresTenantBoundary(factory)
    ids = ("race-register-first", "race-claim-first", "race-snapshot", "repeatable-register")
    with boundary.transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        for run_id in ids:
            repository.create_run(tenant_id=TENANT, run_id=run_id, name="Synthetic lifecycle control", left_source="control-left", right_source="control-right", algorithm_version="control-v1", rule={}, input_hash="synthetic-control", actor_id="control-registrar")

    def payload(run_id: str) -> dict[str, Any]:
        return {"tenant_id": TENANT, "run_id": run_id, "side": "Left", "source_id": "control-left", "record_hash": "control-fingerprint", "amount": "1.00", "currency_code": "USD"}

    def competing(run_id: str, action: str, repeatable: bool, ready: Event, state: dict[str, Any]) -> dict[str, Any]:
        connection = factory.connect()
        try:
            with connection.transaction():
                if repeatable:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                set_local_tenant_scope(connection, TENANT)
                repository = PostgresReconciliationRepository(connection)
                state["pid"] = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
                initial_count = len(repository.list_inputs(tenant_id=TENANT, run_id=run_id))
                ready.set()
                try:
                    if action == "claim":
                        repository.claim_run(tenant_id=TENANT, run_id=run_id, worker_id="control-claimer")
                    else:
                        repository.register_input(**payload(run_id))
                except (PostgresReconciliationIntegrityError, PostgresReconciliationValidationError) as exc:
                    return {"denied": True, "reason": str(exc), "initial_input_count": initial_count}
                return {"denied": False, "initial_input_count": initial_count, "observed_input_count": len(repository.list_inputs(tenant_id=TENANT, run_id=run_id))}
        finally:
            connection.close()

    def observe_wait(connection: Any, future: Future[dict[str, Any]], ready: Event, state: dict[str, Any]) -> bool:
        require(ready.wait(3), "Competing transaction did not start.")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            row = connection.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (state["pid"],)).fetchone()
            if row is not None and row[0] == "Lock":
                return True
            if future.done():
                return False
            time.sleep(0.01)
        raise ValueError("Competing transaction neither waited for a lock nor finished.")

    results: dict[str, Any] = {}
    for run_id, holder_action, other_action, repeatable in (
        (ids[0], "register", "claim", False), (ids[1], "claim", "register", False),
        (ids[2], "register", "claim", True),
    ):
        ready, state = Event(), {}
        with ThreadPoolExecutor(max_workers=1) as pool:
            with boundary.transaction(TENANT) as connection:
                repository = PostgresReconciliationRepository(connection)
                if holder_action == "register":
                    repository.register_input(**payload(run_id))
                else:
                    repository.claim_run(tenant_id=TENANT, run_id=run_id, worker_id="control-claimer")
                future = pool.submit(competing, run_id, other_action, repeatable, ready, state)
                waited = observe_wait(connection, future, ready, state)
            outcome = future.result(timeout=5)
        results[run_id] = {"backend_lock_wait_observed": waited, **outcome}
    first, second, snapshot = (results[name] for name in ids[:3])
    results["read_committed_both_orderings_passed"] = (
        first["backend_lock_wait_observed"] and not first["denied"] and first["observed_input_count"] == 1
        and second["backend_lock_wait_observed"] and second["denied"] and "sealed" in second["reason"]
    )
    results["repeatable_read_claim_refused"] = snapshot["denied"] and "READ COMMITTED" in snapshot["reason"]
    results["repeatable_read_stale_snapshot_reproduced"] = (
        not snapshot["denied"] and snapshot.get("observed_input_count") == 0
    )
    connection = factory.connect()
    try:
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            set_local_tenant_scope(connection, TENANT)
            repository = PostgresReconciliationRepository(connection)
            try:
                repository.register_input(**payload(ids[3]))
            except PostgresReconciliationValidationError as exc:
                results["repeatable_read_new_registration_refused"] = "READ COMMITTED" in str(exc)
            else:
                results["repeatable_read_new_registration_refused"] = False
            # Existing stable input is safe to replay under the same snapshot.
            repository.register_input(**payload(ids[0]))
            results["repeatable_read_exact_replay_allowed"] = True
            results["caller_isolation_unchanged"] = connection.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
    finally:
        connection.close()
    with boundary.transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        snapshot_run = repository.get_run_metadata(tenant_id=TENANT, run_id=ids[2])
        results["refused_claim_has_no_execution_effect"] = snapshot_run["execution_status"] == "Queued" and snapshot_run["execution_attempt"] == 0
        results["refused_registration_has_no_input_effect"] = not repository.list_inputs(tenant_id=TENANT, run_id=ids[3])
    return results


def execute(app_dsn: str, profile: AMLSimProfile, content: bytes) -> dict[str, Any]:
    source = parse_amlsim_sample(content, profile)
    require(len(source) == 45, "This bounded acceptance oracle is the pinned 45-record sample only.")
    sides = project_sides(source, profile)
    offline = run_amlsim_reconciliation(content, profile)
    provenance = {
        "projection": offline["projection"], "source": offline["source"],
        "profile_digest": canonical_digest(profile.model_dump(mode="json")),
        "canonical_source_digest": offline["canonical_source_digest"],
    }
    base_rule = {
        "exact_fields": "reference,currency,account,counterparty,transfer_type",
        "amount_tolerance": "0", "date_window_days": 0,
        "financial_input_policy": STRICT_FINANCIAL_INPUT_POLICY,
        "record_identity_policy": RECORD_IDENTITY_POLICY, "workload_provenance": provenance,
    }
    strict = {**base_rule, "constraint_policy": STRICT_ONE_TO_ONE_CONSTRAINT_POLICY}
    variants = {
        "strict": strict, "permuted": strict,
        "legacy-missing": base_rule,
        "legacy-explicit": {**base_rule, "constraint_policy": LEGACY_CONSTRAINT_POLICY},
        "invalid-policy": {**strict, "constraint_policy": "unknown-v999"},
        "invalid-date": {**strict, "date_window_days": True},
        "invalid-group": {**strict, "allow_one_to_many": True},
    }
    factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    input_hash = canonical_digest({"provenance": provenance, "left": sides[0], "right": sides[1]})
    with boundary.transaction(TENANT) as connection:
        role = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
        require(role is not None and not any(role), "Application role is privileged.")
        repository = PostgresReconciliationRepository(connection)
        for name, rule in variants.items():
            selected = tuple(list(reversed(records)) for records in sides) if name == "permuted" else sides
            register(repository, name, rule, selected, input_hash)
        register(repository, "strict", strict, sides, input_hash)
        require(len(repository.list_inputs(tenant_id=TENANT, run_id="strict")) == 90, "Submission replay duplicated inputs.")
        # Simulate interruption after the real repository commits a worker lease.
        # The real replacement worker must recover this expired claim itself.
        repository.claim_run(tenant_id=TENANT, run_id="strict", worker_id="synthetic-interrupted-worker", lease_seconds=1)
        require_sealed_input_denied(repository, "strict")

    time.sleep(1.1)

    manifest = WorkerPermissionManifest(WORKER, WORKER, "match.discover", "match.run", ("match.discover", "match.run"), "tenant:" + TENANT)
    worker = PostgresReconciliationWorker(
        factory, tenant_supplier=lambda: [TENANT], matcher=LocalDeterministicMatcherAdapter(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id=WORKER, poll_interval_seconds=0, permission_manifest=manifest,
            discovery_policy_permission="match.discover",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id=WORKER, username=WORKER, user_permissions={"match.discover", "match.run"},
                principal_type="service_account", tenant_id=tenant, authorized_tenant_ids=frozenset({TENANT}),
            ),
        ),
    )
    try:
        summary = worker.process_once(request_id="amlsim-persisted-oracle")
        require(summary.discovered == 7 and summary.completed == 4 and summary.failed == 3, "Unexpected durable worker outcomes.")
        require(worker.process_once().discovered == 0, "Finished/failed runs were rediscovered without an operator retry.")
        try:
            worker.process_run(tenant_id=SIBLING, run_id="strict")
        except PostgresReconciliationWorkerError:
            pass
        else:
            raise ValueError("Worker accepted an unauthorized sibling tenant.")
    finally:
        worker.close()

    runs: dict[str, Any] = {}
    decisions: dict[str, list[dict[str, Any]]] = {}
    with boundary.transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        for name, rule in variants.items():
            run = repository.get_run(tenant_id=TENANT, run_id=name)
            inputs = repository.list_inputs(tenant_id=TENANT, run_id=name)
            require_sealed_input_denied(repository, name)
            if name == "strict":
                register(repository, name, rule, sides, input_hash)
                require(repository.list_inputs(tenant_id=TENANT, run_id=name) == inputs, "Completed exact replay changed the input manifest.")
            results = repository.list_results(tenant_id=TENANT, run_id=name)
            exceptions = repository.list_exceptions(tenant_id=TENANT, run_id=name)
            require(run["rule_json"] == rule and run["input_hash"] == input_hash, "Persisted rule/source provenance changed.")
            require(len(inputs) == 90 and not exceptions, "Input/exceptions persisted unexpectedly.")
            require(all(item["record_hash"] == canonical_digest(item["attributes_json"]) for item in inputs), "Registered source record fingerprint changed.")
            if name.startswith("invalid-"):
                require(run["execution_status"] == "Failed" and not results, "Invalid policy produced decision effects.")
            else:
                require(run["execution_status"] == "Complete", "Valid workload did not complete.")
                require(run["input_manifest_hash"] == repository._hash_payload(inputs), "Stored input manifest hash does not verify.")
                require(run["result_set_hash"] == repository._hash_payload(results), "Stored result set hash does not verify.")
                if name == "strict":
                    require(run["execution_attempt"] == 2, "Expired lease was not recovered as a second worker attempt.")
            decisions[name] = decision_projection(results)
            events = connection.execute("SELECT action,actor_id,event_hash FROM reconforge.audit_events WHERE tenant_id=%s AND resource_id=%s ORDER BY action", (TENANT, name)).fetchall()
            actions = {str(row[0]) for row in events}
            require("run_created" in actions and ("run_failed" if name.startswith("invalid-") else "run_completed") in actions, "Durable lifecycle audit evidence missing.")
            require(all(len(str(row[2])) == 64 for row in events), "Audit hash missing.")
            outbox = connection.execute("SELECT event_type FROM reconforge.outbox_events WHERE tenant_id=%s AND aggregate_id=%s", (TENANT, name)).fetchall()
            require({"reconciliation." + action for action in actions} <= {str(row[0]) for row in outbox}, "Lifecycle outbox evidence missing.")
            runs[name] = {
                "execution_status": run["execution_status"], "input_count": len(inputs),
                "result_count": len(results), "result_statuses": dict(Counter(row["status"] for row in results)),
                "rule_digest": canonical_digest(rule), "input_manifest_hash": run["input_manifest_hash"],
                "result_set_hash": run["result_set_hash"], "decision_digest": canonical_digest(decisions[name]),
                "audit_actions": sorted(actions), "audit_actors": sorted({str(row[1]) for row in events}),
                "execution_error": run["execution_error"],
                "execution_attempt": run["execution_attempt"],
            }
        source_ids = {row["source_id"] for row in source}
        oracle = assert_oracle(decisions["strict"], profile, source_ids)
        assert_oracle(decisions["permuted"], profile, source_ids)
        require(decisions["strict"] == decisions["permuted"], "Persisted decisions/lineage changed under input permutation.")
        require(decisions["legacy-missing"] == decisions["legacy-explicit"], "Historical missing policy was reinterpreted.")
        try:
            assert_oracle(decisions["legacy-missing"], profile, source_ids)
        except ValueError:
            pass
        else:
            raise ValueError("The independent fault oracle failed to distinguish legacy scored decisions.")
        require(all(row["lineage_json"]["constraint_policy"] == STRICT_ONE_TO_ONE_CONSTRAINT_POLICY for row in decisions["strict"]), "Strict policy is absent from stored lineage.")
    with boundary.transaction(SIBLING) as connection:
        require(not PostgresReconciliationRepository(connection).list_results(tenant_id=TENANT, run_id="strict"), "RLS disclosed sibling tenant decisions.")
    return {
        "source": provenance, "source_records": 45, "left_records": 45, "right_records": 45,
        "constraint_policy": STRICT_ONE_TO_ONE_CONSTRAINT_POLICY, "oracle": oracle,
        "runs": runs, "worker_summary": asdict(summary), "worker_manifest": manifest.to_dict(),
        "worker_manifest_digest": manifest.digest, "permutation_equal": True,
        "legacy_missing_policy_equal_to_explicit": True, "legacy_rejected_by_independent_oracle": True,
        "submission_replay_preserved_input_count": True,
        "expired_claim_recovered_without_duplicate_decisions": True,
        "claimed_completed_failed_input_manifests_sealed": True,
        "completed_exact_replay_preserves_input_manifest": True,
        "sibling_worker_denied": True, "sibling_rls_read_denied": True,
        "offline_reference_decision_digest": offline["decision_digest"],
        "decisions": decisions["strict"],
        "concurrency": verify_registration_concurrency(factory),
    }


def main() -> int:
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import URL

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--migration-target", default="0094_pg_finance_policy")
    args = parser.parse_args()
    require(args.output.resolve() not in {Path(__file__).resolve(), ROOT / "docs/validation/amlsim-workload.v1.yaml", ROOT / "tests/fixtures/amlsim/tx.csv"}, "Output cannot overwrite a workload input or runner.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    admin_dsn = os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"]
    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_params = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    app_params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    require(all(admin_params.get(key) == app_params.get(key) for key in ("host", "port")), "Admin and application DSNs must address the same test server.")
    require(admin_params.get("user") != app_params.get("user") and bool(app_params.get("user")), "A separate existing application role is required.")
    database = "reconforge_amlsim_" + uuid4().hex[:20]
    before = source_hashes()
    started = time.perf_counter()
    report: dict[str, Any] = {"schema_version": "reconforge-postgres-amlsim-evidence-v1", "status": "failed", "started_at": datetime.now(UTC).isoformat(), "disposable_database": database}
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        require(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None, "Generated database already exists.")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        admin_params["dbname"] = app_params["dbname"] = database
        isolated_admin = psycopg.conninfo.make_conninfo(**admin_params)
        isolated_app = psycopg.conninfo.make_conninfo(**app_params)
        environment = dict(os.environ, PYTHONPATH=str(ROOT))
        environment["RECONFORGE_POSTGRES_DSN"] = URL.create(
            "postgresql+psycopg", username=admin_params["user"], password=admin_params.get("password"),
            host=admin_params.get("host"), port=int(admin_params.get("port", "5432")), database=database,
        ).render_as_string(hide_password=False)
        with args.output.with_suffix(".migration.log").open("w", encoding="utf-8") as log:
            migrated = subprocess.run([sys.executable, "-m", "alembic", "upgrade", args.migration_target], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=False)
        require(migrated.returncode == 0, "Production migrations failed; inspect the adjacent migration log.")
        with psycopg.connect(isolated_admin) as admin:
            report["postgresql_version"] = admin.execute("SHOW server_version").fetchone()[0]
            report["migration_revision"] = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(app_params["user"])))
            tables = ("tenants", "audit_events", "outbox_events", "reconciliation_runs", "reconciliation_inputs", "reconciliation_results", "reconciliation_exceptions", "reconciliation_execution_checkpoints")
            admin.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON {} TO {}").format(sql.SQL(",").join(sql.Identifier("reconforge", name) for name in tables), sql.Identifier(app_params["user"])))
            for tenant in (TENANT, SIBLING):
                admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
        profile = load_amlsim_profile(ROOT / "docs/validation/amlsim-workload.v1.yaml")
        content = (ROOT / "tests/fixtures/amlsim/tx.csv").read_bytes()
        report.update(execute(isolated_app, profile, content))
        require(all(report["concurrency"][name] for name in ("read_committed_both_orderings_passed", "repeatable_read_claim_refused", "repeatable_read_new_registration_refused", "repeatable_read_exact_replay_allowed", "caller_isolation_unchanged", "refused_claim_has_no_execution_effect", "refused_registration_has_no_input_effect")), "Claim/registration concurrency contract failed.")
        after = source_hashes()
        require(before == after, "Runtime/migration source changed during verification; this run cannot be accepted.")
        report.update(status="passed", source_tree_digest=canonical_digest(before), source_file_count=len(before), source_unchanged=True,
                      source_files={name: before[name] for name in (".github/scripts/verify_postgres_amlsim_reconciliation.py", "reconforge/workers/postgres_reconciliation.py", "reconforge/reconciliation/deterministic_engine.py", "reconforge/benchmark/amlsim_reconciliation.py", "reconforge/infrastructure/postgres_reconciliation.py")})
        report["migration_source_files"] = {name: digest for name, digest in before.items() if name.startswith("alembic/")}
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (database,))
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            require(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None, "Disposable database cleanup was not confirmed.")
        report.update(disposable_database_removed=True, wall_seconds=round(time.perf_counter() - started, 6), python=platform.python_version(), platform=platform.platform(), migration_target=args.migration_target)
        report["limitations"] = ["45-row synthetic upstream sample only; not a scale benchmark", "Currency/date epoch and two-sided faults assigned by the scenario", "Repository submission plus durable worker/readback; no HTTP ingestion or financial posting", "No customer results, AML efficacy or external audit acceptance claim"]
        report["report_digest"] = canonical_digest(report)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "source_records": 45, "matched_pairs": report["oracle"]["matched_pairs"], "report_digest": report["report_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
