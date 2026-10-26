"""Independent global SQLite60 authority migration atomicity and legacy custody."""
import sqlite3
from pathlib import Path

import pytest

from reconforge.db.connection import DatabaseError
from reconforge.db.migrations import run_migrations


def legacy(path: Path):
    run_migrations(path, target_version=59)
    with sqlite3.connect(path) as connection:
        connection.execute("""INSERT INTO quality_ncrs
        (workspace_id,ncr_id,lot_id,work_order_id,defect_code,defect_severity,inspector_id,quarantined_quantity_scaled,status,created_at)
        VALUES('default','LEGACY-MIGRATION','SYN-LOT','SYN-WO','SYN-DEFECT','major','legacy-display-name',1000,'open','2026-10-26T00:00:00Z')""")
        return connection.execute("SELECT * FROM quality_ncrs").fetchall()


def test_upgrade_preserves_legacy_without_invented_authority(tmp_path: Path) -> None:
    path = tmp_path / "quality.sqlite"
    before = legacy(path)
    status = run_migrations(path, target_version=60)
    assert status.applied_versions == [60]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM quality_ncrs").fetchall() == before
        assert connection.execute("SELECT * FROM quality_ncr_actor_authorities").fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.parametrize("failure", ["marker", "last-ddl"])
def test_global_migration_failure_rolls_back_all_ddl_marker_and_legacy_rows(tmp_path: Path, monkeypatch, failure: str) -> None:
    import reconforge.db.migrations as migrations

    path = tmp_path / "quality.sqlite"
    before = legacy(path)
    if failure == "marker":
        with sqlite3.connect(path) as connection:
            connection.execute("""CREATE TRIGGER reject_quality_marker BEFORE INSERT ON schema_migrations
            WHEN NEW.version=60 BEGIN SELECT RAISE(ABORT,'Synthetic migration marker failure'); END""")
    else:
        real_connect = migrations.connect
        def restricted_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            def authorize(action, name, *_):
                return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER and name == "quality_ncr_authority_insert_guard" else sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            return connection
        monkeypatch.setattr(migrations, "connect", restricted_connect)
    with pytest.raises(DatabaseError):
        run_migrations(path, target_version=60)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM quality_ncrs").fetchall() == before
        assert connection.execute("PRAGMA user_version").fetchone() == (59,)
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (59,)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='quality_ncr_actor_authorities' OR name LIKE 'quality_ncr_authority_%' OR name='quality_ncr_scope_identity'").fetchall() == []
