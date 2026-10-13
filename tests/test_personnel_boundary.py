"""Personnel configuration/auth admission without a live database claim."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from typer.testing import CliRunner

from reconforge.api.app import create_api_app
from reconforge.api.errors import APIError
from reconforge.api.server_personnel import (
    PERSONNEL_PERMISSION,
    execute_postgres_personnel_scoped,
    validate_personnel_database_pair,
)
from reconforge.auth.models import LocalUser
from reconforge.cli import app
from reconforge.platform.common import ServerPrincipal, server_principal_context

ORDINARY = "postgresql://ordinary:SyntheticOnly@127.0.0.1:5432/erp"
PERSONNEL = "postgresql://personnel:SyntheticOnly@127.0.0.1:5432/erp"


@pytest.mark.parametrize("private", [
    ORDINARY, PERSONNEL.replace("/erp", "/other"), PERSONNEL.replace("127.0.0.1", "localhost"),
    PERSONNEL.replace(":5432", ":5433"), "user=personnel dbname=erp", "service=personnel",
    "invalid=SyntheticOnly", "",
])
def test_personnel_configuration_refuses_ambiguous_or_unseparated_credentials(private: str) -> None:
    with pytest.raises(ValueError) as caught:
        validate_personnel_database_pair(ORDINARY, private)
    assert "SyntheticOnly" not in str(caught.value)
    assert private not in str(caught.value) or private == ""


def test_explicit_personnel_role_pair_and_independent_factory_preserve_default_profile(tmp_path: Path) -> None:
    validate_personnel_database_pair(ORDINARY, PERSONNEL)
    normal = create_api_app(tmp_path / "normal.db", tenant_db_root=tmp_path, postgres_dsn=ORDINARY, postgres_require_tls=False)
    assert normal.state.postgres_personnel_factory is None
    assert normal.state.postgres_finance_core_factory is normal.state.postgres_identity_factory
    private = create_api_app(tmp_path / "private.db", tenant_db_root=tmp_path, postgres_dsn=ORDINARY,
                             postgres_personnel_dsn=PERSONNEL, postgres_require_tls=False)
    assert private.state.postgres_personnel_factory is not private.state.postgres_identity_factory
    assert private.state.postgres_finance_core_factory is private.state.postgres_identity_factory
    assert "SyntheticOnly" not in repr(private.state.postgres_personnel_factory.settings)
    # Pools have no leases here; close both configured resources explicitly.
    normal.state.postgres_identity_factory.close()
    private.state.postgres_identity_factory.close()
    private.state.postgres_personnel_factory.close()


def test_private_profile_requires_existing_server_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="server identity profile"):
        create_api_app(tmp_path / "local.db", postgres_personnel_dsn=PERSONNEL)


@pytest.mark.parametrize("service,disabled,permission,step_up", [
    (False, True, True, True), (True, False, True, True),
    (False, False, False, True), (False, False, True, False),
])
def test_sensitive_admission_denies_before_any_database_access(service: bool, disabled: bool, permission: bool, step_up: bool) -> None:
    request = Request({"type": "http", "app": FastAPI(), "headers": [], "method": "GET", "path": "/"})
    principal = ServerPrincipal(
        user=LocalUser(id="synthetic-user", username="synthetic", display_name="Synthetic", disabled=disabled),
        permissions=frozenset({PERSONNEL_PERMISSION}) if permission else frozenset(),
        principal_type="service_account" if service else "user", step_up_active=step_up,
    )
    with server_principal_context(principal), pytest.raises(APIError) as caught:
        execute_postgres_personnel_scoped(request, lambda *_: pytest.fail("Unadmitted operation executed"))
    assert caught.value.status_code == 403


def test_missing_personnel_factory_is_unavailable_after_authenticated_admission() -> None:
    request = Request({"type": "http", "app": FastAPI(), "headers": [], "method": "GET", "path": "/"})
    principal = ServerPrincipal(
        user=LocalUser(id="synthetic-user", username="synthetic", display_name="Synthetic"),
        permissions=frozenset({PERSONNEL_PERMISSION}), step_up_active=True,
    )
    with server_principal_context(principal), pytest.raises(APIError) as caught:
        execute_postgres_personnel_scoped(request, lambda *_: pytest.fail("Unconfigured operation executed"))
    assert caught.value.status_code == 503


def test_cli_personnel_environment_uses_separate_pool_without_exposing_credentials(tmp_path: Path, monkeypatch: Any) -> None:
    started: list[FastAPI] = []

    def run(application: FastAPI, **kwargs: Any) -> None:
        started.append(application)

    monkeypatch.setattr("reconforge.cli.uvicorn.run", run)
    result = CliRunner().invoke(
        app, ["api", "serve", "--db", str(tmp_path / "unused.db"), "--tenant-db-root", str(tmp_path), "--postgres-no-tls"],
        env={"RECONFORGE_POSTGRES_DSN": ORDINARY, "RECONFORGE_PERSONNEL_POSTGRES_DSN": PERSONNEL},
    )
    assert result.exit_code == 0, result.output
    assert "SyntheticOnly" not in result.output
    assert len(started) == 1
    assert started[0].state.postgres_personnel_factory.settings.dsn == PERSONNEL
    assert started[0].state.postgres_identity_factory.settings.dsn == ORDINARY
    started[0].state.postgres_personnel_factory.close()
    started[0].state.postgres_identity_factory.close()
