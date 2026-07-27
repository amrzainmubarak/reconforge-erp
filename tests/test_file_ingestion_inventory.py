from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from reconforge.io.ingress import CURRENT_TABULAR_INGRESS_POLICY, DEFAULT_TABULAR_INGRESS_POLICY
from reconforge.io.persisted import (
    FINANCIAL_IDEMPOTENCY_JSON_POLICY,
    FINANCIAL_IDEMPOTENCY_JSON_PROFILE,
    FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA,
)
from reconforge.io.structured import (
    CURRENT_STRUCTURED_DOCUMENT_POLICY,
    DEFAULT_STRUCTURED_DOCUMENT_POLICY,
)
from reconforge.modules.registry import list_modules

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "security" / "file-ingestion-inventory.v1.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "file_ingestion_inventory.schema.json"


def _inventory() -> dict[str, Any]:
    payload = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _qualified_call_name(call: ast.Call) -> str | None:
    function = call.func
    if not isinstance(function, ast.Attribute) or not isinstance(function.value, ast.Name):
        return None
    if function.value.id == "pd" and function.attr in {"read_csv", "read_excel"}:
        return f"pandas.{function.attr}"
    if function.value.id == "csv" and function.attr in {"DictReader", "reader"}:
        return f"csv.{function.attr}"
    return None


