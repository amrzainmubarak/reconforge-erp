"""Early shared inventory gates; existing physical/FIFO arithmetic stays native."""

from collections.abc import Iterable, Mapping
from typing import Any


def lock_inventory_quantity_pools(
    connection: Any, tenant_id: str, workspace_id: str, legal_entity_id: str, item_ids: Iterable[str],
) -> None:
    """Preacquire sorted shared gates before old physical/FIFO locks.

    Older supported database revisions have no planning custody. This check is
    deliberately connection-local and uncached, so migration/revocation cannot
    leave a stale process-wide belief. Reads never call this mutation helper.
    SQL mutation triggers independently fence direct writers at the new head.
    """
    items = sorted(set(item_ids))
    if not items:
        return
    row = connection.execute(
        "SELECT to_regprocedure('reconforge.inventory_quantity_source_pool_lock(text,text,text,text)') AS installed",
    ).fetchone()
    installed = row["installed"] if isinstance(row, Mapping) else row[0]
    if installed is None:
        return
    for item_id in items:
        connection.execute(
            "SELECT reconforge.inventory_quantity_source_pool_lock(%s,%s,%s,%s)",
            (tenant_id, workspace_id, legal_entity_id, item_id),
        )
