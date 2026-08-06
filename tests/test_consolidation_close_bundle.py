from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_close_bundle import (
    build_consolidation_close_bundle,
    verify_consolidation_close_bundle_payload,
)
from tests.test_sqlite_consolidation_close import _database, _post, _prepare


def test_close_bundle_is_exposed_and_replay_verifiable(tmp_path: Path) -> None:
    connection = _database(tmp_path)[1]
    repository, _period, run = _prepare(connection)
    detail = repository.get_run(str(run["id"]))

    bundle = detail["close_bundle"]
    assert bundle["evidence_scope"] == "local-control-journal-and-management-only"
    assert bundle["worksheet_result_digest"] == run["worksheet_result_digest"]
    assert bundle["translation_result_digest"] == run["translation_result_digest"]
    assert bundle["effect_digests"] == []
    assert verify_consolidation_close_bundle_payload(bundle).to_dict() == bundle


def test_close_bundle_binds_posting_and_reversal_effects_deterministically(tmp_path: Path) -> None:
    connection = _database(tmp_path)[1]
    repository, _period, run = _prepare(connection)
    posted = _post(repository, run)
    detail = repository.get_run(str(posted["id"]))

    bundle = detail["close_bundle"]
    assert len(bundle["effect_digests"]) == 1
    assert bundle["status"] == "Posted"
    assert build_consolidation_close_bundle(detail).to_dict() == bundle


def test_close_bundle_accepts_postgres_payload_digest_header_alias(tmp_path: Path) -> None:
    connection = _database(tmp_path)[1]
    repository, _period, run = _prepare(connection)
    detail = repository.get_run(str(run["id"]))
    postgres_style = deepcopy(detail)
    postgres_style.pop("worksheet_result_digest", None)
    postgres_style.pop("translation_result_digest", None)
    postgres_style["worksheet_digest"] = "a" * 64

    bundle = build_consolidation_close_bundle(postgres_style)
    assert bundle.worksheet_result_digest == detail["worksheet"]["result_digest"]


def test_close_bundle_binds_impairment_evidence_digests() -> None:
    detail = {
        "id": "RUN-IMP-1",
        "period_id": "PERIOD-1",
        "workspace_id": "WORKSPACE-1",
        "status": "Prepared",
        "worksheet": {
            "result_digest": "a" * 64,
        },
        "worksheet_digest": "b" * 64,
        "translation_evidence": {"result_digest": "c" * 64},
        "management_statement": {
            "artifact_digest": "d" * 64,
            "worksheet_result_digest": "a" * 64,
        },
        "effects": [],
        "journal_digest": "e" * 64,
        "impairment_evidence": [{"artifact_result_digest": "f" * 64}],
    }

    bundle = build_consolidation_close_bundle(detail)
    assert bundle.impairment_artifact_digests == ("f" * 64,)
    assert verify_consolidation_close_bundle_payload(bundle.to_dict()).to_dict() == bundle.to_dict()


def test_close_bundle_binds_deferred_tax_evidence_digests() -> None:
    detail = {
        "id": "RUN-DTAX-1",
        "period_id": "PERIOD-1",
        "workspace_id": "WORKSPACE-1",
        "status": "Prepared",
        "worksheet": {"result_digest": "a" * 64},
        "worksheet_digest": "b" * 64,
        "translation_evidence": {"result_digest": "c" * 64},
        "management_statement": {
            "artifact_digest": "d" * 64,
            "worksheet_result_digest": "a" * 64,
        },
        "effects": [],
        "journal_digest": "e" * 64,
        "deferred_tax_evidence": [{"artifact_result_digest": "f" * 64}],
    }

    bundle = build_consolidation_close_bundle(detail)
    assert bundle.deferred_tax_artifact_digests == ("f" * 64,)
    assert verify_consolidation_close_bundle_payload(bundle.to_dict()).to_dict() == bundle.to_dict()


def test_close_bundle_rejects_cross_run_statement_and_digest_tampering(tmp_path: Path) -> None:
    connection = _database(tmp_path)[1]
    repository, _period, run = _prepare(connection)
    detail = repository.get_run(str(run["id"]))

    mismatched = deepcopy(detail)
    mismatched["management_statement"]["worksheet_result_digest"] = "0" * 64
    with pytest.raises(ConsolidationError, match="different worksheet"):
        build_consolidation_close_bundle(mismatched)

    tampered = deepcopy(detail["close_bundle"])
    tampered["journal_digest"] = "0" * 64
    with pytest.raises(ConsolidationError, match="digest verification"):
        verify_consolidation_close_bundle_payload(tampered)


def test_close_bundle_requires_complete_replay_evidence() -> None:
    with pytest.raises(ConsolidationError, match="evidence is incomplete"):
        build_consolidation_close_bundle({"id": "RUN-1"})
