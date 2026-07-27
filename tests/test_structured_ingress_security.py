from __future__ import annotations

from pathlib import Path
from shutil import copytree

import pytest

from reconforge.config import load_config
from reconforge.io.structured import (
    CURRENT_STRUCTURED_DOCUMENT_POLICY,
    StructuredDocumentError,
    StructuredDocumentPolicy,
    parse_json_document,
    parse_yaml_document,
    read_json_document,
    read_yaml_document,
)
from reconforge.mappings.inspector import inspect_mapping_inputs
from reconforge.mappings.validator import validate_mapping_pack
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.recon_as_code import ReconciliationAsCodeSpec
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
)


def _assert_code(exc: pytest.ExceptionInfo[StructuredDocumentError], code: str) -> None:
    assert exc.value.code == code
    assert str(exc.value) == f"Input document rejected ({code})."


def test_valid_json_and_yaml_preserve_bounded_document_contract() -> None:
    assert parse_json_document('{"schema_version": 1, "amount": "0.10"}') == {
        "schema_version": 1,
        "amount": "0.10",
    }
    assert parse_yaml_document(
        "schema_version: 1\namount: 0.100000000000000005\n",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    ) == {
        "schema_version": 1,
        "amount": "0.100000000000000005",
    }
    assert StructuredDocumentPolicy().policy_id == CURRENT_STRUCTURED_DOCUMENT_POLICY


def test_json_can_preserve_exact_float_lexemes_without_weakening_rejection() -> None:
    payload = parse_json_document(
        '{"amount":0.100000000000000005,"ratio":1e-7,"count":7}',
        preserve_float_lexemes=True,
    )

    assert payload == {
        "amount": "0.100000000000000005",
        "ratio": "1e-7",
        "count": 7,
    }
    with pytest.raises(StructuredDocumentError) as duplicate_exc:
        parse_json_document(
            '{"amount":0.1,"amount":0.2}',
            preserve_float_lexemes=True,
        )
    _assert_code(duplicate_exc, "json_duplicate_key")
    with pytest.raises(StructuredDocumentError) as non_finite_exc:
        parse_json_document('{"amount":NaN}', preserve_float_lexemes=True)
    _assert_code(non_finite_exc, "document_non_finite_number")


def test_structured_file_boundary_rejects_size_type_encoding_and_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = tmp_path / "secret.json"
    oversized.write_text('{"token":"very-sensitive-value"}', encoding="utf-8")
    with pytest.raises(StructuredDocumentError) as size_exc:
        read_json_document(oversized, policy=StructuredDocumentPolicy(max_file_bytes=8))
    _assert_code(size_exc, "document_size_limit")
    assert oversized.name not in str(size_exc.value)
    assert "very-sensitive-value" not in str(size_exc.value)

    unsupported = tmp_path / "document.txt"
    unsupported.write_text("{}", encoding="utf-8")
    with pytest.raises(StructuredDocumentError) as type_exc:
        read_json_document(unsupported)
    _assert_code(type_exc, "document_type_unsupported")

    invalid_utf8 = tmp_path / "invalid.yaml"
    invalid_utf8.write_bytes(b"name: \xff")
    with pytest.raises(StructuredDocumentError) as encoding_exc:
        read_yaml_document(invalid_utf8)
    _assert_code(encoding_exc, "document_encoding_invalid")

    linked = tmp_path / "linked.json"
    linked.write_text("{}", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda candidate: candidate == linked or original(candidate),
    )
    with pytest.raises(StructuredDocumentError) as link_exc:
        read_json_document(linked)
    _assert_code(link_exc, "document_not_regular")


@pytest.mark.parametrize(
    ("payload", "policy", "code"),
    [
        ('{"a": 1, "a": 2}', StructuredDocumentPolicy(), "json_duplicate_key"),
        ('{"value": NaN}', StructuredDocumentPolicy(), "document_non_finite_number"),
        ('{"value": Infinity}', StructuredDocumentPolicy(), "document_non_finite_number"),
        ('{"a": ', StructuredDocumentPolicy(), "json_structure_invalid"),
        ('{"a":{"b":{"c":1}}}', StructuredDocumentPolicy(max_depth=3), "document_depth_limit"),
        ('{"a":1,"b":2}', StructuredDocumentPolicy(max_collection_items=1), "document_collection_limit"),
        ('{"a":1}', StructuredDocumentPolicy(max_nodes=2), "document_node_limit"),
        ('{"a":"abcd"}', StructuredDocumentPolicy(max_scalar_characters=3), "document_scalar_limit"),
        ("1" * 5_000, StructuredDocumentPolicy(), "json_structure_invalid"),
    ],
)
def test_json_rejects_ambiguous_or_over_budget_documents(
    payload: str,
    policy: StructuredDocumentPolicy,
    code: str,
) -> None:
    with pytest.raises(StructuredDocumentError) as exc:
        parse_json_document(payload, policy=policy)
    _assert_code(exc, code)


