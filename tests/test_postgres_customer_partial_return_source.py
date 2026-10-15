"""Real scoped PostgreSQL source-to-Domain mapping, with no CR2 posting claim."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.customer_partial_return_posting import (
    PartialReturnAccountRoles,
    PartialReturnPostingIntent,
    build_partial_return_posting_contract,
)
from reconforge.domain.customer_partial_returns import PartialReturnHistory, prepare_partial_return
from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from reconforge.domain.inventory_receipt_posting import artifacts_for, source_plan_id
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from reconforge.infrastructure.postgres_customer_partial_return_source import map_customer_partial_return_source
from reconforge.infrastructure.postgres_customer_returns import PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from tests.test_postgres_commercial_collections import complete, prepare
from tests.test_postgres_customer_returns import configure_runtime, create_runtime, retained_state
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database, request
from tests.test_postgres_stock_sales import complete_stock_sale, create_reserved_order, create_stock_runtime, execute

_ = receipt_database


class ReadOnlyWitness:
    """Observe every mapper statement on the actual normal-role connection."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.count = 0

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        assert statement.lstrip().upper().startswith("SELECT ")
        self.count += 1
        return self.connection.execute(statement, parameters)


def authorized(connection: Any, runtime: ReceiptRuntime, source_id: str, actor: Any) -> dict[str, Any]:
    owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
    original = owner._source(source_id, lock=False)
    owner._actor(actor, "read", {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
        "source_snapshot": original, "currency_code": original["invoice"]["currency_code"],
        "currency_precision": original["invoice"]["currency_precision"], "amount_minor": original["stock"]["total_minor"]})
    return owner._source(source_id)  # Existing owner supplies its normal customer/invoice/stock locks.


