"""Keep synthetic browser login credentials out of retained evidence."""
import json

import pytest

from tests.test_release_product_browser_runtime import write_public_fixture


def test_browser_fixture_rejects_credentials_before_writing(tmp_path):
    with pytest.raises(ValueError, match="unexpected fields"):
        write_public_fixture(tmp_path, {"tenant": "example", "password": "synthetic-secret"})
    assert not (tmp_path / "browser-fixture.json").exists()


def test_browser_fixture_retains_only_nonsecret_identifiers(tmp_path):
    fixture = {"tenant": "example", "employee_id": "synthetic", "restricted_username": "reviewer"}
    write_public_fixture(tmp_path, fixture)
    assert json.loads((tmp_path / "browser-fixture.json").read_text(encoding="utf-8")) == fixture
