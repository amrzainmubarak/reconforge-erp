"""Actual captured reporting scale, distinct functional books and current caps."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.accrual_deferral_evidence import evidence_chunks
from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_intercompany_fx import PostgresIntercompanyFxRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.utils.money import CurrencyRegistryContext
from tests.intercompany_fx_fixture import rate
from tests.test_postgres_intercompany_fx import (
    PERIODS,
    FxRuntime,
    backing_digest,
    intercompany_fx_database,
    preparation,
    publish,
    pytestmark,
    receipt_database,
    runtime,
)

__all__ = ["intercompany_fx_database", "pytestmark", "receipt_database", "runtime"]
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ReportingRuntime(FxRuntime):
    reporting_entity: str

    @contextmanager
    def actor(self, name: str, *, entities: frozenset[str] | None = None,
              organization_id: str | None = "org") -> Iterator[tuple[Any, PostgresIntercompanyFxRepository, PostingActor]]:
        with super().actor(name, entities=entities or frozenset({"seller", "buyer", self.reporting_entity}),
                           organization_id=organization_id) as context:
            yield context


def reporting_runtime(base: FxRuntime, currency: str, precision: int) -> ReportingRuntime:
    """Add a new native adjustment entity; never rewrite an existing currency."""
    context = CurrencyRegistryContext.from_installed()
    assert context.resolve(currency).spec.minor_units == precision
    entity = "reporting-" + currency.lower()
    with PostgresTenantBoundary(base.base.factory).transaction(base.base.tenant) as connection:
        masters = PostgresMasterDataRepository(connection)
        masters.upsert_currency(tenant_id=base.base.tenant, code=currency, name="Synthetic reporting " + currency,
                                minor_units=precision)
        masters.upsert_legal_entity(tenant_id=base.base.tenant, organization_id="org", entity_id=entity,
            entity_code="REPORT-" + currency, name="Synthetic native reporting " + currency, currency_code=currency)
        PostgresFinanceCoreRepository(connection, base.base.tenant).upsert_journal(
            journal_code="IC2_" + currency, name="Captured reporting " + currency,
            organization_code="ORG", currency_code=currency, workspace="work")
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("maker", "checker", "poster"):
            authority.grant(tenant_id=base.base.tenant, grant_id=f"reporting-{person}-{currency}",
                principal_type="user", principal_id=person, scope_type="legal_entity", scope_id=entity, actor_id=person)
    return ReportingRuntime(base.base, entity)


def original_cycle(rt: ReportingRuntime, currency: str) -> list[dict[str, Any]]:
    request = preparation(amount=10000)
    request = replace(request, reference="NATIVE-REPORTING-PRECISION-" + currency,
        adjustment=replace(request.adjustment, legal_entity_id=rt.reporting_entity,
            entity_code="REPORT-" + currency, currency_code=currency, journal_code="IC2_" + currency))
    with rt.actor("maker") as (_, repository, actor):
        original = repository.prepare(request, command_id="precision-recognize", actor=actor)
    original = publish(rt, original, "precision-recognize")
    with rt.actor("maker") as (_, repository, actor):
        cash = repository.prepare_settlement(original["source_id"], transaction_minor=10000,
            rates={"seller": rate("1.25", "2026-10-04"), "buyer": rate("0.8", "2026-10-04")},
            period_ids=PERIODS, posting_date="2026-10-04", reason="Reviewed full original functional Cash",
            command_id="precision-full-cash", actor=actor)
    cash = publish(rt, cash, "precision-full-cash")
    day = "2026-10-05"
    with rt.actor("maker") as (_, repository, actor):
        adjusted = repository.prepare_elimination(original["source_id"],
            closing_rates={"seller": rate("0.625", day), "buyer": rate("0.4", day)},
            income_rates={"seller": {"2026-10-03": rate("1.25", "2026-10-03"), "2026-10-04": rate("1.25", "2026-10-04")},
                          "buyer": {"2026-10-03": rate("0.8", "2026-10-03"), "2026-10-04": rate("0.8", "2026-10-04")}},
            period_ids=PERIODS, posting_date=day, reason="Reviewed reporting currency historical and closing rates",
            command_id="precision-eliminate", actor=actor)
    return [original, cash, publish(rt, adjusted, "precision-eliminate")]


def original_fraction_proof(proof: dict[str, Any], tmp_path: Path) -> bytes:
    """Externally anchor exact originals around isolated existing stdlib CLI."""
    raw = b"".join(evidence_chunks(proof))
    original_sha = hashlib.sha256(raw).hexdigest()
    original = tmp_path / "native-original.json"
    with original.open("xb") as stream:
        stream.write(raw)
    outputs = []
    for optimized in (False, True):
        output = tmp_path / ("optimized.json" if optimized else "normal.json")
        command = [sys.executable, "-I", *(["-O"] if optimized else []),
            str(ROOT / ".github/scripts/verify_intercompany_fx_cycle_oracle.py"), str(original), "--output", str(output)]
        result = subprocess.run(command, capture_output=True, check=False, timeout=30)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        accepted = json.loads(output.read_bytes())
        assert accepted["passed"] is True and accepted["stage_count"] == 3 and accepted["native_effect_count"] == 5
        assert accepted["original_proof_sha256"] == original_sha and accepted["original_proof_bytes"] == len(raw)
        assert hashlib.sha256(original.read_bytes()).hexdigest() == original_sha
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
    if directory := os.environ.get("RECONFORGE_ICFX_PROOF_DIR"):
        with (Path(directory) / ("reporting-precision-" + uuid4().hex + ".json")).open("xb") as stream:
            stream.write(raw)
    return raw


@pytest.mark.parametrize("currency,precision", [pytest.param("JPY", 0, id="JPY0"), pytest.param("KWD", 3, id="KWD3")])
@pytest.mark.parametrize("permission", ["finance_core.read", "intercompany_fx.read"])
def test_native_reporting_currency_precision_controls_current_elimination_plan_and_evidence_caps(
    runtime: FxRuntime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, currency: str, precision: int, permission: str,
) -> None:
    import reconforge.infrastructure.postgres_operational_finance as authority

    rt = reporting_runtime(runtime, currency, precision)
    stages = original_cycle(rt, currency)
    with rt.actor("poster") as (connection, repository, actor):
        source = repository.get_source(stages[0]["source_id"], actor=actor)
        assert {source["policies"][book]["currency_precision"] for book in ("seller", "buyer", "transaction")} == {2}
        assert source["policies"]["adjustment"]["currency_precision"] == precision
        assert source["policies"]["adjustment"]["currency_code"] == currency
        assert len({policy["currency_registry_digest"] for policy in source["policies"].values()}) == 1
        adjustment = repository.get_plan(stages[-1]["id"], actor=actor)
        assert adjustment["equation"]["translated_trade_minor"] == 100 * 10 ** precision
        assert [abs(next(row["balance_minor"] for row in adjustment["equation"]["translations"][book]["accounts"]
                         if row["role"] == "cash")) for book in ("seller", "buyer")] == [200 * 10 ** precision] * 2
        for entry in adjustment["entries"]:
            assert entry["snapshot"]["entry"]["currency_code"] == currency
            assert entry["snapshot"]["entry"]["currency_precision"] == precision
        operations = {"source": lambda: repository.get_source(source["id"], actor=actor),
            "plan": lambda: repository.get_plan(adjustment["id"], actor=actor),
            "evidence": lambda: repository.evidence(adjustment["id"], actor=actor),
            "report": lambda: repository.report(source["id"], actor=actor)}
        capped = {name: operations[name] for name in ("plan", "evidence")}
        before = {name: b"".join(evidence_chunks(invoke())) for name, invoke in operations.items()}
        native_before = backing_digest(connection, rt.base.tenant)
        original = {"schema_version": "intercompany-fx-original-cycle-proof-v2", "performance_measurement": False,
            "native_role": dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()),
            "stages": [repository.evidence(stage["id"], actor=actor) for stage in stages], "report": operations["report"]()}
        original_fraction_proof(original, tmp_path)
        seen = []
        def cap(maximum: str):
            def evaluate(principal: Any, **context: Any) -> Any:
                seen.append(context)
                return evaluate_principal_access(principal,
                    maximum_amount=Decimal(maximum) if context["required_permission"] == permission else None, **context)
            return evaluate
        with monkeypatch.context() as patch:
            patch.setattr(authority, "evaluate_principal_access", cap("200"))
            for name, invoke in capped.items():
                assert b"".join(evidence_chunks(invoke())) == before[name]
        reporting_admitted_entities = {context["entity_id"] for context in seen
            if context.get("amount") == Decimal("200") and context["required_permission"] == permission}
        # The initial source has no adjustment amount. Existing CentralPolicy
        # refuses a maximum when that amount is absent; do not invent zero.
        with monkeypatch.context() as patch:
            patch.setattr(authority, "evaluate_principal_access", cap("200"))
            for name in ("source", "report"):
                with pytest.raises(FinancePostingError, match="denied"):
                    operations[name]()
        with monkeypatch.context() as patch:
            patch.setattr(authority, "evaluate_principal_access", cap("199"))
            for name, invoke in capped.items():
                with pytest.raises(FinancePostingError, match="denied") as refused:
                    invoke()
                assert "denied" in refused.value.code, name
        assert reporting_admitted_entities == {"seller", "buyer", rt.reporting_entity}
        assert {name: b"".join(evidence_chunks(invoke())) for name, invoke in operations.items()} == before
        assert backing_digest(connection, rt.base.tenant) == native_before
