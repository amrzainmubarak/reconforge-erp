"""Held/engineering sources cannot enter the public receiving factory."""

import pytest

from reconforge.domain.inventory_receipt_posting import InventoryReceiptPostingError
from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository


@pytest.mark.parametrize("prefix", ["ME2-", "ME2W-", "ME2R-", "ME2P-", "ME2K-", "ME2X-"])
@pytest.mark.parametrize("lower", [False, True])
def test_nonreceipt_manufacturing_identity_is_refused_before_database_or_participant_admission(prefix: str, lower: bool) -> None:
    # No connection can be accessed on this deliberately uninitialized receiver.
    # The public precondition must reject even a supplied arbitrary owner object.
    receiver = object.__new__(PostgresInventoryReceiptPostingRepository)
    number = prefix + "reserved-source"
    with pytest.raises(InventoryReceiptPostingError) as refusal:
        receiver._manufacturing_source("unused", number.lower() if lower else number, object())
    assert refusal.value.code == "inventory_receipt_owner_required"
