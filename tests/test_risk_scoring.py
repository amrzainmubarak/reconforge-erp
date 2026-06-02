from __future__ import annotations

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.risk import assess_risk, risk_level


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
