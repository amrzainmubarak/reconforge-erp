"""Native malformed JSONB restrictions cannot publish a capacity reservation."""
import os

import pytest

from reconforge.domain.manufacturing_capacity_scheduling import CapacitySchedulingError, CapacitySlotReservation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_manufacturing_capacity import PostgresManufacturingCapacityRepository
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime, receipt_database  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Native capacity persisted-data oracle requires owned PostgreSQL; review2026-10-26",
)


@pytest.mark.parametrize("corrupt", ["blackouts", "weekdays", "noncanonical-date"])
def test_native_corrupt_calendar_cannot_create_a_reservation(receipt_database, corrupt: str) -> None:  # noqa: F811
    runtime = create_receipt_runtime(receipt_database)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        connection.execute(
            "INSERT INTO reconforge.workcenter_calendars(tenant_id,workspace_id,workcenter_id,name,daily_capacity_minutes,blackout_dates) "
            "VALUES(%s,'work','QA-CENTER','Synthetic malformed persisted calendar',60,%s::jsonb)",
            (runtime.tenant, '{"2026-10-26":true}' if corrupt == "blackouts" else '["20261026"]' if corrupt == "noncanonical-date" else '[]'),
        )
        connection.execute(
            "INSERT INTO reconforge.workcenter_shifts(tenant_id,workspace_id,workcenter_id,shift_id,name,start_minute,end_minute,break_minutes,days_of_week) "
            "VALUES(%s,'work','QA-CENTER','QA-SHIFT','Synthetic shift',480,540,0,%s::jsonb)",
            (runtime.tenant, '[true]' if corrupt == "weekdays" else '[0,1,2,3,4]'),
        )
        before = connection.execute(
            "SELECT to_jsonb(r)::text FROM reconforge.capacity_slot_reservations r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text",
            (runtime.tenant,),
        ).fetchall()
        repository = PostgresManufacturingCapacityRepository(connection, runtime.tenant)
        with pytest.raises(CapacitySchedulingError) as failure:
            repository.book_slot(workspace_id="work", slot=CapacitySlotReservation(
                "QA-RESERVATION", "QA-CENTER", "QA-ORDER", 1, "2026-10-26", 30,
            ))
        assert failure.value.code == "capacity_persisted_data_invalid"
        assert connection.execute(
            "SELECT to_jsonb(r)::text FROM reconforge.capacity_slot_reservations r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text",
            (runtime.tenant,),
        ).fetchall() == before == []
