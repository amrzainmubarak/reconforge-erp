"""Source-qualified management cash flow from original IC2 Cash membership.

This view never posts journals. Historical and closing translation delegate to
the existing captured-policy FX conversion; no second currency engine exists.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from reconforge.domain.finance_policy import FinanceCurrencyPolicy, FinancePolicyError
from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.intercompany_fx import MAX_EFFECT_LINES, MAX_OPERATIONS, PARTIES, converted, minor, signed
from reconforge.utils.money import CurrencyRegistryContext


def refuse(message: str) -> NoReturn:
    raise FinancePostingError("intercompany_cashflow_invalid", message)


@dataclass(frozen=True)
class SourceCashOpening:
    """Explicit source-origin basis; never a whole-company opening balance."""

    source_id: str
    source_digest: str
    origin_plan_id: str
    origin_plan_digest: str
    seller_minor: int
    buyer_minor: int
    basis: str

    def validate(self, source: Mapping[str, Any], origin: Mapping[str, Any]) -> None:
        if (self.source_id != source["id"] or self.source_digest != source["source_digest"]
                or self.origin_plan_id != origin["id"] or self.origin_plan_digest != origin["plan_digest"]
                or self.basis != "complete-native-source-origin-membership"
                or type(self.seller_minor) is not int or type(self.buyer_minor) is not int
                or self.seller_minor != 0 or self.buyer_minor != 0):
            refuse("An explicit known zero opening tied to this native source origin is required.")


def classified_cashflow(source: Mapping[str, Any], report: Mapping[str, Any], stages: Sequence[Mapping[str, Any]], *,
                        opening: SourceCashOpening, context: CurrencyRegistryContext) -> dict[str, Any]:
    if not 2 <= len(stages) <= MAX_OPERATIONS or source["schema_version"] != "intercompany-fx-source-v2":
        refuse("A complete original paired source cycle is required.")
    if source["source_digest"] != digest_payload({key: value for key, value in source.items() if key != "source_digest"}):
        refuse("The original source seal differs.")
    if report["schema_version"] != "intercompany-fx-management-report-v2" or report["reporting_scope"] != "explicit-paired-trade-native-management":
        refuse("An actual posted paired management report is required.")
    if report["report_digest"] != digest_payload({key: value for key, value in report.items() if key != "report_digest"}):
        refuse("The original management report seal differs.")
    if (report["source_id"], report["source_digest"], report["currency_policy"]) != (
            source["id"], source["source_digest"], source["policies"]["adjustment"]):
        refuse("Reporting policy and source membership differ.")
    request = source["request"]
    if (set(source["policies"]) != {"transaction", *PARTIES, "adjustment"}
            or len({request[book]["legal_entity_id"] for book in (*PARTIES, "adjustment")}) != 3):
        refuse("Three distinct original native books and explicit transaction policy are required.")
    for captured in source["policies"].values():
        try:
            FinanceCurrencyPolicy.verify_record(captured, context)
        except FinancePolicyError as exc:
            raise FinancePostingError("intercompany_cashflow_policy_invalid", "Every currency must retain its exact captured registry context.") from exc
    plans = [stage["plan"] for stage in stages]
    if ([plan["sequence"] for plan in plans] != list(range(len(plans))) or plans[0]["kind"] != "recognize"
            or plans[-1]["kind"] != "eliminate" or any(plan["kind"] == "eliminate" for plan in plans[:-1])
            or len({plan["id"] for plan in plans}) != len(plans)):
        refuse("Original native operations must form one complete ordered source lifecycle.")
    opening.validate(source, plans[0])
    elimination = plans[-1]
    if report["adjustment_plan_digest"] != elimination["plan_digest"]:
        refuse("The report does not bind this exact posted native elimination.")
    identities: set[tuple[str, int]] = set()
    effects_by_book: dict[str, set[str]] = {book: set() for book in (*PARTIES, "adjustment")}
    cash: dict[str, list[dict[str, Any]]] = {book: [] for book in PARTIES}
    line_count = 0
    for stage, plan in zip(stages, plans, strict=True):
        if (stage["source"] != source or plan["source_id"] != source["id"] or plan["source_digest"] != source["source_digest"]
                or plan["phase"] != 2 or plan["status"] != "Posted"
                or len({plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]}) != 3
                or not all(type(plan[field]) is str and bool(plan[field]) for field in ("preparer_actor_id", "reviewer_actor_id", "posted_actor_id"))):
            refuse("Every original operation requires its retained three-person posted source.")
        sealed = {key: value for key, value in plan.items() if key not in {
            "phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"}}
        if plan["plan_digest"] != digest_payload(sealed):
            refuse("An original operation seal differs.")
        phases = stage["phases"]
        if (len(phases) != 3 or [row["action"] for row in phases] != [
                "intercompany_fx_prepared", "intercompany_fx_reviewed", "intercompany_fx_posted"]
                or len({row["audit_event_id"] for row in phases}) != 3 or len({row["outbox_event_id"] for row in phases}) != 3
                or [row["actor_id"] for row in phases] != [plan[field] for field in (
                    "preparer_actor_id", "reviewer_actor_id", "posted_actor_id")]
                or not all(row["audit_event_id"] and row["outbox_event_id"]
                    and row["metadata_json"]["plan_digest"] == plan["plan_digest"] for row in phases)):
            refuse("Every operation requires its original exact three-person phase evidence.")
        effects = {effect["id"]: effect for effect in stage["native_effects"]}
        if len(effects) != len(stage["native_effects"]) or set(effects) != set(plan["posting_effect_ids"].values()):
            refuse("Every declared native effect must be captured exactly once.")
        expected_books = {"adjustment"} if plan["kind"] == "eliminate" else set(PARTIES)
        if (len(plan["entries"]) != len(expected_books)
                or {entry["book"] for entry in plan["entries"]} != expected_books
                or set(plan["posting_effect_ids"]) != expected_books
                or len(set(plan["posting_effect_ids"].values())) != len(expected_books)):
            refuse("Native book effect membership differs.")
        for entry in plan["entries"]:
            book = entry["book"]
            effect_id = plan["posting_effect_ids"][book]
            if effect_id in set().union(*effects_by_book.values()):
                refuse("A native effect cannot be reused in another operation or book.")
            effects_by_book[book].add(effect_id)
            effect, snapshot = effects[effect_id], entry["snapshot"]
            header = snapshot["entry"]
            expected = {"workspace_id": request["workspace_id"], "organization_id": request["organization_id"],
                "legal_entity_id": request[book]["legal_entity_id"], **source["policies"][book]}
            if (effect["snapshot"] != snapshot or effect["entry_id"] != entry["entry_id"] or header["id"] != entry["entry_id"]
                    or effect["validation_digest"] != entry["validation_digest"] or digest_payload(snapshot) != entry["validation_digest"]
                    or header["posting_date"] != plan["posting_date"] or header["preparer_actor_id"] != plan["preparer_actor_id"]
                    or not effect["audit_event_id"] or not effect["outbox_event_id"]
                    or effect["posted_actor_id"] != plan["posted_actor_id"] or any(header[field] != value for field, value in expected.items())):
                refuse("Original native snapshot, policy or posting membership differs.")
            native_accounts = source["native_accounts"][book]
            codes = {row["id"]: row["account_code"] for row in native_accounts.values()}
            if (len(codes) != len(native_accounts) or any(row["account_id"] not in codes for row in snapshot["lines"])
                    or any(native_accounts[role]["account_code"] != code
                    for role, code in request[book]["accounts"].items())):
                refuse("Original native account mapping differs.")
            if (sorted((codes[row["account_id"]], row["debit_minor"], row["credit_minor"]) for row in snapshot["lines"])
                    != sorted((row["account_code"], row["debit_minor"], row["credit_minor"])
                        for row in plan["equation"]["books"][book])):
                refuse("Original native lines do not match their reviewed source equation.")
            balance = 0
            for row in snapshot["lines"]:
                line_count += 1
                if line_count > MAX_EFFECT_LINES:
                    refuse("Native source effect line membership exceeds its declared bound.")
                key = (effect_id, row["line_number"])
                if key in identities:
                    refuse("A native line cannot be counted twice.")
                identities.add(key)
                debit = minor(row["debit_minor"], "native Cash debit", zero=True)
                credit = minor(row["credit_minor"], "native Cash credit", zero=True)
                if min(debit, credit) < 0 or (debit > 0) == (credit > 0):
                    refuse("Native lines require exact one-sided nonnegative money.")
                balance = signed(balance + debit - credit, "native book balance")
                if row["account_id"] != source["native_accounts"][book]["cash"]["id"]:
                    continue
                if book == "adjustment" or plan["kind"] != "settle":
                    refuse("Cash outside original paired settlement effects is uncovered.")
                if (book == "seller" and credit) or (book == "buyer" and debit):
                    refuse("Cash direction does not match its source-owned paired settlement.")
                cash[book].append({"effect_id": effect_id, "entry_id": entry["entry_id"], "line_number": row["line_number"],
                    "account_id": row["account_id"], "account_code": request[book]["accounts"]["cash"],
                    "posting_date": plan["posting_date"], "native_minor": debit - credit})
            if balance != 0:
                refuse("Every original native effect must balance before classification.")
    if (set(report["source_effect_ids"]) != effects_by_book["seller"] | effects_by_book["buyer"]
            or len(set(report["source_effect_ids"])) != len(report["source_effect_ids"])
            or set(report["native_adjustment_effect_ids"]) != effects_by_book["adjustment"]
            or len(set(report["native_adjustment_effect_ids"])) != len(report["native_adjustment_effect_ids"])):
        refuse("The report omits or introduces native source/adjustment effects.")
    books: dict[str, dict[str, Any]] = {}
    for book in PARTIES:
        translated = report["entity_translations"][book]
        if translated != elimination["equation"]["translations"][book]:
            refuse("Reporting translation must retain its exact reviewed original elimination membership.")
        if translated["functional_policy"] != source["policies"][book] or translated["reporting_policy"] != report["currency_policy"]:
            refuse("Captured functional/reporting currency policy differs.")
        closing_rate = elimination["command_request"]["closing_rates"][book]
        if translated["closing_rate"] != closing_rate:
            refuse("The closing rate must be the reviewed original elimination rate.")
        rows = [row for row in translated["accounts"] if row["role"] == "cash"]
        if len(rows) != (1 if cash[book] else 0):
            refuse("Original Cash account presence differs from complete native source membership.")
        contributions = rows[0]["contributions"] if rows else []
        retained = {(row["effect_id"], row["line_number"]): row for row in contributions}
        if len(retained) != len(contributions) or set(retained) != {(row["effect_id"], row["line_number"]) for row in cash[book]}:
            refuse("The translated report covers another native Cash line population.")
        movements = []
        native_total = operating = 0
        for original in cash[book]:
            record = retained[(original["effect_id"], original["line_number"])]
            historical_rate = elimination["command_request"]["income_rates"][book][original["posting_date"]]
            if (record["entry_id"] != original["entry_id"] or record["account_id"] != original["account_id"]
                    or record["account_code"] != original["account_code"] or record["posting_date"] != original["posting_date"]
                    or record["debit_minor"] - record["credit_minor"] != original["native_minor"] or record["income_rate"] != historical_rate):
                refuse("Original native Cash amount, account or captured historical rate differs.")
            amount = converted(abs(original["native_minor"]), historical_rate, request["adjustment"]["currency_code"],
                request[book]["currency_code"], context, original["posting_date"], inverse=True)
            movement = amount if original["native_minor"] > 0 else -amount
            operating = signed(operating + movement, "source operating flow")
            native_total = signed(native_total + original["native_minor"], "source native Cash closing")
            movements.append({**original, "historical_rate": dict(historical_rate), "operating_minor": movement})
        closing = converted(abs(native_total), closing_rate, request["adjustment"]["currency_code"],
            request[book]["currency_code"], context, elimination["posting_date"], inverse=True)
        if native_total < 0:
            closing = -closing
        if rows and (rows[0]["native_balance_minor"] != native_total or rows[0]["balance_minor"] != closing):
            refuse("Actual closing translation does not match original Cash contributions.")
        books[book] = {"legal_entity_id": request[book]["legal_entity_id"], "functional_policy": source["policies"][book],
            "opening_minor": 0, "operating_minor": operating, "native_cash_minor": native_total,
            "closing_minor": closing, "fx_on_cash_minor": closing - operating, "closing_rate": dict(closing_rate), "movements": movements}
    operating_total = signed(sum(row["operating_minor"] for row in books.values()), "group operating source flow")
    closing_total = signed(sum(row["closing_minor"] for row in books.values()), "group closing source Cash")
    if closing_total != report["cash_net_movement_minor"]:
        refuse("Original closing Cash differs from the posted management statement.")
    result = {"schema_version": "intercompany-source-cashflow-v1", "scope": "explicit-paired-trade-native-source-membership",
        "source_id": source["id"], "source_digest": source["source_digest"], "report_digest": report["report_digest"],
        "elimination_plan_id": elimination["id"], "elimination_plan_digest": elimination["plan_digest"],
        "reporting_policy": report["currency_policy"], "opening_basis": opening.basis,
        "opening_origin_plan_id": opening.origin_plan_id, "opening_origin_plan_digest": opening.origin_plan_digest,
        "opening_minor": 0, "operating_inflow_minor": sum(max(row["operating_minor"], 0) for row in books.values()),
        "operating_outflow_minor": sum(max(-row["operating_minor"], 0) for row in books.values()),
        "operating_net_minor": operating_total, "fx_on_cash_minor": closing_total - operating_total,
        "closing_minor": closing_total, "books": books,
        "source_effect_ids": sorted(effects_by_book["seller"] | effects_by_book["buyer"]),
        "native_adjustment_effect_ids": sorted(effects_by_book["adjustment"]),
        "limitations": ["Original paired-trade source membership only; no whole-company opening or statutory cash-flow qualification",
            "Recorded native Cash GL; no external bank transfer", "No investment, financing, ownership/NCI or IAS7 legal qualification"]}
    return {**result, "cashflow_digest": digest_payload(result)}
