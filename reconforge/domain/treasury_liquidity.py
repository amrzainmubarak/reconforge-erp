"""Deterministic treasury and cash liquidity forecasting engine.

Enforces zero-float financial arithmetic: all amounts are in integer minor units,
and scenario/risk adjustments use basis points (10,000 bps = 100.00%).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.fixed_assets import exact_minor

FlowDirection = Literal["inflow", "outflow"]
FlowSourceType = Literal["receivable", "payable", "payroll", "tax", "debt_service", "manual"]
FlowStatus = Literal["projected", "confirmed", "disputed", "settled"]
BucketFrequency = Literal["daily", "weekly", "monthly"]

BPS_DENOMINATOR = 10_000


def scale_by_bps(amount_minor: int, bps: int) -> int:
    """Scale an integer minor amount by basis points with deterministic half-up rounding."""
    if not (0 <= bps <= 100_000):  # allow up to 1000%
        raise FinancePostingError("treasury_bps_invalid", "Basis points must be between 0 and 100,000.")
    exact_minor(amount_minor, "amount_minor", zero=True)
    return (amount_minor * bps + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR


@dataclass(frozen=True)
class CashPosition:
    """Confirmed physical or cleared bank balance at an exact value date."""

    workspace_id: str
    organization_id: str
    legal_entity_id: str
    bank_account_id: str
    bank_name: str
    currency: str
    as_of_date: str  # ISO YYYY-MM-DD
    cleared_balance_minor: int
    minimum_covenant_minor: int = 0

    def __post_init__(self) -> None:
        text(self.workspace_id, "workspace_id", maximum=64)
        text(self.organization_id, "organization_id", maximum=64)
        text(self.legal_entity_id, "legal_entity_id", maximum=64)
        text(self.bank_account_id, "bank_account_id", maximum=64)
        text(self.currency, "currency", maximum=3)
        date.fromisoformat(self.as_of_date)
        exact_minor(self.cleared_balance_minor, "cleared_balance_minor", zero=True)
        exact_minor(self.minimum_covenant_minor, "minimum_covenant_minor", zero=True)


@dataclass(frozen=True)
class LiquidityFlow:
    """Expected or contractual cash inflow or outflow."""

    flow_id: str
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    direction: FlowDirection
    source_type: FlowSourceType
    source_reference: str
    currency: str
    due_date: str  # ISO YYYY-MM-DD
    amount_minor: int
    confidence_bps: int = 10_000  # Default 100.00%
    status: FlowStatus = "projected"

    def __post_init__(self) -> None:
        text(self.flow_id, "flow_id", maximum=64)
        text(self.workspace_id, "workspace_id", maximum=64)
        text(self.source_reference, "source_reference", maximum=128)
        text(self.currency, "currency", maximum=3)
        date.fromisoformat(self.due_date)
        exact_minor(self.amount_minor, "amount_minor")
        if not (0 <= self.confidence_bps <= BPS_DENOMINATOR):
            raise FinancePostingError("treasury_confidence_invalid", "Confidence bps must be 0..10,000.")


@dataclass(frozen=True)
class StressScenario:
    """Deterministic stress test parameters."""

    scenario_name: str
    ar_delay_days: int = 0  # Inflow delay
    ar_haircut_bps: int = 0  # Deduct from receivables inflow
    ap_acceleration_days: int = 0  # Outflow moved forward
    unplanned_outflow_minor: int = 0  # Contingency shock

    def __post_init__(self) -> None:
        text(self.scenario_name, "scenario_name", maximum=64)
        if self.ar_delay_days < 0 or self.ap_acceleration_days < 0:
            raise FinancePostingError("treasury_stress_invalid", "Delay/acceleration days cannot be negative.")
        if not (0 <= self.ar_haircut_bps <= BPS_DENOMINATOR):
            raise FinancePostingError("treasury_stress_invalid", "Haircut bps must be 0..10,000.")
        exact_minor(self.unplanned_outflow_minor, "unplanned_outflow_minor", zero=True)


@dataclass(frozen=True)
class LiquidityBucketResult:
    bucket_index: int
    start_date: str
    end_date: str
    opening_balance_minor: int
    contractual_inflow_minor: int
    weighted_inflow_minor: int
    contractual_outflow_minor: int
    weighted_outflow_minor: int
    net_change_minor: int
    closing_balance_minor: int
    covenant_breached: bool


class TreasuryLiquidityEngine:
    """Aggregates balances and flows to generate deterministic liquidity projections."""

    def __init__(self, initial_position: CashPosition) -> None:
        self.position = initial_position
        self.flows: list[LiquidityFlow] = []

    def add_flow(self, flow: LiquidityFlow) -> None:
        if flow.currency != self.position.currency:
            raise FinancePostingError(
                "treasury_currency_mismatch",
                f"Flow currency {flow.currency} does not match treasury position {self.position.currency}.",
            )
        if flow.workspace_id != self.position.workspace_id or flow.legal_entity_id != self.position.legal_entity_id:
            raise FinancePostingError(
                "treasury_scope_mismatch",
                "Flow workspace or entity does not match treasury position.",
            )
        self.flows.append(flow)

    def forecast(
        self,
        horizon_days: int = 30,
        bucket_days: int = 1,
        scenario: StressScenario | None = None,
    ) -> list[LiquidityBucketResult]:
        if horizon_days < 1 or horizon_days > 365:
            raise FinancePostingError("treasury_horizon_invalid", "Horizon must be between 1 and 365 days.")
        if bucket_days < 1 or bucket_days > 90:
            raise FinancePostingError("treasury_bucket_invalid", "Bucket days must be between 1 and 90 days.")

        start_d = date.fromisoformat(self.position.as_of_date)
        current_balance = self.position.cleared_balance_minor
        results: list[LiquidityBucketResult] = []

        total_buckets = (horizon_days + bucket_days - 1) // bucket_days

        for b_idx in range(total_buckets):
            b_start = start_d + timedelta(days=b_idx * bucket_days)
            b_end = min(b_start + timedelta(days=bucket_days - 1), start_d + timedelta(days=horizon_days - 1))

            contractual_in = 0
            weighted_in = 0
            contractual_out = 0
            weighted_out = 0

            for f in self.flows:
                if f.status in ("settled", "disputed"):
                    continue

                effective_date = date.fromisoformat(f.due_date)

                # Apply scenario stress if supplied
                if scenario:
                    if f.direction == "inflow" and f.source_type == "receivable":
                        effective_date += timedelta(days=scenario.ar_delay_days)
                    elif f.direction == "outflow" and f.source_type == "payable":
                        effective_date = max(start_d, effective_date - timedelta(days=scenario.ap_acceleration_days))

                # Check if flow falls inside current bucket
                if b_start <= effective_date <= b_end:
                    if f.direction == "inflow":
                        contractual_in += f.amount_minor
                        # Apply confidence and scenario haircut
                        effective_bps = f.confidence_bps
                        if scenario and f.source_type == "receivable":
                            effective_bps = scale_by_bps(effective_bps, BPS_DENOMINATOR - scenario.ar_haircut_bps)
                        weighted_in += scale_by_bps(f.amount_minor, effective_bps)
                    else:
                        contractual_out += f.amount_minor
                        weighted_out += scale_by_bps(f.amount_minor, f.confidence_bps)

            # Apply contingency shock on bucket 0 if scenario mandates
            if scenario and b_idx == 0 and scenario.unplanned_outflow_minor > 0:
                contractual_out += scenario.unplanned_outflow_minor
                weighted_out += scenario.unplanned_outflow_minor

            net_delta = weighted_in - weighted_out
            closing_balance = current_balance + net_delta
            covenant_breached = closing_balance < self.position.minimum_covenant_minor

            results.append(
                LiquidityBucketResult(
                    bucket_index=b_idx,
                    start_date=b_start.isoformat(),
                    end_date=b_end.isoformat(),
                    opening_balance_minor=current_balance,
                    contractual_inflow_minor=contractual_in,
                    weighted_inflow_minor=weighted_in,
                    contractual_outflow_minor=contractual_out,
                    weighted_outflow_minor=weighted_out,
                    net_change_minor=net_delta,
                    closing_balance_minor=closing_balance,
                    covenant_breached=covenant_breached,
                )
            )

            current_balance = closing_balance

        return results
