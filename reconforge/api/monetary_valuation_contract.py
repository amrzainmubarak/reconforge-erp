"""Closed source-owned FX valuation evidence, without generic FX payloads."""

import re
from collections.abc import Mapping
from typing import Any

from reconforge.api.monetary_public_contract import (
    calendar,
    closed,
    digest,
    integer,
    minor,
    paired_policies,
    rate,
    require,
    scope_of,
    text,
)

VALUATION_FIELDS = frozenset({
    "schema_version", "id", "source_order_id", "fx_source_id", "workspace_id", "organization_id", "legal_entity_id",
    "fx_source_digest", "origin_digest", "kind", "status", "phase", "plan_digest", "period_id", "posting_date", "reason",
    "transaction_policy", "functional_policy", "monetary", "closing_rate", "unrealized_gain_account_code", "unrealized_loss_account_code",
    "original_id", "entry_id", "validation_digest", "posting_effect_id", "preparer_actor_id", "reviewer_actor_id", "posted_actor_id",
})
VALUATION_AMOUNTS = frozenset({
    "transaction_outstanding_minor", "functional_historical_outstanding_minor", "functional_valued_outstanding_minor",
    "functional_unrealized_gain_minor", "functional_unrealized_loss_minor", "functional_turnover_minor",
})


def project_monetary_valuation(value: Any, scope: Mapping[str, Any], source_id: str, plan_id: str | None = None) -> dict[str, Any]:
    row = closed(value, VALUATION_FIELDS)
    require(row["schema_version"] == "stock-monetary-valuation-v1" and row["source_order_id"] == source_id)
    scope_of(row, scope)
    for key in ("id", "source_order_id", "fx_source_id", "period_id", "entry_id", "preparer_actor_id"):
        text(row[key])
    require(re.fullmatch(r"FX1-[a-f0-9]{32}", row["id"]) is not None and (plan_id is None or row["id"] == plan_id))
    for key in ("fx_source_digest", "origin_digest", "plan_digest", "validation_digest"):
        digest(row[key])
    for key in ("unrealized_gain_account_code", "unrealized_loss_account_code"):
        require(type(row[key]) is str and re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", row[key]) is not None)
    require(row["unrealized_gain_account_code"] != row["unrealized_loss_account_code"])
    text(row["reason"], maximum=500)
    calendar(row["posting_date"])
    transaction, functional = paired_policies(row["transaction_policy"], row["functional_policy"])
    require(transaction["currency_code"] != functional["currency_code"])
    integer(row["phase"], maximum=2)
    require(row["status"] == ("Prepared", "Reviewed", "Posted")[row["phase"]]
            and row["kind"] in {"revalue", "reverse_revaluation"})
    inverse = row["kind"] == "reverse_revaluation"
    if inverse:
        text(row["original_id"])
        require(re.fullmatch(r"FX1-[a-f0-9]{32}", row["original_id"]) is not None and row["original_id"] != row["id"])
    else:
        require(row["original_id"] is None)
    # An inverse copies the original UTC rate observation; its later accounting
    # date cannot rewrite that provenance into a new observation.
    observation = row["closing_rate"]
    require(type(observation) is dict and type(observation.get("effective_at")) is str)
    day = observation["effective_at"][:10] if inverse else row["posting_date"]
    row["closing_rate"] = rate(observation, day=day, identity=False)
    require(not inverse or day <= row["posting_date"])
    amounts = closed(row["monetary"], VALUATION_AMOUNTS)
    numbers = {key: minor(value, positive=key == "transaction_outstanding_minor") for key, value in amounts.items()}
    gain, loss = numbers["functional_unrealized_gain_minor"], numbers["functional_unrealized_loss_minor"]
    require((gain == 0) != (loss == 0)
            and numbers["functional_valued_outstanding_minor"] - numbers["functional_historical_outstanding_minor"] == gain - loss
            and numbers["functional_turnover_minor"] == gain + loss)
    for key in ("reviewer_actor_id", "posted_actor_id", "posting_effect_id"):
        text(row[key], nullable=True)
    require((row["reviewer_actor_id"] is not None) == (row["phase"] >= 1)
            and (row["posted_actor_id"] is not None) == (row["phase"] == 2)
            and (row["posting_effect_id"] is not None) == (row["phase"] == 2))
    if row["phase"] >= 1:
        require(row["reviewer_actor_id"] != row["preparer_actor_id"])
    if row["phase"] == 2:
        require(row["posted_actor_id"] not in {row["preparer_actor_id"], row["reviewer_actor_id"]})
    return {**row, "transaction_policy": transaction, "functional_policy": functional, "monetary": amounts}
