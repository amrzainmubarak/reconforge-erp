from __future__ import annotations

import pytest

from reconforge.api.errors import APIError
from reconforge.api.routes.consolidation_deferred_tax import DeferredTaxPrepareRequest
from reconforge.api.routes.consolidation_impairment import ImpairmentPrepareRequest
from reconforge.api.routes.consolidation_intercompany import (
    CanonicalMoneyRequest as IntercompanyMoneyRequest,
)
from reconforge.api.routes.consolidation_intercompany import (
    IntercompanyLineRequest,
)
from reconforge.api.routes.consolidation_ownership_change import OwnershipChangePrepareRequest
from reconforge.api.routes.consolidation_ppa import PpaPrepareRequest
from reconforge.utils.money import Money
from tests.test_api_consolidation_deferred_tax import _body as deferred_tax_body
from tests.test_api_consolidation_impairment import _body as impairment_body
from tests.test_api_consolidation_ownership_change import _body as ownership_change_body
from tests.test_api_consolidation_ppa import _body as ppa_body


def _payload() -> dict[str, object]:
    return Money.from_exact("1.00", "USD", strict_precision=True).to_canonical_dict()


@pytest.mark.parametrize(
    ("request_model", "body_factory", "money_field"),
    (
        (PpaPrepareRequest, ppa_body, "consideration"),
        (DeferredTaxPrepareRequest, deferred_tax_body, "items[0].fair_value"),
        (ImpairmentPrepareRequest, impairment_body, "units[0].carrying_amount"),
        (OwnershipChangePrepareRequest, ownership_change_body, "net_assets"),
    ),
)
def test_api_money_models_reject_noncanonical_amount_text(
    request_model: type[object], body_factory: object, money_field: str
) -> None:
    payload = body_factory()  # type: ignore[operator]
    if money_field == "items[0].fair_value":
        payload["items"][0]["fair_value"]["amount"] = "01.00"  # type: ignore[index]
    elif money_field == "units[0].carrying_amount":
        payload["units"][0]["carrying_amount"]["amount"] = "01.00"  # type: ignore[index]
    else:
        payload[money_field]["amount"] = "01.00"  # type: ignore[index]
    value = request_model.model_validate(payload)  # type: ignore[attr-defined]

    with pytest.raises(APIError, match="monetary input"):
        value.to_domain(prepared_by="api-preparer")  # type: ignore[attr-defined]


def test_intercompany_api_line_rejects_noncanonical_amount_text() -> None:
    payload = _payload()
    payload["amount"] = "01.00"
    line = IntercompanyLineRequest(
        transaction_id="TX-1",
        period_name="2026-08",
        entity_code="ENTITY-A",
        counterparty_code="ENTITY-B",
        reference="IC-1",
        group_account_code="IC-RECEIVABLE",
        account_type="Asset",
        amount=IntercompanyMoneyRequest.model_validate(payload),
        source_reference="ledger:TX-1",
        source_digest="a" * 64,
    )

    with pytest.raises(APIError, match="deterministic validation"):
        line.to_domain()
