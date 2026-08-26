from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict[str, object]:
    payload = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_community_compose_is_a_single_local_sqlite_service() -> None:
    compose = _compose()
    assert compose["name"] == "reconforge-community"

    services = compose["services"]
    assert isinstance(services, dict)
    service = services["reconforge"]
    assert isinstance(service, dict)

    assert service["image"] == "reconforge:community-local"
    assert service["build"] == {"context": ".", "dockerfile": "Dockerfile"}
    command = service["command"]
    assert isinstance(command, list)
    command_text = " ".join(str(part) for part in command)
    assert "reconforge db init --db /data/reconforge.db" in command_text
    assert "reconforge api serve --db /data/reconforge.db" in command_text
    assert "--host 0.0.0.0 --port 8765" in command_text

    assert service["ports"] == ["127.0.0.1:8765:8765"]
    assert service["volumes"] == ["reconforge-data:/data"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]


def test_community_compose_has_internal_network_and_local_health_contract() -> None:
    compose = _compose()
    services = compose["services"]
    assert isinstance(services, dict)
    service = services["reconforge"]
    assert isinstance(service, dict)
    assert service["networks"] == ["local"]

    networks = compose["networks"]
    assert isinstance(networks, dict)
    assert networks["local"] == {"internal": True}

    healthcheck = service["healthcheck"]
    assert isinstance(healthcheck, dict)
    test_command = healthcheck["test"]
    assert isinstance(test_command, list)
    assert test_command[:3] == ["CMD", "python", "-c"]
    assert "/api/v1/health" in str(test_command[3])
    assert healthcheck["retries"] == 10
    assert healthcheck["start_period"] == "15s"

    assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=16m"]
    assert service["stop_grace_period"] == "10s"
