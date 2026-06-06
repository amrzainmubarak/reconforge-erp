from __future__ import annotations

from pathlib import Path

from reconforge.db import connect, run_migrations
from reconforge.platform.controls import ControlTestingService
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.intercompany import IntercompanyService
from reconforge.platform.journals import JournalControlService
from reconforge.platform.matching import MatchingService


def test_journals_intercompany_controls_matching_and_exceptions(tmp_path: Path) -> None:
    db_path = tmp_path / "operations.db"
    run_migrations(db_path)
    journals = tmp_path / "journals.csv"
    journals.write_text(
        "journal_id,period_name,entity_code,posting_date,account_code,amount,currency,reference,approver,is_manual\n"
        "J1,2026-05,US01,2026-06-02,9999,150000,USD,,yes,true\n",
        encoding="utf-8",
    )
    intercompany = tmp_path / "intercompany.csv"
    intercompany.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,posting_date,amount,currency,reference\n"
        "IC1,2026-05,US01,UK01,2026-05-10,100,USD,REF-1\n"
        "IC2,2026-05,UK01,US01,2026-05-11,-80,USD,REF-1\n",
        encoding="utf-8",
    )
    controls = tmp_path / "controls.csv"
    controls.write_text(
        "control_code,name,owner,frequency,description,risk_rating\n"
        "CTRL-1,Review manual journals,Controller,monthly,Manual journal review,high\n",
        encoding="utf-8",
    )
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("id,reference,amount,date\nL1,REF-100,25.00,2026-05-10\n", encoding="utf-8")
    right.write_text("id,reference,amount,date\nR1,REF-100,25.00,2026-05-10\n", encoding="utf-8")

    connection = connect(db_path, require_exists=True)
    try:
        journal_service = JournalControlService(connection)
        journal_service.import_journals(journals)
        journal_count = journal_service.policy_run(
            period_name="2026-05",
            period_end="2026-05-31",
            high_value_threshold=100000,
            high_risk_accounts="9999",
        )

        ic_service = IntercompanyService(connection)
        ic_service.import_transactions(intercompany)
        ic_count = ic_service.match(period_name="2026-05")

        control_service = ControlTestingService(connection)
        control_service.import_library(controls)
        plan_count = control_service.plan_tests(period_name="2026-05", sample_size=1)
        plan = control_service.list_plans(period_name="2026-05")[0]
        control_service.record_result(
            plan_id=str(plan["id"]),
            result_status="Completed",
            effectiveness_status="Ineffective",
            note="Synthetic failure",
        )

        match_result = MatchingService(connection).run(left_path=left, right_path=right, amount_tolerance=0, date_window_days=0)
        queue = ExceptionQueueService(connection).list()
    finally:
        connection.close()

    assert journal_count >= 4
    assert ic_count == 1
    assert plan_count == 1
    assert match_result.matched_count == 1
    assert {record["source_type"] for record in queue} >= {"journal", "intercompany", "control_test"}
