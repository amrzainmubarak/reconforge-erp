from __future__ import annotations

import re
from datetime import UTC, datetime

from reconforge.benchmark.metrics import build_metrics
from reconforge.domain.models import utc_now_text as domain_utc_now_text
from reconforge.evidence.models import EvidenceCase
from reconforge.io.excel import audit_metadata
from reconforge.rules.results import RuleResult
from reconforge.utils.time import utc_now_text, utc_today

UTC_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def assert_utc_text(value: str) -> None:
    assert UTC_TEXT.fullmatch(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC


def test_utc_helpers_preserve_second_precision_z_contract() -> None:
    assert_utc_text(utc_now_text())
    assert_utc_text(domain_utc_now_text())
    assert utc_today() == datetime.now(UTC).date()


def test_generated_models_and_artifacts_use_aware_utc_text() -> None:
    rule = RuleResult(
        rule_id="RULE-1",
        rule_name="Synthetic rule",
        severity="medium",
        entity_type="journal",
        source_file="synthetic.csv",
        source_row=1,
        message="Synthetic exception.",
        recommended_action="Review synthetic evidence.",
        risk_impact=10,
    )
    evidence = EvidenceCase(
        exception_id="SYN-EXC-1",
        exception_type="synthetic",
        severity="medium",
        risk_score=10,
        business_impact="Synthetic impact only.",
        recommended_action="Review synthetic evidence.",
        responsible_department="Synthetic Finance",
    )
    benchmark = build_metrics(
        runtime_seconds=0.1,
        report_generation_time=0.1,
        stock_rows=1,
        gl_rows=1,
        matched_rows=1,
        exception_rows=0,
        memory_mb=1.0,
        engine="pandas",
    )

    for value in (
        rule.triggered_at,
        evidence.generated_at,
        benchmark.timestamp,
        audit_metadata("Synthetic Co", "Synthetic report", "USD")["generated_at"],
    ):
        assert_utc_text(value)
