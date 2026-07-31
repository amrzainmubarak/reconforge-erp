"""High-level rule pack execution and versioned result artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from reconforge.io.generated import GeneratedArtifactError, read_generated_json_document
from reconforge.io.writers import ensure_output_dir, write_csv, write_json
from reconforge.rules.evaluator import evaluate_rule
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.models import ControlPack
from reconforge.rules.results import RuleResult, results_to_records
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    validate_financial_input_policy,
)
from reconforge.utils.time import utc_now_text

RULE_RESULTS_SCHEMA_VERSION = 2
_RULE_RESULTS_ARTIFACT_TYPE = "reconforge-rule-results"
_RULE_RESULTS_INTEGRITY_BOUNDARY = (
    "Local content digests only; this artifact is not a signature, audit opinion, "
    "compliance certification, or proof of source-system authenticity."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class InputFileFingerprint:
    """Bounded identity data for one local CSV consumed by a rule run."""

    name: str
    bytes: int
    sha256: str

    def to_record(self) -> dict[str, str | int]:
        """Return the stable JSON representation."""

        return {"name": self.name, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class RulePackExecution:
    """One evaluated rule pack plus deterministic provenance."""

    pack: ControlPack
    results: list[RuleResult]
    input_files: tuple[InputFileFingerprint, ...]
    financial_input_policy: FinancialInputPolicy
    decision_digest: str
    generated_at: str


@dataclass(frozen=True)
class RuleResultsDocument:
    """A historical v1 or verified current rule-results document."""

    schema_version: Literal[1, 2]
    results: list[dict[str, Any]]
    verification_status: Literal["legacy-unverified", "verified"]
    payload: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _input_fingerprints(input_dir: Path) -> tuple[InputFileFingerprint, ...]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Rule input directory not found: {input_dir}")
    fingerprints: list[InputFileFingerprint] = []
    for path in sorted(input_dir.glob("*.csv"), key=lambda item: item.name):
        fingerprints.append(
            InputFileFingerprint(
                name=path.name,
                bytes=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    return tuple(fingerprints)


def _decision_records(results: list[RuleResult]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in record.items() if key != "triggered_at"} for record in results_to_records(results)
    ]


def _decision_digest(
    *,
    pack: ControlPack,
    results: list[RuleResult],
    input_files: tuple[InputFileFingerprint, ...],
    financial_input_policy: FinancialInputPolicy,
) -> str:
    return _canonical_digest(
        {
            "schema_version": RULE_RESULTS_SCHEMA_VERSION,
            "financial_input_policy": financial_input_policy,
            "rule_pack": {
                "pack_id": pack.metadata.pack_id,
                "version": pack.metadata.version,
                "digest": pack.rule_pack_digest,
            },
            "input_files": [item.to_record() for item in input_files],
            "results": _decision_records(results),
        }
    )


def execute_rule_pack(
    input_dir: Path | str,
    pack_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> RulePackExecution:
    """Run a pack and retain the provenance needed by current artifacts."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    base = Path(input_dir)
    pack = load_rule_pack(
        pack_path,
        financial_input_policy=input_policy,
    )
    fingerprints = _input_fingerprints(base)
    results: list[RuleResult] = []
    for rule in pack.rules:
        results.extend(
            evaluate_rule(
                base,
                rule,
                financial_input_policy=input_policy,
            )
        )
    if _input_fingerprints(base) != fingerprints:
        raise ValueError("Rule input files changed during execution")
    return RulePackExecution(
        pack=pack,
        results=results,
        input_files=fingerprints,
        financial_input_policy=input_policy,
        decision_digest=_decision_digest(
            pack=pack,
            results=results,
            input_files=fingerprints,
            financial_input_policy=input_policy,
        ),
        generated_at=utc_now_text(),
    )


def run_rule_pack(
    input_dir: Path | str,
    pack_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> list[RuleResult]:
    """Run all rules, preserving the historical list-returning API."""

    return execute_rule_pack(
        input_dir,
        pack_path,
        financial_input_policy=financial_input_policy,
    ).results


def _empty_result_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "rule_id",
            "rule_name",
            "severity",
            "confidence",
            "entity_type",
            "source_file",
            "source_row",
            "affected_reference",
            "affected_work_order",
            "affected_product",
            "affected_customer",
            "amount_impact",
            "message",
            "business_impact",
            "recommended_action",
            "risk_impact",
            "evidence_fields",
            "triggered_at",
        ],
    )


def write_rule_results(
    results: list[RuleResult],
    output_dir: Path | str,
) -> list[Path]:
    """Write historical unversioned v1 results for compatibility callers."""

    target = ensure_output_dir(output_dir)
    records = results_to_records(results)
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = _empty_result_frame()
    csv_path = write_csv(frame, target, "rule_results")
    json_path = write_json({"results": records}, target, "rule_results")
    return [csv_path, json_path]


def _execution_payload(execution: RulePackExecution) -> dict[str, Any]:
    if execution.pack.financial_input_policy != execution.financial_input_policy:
        raise ValueError("Rule execution policy does not match its loaded pack")
    expected_decision_digest = _decision_digest(
        pack=execution.pack,
        results=execution.results,
        input_files=execution.input_files,
        financial_input_policy=execution.financial_input_policy,
    )
    if not hmac.compare_digest(execution.decision_digest, expected_decision_digest):
        raise ValueError("Rule execution decision digest verification failed")
    payload: dict[str, Any] = {
        "schema_version": RULE_RESULTS_SCHEMA_VERSION,
        "artifact_type": _RULE_RESULTS_ARTIFACT_TYPE,
        "generated_at": execution.generated_at,
        "financial_input_policy": execution.financial_input_policy,
        "rule_pack": {
            "pack_id": execution.pack.metadata.pack_id,
            "name": execution.pack.metadata.name,
            "version": execution.pack.metadata.version,
            "digest": execution.pack.rule_pack_digest,
        },
        "input_files": [item.to_record() for item in execution.input_files],
        "result_count": len(execution.results),
        "decision_digest": execution.decision_digest,
        "integrity_boundary": _RULE_RESULTS_INTEGRITY_BOUNDARY,
        "results": results_to_records(execution.results),
    }
    payload["artifact_digest"] = _canonical_digest(payload)
    return payload


