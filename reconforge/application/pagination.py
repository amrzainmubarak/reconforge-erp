"""Signed opaque cursor and deterministic keyset pagination contracts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, parse_json_document

_CURSOR_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4096,
    max_nodes=64,
    max_depth=4,
    max_collection_items=12,
    max_scalar_characters=512,
    max_yaml_aliases=1,
)
_DIRECTIONS = {"asc", "desc"}


class CursorError(ValueError):
    """Safe cursor rejection with a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Cursor rejected ({code}).")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > 4096 or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
        raise CursorError("cursor_encoding_invalid")
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except ValueError as exc:
        raise CursorError("cursor_encoding_invalid") from exc


def cursor_scope_digest(scope: Mapping[str, str]) -> str:
    """Bind a cursor to allowlisted tenant/filter context without exposing it."""

    if not scope or any(not isinstance(key, str) or not isinstance(value, str) for key, value in scope.items()):
        raise CursorError("cursor_scope_invalid")
    encoded = json.dumps(dict(scope), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CursorPosition:
    """Versioned keyset location bound to one query scope and ordering."""

    sort_key: str
    direction: str
    scope_digest: str
    values: tuple[str | int, ...]
    tie_breaker: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise CursorError("cursor_version_unsupported")
        if not self.sort_key or len(self.sort_key) > 80 or self.direction not in _DIRECTIONS:
            raise CursorError("cursor_order_invalid")
        if len(self.scope_digest) != 64 or any(character not in "0123456789abcdef" for character in self.scope_digest):
            raise CursorError("cursor_scope_invalid")
        if not 1 <= len(self.values) <= 4 or any(
            isinstance(value, bool) or not isinstance(value, (str, int)) for value in self.values
        ):
            raise CursorError("cursor_position_invalid")
        if not self.tie_breaker or len(self.tie_breaker) > 256:
            raise CursorError("cursor_tie_breaker_invalid")


class CursorCodec:
    """Encode and authenticate opaque cursors with an operator-owned key."""

    def __init__(self, signing_key: bytes) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise CursorError("cursor_signing_key_invalid")
        self._signing_key = signing_key

    def encode(self, position: CursorPosition) -> str:
        payload = json.dumps(
            {
                "d": position.direction,
                "p": list(position.values),
                "q": position.scope_digest,
                "s": position.sort_key,
                "t": position.tie_breaker,
                "v": position.schema_version,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        signature = hmac.digest(self._signing_key, payload, "sha256")
        return f"{_b64encode(payload)}.{_b64encode(signature)}"

    def decode(self, token: str) -> CursorPosition:
        if not isinstance(token, str) or not token or len(token) > 4096 or token.count(".") != 1:
            raise CursorError("cursor_token_invalid")
        payload_text, signature_text = token.split(".", 1)
        payload, signature = _b64decode(payload_text), _b64decode(signature_text)
        expected = hmac.digest(self._signing_key, payload, "sha256")
        if len(signature) != len(expected) or not hmac.compare_digest(signature, expected):
            raise CursorError("cursor_signature_invalid")
        try:
            payload_document = payload.decode("utf-8", errors="strict")
            document = parse_json_document(
                payload_document, policy=_CURSOR_POLICY, reject_fractional_numbers=True
            )
        except (StructuredDocumentError, UnicodeDecodeError) as exc:
            raise CursorError("cursor_payload_invalid") from exc
        if not isinstance(document, dict) or set(document) != {"d", "p", "q", "s", "t", "v"}:
            raise CursorError("cursor_payload_invalid")
        values = document["p"]
        if (
            not isinstance(values, list)
            or not isinstance(document["d"], str)
            or not isinstance(document["q"], str)
            or not isinstance(document["s"], str)
            or not isinstance(document["t"], str)
            or isinstance(document["v"], bool)
            or not isinstance(document["v"], int)
        ):
            raise CursorError("cursor_payload_invalid")
        try:
            return CursorPosition(
                sort_key=document["s"], direction=document["d"],
                scope_digest=document["q"], values=tuple(values),
                tie_breaker=document["t"], schema_version=document["v"],
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, CursorError):
                raise
            raise CursorError("cursor_payload_invalid") from exc


@dataclass(frozen=True)
class SortDefinition:
    """Allowlisted public sort mapped to stable record fields."""

    name: str
    fields: tuple[str, ...]
    tie_breaker_field: str = "id"

    def __post_init__(self) -> None:
        if not self.name or not 1 <= len(self.fields) <= 4 or any(not field for field in self.fields):
            raise CursorError("cursor_sort_definition_invalid")
        if not self.tie_breaker_field or self.tie_breaker_field in self.fields:
            raise CursorError("cursor_sort_definition_invalid")


@dataclass(frozen=True)
class CursorPage:
    items: tuple[Mapping[str, object], ...]
    next_cursor: str | None


class KeysetPaginator:
    """Reference keyset implementation proving stable duplicate-free semantics."""

    def __init__(self, codec: CursorCodec, definitions: Sequence[SortDefinition]) -> None:
        self.codec = codec
        self.definitions = {definition.name: definition for definition in definitions}
        if not self.definitions or len(self.definitions) != len(definitions):
            raise CursorError("cursor_sort_definition_invalid")

    @staticmethod
    def _value(record: Mapping[str, object], field: str) -> str | int:
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise CursorError("cursor_record_value_invalid")
        return value

    def page(
        self, records: Sequence[Mapping[str, object]], *, sort_key: str, direction: str,
        scope_digest: str, limit: int, cursor: str | None = None,
    ) -> CursorPage:
        definition = self.definitions.get(sort_key)
        if definition is None or direction not in _DIRECTIONS:
            raise CursorError("cursor_order_invalid")
        if isinstance(limit, bool) or not 1 <= limit <= 500:
            raise CursorError("cursor_limit_invalid")
        if len(scope_digest) != 64 or any(character not in "0123456789abcdef" for character in scope_digest):
            raise CursorError("cursor_scope_invalid")
        boundary: tuple[object, ...] | None = None
        if cursor is not None:
            position = self.codec.decode(cursor)
            if (position.sort_key, position.direction, position.scope_digest) != (sort_key, direction, scope_digest):
                raise CursorError("cursor_context_mismatch")
            if len(position.values) != len(definition.fields):
                raise CursorError("cursor_position_invalid")
            boundary = (*position.values, position.tie_breaker)

        def record_key(record: Mapping[str, object]) -> tuple[object, ...]:
            tie_breaker = self._value(record, definition.tie_breaker_field)
            if not isinstance(tie_breaker, str) or not tie_breaker:
                raise CursorError("cursor_tie_breaker_invalid")
            return (*(self._value(record, field) for field in definition.fields), tie_breaker)

        try:
            ordered = sorted(records, key=record_key, reverse=direction == "desc")
        except TypeError as exc:
            raise CursorError("cursor_record_value_invalid") from exc
        if boundary is not None:
            try:
                ordered = [
                    record for record in ordered
                    if (record_key(record) > boundary if direction == "asc" else record_key(record) < boundary)
                ]
            except TypeError as exc:
                raise CursorError("cursor_record_value_invalid") from exc
        selected = ordered[:limit]
        next_cursor = None
        if len(ordered) > limit and selected:
            last = selected[-1]
            next_cursor = self.codec.encode(CursorPosition(
                sort_key=sort_key, direction=direction, scope_digest=scope_digest,
                values=tuple(self._value(last, field) for field in definition.fields),
                tie_breaker=str(self._value(last, definition.tie_breaker_field)),
            ))
        return CursorPage(tuple(selected), next_cursor)
