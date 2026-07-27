"""Safe YAML loading helpers for exact financial scalar ingress."""

from __future__ import annotations

from typing import Any, TextIO

import yaml

from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    validate_financial_input_policy,
)


class _ExactFinancialScalarSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that retains source text for decimal-like scalars."""


class DuplicateYamlKeyError(yaml.YAMLError):
    """Raised when a bounded YAML document repeats an effective mapping key."""


class _UniqueMappingMixin:
    """Construct mappings without PyYAML's silent last-key-wins behavior."""

    def construct_mapping(self, node: yaml.nodes.MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, yaml.nodes.MappingNode):
            raise DuplicateYamlKeyError("expected a mapping node")
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)  # type: ignore[attr-defined]
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise DuplicateYamlKeyError("mapping key is not hashable") from exc
            if duplicate:
                raise DuplicateYamlKeyError("duplicate mapping key")
            mapping[key] = self.construct_object(value_node, deep=deep)  # type: ignore[attr-defined]
        return mapping


class _UniqueSafeLoader(_UniqueMappingMixin, yaml.SafeLoader):
    """Safe loader variant that rejects duplicate mapping keys."""


class _ExactUniqueFinancialScalarSafeLoader(_UniqueMappingMixin, _ExactFinancialScalarSafeLoader):
    """Exact financial loader variant that rejects duplicate mapping keys."""


def _construct_decimal_lexeme(
    loader: _ExactFinancialScalarSafeLoader,
    node: yaml.nodes.ScalarNode,
) -> str:
    """Return the original scalar text instead of creating binary floating point."""

    return loader.construct_scalar(node)


_ExactFinancialScalarSafeLoader.add_constructor(
    "tag:yaml.org,2002:float",
    _construct_decimal_lexeme,
)


def load_safe_yaml(
    stream: str | TextIO,
    *,
    financial_input_policy: FinancialInputPolicy,
    reject_duplicate_keys: bool = False,
) -> object:
    """Load safe YAML and preserve decimal lexemes under strict-v2."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    if input_policy == STRICT_FINANCIAL_INPUT_POLICY:
        loader_type = (
            _ExactUniqueFinancialScalarSafeLoader
            if reject_duplicate_keys
            else _ExactFinancialScalarSafeLoader
        )
        exact_loader = loader_type(stream)
        try:
            return exact_loader.get_single_data()
        finally:
            exact_loader.dispose()
    if reject_duplicate_keys:
        unique_loader = _UniqueSafeLoader(stream)
        try:
            return unique_loader.get_single_data()
        finally:
            unique_loader.dispose()
    return yaml.safe_load(stream)
