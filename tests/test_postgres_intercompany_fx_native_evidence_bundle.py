"""Original complete evidence batching preserves current native authority."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest

from reconforge.application.accrual_deferral_evidence import evidence_chunks
from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_intercompany_fx import FxRuntime, backing_digest, recognize
from tests.test_postgres_intercompany_fx_api import ROOT, client
from tests.test_postgres_intercompany_group_diagnostic import closed_source
from tests.test_postgres_intercompany_reporting_currency_precision import (
    original_cycle,
    original_fraction_proof,
    reporting_runtime,
)

pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def seller_cap(permission, maximum, seen):
    def evaluate(principal, **request_context):
        seen.append(request_context)
        # The real policy ceiling is qualified to the original seller entity.
        # Other entities are legitimately uncapped; no absent amount is invented.
        return evaluate_principal_access(principal, maximum_amount=Decimal(maximum)
            if request_context["required_permission"] == permission and request_context["entity_id"] == "seller" else None,
            **request_context)
    return evaluate


def test_actual_native_http_bundle_preserves_every_existing_original_proof_byte_and_fraction_oracle(
    runtime: FxRuntime, intercompany_fx_database: tuple[str, str], tmp_path: Path,
) -> None:
    source_id = closed_source(runtime, "native-bundle-http").opening.source_id
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.base.tenant)
        bundle = repository.native_evidence_bundle(source_id, actor=actor)
        assert bundle["source"] == repository.get_source(source_id, actor=actor)
        assert len(bundle["plan_evidence"]) == 4
        for plan, proof in zip(bundle["source"]["plans"], bundle["plan_evidence"], strict=True):
            assert b"".join(evidence_chunks(proof)) == b"".join(evidence_chunks(repository.evidence(plan["id"], actor=actor)))
        original = {"schema_version": "intercompany-fx-original-cycle-proof-v2", "performance_measurement": False,
            "native_role": dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()),
            "stages": bundle["plan_evidence"], "report": repository.report(source_id, actor=actor)}
        raw = b"".join(evidence_chunks(original))
        raw_sha = hashlib.sha256(raw).hexdigest()
        path = tmp_path / "original-bundle-cycle.json"
        path.write_bytes(raw)
        outputs = []
        for optimized in (False, True):
            output = tmp_path / ("optimized-proof.json" if optimized else "normal-proof.json")
            command = [sys.executable, "-I", *(["-O"] if optimized else []),
                str(Path(__file__).resolve().parents[1] / ".github/scripts/verify_intercompany_fx_cycle_oracle.py"),
                str(path), "--output", str(output)]
            result = subprocess.run(command, capture_output=True, check=False, timeout=30)
            assert result.returncode == 0, result.stderr.decode("utf8", errors="replace")
            accepted = json.loads(output.read_bytes())
            assert accepted["passed"] is True and accepted["stage_count"] == 4 and accepted["native_effect_count"] == 7
            assert accepted["original_proof_sha256"] == raw_sha and accepted["original_proof_bytes"] == len(raw)
            assert path.read_bytes() == raw
            outputs.append(output.read_bytes())
        assert outputs[0] == outputs[1]
        if directory := os.environ.get("RECONFORGE_ICFX_PROOF_DIR"):
            with (Path(directory) / ("native-bundle-original-" + uuid4().hex + ".json")).open("xb") as stream:
                stream.write(raw)
        assert backing_digest(connection, runtime.base.tenant) == before
    with client(runtime, intercompany_fx_database, tmp_path / "http", "poster", step_up=False) as (session, headers):
        response = session.get(ROOT + "/sources/" + source_id + "/native-evidence-bundle", headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.content) == int(response.headers["Content-Length"])
        assert hashlib.sha256(response.content).hexdigest() == response.headers["X-ReconForge-Evidence-SHA256"]
        projected = response.json()["bundle"]
        assert projected["schema_version"] == "intercompany-fx-source-native-evidence-bundle-v1"
        assert projected["complete_source"] is True
        assert projected["source"] == session.get(ROOT + "/sources/" + source_id, headers=headers).json()["source"]
        for plan, proof in zip(projected["source"]["plans"], projected["plan_evidence"], strict=True):
            existing = session.get(ROOT + "/plans/" + plan["id"] + "/evidence", headers=headers)
            assert existing.status_code == 200
            assert b"".join(evidence_chunks(proof)) == b"".join(evidence_chunks(existing.json()["evidence"]))
            assert proof["plan"] == plan
        assert session.get(ROOT + "/sources/" + source_id + "/native-evidence-bundle",
            headers={**headers, "X-ReconForge-Legal-Entity": "seller"}).status_code == 403
    with runtime.actor("poster", entities=frozenset({"seller", "buyer"})) as (_, repository, actor), pytest.raises(FinancePostingError, match="denied"):
        repository.native_evidence_bundle(source_id, actor=actor)


def test_bundle_refuses_unclosed_source_and_whole_capture_budget_without_partial_headers(
    runtime: FxRuntime, intercompany_fx_database: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reconforge.application.accrual_deferral_evidence as codec

    incomplete = recognize(runtime)
    with client(runtime, intercompany_fx_database, tmp_path, "poster", step_up=False) as (session, headers):
        denied = session.get(ROOT + "/sources/" + incomplete["source_id"] + "/native-evidence-bundle", headers=headers)
        assert denied.status_code == 400 and denied.json()["error"]["code"] == "intercompany_fx_bundle_incomplete"
    source_id = closed_source(runtime, "native-bundle-budget").opening.source_id
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.base.tenant)
        retained = repository.native_evidence_bundle(source_id, actor=actor)
        monkeypatch.setattr(codec, "MAX_EVIDENCE_NODES", 1)
        with pytest.raises(FinancePostingError, match="budget") as failure:
            repository.native_evidence_bundle(source_id, actor=actor)
        assert "too_large" in failure.value.code
        monkeypatch.undo()
        assert repository.native_evidence_bundle(source_id, actor=actor) == retained
        assert backing_digest(connection, runtime.base.tenant) == before
    with client(runtime, intercompany_fx_database, tmp_path / "budget", "poster", step_up=False) as (session, headers):
        monkeypatch.setattr(codec, "MAX_EVIDENCE_NODES", 1)
        refused = session.get(ROOT + "/sources/" + source_id + "/native-evidence-bundle", headers=headers)
        assert refused.status_code == 413
        assert "X-ReconForge-Evidence-SHA256" not in refused.headers
        assert "bundle" not in refused.json()


@pytest.mark.parametrize("permission", ["finance_core.read", "intercompany_fx.read"])
def test_bundle_retains_absent_initial_adjustment_amount_cap_denial(
    runtime: FxRuntime, monkeypatch: pytest.MonkeyPatch, permission: str,
) -> None:
    import reconforge.infrastructure.postgres_operational_finance as authority

    source_id = closed_source(runtime, "native-bundle-cap").opening.source_id
    with runtime.actor("poster") as (connection, repository, actor):
        original = repository.native_evidence_bundle(source_id, actor=actor)
        before = backing_digest(connection, runtime.base.tenant)
        def cap(principal, **context):
            return evaluate_principal_access(principal,
                maximum_amount=Decimal("20000") if context["required_permission"] == permission else None, **context)
        monkeypatch.setattr(authority, "evaluate_principal_access", cap)
        with pytest.raises(FinancePostingError, match="denied"):
            repository.native_evidence_bundle(source_id, actor=actor)
        monkeypatch.undo()
        assert repository.native_evidence_bundle(source_id, actor=actor) == original
        assert backing_digest(connection, runtime.base.tenant) == before


def test_bundle_rechecks_cached_current_grant_after_actual_source_lock_wait(runtime: FxRuntime) -> None:
    source_id = closed_source(runtime, "native-bundle-wait").opening.source_id
    pids: Queue[int] = Queue()
    def read():
        try:
            with runtime.actor("poster") as (connection, repository, actor):
                pids.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                return repository.native_evidence_bundle(source_id, actor=actor)
        except FinancePostingError as exc:
            return exc
    blocker = runtime.base.factory.connect()
    blocker.execute("SELECT set_config('app.tenant_id',%s,true),set_config('app.workspace_id','work',true),set_config('app.organization_id','org',true)", (runtime.base.tenant,))
    blocker_pid = blocker.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
    blocker.execute("SELECT id FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s AND id=%s FOR UPDATE", (runtime.base.tenant, source_id))
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(read)
            pid = pids.get(timeout=10)
            with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
                deadline = monotonic() + 10
                while blocker_pid not in connection.execute("SELECT pg_blocking_pids(%s) pids", (pid,)).fetchone()["pids"]:
                    assert monotonic() < deadline, "Actual bundle source-row wait was not established"
                    sleep(.02)
                PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.base.tenant, grant_id="ic2-poster-group",
                    actor_id="maker", reason="Withdraw current original bundle adjustment scope while waiting")
            blocker.rollback()
            denied = future.result(timeout=15)
            assert isinstance(denied, FinancePostingError) and "denied" in denied.code
    finally:
        blocker.rollback()
        blocker.close()


def test_bundle_current_role_revocation_refuses_cached_both_read_permissions(runtime: FxRuntime) -> None:
    source_id = closed_source(runtime, "native-bundle-role").opening.source_id
    for permission in ("finance_core.read", "intercompany_fx.read"):
        with runtime.actor("poster") as (_, repository, actor):
            assert permission in actor.permissions
            with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
                connection.execute("""UPDATE reconforge.identity_role_permissions SET active=false,revoked_at=now(),
                    revoked_by='maker',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name=%s""",
                    (runtime.base.tenant, permission))
            with pytest.raises(FinancePostingError, match="denied"):
                repository.native_evidence_bundle(source_id, actor=actor)
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            connection.execute("""UPDATE reconforge.identity_role_permissions SET active=true,revoked_at=NULL,
                revoked_by=NULL,revocation_reason_code=NULL WHERE tenant_id=%s AND permission_name=%s""",
                (runtime.base.tenant, permission))


@pytest.mark.parametrize("currency,precision", [("JPY", 0), ("KWD", 3)])
def test_bundle_current_reporting_precision_caps_original_seller_scope_under_both_read_permissions(
    runtime: FxRuntime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, currency: str, precision: int,
) -> None:
    import reconforge.infrastructure.postgres_operational_finance as authority

    rt = reporting_runtime(runtime, currency, precision)
    stages = original_cycle(rt, currency)
    with rt.actor("poster") as (connection, repository, actor):
        original = repository.native_evidence_bundle(stages[0]["source_id"], actor=actor)
        source = original["source"]
        assert source["policies"]["adjustment"]["currency_precision"] == precision
        assert {source["policies"][book]["currency_precision"] for book in ("seller", "buyer", "transaction")} == {2}
        translated = original["plan_evidence"][-1]["plan"]["equation"]["translations"]["seller"]["accounts"]
        assert next(row["balance_minor"] for row in translated if row["role"] == "cash") == 200 * 10 ** precision
        before = b"".join(evidence_chunks(original))
        original_fraction_proof({"schema_version": "intercompany-fx-original-cycle-proof-v2", "performance_measurement": False,
            "native_role": dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()),
            "stages": original["plan_evidence"], "report": repository.report(source["id"], actor=actor)}, tmp_path)
        native = backing_digest(connection, rt.base.tenant)
        for permission in ("finance_core.read", "intercompany_fx.read"):
            seen = []
            with monkeypatch.context() as patch:
                patch.setattr(authority, "evaluate_principal_access", seller_cap(permission, "200", seen))
                assert b"".join(evidence_chunks(repository.native_evidence_bundle(source["id"], actor=actor))) == before
            assert any(context["entity_id"] == "seller" and context["required_permission"] == permission
                       and context.get("amount") == Decimal("200") for context in seen)
            with monkeypatch.context() as patch:
                patch.setattr(authority, "evaluate_principal_access", seller_cap(permission, "199", seen))
                with pytest.raises(FinancePostingError, match="denied"):
                    repository.native_evidence_bundle(source["id"], actor=actor)
        assert b"".join(evidence_chunks(repository.native_evidence_bundle(source["id"], actor=actor))) == before
        assert backing_digest(connection, rt.base.tenant) == native
