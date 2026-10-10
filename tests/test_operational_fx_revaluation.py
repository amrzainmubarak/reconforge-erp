"""Independent rational closing-rate and complete inverse financial oracles."""

from decimal import localcontext

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.operational_fx_revaluation import revaluation_equation, reversal_equation
from reconforge.domain.operational_fx_tax import HistoricalRate, invoice_equation
from reconforge.infrastructure.postgres_operational_fx_revaluation_schema import CLOSE_SQL, ORIGINAL_CLOSE, UPGRADE_SQL
from reconforge.utils.money import CurrencyRegistryContext
from tests.test_operational_fx_tax import invoice, translated


@pytest.mark.parametrize(("foreign", "functional", "fp", "lp", "original", "closing"), [
    ("EUR", "USD", 2, 2, "1.25", "1.35"), ("EUR", "USD", 2, 2, "1.25", "1.15"),
    ("JPY", "KWD", 0, 3, "0.00205123", "0.00215123"), ("KWD", "JPY", 3, 0, "492.123456789012", "470.123456789012"),
])
def test_partial_outstanding_closing_valuation_and_inverse_match_independent_fractions(
    foreign: str, functional: str, fp: int, lp: int, original: str, closing: str,
) -> None:
    context = CurrencyRegistryContext.from_installed()
    source = invoice_equation(invoice(foreign=foreign, amount=10001, rate=original), functional, context)
    paid = 4000
    historical = translated(paid, original, fp, lp)
    with localcontext() as decimal_context:
        decimal_context.prec = 6
        equation = revaluation_equation(source, foreign_before_minor=paid, historical_before_minor=historical,
            closing_rate=HistoricalRate(closing, "Synthetic closing observation", "2026-10-11T23:00:00Z"), posting_date="2026-10-11",
            unrealized_gain_account_code="UGAIN", unrealized_loss_account_code="ULOSS", context=context)
    carrying = source["functional_gross_minor"] - historical
    valued = translated(source["foreign_gross_minor"] - paid, closing, fp, lp)
    difference = valued - carrying
    assert equation["historical_outstanding_minor"] == carrying and equation["valued_outstanding_minor"] == valued
    assert equation["unrealized_fx_minor"] == difference and equation["amount_minor"] == abs(difference)
    assert sum(line["debit_minor"] for line in equation["lines"]) == sum(line["credit_minor"] for line in equation["lines"]) == abs(difference)
    original_plan = {"id": "FX1-original", "kind": "revalue", "phase": 2, "posting_effect_id": "native-original",
                     "equation": equation, "plan_digest": digest_payload(equation)}
    reverse = reversal_equation(original_plan)
    assert reverse["unrealized_fx_minor"] == -difference and reverse["original_posting_effect_id"] == "native-original"
    assert reverse["original_equation_digest"] == digest_payload(equation)
    for first, second in zip(equation["lines"], reverse["lines"], strict=True):
        assert (first["account_code"], first["debit_minor"], first["credit_minor"]) == (second["account_code"], second["credit_minor"], second["debit_minor"])


@pytest.mark.parametrize("invalid", ["basis", "paid", "zero", "account", "timestamp"])
def test_revaluation_rejects_wrong_original_basis_zero_effect_and_ambiguous_roles(invalid: str) -> None:
    context = CurrencyRegistryContext.from_installed()
    source = invoice_equation(invoice(rate="1.25"), "USD", context)
    values = {"foreign_before_minor": 4000, "historical_before_minor": 5000,
              "closing_rate": HistoricalRate("1.35", "Synthetic", "2026-10-11T23:00:00Z"), "posting_date": "2026-10-11",
              "unrealized_gain_account_code": "UGAIN", "unrealized_loss_account_code": "ULOSS", "context": context}
    if invalid == "basis":
        values["historical_before_minor"] = 5001
    if invalid == "paid":
        values["foreign_before_minor"], values["historical_before_minor"] = source["foreign_gross_minor"], source["functional_gross_minor"]
    if invalid == "zero":
        values["closing_rate"] = HistoricalRate("1.25", "Synthetic", "2026-10-11T23:00:00Z")
    if invalid == "account":
        values["unrealized_gain_account_code"] = "REVENUE"
    if invalid == "timestamp":
        values["closing_rate"] = HistoricalRate("1.35", "Synthetic", "2026-10-12T23:00:00Z")
    with pytest.raises(FinancePostingError):
        revaluation_equation(source, **values)  # type: ignore[arg-type]


def test_additive_schema_preserves_native_snapshot_and_current_authority_closure() -> None:
    for clause in ("fx_policy(t,a->'foreign_policy')", "a->'tax_components'=components", "v->'snapshot'=jsonb_build_object",
                   "Every FX phase requires its immutable command acknowledgement", "l.posted_actor_id NOT IN (e.preparer_actor_id,r.reviewer_actor_id)"):
        assert clause in ORIGINAL_CLOSE and clause in CLOSE_SQL
    assert "SECURITY DEFINER" not in UPGRADE_SQL and "CREATE TRIGGER" not in UPGRADE_SQL
    assert "finance_core.reverse" in UPGRADE_SQL
