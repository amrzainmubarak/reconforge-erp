from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "manage_developer_environment.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("manage_developer_environment", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()
DeveloperEnvironmentError = MODULE.DeveloperEnvironmentError


def test_default_environment_name_is_platform_specific() -> None:
    assert MODULE._default_environment_name("win32") == ".venv-windows"
    assert MODULE._default_environment_name("darwin") == ".venv-macos"
    assert MODULE._default_environment_name("linux") == ".venv-linux"


def test_environment_path_must_be_a_direct_named_project_child(tmp_path: Path) -> None:
    assert MODULE._resolve_environment_path(tmp_path, Path(".venv-windows")) == tmp_path / ".venv-windows"

    for unsafe in (Path(".venv"), Path("nested/.venv-windows"), tmp_path.parent / ".venv-windows"):
        with pytest.raises(DeveloperEnvironmentError, match="direct project child"):
            MODULE._resolve_environment_path(tmp_path, unsafe)


def test_missing_environment_has_stable_non_destructive_finding(tmp_path: Path) -> None:
    target = tmp_path / ".venv-windows"

    result = MODULE._inspect_environment(
        target,
        python_version="3.12",
        platform_name="nt",
        project_root=tmp_path,
        timeout_seconds=1,
    )

    assert result == {
        "code": "DEVENV-ENV-MISSING",
        "detail": "run the non-destructive bootstrap command",
        "path": ".venv-windows",
        "status": "missing",
    }


def test_foreign_environment_is_rejected_without_modification(tmp_path: Path) -> None:
    target = tmp_path / ".venv-windows"
    target.mkdir()
    (target / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    before = (target / "pyvenv.cfg").read_bytes()

    result = MODULE._inspect_environment(
        target,
        python_version="3.12",
        platform_name="nt",
        project_root=tmp_path,
        timeout_seconds=1,
    )

    assert result["code"] == "DEVENV-ENV-FOREIGN"
    assert result["status"] == "failed"
    assert (target / "pyvenv.cfg").read_bytes() == before


def test_activation_command_matches_the_selected_platform(tmp_path: Path) -> None:
    target = tmp_path / ".venv-windows"

    assert MODULE._activation_command(target, "nt", tmp_path) == "& ./.venv-windows/Scripts/Activate.ps1"
    assert MODULE._activation_command(target, "posix", tmp_path) == "source ./.venv-windows/bin/activate"


def test_sync_command_is_locked_complete_and_non_editable() -> None:
    assert MODULE._sync_command("3.12") == [
        "uv",
        "sync",
        "--locked",
        "--all-extras",
        "--no-editable",
        "--python",
        "3.12",
    ]


def test_bootstrap_refuses_a_failed_existing_target_before_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".venv-windows"
    target.mkdir()
    monkeypatch.setattr(MODULE, "_base_context", lambda *_args, **_kwargs: (tmp_path, target, "0.11.32"))
    monkeypatch.setattr(
        MODULE,
        "_inspect_environment",
        lambda *_args, **_kwargs: {
            "code": "DEVENV-ENV-FOREIGN",
            "detail": "foreign",
            "path": ".venv-windows",
            "status": "failed",
        },
    )

    with pytest.raises(DeveloperEnvironmentError, match="manual review"):
        MODULE.bootstrap(
            project_root=tmp_path,
            environment_path=Path(".venv-windows"),
            python_version="3.12",
            timeout_seconds=1,
        )


def test_policy_rejects_unsupported_python() -> None:
    policy = MODULE._load_policy(ROOT)

    assert MODULE._policy_runtime(policy, "3.11") == "0.11.32"
    assert MODULE._policy_runtime(policy, "3.12") == "0.11.32"
    with pytest.raises(DeveloperEnvironmentError, match="outside"):
        MODULE._policy_runtime(policy, "3.14")