def write_rule_execution(
    execution: RulePackExecution,
    output_dir: Path | str,
) -> list[Path]:
    """Write current v2 CSV and self-verifying JSON rule artifacts."""

    payload = _execution_payload(execution)
    target = ensure_output_dir(output_dir)
    records = results_to_records(execution.results)
    provenance = {
        "financial_input_policy": execution.financial_input_policy,
        "rule_pack_id": execution.pack.metadata.pack_id,
        "rule_pack_version": execution.pack.metadata.version,
        "rule_pack_digest": execution.pack.rule_pack_digest,
        "decision_digest": execution.decision_digest,
    }
    frame = pd.DataFrame([{**record, **provenance} for record in records])
    if frame.empty:
        frame = _empty_result_frame()
        for name in provenance:
            frame[name] = pd.Series(dtype="object")
    csv_path = write_csv(frame, target, "rule_results")
    json_path = write_json(payload, target, "rule_results")
    return [csv_path, json_path]


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Rule results {field_name} must be an object")
    return value


def _require_results(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Rule results must contain an array of objects")
    return value


def verify_rule_results_payload(
    payload: dict[str, Any],
    *,
    input_dir: Path | str | None = None,
    pack_path: Path | str | None = None,
) -> None:
    """Verify v2 content digests and optional local source/pack identity."""

    if payload.get("schema_version") != RULE_RESULTS_SCHEMA_VERSION:
        raise ValueError("Only current v2 rule results have verifiable digests")
    if payload.get("artifact_type") != _RULE_RESULTS_ARTIFACT_TYPE:
        raise ValueError("Rule results artifact type is invalid")
    results = _require_results(payload.get("results"))
    rule_pack = _require_mapping(payload.get("rule_pack"), "rule_pack")
    input_policy = validate_financial_input_policy(payload.get("financial_input_policy"))
    input_files = payload.get("input_files")
    if not isinstance(input_files, list) or not all(isinstance(item, dict) for item in input_files):
        raise ValueError("Rule results input_files must be an array of objects")
    input_names: list[str] = []
    for item in input_files:
        name = item.get("name")
        byte_count = item.get("bytes")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".csv")
            or isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 0
            or not isinstance(digest, str)
            or _SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise ValueError("Rule results contain an invalid input fingerprint")
        input_names.append(name)
    if input_names != sorted(set(input_names)):
        raise ValueError("Rule results input fingerprints must be unique and sorted")
    if payload.get("result_count") != len(results):
        raise ValueError("Rule results count does not match its records")
    if payload.get("integrity_boundary") != _RULE_RESULTS_INTEGRITY_BOUNDARY:
        raise ValueError("Rule results integrity boundary is invalid")
    expected_decision_digest = _canonical_digest(
        {
            "schema_version": RULE_RESULTS_SCHEMA_VERSION,
            "financial_input_policy": input_policy,
            "rule_pack": {
                "pack_id": rule_pack.get("pack_id"),
                "version": rule_pack.get("version"),
                "digest": rule_pack.get("digest"),
            },
            "input_files": input_files,
            "results": [{key: value for key, value in record.items() if key != "triggered_at"} for record in results],
        }
    )
    decision_digest = payload.get("decision_digest")
    if not isinstance(decision_digest, str) or not hmac.compare_digest(
        decision_digest,
        expected_decision_digest,
    ):
        raise ValueError("Rule results decision digest verification failed")
    artifact_without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    artifact_digest = payload.get("artifact_digest")
    if not isinstance(artifact_digest, str) or not hmac.compare_digest(
        artifact_digest,
        _canonical_digest(artifact_without_digest),
    ):
        raise ValueError("Rule results artifact digest verification failed")
    if input_dir is not None:
        current_inputs = [item.to_record() for item in _input_fingerprints(Path(input_dir))]
        if input_files != current_inputs:
            raise ValueError("Rule results input fingerprint verification failed")
    if pack_path is not None:
        current_pack = load_rule_pack(
            pack_path,
            financial_input_policy=input_policy,
        )
        expected_pack = {
            "pack_id": current_pack.metadata.pack_id,
            "name": current_pack.metadata.name,
            "version": current_pack.metadata.version,
            "digest": current_pack.rule_pack_digest,
        }
        if rule_pack != expected_pack:
            raise ValueError("Rule results pack fingerprint verification failed")


def read_rule_results(path: Path | str) -> RuleResultsDocument:
    """Read historical v1 or verify current v2 local rule results."""

    try:
        payload = read_generated_json_document(Path(path), mode="display").payload
    except GeneratedArtifactError as exc:
        raise ValueError("Rule results JSON is invalid") from exc
    document = _require_mapping(payload, "document")
    results = _require_results(document.get("results"))
    if "schema_version" not in document:
        return RuleResultsDocument(
            schema_version=1,
            results=results,
            verification_status="legacy-unverified",
            payload=document,
        )
    verify_rule_results_payload(document)
    return RuleResultsDocument(
        schema_version=2,
        results=results,
        verification_status="verified",
        payload=document,
    )
