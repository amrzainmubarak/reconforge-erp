"""Protect in-memory synthetic browser fixture metadata."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_release_product_browser_runtime import install_browser_fixture_endpoint


def test_fixture_endpoint_requires_independent_key_and_never_returns_credentials(tmp_path):
    app = FastAPI()
    fixture = {"tenant": "example", "employee_id": "synthetic", "restricted_username": "reviewer"}
    key = "a" * 64
    install_browser_fixture_endpoint(app, fixture, key)
    with TestClient(app) as client:
        assert client.get("/__test/browser-fixture").status_code == 403
        assert client.get("/__test/browser-fixture", headers={"x-reconforge-fixture-key": "wrong"}).status_code == 403
        response = client.get("/__test/browser-fixture", headers={"x-reconforge-fixture-key": key})
        assert response.status_code == 200
        assert response.json() == fixture
        assert response.headers["cache-control"] == "no-store"
    assert not (tmp_path / "browser-fixture.json").exists()


def test_fixture_endpoint_rejects_credentials_and_weak_keys():
    app = FastAPI()
    with pytest.raises(ValueError, match="unexpected fields"):
        install_browser_fixture_endpoint(app, {"tenant": "example", "password": "synthetic-secret"}, "a" * 64)
    with pytest.raises(ValueError, match="fixture key"):
        install_browser_fixture_endpoint(app, {"tenant": "example"}, "short")
