"""Fail-closed resource limits for local JSON and YAML documents."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, NoReturn

import yaml

from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
)
from reconforge.utils.yaml import DuplicateYamlKeyError, load_safe_yaml

CURRENT_STRUCTURED_DOCUMENT_POLICY = "structured-document-ingress-v1"
_JSON_SUFFIXES = frozenset({".json"})
_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


class StructuredDocumentError(ValueError):
    """Safe document rejection containing only a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Input document rejected ({code}).")


@dataclass(frozen=True)
class StructuredDocumentPolicy:
    """Byte and object-graph ceilings for one JSON or YAML document."""

    policy_id: str = CURRENT_STRUCTURED_DOCUMENT_POLICY
    max_file_bytes: int = 8 * 1024 * 1024
    max_nodes: int = 200_000
    max_depth: int = 64
    max_collection_items: int = 100_000
    max_scalar_characters: int = 1_000_000
    max_yaml_aliases: int = 64

    def __post_init__(self) -> None:
        values = (
            self.max_file_bytes,
            self.max_nodes,
            self.max_depth,
            self.max_collection_items,
            self.max_scalar_characters,
            self.max_yaml_aliases,
        )
        if self.policy_id != CURRENT_STRUCTURED_DOCUMENT_POLICY or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values
        ):
            raise ValueError("Invalid structured document policy")


DEFAULT_STRUCTURED_DOCUMENT_POLICY = StructuredDocumentPolicy()


def _reject(code: str) -> NoReturn:
    raise StructuredDocumentError(code)


def _read_text(
    path: Path | str,
    *,
    suffixes: frozenset[str],
    allow_blank: bool,
    policy: StructuredDocumentPolicy,
) -> str:
    source = Path(path)
    if source.suffix.lower() not in suffixes:
        _reject("document_type_unsupported")
    try:
        if source.is_symlink() or not source.exists() or not source.is_file():
            _reject("document_not_regular")
        size = source.stat().st_size
        if size > policy.max_file_bytes:
            _reject("document_size_limit")
        with source.open("rb") as handle:
            payload = handle.read(policy.max_file_bytes + 1)
    except StructuredDocumentError:
        raise
    except OSError as exc:
        raise StructuredDocumentError("document_unreadable") from exc
    if len(payload) != size or len(payload) > policy.max_file_bytes:
        _reject("document_size_changed")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise StructuredDocumentError("document_encoding_invalid") from exc
    if not allow_blank and not text.strip():
        _reject("document_empty")
    return text


