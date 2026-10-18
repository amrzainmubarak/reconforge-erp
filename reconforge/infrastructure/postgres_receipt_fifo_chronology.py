"""Additive FIFO chronology scope correction; historical source SQL stays frozen.

Untracked receipt costing shares the entity/item pool across physical warehouses.
An unrelated item cannot alter its FIFO costs. Ordering and consumed-layer guards
within the affected pool remain unchanged, including same-day reserved ordering.
"""
from typing import Any

from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import _LINK_SQL

DOWNGRADE_SQL = _LINK_SQL
_EARLIER = "AND m.status='Posted' AND m.movement_type<>'Transfer'"
_LATER = "AND v.status='Approved' AND (m.movement_date,m.movement_number)"
_SCOPE = "EXISTS(SELECT 1 FROM reconforge.inventory_movement_lines l WHERE l.tenant_id=m.tenant_id AND l.movement_id=m.id AND l.item_id=p.item_id)"
if DOWNGRADE_SQL.count(_EARLIER) != 1 or DOWNGRADE_SQL.count(_LATER) != 1:
    raise RuntimeError("Frozen receipt link guard changed; review the forward chronology migration")
UPGRADE_SQL = DOWNGRADE_SQL.replace(_EARLIER, f"AND {_SCOPE} {_EARLIER}", 1).replace(
    _LATER, f"AND {_SCOPE} {_LATER}", 1)


def install_postgres_receipt_fifo_chronology(connection: Any) -> None:
    connection.execute(UPGRADE_SQL)
