"""Exact public financial request boundaries before native API registration."""
from typing import Any

import pytest
from pydantic import ValidationError

from reconforge.api.routes.manufacturing_execution_v2 import CostClaim, OperationReport, project_v2


def test_rate_minor_text_preserves_full_native_integer_without_javascript_float() -> None:
    claim = CostClaim(effect_id="FPE-original", line_id="GLEL-original", kind="Labor", operation_sequence=1,
        minutes=1, rate_minor_per_hour="9000000000000000000")
    assert claim.claim_payload()["rate_minor_per_hour"] == 9_000_000_000_000_000_000
    projected = project_v2({"claims": [claim.claim_payload()], "cost_minor": 9_000_000_000_000_000_000})
    assert projected["claims"][0]["rate_minor_per_hour"] == "9000000000000000000"
    assert projected["cost_minor"] == "9000000000000000000"
    assert project_v2({"minutes": 9_000_000_000_000_000_000}) == {"minutes": "9000000000000000000"}


@pytest.mark.parametrize("value", [True, 600.0, 600, "0600", "6e2", "0", "-600", None])
def test_rate_contract_refuses_coercion_and_noncanonical_money(value: Any) -> None:
    with pytest.raises(ValidationError):
        CostClaim(effect_id="FPE-original", line_id="GLEL-original", kind="Labor", operation_sequence=1, minutes=60, rate_minor_per_hour=value)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_operation_integer_metadata_never_accepts_bool_float_or_text(value: Any) -> None:
    with pytest.raises(ValidationError):
        OperationReport(sequence=value, minutes=1, evidence_reference="SYN-OP-1")
