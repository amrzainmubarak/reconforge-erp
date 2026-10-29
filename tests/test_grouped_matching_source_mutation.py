import tempfile
from pathlib import Path

import pytest

import reconforge.benchmark.grouped_matching_source_mutation as mutation
from reconforge.benchmark.grouped_matching_source_mutation import (
    run_source_mutation_campaign,
    verify_source_mutation_campaign,
)


def test_targeted_grouped_matching_source_mutations_are_killed() -> None:
    result = run_source_mutation_campaign()
    verify_source_mutation_campaign(result)
    assert result.mutants == result.killed == 3
    assert result.survivors == ()


def test_mutants_are_loaded_when_temporary_directory_inherits_parent_pytest_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An ancestor pytest configuration can prepend the original project to the
    # child import path, bypassing mutations unless the child is isolated.
    project_root = Path(__file__).resolve().parents[1]
    (tmp_path / "pytest.ini").write_text(f"[pytest]\npythonpath = {project_root.as_posix()}\n", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    result = run_source_mutation_campaign()
    verify_source_mutation_campaign(result)
    assert result.killed == 3


def test_campaign_refuses_to_count_broken_baseline_as_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mutation, "_CONTRACT", "def test_baseline():\n    assert False\n")
    with pytest.raises(RuntimeError, match="baseline"):
        run_source_mutation_campaign()


def test_failed_source_origin_is_an_invalid_run_not_a_killed_mutant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_contract = mutation._CONTRACT.replace(
        "assert Path(grouped_matching.__file__).resolve() == expected.resolve()",
        "assert False, 'wrong source origin'",
    )
    assert bad_contract != mutation._CONTRACT
    monkeypatch.setattr(mutation, "_CONTRACT", bad_contract)
    child = tmp_path / "child"
    child.mkdir()
    source = (Path(__file__).resolve().parents[1] / "reconforge/domain/grouped_matching.py").read_text(encoding="utf-8")
    mutation._prepare_child(child, source)
    with pytest.raises(RuntimeError, match="origin"):
        mutation._run_contract(child)


def test_unexpected_runtime_error_cannot_count_as_a_killed_mutant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_contract = mutation._CONTRACT.replace(
        '    assert result.status == "matched"',
        '    raise RuntimeError("synthetic infrastructure failure")',
        1,
    )
    monkeypatch.setattr(mutation, "_CONTRACT", bad_contract)
    child = tmp_path / "child"
    child.mkdir()
    source = (Path(__file__).resolve().parents[1] / "reconforge/domain/grouped_matching.py").read_text(encoding="utf-8")
    mutation._prepare_child(child, source)
    with pytest.raises(RuntimeError, match="unexpected"):
        mutation._run_contract(child, ("test_partial_settlement_is_supported",))


def test_failure_in_wrong_contract_cannot_count_as_a_killed_mutant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_contract = mutation._CONTRACT.replace(
        '    assert result.status == "unmatched"',
        '    assert result.status == "matched"',
    )
    assert bad_contract != mutation._CONTRACT
    monkeypatch.setattr(mutation, "_CONTRACT", bad_contract)
    child = tmp_path / "child"
    child.mkdir()
    source = (Path(__file__).resolve().parents[1] / "reconforge/domain/grouped_matching.py").read_text(encoding="utf-8")
    mutation._prepare_child(child, source)
    with pytest.raises(RuntimeError, match="unexpected"):
        mutation._run_contract(child, ("test_partial_settlement_is_supported",))