def _validate_graph(value: object, policy: StructuredDocumentPolicy) -> None:
    stack: list[tuple[object, int, bool]] = [(value, 1, False)]
    active_containers: set[int] = set()
    nodes = 0
    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue
        nodes += 1
        if nodes > policy.max_nodes:
            _reject("document_node_limit")
        if depth > policy.max_depth:
            _reject("document_depth_limit")

        children: list[object] | None = None
        if isinstance(current, Mapping):
            if len(current) > policy.max_collection_items:
                _reject("document_collection_limit")
            children = []
            for key, item in current.items():
                children.extend((key, item))
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if len(current) > policy.max_collection_items:
                _reject("document_collection_limit")
            children = list(current)

        if children is not None:
            identity = id(current)
            if identity in active_containers:
                _reject("document_cycle_forbidden")
            active_containers.add(identity)
            stack.append((current, depth, True))
            stack.extend((child, depth + 1, False) for child in reversed(children))
            continue

        if isinstance(current, float) and not math.isfinite(current):
            _reject("document_non_finite_number")
        if isinstance(current, str) and len(current) > policy.max_scalar_characters:
            _reject("document_scalar_limit")
        if not isinstance(current, (str, int, float, bool, type(None), date, datetime)):
            _reject("document_value_type_unsupported")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("json_duplicate_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> NoReturn:
    _reject("document_non_finite_number")


def _reject_json_fraction(_value: str) -> NoReturn:
    _reject("document_fractional_number_forbidden")


def parse_json_document(
    text: str,
    *,
    preserve_float_lexemes: bool = False,
    reject_fractional_numbers: bool = False,
    policy: StructuredDocumentPolicy = DEFAULT_STRUCTURED_DOCUMENT_POLICY,
) -> object:
    """Parse bounded JSON text with duplicate-key and non-finite rejection.

    When ``preserve_float_lexemes`` is true, JSON fractional/exponent numbers
    are returned as their exact source strings. When ``reject_fractional_numbers``
    is true, those tokens fail closed. Integer tokens remain integers.
    """

    if preserve_float_lexemes and reject_fractional_numbers:
        raise ValueError("JSON fractional-number modes are mutually exclusive")

    if len(text) > policy.max_file_bytes:
        _reject("document_size_limit")
    try:
        encoded_size = len(text.encode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise StructuredDocumentError("document_encoding_invalid") from exc
    if encoded_size > policy.max_file_bytes:
        _reject("document_size_limit")
    if not text.strip():
        _reject("document_empty")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_float=(
                _reject_json_fraction
                if reject_fractional_numbers
                else str if preserve_float_lexemes else float
            ),
            parse_constant=_reject_json_constant,
        )
    except StructuredDocumentError:
        raise
    except (ValueError, RecursionError) as exc:
        raise StructuredDocumentError("json_structure_invalid") from exc
    _validate_graph(payload, policy)
    return payload


def read_json_document(
    path: Path | str,
    *,
    preserve_float_lexemes: bool = False,
    policy: StructuredDocumentPolicy = DEFAULT_STRUCTURED_DOCUMENT_POLICY,
) -> object:
    """Read one bounded UTF-8 JSON file."""

    text = _read_text(path, suffixes=_JSON_SUFFIXES, allow_blank=False, policy=policy)
    return parse_json_document(
        text,
        preserve_float_lexemes=preserve_float_lexemes,
        policy=policy,
    )


def _preflight_yaml(text: str, policy: StructuredDocumentPolicy) -> None:
    aliases = 0
    nodes = 0
    depth = 0
    documents = 0
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.events.DocumentStartEvent):
                documents += 1
                if documents > 1:
                    _reject("yaml_multiple_documents")
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                nodes += 1
                depth += 1
                if depth > policy.max_depth:
                    _reject("document_depth_limit")
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.events.ScalarEvent):
                nodes += 1
                if len(event.value) > policy.max_scalar_characters:
                    _reject("document_scalar_limit")
                implicit_merge = event.value == "<<" and event.implicit[0]
                if event.tag == "tag:yaml.org,2002:merge" or implicit_merge:
                    _reject("yaml_merge_forbidden")
            elif isinstance(event, yaml.events.AliasEvent):
                nodes += 1
                aliases += 1
                if aliases > policy.max_yaml_aliases:
                    _reject("yaml_alias_limit")
            if nodes > policy.max_nodes:
                _reject("document_node_limit")
    except StructuredDocumentError:
        raise
    except (yaml.YAMLError, RecursionError) as exc:
        raise StructuredDocumentError("yaml_structure_invalid") from exc


def parse_yaml_document(
    text: str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    policy: StructuredDocumentPolicy = DEFAULT_STRUCTURED_DOCUMENT_POLICY,
) -> object:
    """Parse one bounded safe YAML document with exact optional financial lexemes."""

    if len(text) > policy.max_file_bytes:
        _reject("document_size_limit")
    try:
        encoded_size = len(text.encode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise StructuredDocumentError("document_encoding_invalid") from exc
    if encoded_size > policy.max_file_bytes:
        _reject("document_size_limit")
    _preflight_yaml(text, policy)
    try:
        payload = load_safe_yaml(
            text,
            financial_input_policy=financial_input_policy,
            reject_duplicate_keys=True,
        )
    except DuplicateYamlKeyError as exc:
        raise StructuredDocumentError("yaml_duplicate_key") from exc
    except StructuredDocumentError:
        raise
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        raise StructuredDocumentError("yaml_structure_invalid") from exc
    _validate_graph(payload, policy)
    return payload


def read_yaml_document(
    path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    policy: StructuredDocumentPolicy = DEFAULT_STRUCTURED_DOCUMENT_POLICY,
) -> object:
    """Read one bounded UTF-8 YAML file; a blank file remains the YAML null value."""

    text = _read_text(path, suffixes=_YAML_SUFFIXES, allow_blank=True, policy=policy)
    return parse_yaml_document(
        text,
        financial_input_policy=financial_input_policy,
        policy=policy,
    )


__all__ = [
    "CURRENT_STRUCTURED_DOCUMENT_POLICY",
    "DEFAULT_STRUCTURED_DOCUMENT_POLICY",
    "StructuredDocumentError",
    "StructuredDocumentPolicy",
    "parse_json_document",
    "parse_yaml_document",
    "read_json_document",
    "read_yaml_document",
]