@pytest.mark.parametrize(
    ("payload", "policy", "code"),
    [
        ("key: 1\nkey: 2\n", StructuredDocumentPolicy(), "yaml_duplicate_key"),
        (
            "base: &base [1]\none: *base\ntwo: *base\n",
            StructuredDocumentPolicy(max_yaml_aliases=1),
            "yaml_alias_limit",
        ),
        ("cycle: &cycle\n  self: *cycle\n", StructuredDocumentPolicy(), "document_cycle_forbidden"),
        ("a:\n  b:\n    c: 1\n", StructuredDocumentPolicy(max_depth=2), "document_depth_limit"),
        ("a: 1\nb: 2\n", StructuredDocumentPolicy(max_collection_items=1), "document_collection_limit"),
        ("a: [1, 2]\n", StructuredDocumentPolicy(max_nodes=3), "document_node_limit"),
        ("a: abcd\n", StructuredDocumentPolicy(max_scalar_characters=3), "document_scalar_limit"),
        ("value: .nan\n", StructuredDocumentPolicy(), "document_non_finite_number"),
        ("value: !!python/object/apply:builtins.eval ['1 + 1']\n", StructuredDocumentPolicy(), "yaml_structure_invalid"),
        ("value: " + "1" * 5_000 + "\n", StructuredDocumentPolicy(), "yaml_structure_invalid"),
        ("value: !!binary SGVsbG8=\n", StructuredDocumentPolicy(), "document_value_type_unsupported"),
        ("first: 1\n---\nsecond: 2\n", StructuredDocumentPolicy(), "yaml_multiple_documents"),
        ("base: &base {x: 1}\nmerged: {<<: *base}\n", StructuredDocumentPolicy(), "yaml_merge_forbidden"),
    ],
)
def test_yaml_rejects_ambiguous_unsafe_or_over_budget_documents(
    payload: str,
    policy: StructuredDocumentPolicy,
    code: str,
) -> None:
    with pytest.raises(StructuredDocumentError) as exc:
        parse_yaml_document(
            payload,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
            policy=policy,
        )
    _assert_code(exc, code)


def test_quoted_merge_text_is_data_not_a_yaml_merge() -> None:
    assert parse_yaml_document(
        '"<<": ordinary-text\n',
        financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
    ) == {"<<": "ordinary-text"}


def test_config_rule_mapping_and_reconciliation_definitions_use_bounded_yaml(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "reconforge.yml"
    config_path.write_text("amount_tolerance: 1\namount_tolerance: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"yaml_duplicate_key") as config_exc:
        load_config(config_path)
    assert str(config_path) not in str(config_exc.value)

    rule_pack = tmp_path / "rule-pack"
    copytree(Path("control-packs") / "audit-basic", rule_pack)
    with (rule_pack / "pack.yml").open("a", encoding="utf-8") as handle:
        handle.write("pack_id: duplicate\n")
    with pytest.raises(ValueError, match=r"yaml_duplicate_key") as rule_exc:
        load_rule_pack(rule_pack)
    assert str(rule_pack) not in str(rule_exc.value)

    mapping_pack = tmp_path / "mapping-pack"
    copytree(Path("control-packs") / "odoo-inventory-valuation", mapping_pack)
    with (mapping_pack / "mapping.yml").open("a", encoding="utf-8") as handle:
        handle.write("profile_id: duplicate\n")
    validation = validate_mapping_pack(mapping_pack)
    mapping_check = next(check for check in validation.checks if check.name == "mapping.yml YAML")
    assert not mapping_check.passed
    assert mapping_check.detail == "Malformed YAML: Input document rejected (yaml_duplicate_key)."

    with pytest.raises(StructuredDocumentError) as inspector_exc:
        inspect_mapping_inputs(tmp_path / "input", mapping_pack, tmp_path / "output")
    _assert_code(inspector_exc, "yaml_duplicate_key")

    duplicate_spec = """
reconciliation_id: first
reconciliation_id: second
title: Duplicate
"""
    with pytest.raises(StructuredDocumentError) as spec_exc:
        ReconciliationAsCodeSpec.from_yaml(duplicate_spec)
    _assert_code(spec_exc, "yaml_duplicate_key")


def test_valid_existing_rule_and_mapping_packs_remain_compatible(tmp_path: Path) -> None:
    rule_pack = load_rule_pack(
        Path("control-packs") / "audit-basic",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    assert rule_pack.rules

    mapping_pack = Path("control-packs") / "odoo-inventory-valuation"
    assert validate_mapping_pack(mapping_pack).passed
    inspection = inspect_mapping_inputs(tmp_path / "input", mapping_pack, tmp_path / "output")
    assert inspection.profile_id

    spec = ReconciliationAsCodeSpec.from_yaml(
        """
reconciliation_id: bounded-spec
title: Bounded specification
matching_strategies:
  - name: Exact
    strategy_type: exact_1to1
    amount_tolerance: 0.100000000000000005
"""
    )
    assert spec.matching_strategies[0].amount_tolerance == "0.100000000000000005"
