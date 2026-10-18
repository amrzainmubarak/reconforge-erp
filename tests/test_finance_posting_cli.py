"""Actual offline password-bound commands, independent review and exact recovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from tests.test_finance_core import _balanced_lines, _seed_finance_model

PASSWORD = "Synthetic-cli-posting-password-123"
runner = CliRunner()


@pytest.fixture
def posting_cli(tmp_path: Path):
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, period = _seed_finance_model(connection)
        auth = LocalAuthService(connection)
        maker = auth.init_admin(username="maker", password=PASSWORD)
        checker = auth.create_user(username="checker", password=PASSWORD, role="admin")
        auth.create_user(username="reader", password=PASSWORD, role="auditor-readonly")
    payload = {
        "entry_number": "CLI-ORIGINAL", "organization_code": "SYN", "entity_code": "EG01",
        "period_id": period["id"], "journal_code": "GJ", "posting_date": "2026-07-05",
        "description": "Synthetic independently reviewed CLI posting", "lines": _balanced_lines(),
    }
    input_path = tmp_path / "draft.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    return path, input_path, period, maker, checker


def invoke(path: Path, command: str, *args: str, username: str = "checker", password: str = PASSWORD):
    result = runner.invoke(app, [
        "finance-core", "posting", command, "--db", str(path), "--username", username, *args,
    ], input=password + "\n")
    assert PASSWORD not in result.output
    return result


def successful(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output.splitlines()[-1])


def test_real_cli_draft_review_post_replay_and_full_reversal(posting_cli) -> None:
    path, input_path, period, maker, checker = posting_cli
    entry = successful(invoke(path, "draft", "--input", str(input_path), username="maker"))["entry"]
    assert entry["status"] == "Draft"
    self_review = invoke(path, "review", "--entry-id", entry["id"], "--reason", "Forbidden own review", username="maker")
    assert self_review.exit_code == 1 and "Segregation" in self_review.output
    review = successful(invoke(path, "review", "--entry-id", entry["id"], "--reason", "Independent exact review"))["review"]
    assert review["preparer_actor_id"] == maker.id
    assert review["validator_actor_id"] == checker.id
    assert review["validation_digest"] == review["current_content_digest"]
    post_args = (
        "--entry-id", entry["id"], "--command-id", "cli-post-1",
        "--expected-validation-digest", review["validation_digest"], "--reason", "Explicit reviewed posting",
    )
    assert invoke(path, "post", *post_args, username="maker").exit_code == 1
    assert invoke(path, "post", *post_args, username="reader").exit_code == 1
    posted = successful(invoke(path, "post", *post_args))["posting"]
    as_of = successful(invoke(path, "balances-as-of", "--period-id", str(period["id"]), "--as-of-date", "2026-07-05", "--organization", "SYN", "--entity", "EG01", username="reader"))["balances"]
    assert as_of["totals"]["opening"]["effect_count"] == 0
    assert as_of["totals"]["closing"]["balance_totals"]["debit_minor"] == "100000"
    invalid = invoke(path, "balances-as-of", "--period-id", str(period["id"]), "--as-of-date", "2026-08-01", "--organization", "SYN", "--entity", "EG01", username="reader")
    assert invalid.exit_code == 1 and "posting_date_invalid" in invalid.output
    assert successful(invoke(path, "post", *post_args))["posting"] == posted
    assert successful(invoke(path, "effect", "--effect-id", posted["id"]))["posting"] == posted
    changed = invoke(path, "post", *post_args[:-1], "Changed retry reason")
    assert changed.exit_code == 1 and "posting_command_conflict" in changed.output
    reverse_args = (
        "--effect-id", posted["id"], "--command-id", "cli-reverse-1", "--entry-number", "CLI-REVERSAL",
        "--period-id", str(period["id"]), "--date", "2026-07-06", "--reason", "Full synthetic correction",
    )
    reversal = successful(invoke(path, "reverse", *reverse_args, username="maker"))["reversal"]
    assert successful(invoke(path, "reverse", *reverse_args, username="maker"))["reversal"] == reversal
    assert reversal["status"] == "Draft" and reversal["preparer_actor_id"] == maker.id
    reversed_review = successful(invoke(path, "review", "--entry-id", reversal["entry_id"], "--reason", "Independent reversal review"))["review"]
    inverse = successful(invoke(path, "post", "--entry-id", reversal["entry_id"], "--command-id", "cli-post-reversal",
        "--expected-validation-digest", reversed_review["validation_digest"], "--reason", "Explicit reversal posting"))["posting"]
    assert inverse["reverses_effect_id"] == posted["id"]
    balance = successful(invoke(path, "trial-balance", "--period-id", str(period["id"]), "--organization", "SYN", "--entity", "EG01"))["trial_balance"]
    assert balance["balance_scope"] == "selected-period-net-activity"
    assert balance["effect_count"] == 2
    assert balance["turnover_totals"] == {"debit_minor": "200000", "credit_minor": "200000", "balanced": True}
    assert balance["balance_totals"] == {"debit_minor": "0", "credit_minor": "0", "balanced": True}
    with connect(path, require_exists=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_commands").fetchone()[0] == 3


def test_cli_authentication_and_closed_input_create_no_false_effects(posting_cli) -> None:
    path, input_path, _, _, _ = posting_cli
    wrong_password = invoke(path, "draft", "--input", str(input_path), username="maker", password="Wrong-synthetic-password")
    assert wrong_password.exit_code == 1 and "posting_authentication_failed" in wrong_password.output
    forged_identity = invoke(path, "draft", "--input", str(input_path), "--actor", "checker", username="maker")
    assert forged_identity.exit_code == 2 and "No such option" in forged_identity.output
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    for field, value in (("currency_code", "USD"), ("actor_id", "checker"), ("source_type", "Imported")):
        input_path.write_text(json.dumps({**payload, field: value}), encoding="utf-8")
        rejected = invoke(path, "draft", "--input", str(input_path), username="maker")
        assert rejected.exit_code == 1, rejected.output
    with connect(path, require_exists=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_commands").fetchone()[0] == 0


def test_cli_late_receipt_failure_does_not_acknowledge_or_partially_commit(posting_cli) -> None:
    path, input_path, _, _, _ = posting_cli
    entry = successful(invoke(path, "draft", "--input", str(input_path), username="maker"))["entry"]
    review = successful(invoke(path, "review", "--entry-id", entry["id"], "--reason", "Independent review"))["review"]
    with connect(path, require_exists=True) as connection:
        before = tuple(connection.execute("SELECT (SELECT COUNT(*) FROM audit_events),(SELECT COUNT(*) FROM outbox_events)").fetchone())
        connection.execute("CREATE TRIGGER synthetic_cli_fail BEFORE INSERT ON finance_posting_commands BEGIN SELECT RAISE(ABORT,'synthetic_private_error'); END")
    result = invoke(path, "post", "--entry-id", entry["id"], "--command-id", "uncertain-command",
        "--expected-validation-digest", review["validation_digest"], "--reason", "Explicit reviewed posting")
    assert result.exit_code == 1 and "posting_storage_failed" in result.output
    assert "synthetic_private_error" not in result.output and '"posting"' not in result.output
    with connect(path, require_exists=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_commands").fetchone()[0] == 0
        after = tuple(connection.execute("SELECT (SELECT COUNT(*) FROM audit_events),(SELECT COUNT(*) FROM outbox_events)").fetchone())
        assert after == before
