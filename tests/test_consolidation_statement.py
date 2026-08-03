from dataclasses import replace
from decimal import Decimal

import pytest

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet
from reconforge.domain.consolidation_statement import (
    build_management_statement_package,
    build_management_trial_balance,
    verify_management_statement_package,
    verify_management_trial_balance,
)
from tests.test_consolidation_lifecycle import _request


def test_management_trial_balance_is_exact_lineaged_and_permutation_stable() -> None:
    first = build_management_trial_balance(prepare_consolidation_worksheet(_request()))
    second = build_management_trial_balance(prepare_consolidation_worksheet(_request()))
    assert first.total_balance.amount == Decimal("0")
    assert first.artifact_digest == second.artifact_digest
    assert all(line.source_references for line in first.lines)
    assert verify_management_trial_balance(first) == first


def test_management_trial_balance_rejects_tampered_digest() -> None:
    artifact = build_management_trial_balance(prepare_consolidation_worksheet(_request()))
    with pytest.raises(ConsolidationError, match="digest"):
        verify_management_trial_balance(replace(artifact, group_code="TAMPERED"))


def test_management_statement_package_is_sectioned_balanced_and_replayable() -> None:
    worksheet = prepare_consolidation_worksheet(_request())
    first = build_management_statement_package(worksheet)
    second = build_management_statement_package(worksheet)

    assert first.artifact_digest == second.artifact_digest
    assert [section.account_type for section in first.sections] == sorted(
        section.account_type for section in first.sections
    )
    assert first.total_balance.amount == Decimal("0")
    assert all(section.total_balance.currency == "USD" for section in first.sections)
    assert verify_management_statement_package(first) == first


def test_management_statement_package_rejects_tampered_section_total() -> None:
    artifact = build_management_statement_package(prepare_consolidation_worksheet(_request()))
    section = artifact.sections[0]
    tampered = replace(artifact, sections=(replace(section, total_balance=section.total_balance + section.lines[0].amount),) + artifact.sections[1:])
    with pytest.raises(ConsolidationError, match="digest"):
        verify_management_statement_package(tampered)
