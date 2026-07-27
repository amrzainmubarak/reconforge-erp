from __future__ import annotations

from decimal import Decimal

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.risk import amount_component, assess_risk, risk_level
from reconforge.risk.scoring import score_exception


def test_risk_level_boundaries() -> None:
    assert risk_level(30) == "Low"
    assert risk_level(31) == "Medium"
    assert risk_level(61) == "High"
    assert risk_level(81) == "Critical"


def test_missing_gl_high_amount_is_critical(config: ReconForgeConfig) -> None:
    assessment = assess_risk("stock_without_gl", config, amount=5000)
    assert assessment.level == "Critical"


def test_missing_old_part_return_is_high_or_medium(config: ReconForgeConfig) -> None:
    assessment = assess_risk("missing_old_part_return", config, amount=360)
    assert assessment.score >= 55


def test_risk_amount_component_uses_exact_decimal_thresholds() -> None:
    assert amount_component(Decimal("1000.50")) == 20
    assert amount_component(Decimal("250.01"), baseline=Decimal("250")) == 20
    assert amount_component("not-a-number") == 0


def test_risk_scoring_invalid_amount_factors_do_not_crash_or_cast_to_zero() -> None:
    valid = score_exception("stock_without_gl", {"amount": "1200.00", "variance": "5000.00"})
    invalid = score_exception("stock_without_gl", {"amount": "N/A?", "variance": "bad-value"})
    baseline = score_exception("stock_without_gl", {})

    assert valid >= baseline
    assert invalid == baseline


def test_risk_scoring_invalid_aging_days_defaults_to_zero() -> None:
    result = score_exception("stock_without_gl", {"amount": "N/A?", "aging_days": "bad-number"})
    assert result == score_exception("stock_without_gl", {"amount": "N/A?"})
