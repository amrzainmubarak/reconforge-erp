"""Tests for API dependencies (idempotency keys & cursor pagination)."""

from __future__ import annotations

import pytest

from reconforge.api.dependencies import (
    get_cursor_pagination,
    get_idempotency_key,
)
from reconforge.api.errors import APIError


def test_cursor_pagination_defaults() -> None:
    params = get_cursor_pagination()
    assert params.cursor is None
    assert params.limit == 50


def test_cursor_pagination_custom() -> None:
    params = get_cursor_pagination(cursor="eyJsYXN0X2lkIjoxMH0=", limit=100)
    assert params.cursor == "eyJsYXN0X2lkIjoxMH0="
    assert params.limit == 100


def test_cursor_pagination_rejects_blank_cursor() -> None:
    with pytest.raises(APIError) as exc_info:
        get_cursor_pagination(cursor="   ", limit=50)
    assert exc_info.value.code == "invalid_cursor"


def test_idempotency_key_absent() -> None:
    assert get_idempotency_key(None, None) is None


def test_idempotency_key_standard_header() -> None:
    key = get_idempotency_key("repeat-repeat-repeat", None)
    assert key == "repeat-repeat-repeat"


def test_idempotency_key_custom_header_alias() -> None:
    key = get_idempotency_key(None, "x-key-999")
    assert key == "x-key-999"


def test_idempotency_key_rejects_blank() -> None:
    with pytest.raises(APIError) as exc_info:
        get_idempotency_key("   ", None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_idempotency_key"
