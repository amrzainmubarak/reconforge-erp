"""Bounded-memory exact fold of immutable native posting evidence.

The evidence lives in a durable ordered membership set. Summary memory depends
on the reviewed chart, rather than the number of posting effects or lines.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_balances import POLICY_FIELDS, balance_window
from reconforge.domain.finance_posting import digest_payload, validation_digest
from reconforge.domain.financial_reporting import SECTIONS, fail, validate_mapping_accounts

SNAPSHOT_CONTRACT = "financial-reporting-snapshot-v1"
EVIDENCE_CHAIN_SEED = digest_payload([SNAPSHOT_CONTRACT, "ordered-native-evidence"])
MAX_EVIDENCE_PAGE = 200


def chain_link(previous: str, ordinal: int, effect_id: str, validation: str) -> str:
    return digest_payload([previous, ordinal, effect_id, validation])


def amounts(debit: int, credit: int) -> dict[str, int]:
    difference = debit - credit
    return {
        "debit_minor": debit, "credit_minor": credit, "balance_minor": difference,
        "debit_balance_minor": max(difference, 0), "credit_balance_minor": max(-difference, 0),
    }


class StreamingFinancialReport:
    """One-pass fold; no retained posting list, source IDs set or floating money."""

    def __init__(self, mapping: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
        validate_mapping_accounts(mapping["accounts"])
        self.mapping, self.metadata = mapping, dict(metadata)
        self.start, _, self.cutoff = balance_window(
            metadata["period_start"], metadata["period_end"], metadata["as_of_date"]
        )
        self.classified = {row["account_id"]: row for row in mapping["accounts"]}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.policy: dict[str, Any] | None = None
        self.counts = {"opening": 0, "activity": 0}
        self.line_count = self.cash_count = self.inflow = self.outflow = 0
        self.previous_id = ""
        self.chain = EVIDENCE_CHAIN_SEED

    def consume(self, effect: Mapping[str, Any]) -> tuple[int, str, str]:
        snapshot, identifier = effect["snapshot"], effect["id"]
        header = snapshot["entry"]
        if (
            identifier <= self.previous_id or effect["entry_id"] != header["id"]
            or effect["validation_digest"] != validation_digest(snapshot)
            or any(effect[key] != self.mapping[key] or header[key] != self.mapping[key]
                   for key in ("workspace_id", "organization_id", "legal_entity_id"))
        ):
            fail("Streamed native posting evidence has duplicate, unordered or foreign source.", "financial_reporting_integrity_invalid")
        day = header["posting_date"]
        phase = "opening" if day < self.start else "activity"
        if day > self.cutoff or (phase == "activity" and header["period_id"] != self.metadata["period_id"]):
            fail("Streamed native evidence exceeds or overlaps the selected period.", "posting_period_ambiguous")
        policy = {key: effect[key] for key in POLICY_FIELDS}
        if any(header[key] != policy[key] for key in POLICY_FIELDS) or (self.policy is not None and self.policy != policy):
            fail("Streamed statements require one retained currency policy.", "posting_policy_mismatch")
        debit = credit = cash = 0
        for line in snapshot["lines"]:
            dr, cr = line["debit_minor"], line["credit_minor"]
            if type(dr) is not int or type(cr) is not int or min(dr, cr) < 0 or (dr == 0) == (cr == 0):
                fail("Native posting lines require exact positive minor units.", "financial_reporting_integrity_invalid")
            master = self.classified.get(line["account_id"])
            if master is None:
                fail("Every streamed account requires explicit reviewed classification.", "financial_reporting_unmapped")
            account = self.accounts.setdefault(line["account_id"], {
                **master, "opening": amounts(0, 0), "activity": amounts(0, 0), "line_count": 0,
            })
            current = account[phase]
            account[phase] = amounts(current["debit_minor"] + dr, current["credit_minor"] + cr)
            account["line_count"] += 1
            debit += dr
            credit += cr
            if master["is_cash"]:
                cash += dr - cr
        if not snapshot["lines"] or debit != credit:
            fail("Streamed native effects must balance exactly.", "financial_reporting_integrity_invalid")
        self.policy = policy
        self.counts[phase] += 1
        self.line_count += len(snapshot["lines"])
        if phase == "activity" and any(self.classified[line["account_id"]]["is_cash"] for line in snapshot["lines"]):
            self.cash_count += 1
            self.inflow += max(cash, 0)
            self.outflow += max(-cash, 0)
        ordinal, previous = sum(self.counts.values()), self.chain
        self.chain = chain_link(previous, ordinal, identifier, effect["validation_digest"])
        self.previous_id = identifier
        return ordinal, previous, self.chain

    def finish(self) -> dict[str, Any]:
        sections = {key: {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0} for key in SECTIONS}
        cash = {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0,
                "inflow_minor": self.inflow, "outflow_minor": self.outflow, "movement_count": self.cash_count}
        accounts = sorted(self.accounts.values(), key=lambda row: row["account_id"])
        for account in accounts:
            account["closing"] = amounts(account["opening"]["debit_minor"] + account["activity"]["debit_minor"],
                                         account["opening"]["credit_minor"] + account["activity"]["credit_minor"])
            sign = 1 if account["account_type"] in {"Asset", "Expense"} else -1
            for phase in ("opening", "activity", "closing"):
                sections[account["section"]][phase + "_minor"] += sign * account[phase]["balance_minor"]
                if account["is_cash"]:
                    cash[phase + "_minor"] += account[phase]["balance_minor"]
        totals: dict[str, Any] = {}
        for phase in ("opening", "activity", "closing"):
            dr, cr, net_dr, net_cr = (sum(row[phase][field] for row in accounts) for field in
                                    ("debit_minor", "credit_minor", "debit_balance_minor", "credit_balance_minor"))
            if dr != cr or net_dr != net_cr:
                fail("Streamed report turnover and balances must balance exactly.", "financial_reporting_integrity_invalid")
            totals[phase] = {"effect_count": sum(self.counts.values()) if phase == "closing" else self.counts[phase],
                             "turnover_totals": {"debit_minor": dr, "credit_minor": cr, "balanced": True},
                             "balance_totals": {"debit_minor": net_dr, "credit_minor": net_cr, "balanced": True}}
        assets = sections["CurrentAsset"]["closing_minor"] + sections["NonCurrentAsset"]["closing_minor"]
        liabilities = sections["CurrentLiability"]["closing_minor"] + sections["NonCurrentLiability"]["closing_minor"]
        equity = sections["Equity"]["closing_minor"]
        result = sections["Income"]["closing_minor"] - sections["Expense"]["closing_minor"]
        if assets != liabilities + equity + result or cash["activity_minor"] != self.inflow - self.outflow:
            fail("Streamed financial statement equations differ.", "financial_reporting_integrity_invalid")
        payload = {
            "contract_version": SNAPSHOT_CONTRACT, "balance_scope": "immutable-captured-native-postings",
            **self.metadata, "map_id": self.mapping["id"], "map_digest": self.mapping["map_digest"],
            "currency_policy": self.policy, "effect_count": sum(self.counts.values()), "line_count": self.line_count,
            "evidence_digest": self.chain, "trial_balance": {"accounts": accounts, "totals": totals}, "sections": sections,
            "balance_sheet": {"assets_minor": assets, "liabilities_minor": liabilities, "equity_minor": equity,
                              "accumulated_unclosed_result_minor": result, "balanced": True},
            "income_statement": {"income_minor": sections["Income"]["activity_minor"], "expense_minor": sections["Expense"]["activity_minor"],
                                 "result_minor": sections["Income"]["activity_minor"] - sections["Expense"]["activity_minor"]},
            "cash_movements": cash,
        }
        return {**payload, "report_digest": digest_payload(payload)}
