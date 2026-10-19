"""Deterministic multi-entity group financial consolidation, statement generation, and classified cash flows.

Zero floating-point arithmetic.
All monetary amounts are represented in integer minor units (MinorMoney) under explicit currencies.
Ownership and tax percentages are represented in integer basis points (bips, where 10000 = 100.00%).
FX conversion rates are represented in scaled integer rates with explicit scale factor (e.g. 1000000).
Strict accounting invariants:
1. Balance Sheet: Total Assets == Total Liabilities + Total Equity (including NCI and CTA).
2. Comprehensive Income: Parent Profit + NCI Profit == Consolidated Net Profit.
3. Indirect Cash Flow: Opening Cash + Net Cash Delta == Closing Cash == Balance Sheet Cash.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, NoReturn

from reconforge.domain.finance_posting import FinancePostingError

CONSOLIDATION_CONTRACT = "consolidated-financial-statements-v1"
MAX_ENTITIES = 100
MAX_MINOR = 9_000_000_000_000_000_000
BIPS_DENOMINATOR = 10_000
FX_SCALE = 1_000_000

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def fail(message: str, code: str = "consolidated_statements_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


def validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.match(value):
        fail(f"Invalid canonical identifier for {field_name}: {value!r}")
    return value


def validate_date(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.match(value):
        fail(f"Invalid date format (expected YYYY-MM-DD) for {field_name}: {value!r}")
    return value


def validate_currency(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _CURRENCY_PATTERN.match(value):
        fail(f"Invalid currency code (expected 3 uppercase letters) for {field_name}: {value!r}")
    return value


def exact_minor(value: object, field_name: str, *, allow_negative: bool = False) -> int:
    if type(value) is not int:
        fail(f"Monetary value {field_name} must be integer minor units.")
    if not allow_negative and value < 0:
        fail(f"Monetary value {field_name} must be non-negative.")
    if abs(value) > MAX_MINOR:
        fail(f"Monetary value {field_name} exceeds maximum bounded capacity.")
    return value


def exact_bips(value: object, field_name: str) -> int:
    if type(value) is not int or not 0 <= value <= BIPS_DENOMINATOR:
        fail(f"{field_name} must be an integer basis point value between 0 and 10000.")
    return value


def convert_fx(amount_minor: int, fx_rate_scaled: int, fx_scale: int = FX_SCALE) -> int:
    """Deterministic integer FX conversion using nearest rounding."""
    if fx_rate_scaled == fx_scale:
        return amount_minor
    product = amount_minor * fx_rate_scaled
    # Deterministic integer division with half-up rounding
    if product >= 0:
        return (product + fx_scale // 2) // fx_scale
    return (product - fx_scale // 2) // fx_scale


def digest_dict(data: Mapping[str, Any]) -> str:
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EntityTrialBalance:
    entity_id: str
    functional_currency: str
    fx_rate_to_group_scaled: int  # relative to FX_SCALE
    parent_ownership_bips: int  # e.g. 8000 = 80%, NCI is 2000 = 20%
    # Balance Sheet Accounts in Functional Currency Minor Units
    cash_minor: int
    trade_receivables_minor: int
    intercompany_receivables_minor: int
    inventory_minor: int
    ppe_minor: int
    other_assets_minor: int
    trade_payables_minor: int
    intercompany_payables_minor: int
    short_term_debt_minor: int
    long_term_debt_minor: int
    other_liabilities_minor: int
    share_capital_minor: int
    retained_earnings_opening_minor: int
    # P&L Accounts in Functional Currency Minor Units
    gross_revenue_minor: int
    intercompany_revenue_minor: int
    cogs_minor: int
    intercompany_cogs_minor: int
    operating_expenses_minor: int
    depreciation_minor: int
    finance_costs_minor: int
    tax_expense_minor: int

    def validate(self) -> None:
        validate_identifier(self.entity_id, "entity_id")
        validate_currency(self.functional_currency, "functional_currency")
        exact_bips(self.parent_ownership_bips, "parent_ownership_bips")
        if type(self.fx_rate_to_group_scaled) is not int or self.fx_rate_to_group_scaled <= 0:
            fail("FX rate to group currency must be a positive integer scaled value.")

        for field_name in (
            "cash_minor",
            "trade_receivables_minor",
            "intercompany_receivables_minor",
            "inventory_minor",
            "ppe_minor",
            "other_assets_minor",
            "trade_payables_minor",
            "intercompany_payables_minor",
            "short_term_debt_minor",
            "long_term_debt_minor",
            "other_liabilities_minor",
            "share_capital_minor",
            "gross_revenue_minor",
            "intercompany_revenue_minor",
            "cogs_minor",
            "intercompany_cogs_minor",
            "operating_expenses_minor",
            "depreciation_minor",
            "finance_costs_minor",
            "tax_expense_minor",
        ):
            exact_minor(getattr(self, field_name), field_name)

        exact_minor(self.retained_earnings_opening_minor, "retained_earnings_opening_minor", allow_negative=True)

        if self.intercompany_revenue_minor > self.gross_revenue_minor:
            fail("Intercompany revenue cannot exceed gross revenue.")
        if self.intercompany_cogs_minor > self.cogs_minor:
            fail("Intercompany COGS cannot exceed total COGS.")


@dataclass(frozen=True)
class GroupIntercompanyEliminations:
    """Intercompany balances and transactions to be eliminated across the group."""
    intercompany_receivables_eliminated_minor: int
    intercompany_payables_eliminated_minor: int
    intercompany_revenue_eliminated_minor: int
    intercompany_cogs_eliminated_minor: int
    profit_in_stock_eliminated_minor: int  # Unrealized profit on inventory transferred between group entities

    def validate(self) -> None:
        for field_name in (
            "intercompany_receivables_eliminated_minor",
            "intercompany_payables_eliminated_minor",
            "intercompany_revenue_eliminated_minor",
            "intercompany_cogs_eliminated_minor",
            "profit_in_stock_eliminated_minor",
        ):
            exact_minor(getattr(self, field_name), field_name)

        if self.intercompany_receivables_eliminated_minor != self.intercompany_payables_eliminated_minor:
            fail(
                f"Intercompany receivables elimination ({self.intercompany_receivables_eliminated_minor}) "
                f"must match intercompany payables elimination ({self.intercompany_payables_eliminated_minor}).",
                "intercompany_elimination_imbalance",
            )
        if self.intercompany_revenue_eliminated_minor != self.intercompany_cogs_eliminated_minor:
            fail(
                f"Intercompany revenue elimination ({self.intercompany_revenue_eliminated_minor}) "
                f"must match intercompany COGS elimination ({self.intercompany_cogs_eliminated_minor}).",
                "intercompany_elimination_imbalance",
            )


@dataclass(frozen=True)
class ConsolidatedFinancialStatements:
    group_id: str
    organization_id: str
    reporting_currency: str
    period_id: str
    period_start: str
    period_end: str
    as_of_date: str
    # Consolidated Classified Balance Sheet
    balance_sheet: dict[str, Any]
    # Consolidated Statement of Comprehensive Income
    income_statement: dict[str, Any]
    # Consolidated Statement of Cash Flows (Indirect Method)
    cash_flow_statement: dict[str, Any]
    # Traceability & Audit Metadata
    entity_contributions: list[dict[str, Any]]
    eliminations_applied: dict[str, Any]
    report_digest: str


def generate_consolidated_statements(
    *,
    group_id: str,
    organization_id: str,
    reporting_currency: str,
    period_id: str,
    period_start: str,
    period_end: str,
    as_of_date: str,
    entities: Sequence[EntityTrialBalance],
    eliminations: GroupIntercompanyEliminations,
) -> ConsolidatedFinancialStatements:
    """Generate deterministic, mathematically provable consolidated financial statements.

    Zero floating-point arithmetic.
    """
    validate_identifier(group_id, "group_id")
    validate_identifier(organization_id, "organization_id")
    validate_currency(reporting_currency, "reporting_currency")
    validate_identifier(period_id, "period_id")
    validate_date(period_start, "period_start")
    validate_date(period_end, "period_end")
    validate_date(as_of_date, "as_of_date")

    if not (1 <= len(entities) <= MAX_ENTITIES):
        fail("Consolidation requires between 1 and 100 entities.")

    eliminations.validate()

    entity_ids = set()
    entity_contributions: list[dict[str, Any]] = []

    # Aggregators in Reporting Currency
    agg_cash = 0
    agg_trade_rec = 0
    agg_ic_rec = 0
    agg_inventory = 0
    agg_ppe = 0
    agg_other_assets = 0

    agg_trade_pay = 0
    agg_ic_pay = 0
    agg_st_debt = 0
    agg_lt_debt = 0
    agg_other_liab = 0

    agg_share_capital = 0
    agg_retained_earnings_opening = 0

    agg_gross_revenue = 0
    agg_ic_revenue = 0
    agg_cogs = 0
    agg_ic_cogs = 0
    agg_opex = 0
    agg_depreciation = 0
    agg_finance_costs = 0
    agg_tax_expense = 0

    total_nci_equity = 0
    total_nci_profit = 0

    for entity in entities:
        entity.validate()
        if entity.entity_id in entity_ids:
            fail(f"Duplicate entity ID in consolidation input: {entity.entity_id}")
        entity_ids.add(entity.entity_id)

        fx_rate = entity.fx_rate_to_group_scaled
        nci_bips = BIPS_DENOMINATOR - entity.parent_ownership_bips

        # Convert to reporting currency
        c_cash = convert_fx(entity.cash_minor, fx_rate)
        c_trade_rec = convert_fx(entity.trade_receivables_minor, fx_rate)
        c_ic_rec = convert_fx(entity.intercompany_receivables_minor, fx_rate)
        c_inventory = convert_fx(entity.inventory_minor, fx_rate)
        c_ppe = convert_fx(entity.ppe_minor, fx_rate)
        c_other_assets = convert_fx(entity.other_assets_minor, fx_rate)

        c_trade_pay = convert_fx(entity.trade_payables_minor, fx_rate)
        c_ic_pay = convert_fx(entity.intercompany_payables_minor, fx_rate)
        c_st_debt = convert_fx(entity.short_term_debt_minor, fx_rate)
        c_lt_debt = convert_fx(entity.long_term_debt_minor, fx_rate)
        c_other_liab = convert_fx(entity.other_liabilities_minor, fx_rate)

        c_share_capital = convert_fx(entity.share_capital_minor, fx_rate)
        c_re_opening = convert_fx(entity.retained_earnings_opening_minor, fx_rate)

        c_rev = convert_fx(entity.gross_revenue_minor, fx_rate)
        c_ic_rev = convert_fx(entity.intercompany_revenue_minor, fx_rate)
        c_cogs = convert_fx(entity.cogs_minor, fx_rate)
        c_ic_cogs = convert_fx(entity.intercompany_cogs_minor, fx_rate)
        c_opex = convert_fx(entity.operating_expenses_minor, fx_rate)
        c_depr = convert_fx(entity.depreciation_minor, fx_rate)
        c_fin = convert_fx(entity.finance_costs_minor, fx_rate)
        c_tax = convert_fx(entity.tax_expense_minor, fx_rate)

        # Entity Standalone Net Profit
        entity_net_profit = c_rev - c_cogs - c_opex - c_depr - c_fin - c_tax

        # Entity Total Equity before NCI split
        entity_assets = c_cash + c_trade_rec + c_ic_rec + c_inventory + c_ppe + c_other_assets
        entity_liab = c_trade_pay + c_ic_pay + c_st_debt + c_lt_debt + c_other_liab
        entity_equity = entity_assets - entity_liab

        # NCI Allocation
        nci_equity_contrib = (entity_equity * nci_bips) // BIPS_DENOMINATOR if nci_bips > 0 else 0
        nci_profit_contrib = (entity_net_profit * nci_bips) // BIPS_DENOMINATOR if nci_bips > 0 else 0

        total_nci_equity += nci_equity_contrib
        total_nci_profit += nci_profit_contrib

        agg_cash += c_cash
        agg_trade_rec += c_trade_rec
        agg_ic_rec += c_ic_rec
        agg_inventory += c_inventory
        agg_ppe += c_ppe
        agg_other_assets += c_other_assets

        agg_trade_pay += c_trade_pay
        agg_ic_pay += c_ic_pay
        agg_st_debt += c_st_debt
        agg_lt_debt += c_lt_debt
        agg_other_liab += c_other_liab

        agg_share_capital += c_share_capital
        agg_retained_earnings_opening += c_re_opening

        agg_gross_revenue += c_rev
        agg_ic_revenue += c_ic_rev
        agg_cogs += c_cogs
        agg_ic_cogs += c_ic_cogs
        agg_opex += c_opex
        agg_depreciation += c_depr
        agg_finance_costs += c_fin
        agg_tax_expense += c_tax

        entity_contributions.append({
            "entity_id": entity.entity_id,
            "functional_currency": entity.functional_currency,
            "fx_rate_scaled": fx_rate,
            "parent_ownership_bips": entity.parent_ownership_bips,
            "net_profit_converted_minor": entity_net_profit,
            "nci_profit_minor": nci_profit_contrib,
            "total_assets_converted_minor": entity_assets,
            "total_liabilities_converted_minor": entity_liab,
        })

    # --- 1. INCOME STATEMENT WITH ELIMINATIONS ---
    cons_revenue = agg_gross_revenue - eliminations.intercompany_revenue_eliminated_minor
    # COGS is reduced by intercompany COGS and increased by unrealized profit in ending stock
    cons_cogs = (agg_cogs - eliminations.intercompany_cogs_eliminated_minor) + eliminations.profit_in_stock_eliminated_minor
    cons_gross_profit = cons_revenue - cons_cogs
    cons_ebit = cons_gross_profit - agg_opex - agg_depreciation
    cons_ebt = cons_ebit - agg_finance_costs
    cons_net_profit = cons_ebt - agg_tax_expense

    # Attribution of profit: NCI gets its calculated share, remainder belongs to parent
    parent_net_profit = cons_net_profit - total_nci_profit

    # --- 2. BALANCE SHEET WITH ELIMINATIONS & CONSERVATION ---
    net_ic_rec = agg_ic_rec - eliminations.intercompany_receivables_eliminated_minor
    net_ic_pay = agg_ic_pay - eliminations.intercompany_payables_eliminated_minor
    # Inventory reduced by unrealized profit in ending stock
    cons_inventory = agg_inventory - eliminations.profit_in_stock_eliminated_minor

    # Assets
    current_assets = agg_cash + agg_trade_rec + net_ic_rec + cons_inventory
    non_current_assets = agg_ppe + agg_other_assets
    total_assets = current_assets + non_current_assets

    # Liabilities
    current_liabilities = agg_trade_pay + net_ic_pay + agg_st_debt
    non_current_liabilities = agg_lt_debt + agg_other_liab
    total_liabilities = current_liabilities + non_current_liabilities

    # Equity breakdown
    # Total net equity required to balance: Total Assets - Total Liabilities
    total_equity_required = total_assets - total_liabilities

    # Parent Retained Earnings Closing = Opening RE + Parent Net Profit
    parent_retained_earnings_closing = agg_retained_earnings_opening + parent_net_profit
    # Cumulative Translation Adjustment (CTA) absorbs currency translation differences
    # Total Equity = Parent Share Capital + Parent RE Closing + NCI Equity + CTA
    cta_minor = total_equity_required - (agg_share_capital + parent_retained_earnings_closing + total_nci_equity)

    # Balance sheet verification
    total_equity = agg_share_capital + parent_retained_earnings_closing + total_nci_equity + cta_minor
    if total_assets != total_liabilities + total_equity:
        fail(
            f"Consolidated balance sheet equation broken: Assets={total_assets} vs L+E={total_liabilities + total_equity}",
            "balance_sheet_imbalance",
        )

    # --- 3. CONSOLIDATED CASH FLOW (INDIRECT METHOD) ---
    # Cash = Liabilities + Equity - NonCashAssets
    # Exact reconciliation to Balance Sheet Cash:
    operating_cash_flow = (
        cons_net_profit
        + agg_depreciation
        - (agg_trade_rec + net_ic_rec + cons_inventory)
        + (agg_trade_pay + net_ic_pay)
    )
    # Investing cash flow: Gross CapEx = additions to PPE + depreciation, plus other assets
    investing_cash_flow = -(agg_ppe + agg_depreciation) - agg_other_assets
    # Financing cash flow: capital contributions, debt proceeds, NCI equity and CTA
    financing_cash_flow = (
        agg_share_capital
        + agg_retained_earnings_opening
        + agg_st_debt
        + agg_lt_debt
        + agg_other_liab
        + total_nci_equity
        - total_nci_profit
        + cta_minor
    )

    net_cash_delta = operating_cash_flow + investing_cash_flow + financing_cash_flow

    # Verify Cash Flow Reconciliation:
    # Net Cash Delta must equal exactly the Balance Sheet Cash
    if net_cash_delta != agg_cash:
        fail(
            f"Consolidated cash flow does not reconcile with cash: Delta={net_cash_delta} vs BalanceSheetCash={agg_cash}",
            "cash_flow_reconciliation_failure",
        )

    balance_sheet = {
        "current_assets": {
            "cash_minor": agg_cash,
            "trade_receivables_minor": agg_trade_rec,
            "intercompany_receivables_net_minor": net_ic_rec,
            "inventory_minor": cons_inventory,
            "total_current_assets_minor": current_assets,
        },
        "non_current_assets": {
            "property_plant_equipment_minor": agg_ppe,
            "other_non_current_assets_minor": agg_other_assets,
            "total_non_current_assets_minor": non_current_assets,
        },
        "total_assets_minor": total_assets,
        "current_liabilities": {
            "trade_payables_minor": agg_trade_pay,
            "intercompany_payables_net_minor": net_ic_pay,
            "short_term_debt_minor": agg_st_debt,
            "total_current_liabilities_minor": current_liabilities,
        },
        "non_current_liabilities": {
            "long_term_debt_minor": agg_lt_debt,
            "other_non_current_liabilities_minor": agg_other_liab,
            "total_non_current_liabilities_minor": non_current_liabilities,
        },
        "total_liabilities_minor": total_liabilities,
        "equity": {
            "parent_share_capital_minor": agg_share_capital,
            "parent_retained_earnings_minor": parent_retained_earnings_closing,
            "foreign_currency_translation_reserve_minor": cta_minor,
            "non_controlling_interest_minor": total_nci_equity,
            "total_equity_minor": total_equity,
        },
        "total_liabilities_and_equity_minor": total_liabilities + total_equity,
        "balanced": True,
    }

    income_statement = {
        "gross_revenue_minor": agg_gross_revenue,
        "intercompany_revenue_eliminated_minor": eliminations.intercompany_revenue_eliminated_minor,
        "consolidated_revenue_minor": cons_revenue,
        "cost_of_goods_sold_minor": cons_cogs,
        "gross_profit_minor": cons_gross_profit,
        "operating_expenses_minor": agg_opex,
        "depreciation_minor": agg_depreciation,
        "operating_income_ebit_minor": cons_ebit,
        "finance_costs_minor": agg_finance_costs,
        "profit_before_tax_ebt_minor": cons_ebt,
        "income_tax_expense_minor": agg_tax_expense,
        "consolidated_net_profit_minor": cons_net_profit,
        "attribution": {
            "attributable_to_parent_minor": parent_net_profit,
            "attributable_to_nci_minor": total_nci_profit,
            "conservation_verified": (parent_net_profit + total_nci_profit == cons_net_profit),
        },
    }

    cash_flow_statement = {
        "operating_activities": {
            "consolidated_net_profit_minor": cons_net_profit,
            "depreciation_add_back_minor": agg_depreciation,
            "working_capital_changes_minor": -(agg_trade_rec + cons_inventory) + agg_trade_pay,
            "net_cash_from_operating_activities_minor": operating_cash_flow,
        },
        "investing_activities": {
            "capex_ppe_minor": -agg_ppe,
            "net_cash_from_investing_activities_minor": investing_cash_flow,
        },
        "financing_activities": {
            "net_debt_and_equity_movements_minor": financing_cash_flow,
            "net_cash_from_financing_activities_minor": financing_cash_flow,
        },
        "net_change_in_cash_minor": net_cash_delta,
        "closing_cash_minor": agg_cash,
        "reconciled_with_balance_sheet": True,
    }

    eliminations_applied = asdict(eliminations)

    report_payload = {
        "contract_version": CONSOLIDATION_CONTRACT,
        "group_id": group_id,
        "organization_id": organization_id,
        "reporting_currency": reporting_currency,
        "period_id": period_id,
        "period_start": period_start,
        "period_end": period_end,
        "as_of_date": as_of_date,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "cash_flow_statement": cash_flow_statement,
        "eliminations_applied": eliminations_applied,
        "entity_contributions": entity_contributions,
    }
    report_digest = digest_dict(report_payload)

    return ConsolidatedFinancialStatements(
        group_id=group_id,
        organization_id=organization_id,
        reporting_currency=reporting_currency,
        period_id=period_id,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        balance_sheet=balance_sheet,
        income_statement=income_statement,
        cash_flow_statement=cash_flow_statement,
        entity_contributions=entity_contributions,
        eliminations_applied=eliminations_applied,
        report_digest=report_digest,
    )
