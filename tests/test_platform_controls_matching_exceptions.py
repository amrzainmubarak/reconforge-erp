from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.platform.common import PlatformError
from reconforge.platform.controls import ControlTestingService
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.intercompany import IntercompanyService
from reconforge.platform.journals import JournalControlService
from reconforge.platform.matching import MatchingService

runner = CliRunner()


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


def test_journal_and_intercompany_amounts_use_canonical_decimal_text_and_reject_invalid_values(tmp_path: Path) -> None:
    db_path = tmp_path / "decimal-operations.db"
    journal_path = tmp_path / "invalid-journal.csv"
    journal_path.write_text(
        "journal_id,period_name,entity_code,posting_date,account_code,amount,currency\n"
        "J-BAD,2026-05,US01,2026-05-10,1000,not-a-number,USD\n",
        encoding="utf-8",
    )
    intercompany_path = tmp_path / "invalid-intercompany.csv"
    intercompany_path.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,posting_date,amount,currency,reference\n"
        "IC-BAD,2026-05,US01,UK01,2026-05-10,,USD,REF-BAD\n",
        encoding="utf-8",
    )
    valid_journal_path = tmp_path / "valid-journal.csv"
    valid_journal_path.write_text(
        "journal_id,period_name,entity_code,posting_date,account_code,amount,currency\n"
        "J-VALID,2026-05,US01,2026-05-10,1000,123456789.123456789,USD\n",
        encoding="utf-8",
    )
    valid_intercompany_path = tmp_path / "valid-intercompany.csv"
    valid_intercompany_path.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,posting_date,amount,currency,reference\n"
        "IC-VALID,2026-05,US01,UK01,2026-05-10,987654321.987654321,USD,REF-VALID\n",
        encoding="utf-8",
    )
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        with pytest.raises(PlatformError, match="financial amount"):
            JournalControlService(connection).import_journals(journal_path)
        with pytest.raises(PlatformError, match="financial amount"):
            IntercompanyService(connection).import_transactions(intercompany_path)
        JournalControlService(connection).import_journals(valid_journal_path)
        IntercompanyService(connection).import_transactions(valid_intercompany_path)
        journal_amount = connection.execute(
            "SELECT amount_decimal FROM journal_entries WHERE journal_id = 'J-VALID'",
        ).fetchone()["amount_decimal"]
        intercompany_amount = connection.execute(
            "SELECT amount_decimal FROM intercompany_transactions WHERE transaction_id = 'IC-VALID'",
        ).fetchone()["amount_decimal"]
    finally:
        connection.close()

    assert journal_amount == "123456789.123456789"
    assert intercompany_amount == "987654321.987654321"


def test_financial_policy_cli_options_preserve_exact_decimal_boundaries(tmp_path: Path) -> None:
    db_path = tmp_path / "exact-policy-cli.db"
    journal_path = tmp_path / "exact-policy-journal.csv"
    journal_path.write_text(
        "journal_id,period_name,entity_code,posting_date,account_code,amount,currency,reference,approver,is_manual\n"
        "J-EXACT,2026-05,US01,2026-05-10,1000,100000.00000000000,USD,REF-1,APPROVER,false\n",
        encoding="utf-8",
    )
    intercompany_path = tmp_path / "exact-policy-intercompany.csv"
    intercompany_path.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,posting_date,amount,currency,reference\n"
        "IC-EXACT-1,2026-05,US01,UK01,2026-05-10,1.000000000000000000,USD,REF-EXACT\n"
        "IC-EXACT-2,2026-05,UK01,US01,2026-05-10,-0.899999999999999997,USD,REF-EXACT\n",
        encoding="utf-8",
    )
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        JournalControlService(connection).import_journals(journal_path)
        IntercompanyService(connection).import_transactions(intercompany_path)
    finally:
        connection.close()

    journal_result = runner.invoke(
        app,
        [
            "journals",
            "policy-run",
            "--db",
            str(db_path),
            "--period",
            "2026-05",
            "--high-value",
            "100000.00000000001",
        ],
    )
    intercompany_result = runner.invoke(
        app,
        [
            "intercompany",
            "match",
            "--db",
            str(db_path),
            "--period",
            "2026-05",
            "--tolerance",
            "0.100000000000000005",
        ],
    )

    assert journal_result.exit_code == 0, journal_result.output
    assert intercompany_result.exit_code == 0, intercompany_result.output
    connection = connect(db_path, require_exists=True)
    try:
        high_value_count = connection.execute(
            "SELECT COUNT(*) AS count FROM journal_exceptions WHERE policy_code = 'HIGH_VALUE'",
        ).fetchone()["count"]
        intercompany_case_count = connection.execute(
            "SELECT COUNT(*) AS count FROM intercompany_cases",
        ).fetchone()["count"]
    finally:
        connection.close()
    assert high_value_count == 0
    assert intercompany_case_count == 0