def create_two_layer_source(receipt_database: tuple[str, str]) -> tuple[ReceiptRuntime, str, str]:
    """Create the genuine reviewed two-layer sale for native and HTTPS callers."""
    runtime = create_stock_runtime(receipt_database)
    configure_runtime(runtime)
    with runtime.actor("maker") as (connection, _, _actor):
        first = connection.execute("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["id"]
    scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    # Use ordinary real receipt identities, choosing a bounded name which makes
    # UUID/string sorting reverse the actual earlier/later reviewed FIFO order.
    names = [f"SECOND-LAYER-{index}" for index in range(256)]
    second_name = next(name for name in names if str(artifacts_for(source_plan_id(scope, name), "Receipt", None)["cost_layer_id"]) < first)
    with runtime.actor("maker") as (_, owner, actor):
        plan = owner.prepare_receipt(replace(request(second_name), posting_date="2026-10-04", total_value_minor=20000),
                                     command_id="second-prepare", actor=actor)
    with runtime.actor("checker") as (_, owner, actor):
        review = owner.review(plan["plan_id"], command_id="second-review", expected_plan_digest=plan["plan_digest"],
                             reason="Independent second actual FIFO layer", actor=actor)
    with runtime.actor("poster") as (_, owner, actor):
        owner.commit(plan["plan_id"], command_id="second-post", expected_review_digest=review["review_digest"],
                     reason="Publish second actual layer", actor=actor)
    sale = create_reserved_order(runtime, "TWO-LAYER-ORIGINAL", "15")
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    sale = execute(runtime, sale, "review-issue", "checker")
    sale = execute(runtime, sale, "deliver", "poster")
    args = SalesInvoicePreparation("TWO-LAYER-INVOICE", "2026-10-09", "2026-10-31", "SALES", "period", "AR", "REVENUE", "Original two-layer sale").payload()
    args.pop("reason")
    sale = execute(runtime, sale, "prepare-invoice", "maker", args)
    sale = execute(runtime, sale, "review-invoice", "checker")
    sale = execute(runtime, sale, "invoice", "poster")
    complete(runtime, prepare(runtime, sale["invoice_id"], 10000, "TWO-LAYER"), "TWO-LAYER")
    return runtime, sale["id"], sale["invoice_id"]


@pytest.fixture(scope="module")
def two_layer_source(receipt_database: tuple[str, str]) -> tuple[ReceiptRuntime, str, str]:
    return create_two_layer_source(receipt_database)


def test_real_two_layer_issue_order_becomes_typed_source_and_exact_unposted_corrections_without_any_row_change(
    two_layer_source: tuple[ReceiptRuntime, str, str],
) -> None:
    runtime, source_id, invoice_id = two_layer_source
    before = retained_state(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        original = authorized(connection, runtime, source_id, actor)
        original_json = canonical_json(original)
        witness = ReadOnlyWitness(connection)
        mapped = map_customer_partial_return_source(witness, runtime.tenant, original)
        assert witness.count > 0
        source = mapped.source
        actual_order = [row["cost_layer_id"] for row in original["stock"]["issue_plan"]["allocations"]]
        assert actual_order != sorted(actual_order)
        assert [row.cost_layer_id for row in source.consumptions] == actual_order
        assert [(row.quantity_scaled, row.value_minor) for row in source.consumptions] == [(10, 12000), (5, 10000)]
        assert (source.source_order_id, source.invoice_id, source.quantity_scaled, source.gross_minor, source.collected_minor) == (
            source_id, invoice_id, 15, 67500, 10000)
        assert source.tax_minor == 0 and source.inventory_lot_id is None and source.serial_tracked is False
        assert source.currency_policy.precision == 2 and source.functional_currency == "USD"
        selected = prepare_partial_return(PartialReturnHistory(source), 12)
        assert Fraction(selected.credit_minor) == Fraction(67500 * 12, 15) == 54000
        assert Fraction(selected.cogs_restored_minor) == Fraction(12000) + Fraction(10000 * 2, 5) == 16000
        ar, revenue = source.original_revenue.snapshot()["lines"]
        cogs, inventory = source.original_cogs.snapshot()["lines"]
        refund = connection.execute("SELECT id FROM reconforge.finance_accounts WHERE tenant_id=%s AND account_code='REFUND'",
                                    (runtime.tenant,)).fetchone()["id"]
        roles = PartialReturnAccountRoles(source.scope, source.fingerprint, source.currency_policy,
            ar["account_id"], revenue["account_id"], inventory["account_id"], cogs["account_id"], refund, "Liability")
        proposal = build_partial_return_posting_contract(selected, roles=roles,
            intent=PartialReturnPostingIntent("period", "2026-10-14", "Unposted original native portion"))
        assert proposal.payload()["postable"] is False
        assert proposal.cost_restoration.payload()["lines"][0]["debit_minor"] == 16000
        assert canonical_json(original) == original_json
        observations = mapped.collection_evidence()
        assert len(observations) == 1 and observations[0]["allocation"]["amount_minor"] == 10000
        assert observations[0]["owner_kind"] == "Commercial"
        observations[0]["allocation"]["amount_minor"] = 1
        assert mapped.collection_evidence()[0]["allocation"]["amount_minor"] == 10000
    assert retained_state(runtime) == before


def test_caller_membership_source_swaps_and_boolean_money_are_not_native_evidence(
    two_layer_source: tuple[ReceiptRuntime, str, str],
) -> None:
    runtime, source_id, _invoice_id = two_layer_source
    before = retained_state(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        original = authorized(connection, runtime, source_id, actor)
        for change in ("missing", "extra", "receipt_sum", "effect", "consumption", "allocation_order", "tax", "invoice"):
            forged = deepcopy(original)
            if change == "missing":
                forged.pop("cogs")
            elif change == "extra":
                forged["caller_approval"] = True
            elif change == "receipt_sum":
                forged["allocated_minor"] = True
            elif change == "effect":
                forged["revenue"]["id"] = forged["cogs"]["id"]
            elif change == "consumption":
                forged["consumptions"].append(deepcopy(forged["consumptions"][0]))
            elif change == "allocation_order":
                forged["stock"]["issue_plan"]["allocations"].reverse()
            elif change == "tax":
                forged["invoice"]["tax_minor"] = None
            else:
                forged["stock"]["invoice_id"] = "ANOTHER-INVOICE"
            with pytest.raises(FinancePostingError) as refusal:
                map_customer_partial_return_source(connection, runtime.tenant, forged)
            assert refusal.value.code == "customer_partial_return_source_invalid"
        with pytest.raises(FinancePostingError):
            map_customer_partial_return_source(connection, "OTHER-TENANT", original)
    assert retained_state(runtime) == before


def test_retained_registry_context_is_used_without_installing_or_recapturing_current_policy(
    two_layer_source: tuple[ReceiptRuntime, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    from reconforge.utils.money import CurrencyRegistryContext

    runtime, source_id, _invoice_id = two_layer_source
    before = retained_state(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        original = authorized(connection, runtime, source_id, actor)
        expected = map_customer_partial_return_source(connection, runtime.tenant, original)
        # Legitimate direct SQL cannot mutate historical currency precision.
        # This proves refusal, not execution after a changed economic master.
        with pytest.raises(psycopg.errors.RaiseException) as refusal, connection.transaction():
            connection.execute("UPDATE reconforge.currencies SET minor_units=3 WHERE tenant_id=%s AND code='USD'", (runtime.tenant,))
        assert refusal.value.sqlstate == "P0001"
        assert "Currency code and precision are immutable" in str(refusal.value)
        def no_installed_context(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("The original mapper must use the captured snapshot")
        monkeypatch.setattr(CurrencyRegistryContext, "from_installed", no_installed_context)
        actual = map_customer_partial_return_source(connection, runtime.tenant, original)
        assert actual.source.fingerprint == expected.source.fingerprint
        assert actual.source.registry_context.registry_manifest.digest == original["cogs"]["currency_registry_digest"]
    assert retained_state(runtime) == before


@pytest.mark.parametrize("full_stock_owner", [False, True], ids=["full-commercial", "full-stock"])
def test_fully_paid_real_source_preserves_original_cash_owner_membership(
    receipt_database: tuple[str, str], full_stock_owner: bool,
) -> None:
    if full_stock_owner:
        runtime = create_stock_runtime(receipt_database)
        configure_runtime(runtime)
        source_id = complete_stock_sale(runtime)["id"]  # Actual standalone owner; never bypass a Commerce tranche.
    else:
        runtime, source_id, _invoice_id = create_runtime(receipt_database, 45000)
    before = retained_state(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        mapped = map_customer_partial_return_source(connection, runtime.tenant, authorized(connection, runtime, source_id, actor))
        expected_gross_minor = 22500 if full_stock_owner else 45000
        assert mapped.source.gross_minor == mapped.source.collected_minor == expected_gross_minor
        assert mapped.collection_evidence()[0]["owner_kind"] == ("Stock" if full_stock_owner else "Commercial")
        portion = prepare_partial_return(PartialReturnHistory(mapped.source), 1)
        assert (portion.credit_minor, portion.receivable_released_minor, portion.refund_entitlement_delta_minor) == (4500, 0, 4500)
    assert retained_state(runtime) == before


def test_real_differing_owned_cash_accounts_are_a_finite_refund_scope_refusal(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, invoice_id = create_runtime(receipt_database, 10000)
    # Use the existing normal-role, tenant-only reference fixture seed path.
    # Chart-wide master creation is not admitted through an entity-scoped actor.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        PostgresFinanceCoreRepository(connection, runtime.tenant).upsert_account(account_code="CASH2", name="Second original cash",
            account_type="Asset", normal_balance="Debit", workspace="work")
    with runtime.actor("maker") as (connection, _, actor):
        plan = PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(CommercialCollectionPreparation(
            workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY",
            source_id=invoice_id, journal_code="CASH", period_id="period", posting_date="2026-10-10", debit_account_code="CASH2",
            credit_account_code="AR", reason="Distinct real original cash account", amount_minor=1000,
            receipt_number="SECOND-OWNED-CASH"), command_id="second-cash-prepare", actor=actor)
    complete(runtime, plan, "SECOND-CASH")
    before = retained_state(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        with pytest.raises(FinancePostingError) as refusal:
            map_customer_partial_return_source(connection, runtime.tenant, authorized(connection, runtime, source_id, actor))
        assert refusal.value.code == "customer_partial_return_source_invalid"
    assert retained_state(runtime) == before
