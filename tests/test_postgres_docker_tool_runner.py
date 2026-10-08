"""The disposable Docker runner must accept native recovery preflight argv."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

from reconforge.infrastructure.postgres_backup import PostgresBackupSettings, PostgresNativeBackupAdapter


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / ".github/scripts/verify_postgres_upgrade.py"
    spec = spec_from_file_location("docker_tool_runner_contract", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("service,database,expected", [
    ("source", None, "postgres"),
    ("maintenance", None, "postgres"),
    ("maintenance", "reconforge_restore_contract", "reconforge_restore_contract"),
])
@pytest.mark.parametrize("pinned_profile", [False, True])
def test_native_profile_preflight_reaches_container_source_or_isolated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service: str, database: str | None, expected: str,
    pinned_profile: bool,
) -> None:
    module = _module()
    runner = module.DockerPostgresRunner("synthetic-owned-container")
    commands: list[tuple[str, ...]] = []
    scripts: list[str] = []
    monkeypatch.setattr(runner, "_exec", lambda command: commands.append(tuple(command)))
    monkeypatch.setattr(module, "_command", lambda command: scripts.append(Path(command[2]).read_text(encoding="ascii")))
    adapter = PostgresNativeBackupAdapter(
        PostgresBackupSettings(
            source_service="source", maintenance_service="maintenance",
            restore_database="reconforge_restore_contract", tools=module._tools(tmp_path / "tools"),
            recovery_profile="synthetic-pinned-profile" if pinned_profile else None,
            expected_alembic_revision="0106_pg_ap_link_reversal" if pinned_profile else None,
        ),
        runner=runner,
    )
    # Exercise the adapter's real closed preflight command, not a copied argv fixture.
    adapter._verify_recovery_profile(service=service, database=database, action="synthetic profile verification")
    assert len(commands) == 1
    assert commands[0][:5] == ("psql", "-U", "postgres", "-d", expected)
    if pinned_profile:
        assert "--file" in commands[0]
        assert "reconforge_expected_revision=0106_pg_ap_link_reversal" in commands[0]
        assert len(scripts) == 1 and ":'reconforge_expected_revision'" in scripts[0]
    else:
        assert "to_regclass('reconforge.tenants')" in commands[0][-1]
        assert scripts == []
