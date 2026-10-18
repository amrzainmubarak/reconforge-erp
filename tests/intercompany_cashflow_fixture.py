"""Planned synthetic native-shaped originals; never a database execution claim."""

from typing import Any

from reconforge.domain.finance_posting import digest_payload
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.domain.intercompany_fx import elimination_equation, group_report
from tests.test_intercompany_fx import equations, translations


def fixture() -> tuple[dict[str, Any], Any, SourceCashOpening]:
    source, context, recognition, settlement, revaluation, cash_rates, closing_rates = equations()
    _, translated = translations()
    source["native_accounts"] = {book: {role: {"id": "ACC-" + code, "account_code": code, "chart_id": "CHART",
        "account_type": "Asset" if role == "cash" else "Other"} for role, code in source["request"][book]["accounts"].items()}
        for book in ("seller", "buyer", "adjustment")}
    source["source_digest"] = digest_payload({key: value for key, value in source.items() if key != "source_digest"})
    for translation in translated.values():
        for account in translation["accounts"]:
            for row in account["contributions"]:
                row["account_id"] = "ACC-" + row["account_code"]
        translation["translation_digest"] = digest_payload({key: value for key, value in translation.items() if key != "translation_digest"})
    elimination = {**elimination_equation(source, translated), "translations": translated}
    income = {book: {"2026-10-03": source["request"][book + "_original_rate"], "2026-10-04": cash_rates[book],
        "2026-10-31": closing_rates[book]} for book in ("seller", "buyer")}
    stages = []
    adjustment_rows = []
    for sequence, (kind, equation, day) in enumerate((
        ("recognize", recognition, "2026-10-03"), ("settle", settlement, "2026-10-04"),
        ("revalue", revaluation, "2026-10-31"), ("eliminate", elimination, "2026-10-31"),
    )):
        entries, effects, effect_ids = [], [], {}
        for book, rows in sorted(equation["books"].items()):
            entry_id, effect_id = f"entry-{sequence}-{book}", f"native-{sequence}-{book}"
            snapshot = {"schema_version": "finance-entry-review-v1", "entry": {"id": entry_id,
                "workspace_id": "work", "organization_id": "org", "legal_entity_id": source["request"][book]["legal_entity_id"],
                "posting_date": day, "preparer_actor_id": "maker", **source["policies"][book]}, "lines": [
                    {"line_number": index, "account_id": "ACC-" + row["account_code"], "debit_minor": row["debit_minor"],
                        "credit_minor": row["credit_minor"], "dimensions": {}} for index, row in enumerate(rows, 1)]}
            validation = digest_payload(snapshot)
            entries.append({"book": book, "entry_id": entry_id, "snapshot": snapshot, "validation_digest": validation})
            effects.append({"id": effect_id, "entry_id": entry_id, "snapshot": snapshot, "validation_digest": validation,
                "posted_actor_id": "poster", "audit_event_id": f"audit-{sequence}-{book}", "outbox_event_id": f"outbox-{sequence}-{book}"})
            effect_ids[book] = effect_id
            if book == "adjustment":
                adjustment_rows = [{**row, "effect_id": effect_id, "entry_id": entry_id, "line_number": index}
                    for index, row in enumerate(rows, 1)]
        plan = {"id": "IC2-" + f"{sequence + 1:032x}", "source_id": source["id"], "source_digest": source["source_digest"],
            "kind": kind, "sequence": sequence, "posting_date": day, "equation": equation,
            "preparer_actor_id": "maker", "entries": entries,
            "command_request": {"closing_rates": closing_rates, "income_rates": income} if kind == "eliminate" else {}}
        plan["plan_digest"] = digest_payload(plan)
        plan.update(phase=2, status="Posted", reviewer_actor_id="checker", posted_actor_id="poster", posting_effect_ids=effect_ids)
        phases = [{"action": "intercompany_fx_" + action, "actor_id": actor,
            "audit_event_id": f"phase-audit-{sequence}-{action}", "outbox_event_id": f"phase-outbox-{sequence}-{action}",
            "metadata_json": {"plan_digest": plan["plan_digest"]}} for action, actor in (
                ("prepared", "maker"), ("reviewed", "checker"), ("posted", "poster"))]
        stages.append({"source": source, "plan": plan, "native_effects": effects, "phases": phases})
    report = group_report(source, translated, adjustment_rows, plan_digest=stages[-1]["plan"]["plan_digest"])
    report["source_effect_ids"] = sorted(effect for stage in stages[:-1] for effect in stage["plan"]["posting_effect_ids"].values())
    report["native_adjustment_effect_ids"] = sorted(stages[-1]["plan"]["posting_effect_ids"].values())
    report["report_digest"] = digest_payload({key: value for key, value in report.items() if key != "report_digest"})
    origin = stages[0]["plan"]
    opening = SourceCashOpening(source["id"], source["source_digest"], origin["id"], origin["plan_digest"], 0, 0,
        "complete-native-source-origin-membership")
    return {"source": source, "report": report, "stages": stages, "native_execution_proven": False}, context, opening