def _production_tabular_parser_calls() -> Counter[tuple[str, str]]:
    calls: Counter[tuple[str, str]] = Counter()
    for path in sorted((ROOT / "reconforge").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (name := _qualified_call_name(node)) is not None:
                calls[(relative, name)] += 1
    return calls


def _production_yaml_parser_calls() -> Counter[tuple[str, str]]:
    calls: Counter[tuple[str, str]] = Counter()
    parser_names = {"load", "parse", "safe_load"}
    for path in sorted((ROOT / "reconforge").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        module_aliases = {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "yaml"
        }
        direct_aliases = {
            alias.asname or alias.name: alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "yaml"
            for alias in node.names
            if alias.name in parser_names
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id in module_aliases
                and function.attr in parser_names
            ):
                calls[(relative, f"yaml.{function.attr}")] += 1
            elif isinstance(function, ast.Name) and function.id in direct_aliases:
                calls[(relative, f"yaml.{direct_aliases[function.id]}")] += 1
    return calls


def _production_json_parser_calls() -> Counter[tuple[str, str]]:
    calls: Counter[tuple[str, str]] = Counter()
    for path in sorted((ROOT / "reconforge").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        module_aliases = {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "json"
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id in module_aliases
                and function.attr in {"load", "loads"}
            ):
                calls[(relative, f"json.{function.attr}")] += 1
    return calls


def _declared_python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef):
            symbols.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(f"{node.name}.{child.name}")
    return symbols


def test_file_ingestion_inventory_matches_closed_schema_and_repository() -> None:
    inventory = _inventory()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(inventory)

    active_modules = {module.module_id for module in list_modules()}
    risk_ids = {
        risk["id"]
        for risk in yaml.safe_load((ROOT / "docs" / "risk-register.yaml").read_text(encoding="utf-8"))["risks"]
    }
    surface_ids = [surface["id"] for surface in inventory["surfaces"]]
    assert surface_ids == [f"FI-{number:03d}" for number in range(1, len(surface_ids) + 1)]
    assert len(surface_ids) == len(set(surface_ids))

    for surface in inventory["surfaces"]:
        assert set(surface["module_ids"]) <= active_modules
        assert set(surface["residual_risk_ids"]) <= risk_ids
        for entrypoint in surface["entrypoints"]:
            path_text, symbol = entrypoint.split("::", maxsplit=1)
            path = ROOT / path_text
            assert path.is_file(), entrypoint
            assert symbol in _declared_python_symbols(path), entrypoint
        for evidence in surface["test_evidence"]:
            assert (ROOT / evidence).is_file(), evidence


def test_documented_tabular_policy_is_exactly_the_runtime_default() -> None:
    documented = _inventory()["tabular_policy"]
    runtime = DEFAULT_TABULAR_INGRESS_POLICY
    assert documented == {
        "id": CURRENT_TABULAR_INGRESS_POLICY,
        "implementation": "reconforge/io/ingress.py",
        "accepted_extensions": [".csv", ".xls", ".xlsx"],
        "max_file_bytes": runtime.max_file_bytes,
        "max_rows": runtime.max_rows,
        "max_columns": runtime.max_columns,
        "max_cells": runtime.max_cells,
        "max_csv_field_characters": runtime.max_csv_field_characters,
        "max_archive_members": runtime.max_archive_members,
        "max_archive_member_bytes": runtime.max_archive_member_bytes,
        "max_archive_uncompressed_bytes": runtime.max_archive_uncompressed_bytes,
        "max_archive_compression_ratio": runtime.max_archive_compression_ratio,
    }


def test_documented_structured_policy_is_exactly_the_runtime_default() -> None:
    documented = _inventory()["structured_document_policy"]
    runtime = DEFAULT_STRUCTURED_DOCUMENT_POLICY
    assert documented == {
        "id": CURRENT_STRUCTURED_DOCUMENT_POLICY,
        "implementation": "reconforge/io/structured.py",
        "accepted_extensions": [".json", ".yaml", ".yml"],
        "max_file_bytes": runtime.max_file_bytes,
        "max_nodes": runtime.max_nodes,
        "max_depth": runtime.max_depth,
        "max_collection_items": runtime.max_collection_items,
        "max_scalar_characters": runtime.max_scalar_characters,
        "max_yaml_aliases": runtime.max_yaml_aliases,
    }


def test_documented_financial_idempotency_policy_is_exactly_runtime() -> None:
    documented = _inventory()["persisted_json_policies"]
    runtime = FINANCIAL_IDEMPOTENCY_JSON_POLICY
    assert documented == [
        {
            "id": FINANCIAL_IDEMPOTENCY_JSON_PROFILE,
            "implementation": "reconforge/io/persisted.py",
            "schema_id": FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA,
            "schema_path": "docs/schemas/financial_idempotency_response.schema.json",
            "max_utf8_bytes": runtime.max_file_bytes,
            "max_nodes": runtime.max_nodes,
            "max_depth": runtime.max_depth,
            "max_collection_items": runtime.max_collection_items,
            "max_scalar_characters": runtime.max_scalar_characters,
            "unique_keys": True,
            "object_root": True,
            "integer_number_tokens_only": True,
            "canonical_producer_text": True,
        }
    ]


def test_direct_tabular_parser_inventory_is_an_exact_ast_allowlist() -> None:
    inventory = _inventory()
    declared: Counter[tuple[str, str]] = Counter()
    known_surfaces = {surface["id"] for surface in inventory["surfaces"]}
    for entry in inventory["direct_tabular_parser_allowlist"]:
        key = (entry["path"], entry["parser"])
        assert key not in declared
        assert entry["surface_id"] in known_surfaces
        declared[key] = int(entry["call_count"])

    assert _production_tabular_parser_calls() == declared


def test_direct_json_parser_inventory_is_an_exact_ast_allowlist() -> None:
    inventory = _inventory()
    declared: Counter[tuple[str, str]] = Counter()
    known_surfaces = {surface["id"] for surface in inventory["surfaces"]}
    for entry in inventory["direct_json_parser_allowlist"]:
        key = (entry["path"], entry["parser"])
        assert key not in declared
        assert entry["surface_id"] in known_surfaces
        declared[key] = int(entry["call_count"])

    assert _production_json_parser_calls() == declared


def test_direct_yaml_parser_inventory_is_an_exact_ast_allowlist() -> None:
    inventory = _inventory()
    declared: Counter[tuple[str, str]] = Counter()
    known_surfaces = {surface["id"] for surface in inventory["surfaces"]}
    for entry in inventory["direct_yaml_parser_allowlist"]:
        key = (entry["path"], entry["parser"])
        assert key not in declared
        assert entry["surface_id"] in known_surfaces
        declared[key] = int(entry["call_count"])

    assert _production_yaml_parser_calls() == declared
