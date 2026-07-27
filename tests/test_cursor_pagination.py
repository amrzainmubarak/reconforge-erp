from __future__ import annotations

import base64
import json

import pytest

from reconforge.application.pagination import (
    CursorCodec,
    CursorError,
    CursorPosition,
    KeysetPaginator,
    SortDefinition,
    cursor_scope_digest,
)

KEY = b"reconforge-test-cursor-key-32bytes-minimum"


def _paginator() -> KeysetPaginator:
    return KeysetPaginator(CursorCodec(KEY), [SortDefinition("created", ("created_at",))])


def _records() -> list[dict[str, object]]:
    return [
        {"id": "A", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "B", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "C", "created_at": "2026-01-02T00:00:00Z"},
        {"id": "D", "created_at": "2026-01-03T00:00:00Z"},
    ]


def test_cursor_round_trip_is_opaque_deterministic_and_context_bound() -> None:
    codec = CursorCodec(KEY)
    scope = cursor_scope_digest({"tenant": "tenant-a", "status": "open"})
    position = CursorPosition("created", "asc", scope, ("2026-01-01T00:00:00Z",), "B")
    token = codec.encode(position)
    assert token == codec.encode(position)
    assert codec.decode(token) == position
    assert "tenant-a" not in token and "created_at" not in token


@pytest.mark.parametrize("mutation", ["payload", "signature", "truncated", "oversized"])
def test_cursor_rejects_mutation_and_resource_abuse(mutation: str) -> None:
    codec = CursorCodec(KEY)
    token = codec.encode(CursorPosition("created", "asc", "a" * 64, ("x",), "ID"))
    payload, signature = token.split(".")
    if mutation == "payload":
        token = ("A" if payload[0] != "A" else "B") + payload[1:] + "." + signature
    elif mutation == "signature":
        token = payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    elif mutation == "truncated":
        token = payload
    else:
        token = "A" * 4097
    with pytest.raises(CursorError):
        codec.decode(token)


def test_cursor_rejects_validly_signed_unknown_or_ambiguous_payload() -> None:
    codec = CursorCodec(KEY)
    valid = codec.encode(CursorPosition("created", "asc", "b" * 64, ("x",), "ID"))
    payload_text, _ = valid.split(".")
    payload = json.loads(base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4)))
    payload["extra"] = True
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    import hmac

    forged = (
        base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()
        + "."
        + base64.urlsafe_b64encode(hmac.digest(KEY, encoded, "sha256")).rstrip(b"=").decode()
    )
    with pytest.raises(CursorError, match="payload"):
        codec.decode(forged)


def test_keyset_pages_duplicate_sort_values_without_skip_or_repeat() -> None:
    paginator = _paginator()
    scope = cursor_scope_digest({"tenant": "tenant-a", "status": "all"})
    first = paginator.page(_records(), sort_key="created", direction="asc", scope_digest=scope, limit=2)
    second = paginator.page(
        _records(), sort_key="created", direction="asc", scope_digest=scope,
        limit=2, cursor=first.next_cursor,
    )
    assert [row["id"] for row in first.items] == ["A", "B"]
    assert [row["id"] for row in second.items] == ["C", "D"]
    assert first.next_cursor is not None and second.next_cursor is None


def test_keyset_cursor_survives_insert_delete_and_descending_order() -> None:
    paginator = _paginator()
    scope = cursor_scope_digest({"tenant": "tenant-a"})
    first = paginator.page(_records(), sort_key="created", direction="asc", scope_digest=scope, limit=2)
    changed = [record for record in _records() if record["id"] != "B"]
    changed.extend([
        {"id": "AA", "created_at": "2025-12-31T00:00:00Z"},
        {"id": "E", "created_at": "2026-01-02T00:00:00Z"},
    ])
    second = paginator.page(
        changed, sort_key="created", direction="asc", scope_digest=scope,
        limit=3, cursor=first.next_cursor,
    )
    assert [row["id"] for row in second.items] == ["C", "E", "D"]
    descending = paginator.page(_records(), sort_key="created", direction="desc", scope_digest=scope, limit=4)
    assert [row["id"] for row in descending.items] == ["D", "C", "B", "A"]


def test_cursor_rejects_filter_sort_direction_and_key_mismatch() -> None:
    paginator = _paginator()
    scope = cursor_scope_digest({"tenant": "tenant-a", "status": "open"})
    first = paginator.page(_records(), sort_key="created", direction="asc", scope_digest=scope, limit=1)
    for changed_scope, direction, sort_key in (
        (cursor_scope_digest({"tenant": "tenant-b", "status": "open"}), "asc", "created"),
        (scope, "desc", "created"),
        (scope, "asc", "unknown"),
    ):
        with pytest.raises(CursorError):
            paginator.page(
                _records(), sort_key=sort_key, direction=direction,
                scope_digest=changed_scope, limit=1, cursor=first.next_cursor,
            )


def test_cursor_signing_key_and_sort_definitions_fail_closed() -> None:
    with pytest.raises(CursorError, match="signing_key"):
        CursorCodec(b"short")
    with pytest.raises(CursorError, match="sort_definition"):
        KeysetPaginator(CursorCodec(KEY), [SortDefinition("created", ("created_at",)), SortDefinition("created", ("id",))])
