"""Restore equivalence never discards an altered predicate or another object."""

import pytest

from tests.accrual_deferral_restore_catalog import LEGACY_CHECK_REPARSE, retained_catalog


@pytest.mark.parametrize("key,forms", LEGACY_CHECK_REPARSE.items())
def test_only_exact_observed_nested_and_reparse_is_equivalent(key: tuple[str, str], forms: tuple[str, str]) -> None:
    before = {"constraints": [(*key, forms[0])], "functions": [("closed", "exact original bytes")]}
    after = {"constraints": [(*key, forms[1])], "functions": [("closed", "exact original bytes")]}
    assert retained_catalog(before) == retained_catalog(after)
    changed = {**after, "constraints": [(*key, forms[1].replace(" AND ", " OR ", 1))]}
    assert retained_catalog(before) != retained_catalog(changed)
    renamed = {**after, "constraints": [(key[0], key[1] + "_changed", forms[1])]}
    assert retained_catalog(before) != retained_catalog(renamed)
    assert retained_catalog(before) != retained_catalog({**after, "functions": [("closed", "altered body")]})


def test_owned_constraint_is_byte_exact_even_if_legacy_shape_matches() -> None:
    forms = next(iter(LEGACY_CHECK_REPARSE.values()))
    before = {"constraints": [("accrual_deferral_sources", "ad1_check", forms[0])]}
    after = {"constraints": [("accrual_deferral_sources", "ad1_check", forms[1])]}
    assert retained_catalog(before) != retained_catalog(after)
