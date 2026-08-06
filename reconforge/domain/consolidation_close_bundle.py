"""Replay-verifiable evidence bundle for one governed consolidation close run.

The bundle is an immutable index over artifacts that the repositories already
replay before exposure. It does not calculate accounting results, create a
posting, or make a statutory-reporting claim; it prevents consumers from
combining evidence from different runs or periods.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from reconforge.domain.consolidation import ConsolidationError

CONSOLIDATION_CLOSE_BUNDLE_SCHEMA_VERSION = 1
CONSOLIDATION_CLOSE_BUNDLE_ALGORITHM_VERSION = "consolidation-close-bundle-v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_STATUSES = frozenset({"Prepared", "Approved", "Posted", "ReversalPrepared", "Reversed"})


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ConsolidationError(f"{field} is invalid.")
    return value.strip()


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ConsolidationError(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _json_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _sequence_digest(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConsolidationError(f"{field} must be a list.")
    items = tuple(_digest(item, f"{field} item") for item in value)
    if items != tuple(sorted(items)) or len(set(items)) != len(items):
        raise ConsolidationError(f"{field} must be sorted and unique.")
    return items


@dataclass(frozen=True)
class ConsolidationCloseBundle:
    """Digest-bound index for a replay-verified close run."""

    workspace: str
    period_id: str
    run_id: str
    status: str
    worksheet_result_digest: str
    translation_result_digest: str
    management_statement_digest: str
    journal_digest: str
    effect_digests: tuple[str, ...]
    evidence_scope: str
    bundle_digest: str
    intercompany_artifact_digests: tuple[str, ...] = ()
    impairment_artifact_digests: tuple[str, ...] = ()
    schema_version: int = CONSOLIDATION_CLOSE_BUNDLE_SCHEMA_VERSION
    algorithm_version: str = CONSOLIDATION_CLOSE_BUNDLE_ALGORITHM_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", _identifier(self.workspace, "Close bundle workspace"))
        object.__setattr__(self, "period_id", _identifier(self.period_id, "Close bundle period"))
        object.__setattr__(self, "run_id", _identifier(self.run_id, "Close bundle run"))
        if self.status not in _STATUSES:
            raise ConsolidationError("Close bundle status is not supported.")
        for name in (
            "worksheet_result_digest",
            "translation_result_digest",
            "management_statement_digest",
            "journal_digest",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), f"Close bundle {name}"))
        object.__setattr__(self, "effect_digests", _sequence_digest(self.effect_digests, "Close bundle effects"))
        object.__setattr__(
            self,
            "intercompany_artifact_digests",
            _sequence_digest(self.intercompany_artifact_digests, "Close bundle intercompany artifacts"),
        )
        object.__setattr__(
            self,
            "impairment_artifact_digests",
            _sequence_digest(self.impairment_artifact_digests, "Close bundle impairment artifacts"),
        )
        if self.evidence_scope != "local-control-journal-and-management-only":
            raise ConsolidationError("Close bundle evidence scope is unsupported.")
        if self.schema_version != CONSOLIDATION_CLOSE_BUNDLE_SCHEMA_VERSION:
            raise ConsolidationError("Close bundle schema is unsupported.")
        if self.algorithm_version != CONSOLIDATION_CLOSE_BUNDLE_ALGORITHM_VERSION:
            raise ConsolidationError("Close bundle algorithm is unsupported.")
        _digest(self.bundle_digest, "Close bundle digest")

    def _payload(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "effect_digests": list(self.effect_digests),
            "evidence_scope": self.evidence_scope,
            "intercompany_artifact_digests": list(self.intercompany_artifact_digests),
            "impairment_artifact_digests": list(self.impairment_artifact_digests),
            "journal_digest": self.journal_digest,
            "management_statement_digest": self.management_statement_digest,
            "period_id": self.period_id,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "translation_result_digest": self.translation_result_digest,
            "worksheet_result_digest": self.worksheet_result_digest,
            "workspace": self.workspace,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["bundle_digest"] = self.bundle_digest
        return payload


def _bundle_from_payload(payload: Mapping[str, object], *, bundle_digest: str) -> ConsolidationCloseBundle:
    had_intercompany_field = "intercompany_artifact_digests" in payload
    had_impairment_field = "impairment_artifact_digests" in payload
    provisional = ConsolidationCloseBundle(
        workspace=cast(str, payload.get("workspace")),
        period_id=cast(str, payload.get("period_id")),
        run_id=cast(str, payload.get("run_id")),
        status=cast(str, payload.get("status")),
        worksheet_result_digest=cast(str, payload.get("worksheet_result_digest")),
        translation_result_digest=cast(str, payload.get("translation_result_digest")),
        management_statement_digest=cast(str, payload.get("management_statement_digest")),
        journal_digest=cast(str, payload.get("journal_digest")),
        effect_digests=cast(tuple[str, ...], payload.get("effect_digests", ())),
        intercompany_artifact_digests=cast(tuple[str, ...], payload.get("intercompany_artifact_digests", ())),
        impairment_artifact_digests=cast(tuple[str, ...], payload.get("impairment_artifact_digests", ())),
        evidence_scope=cast(str, payload.get("evidence_scope")),
        bundle_digest=bundle_digest,
        schema_version=cast(int, payload.get("schema_version")),
        algorithm_version=cast(str, payload.get("algorithm_version")),
    )
    expected_payload = provisional._payload()
    # Bundles emitted before ADR 0336 did not carry intercompany evidence. Keep
    # their verification readable while all newly generated bundles include the
    # additive field and digest it explicitly.
    if not had_intercompany_field:
        expected_payload.pop("intercompany_artifact_digests", None)
    if not had_impairment_field:
        expected_payload.pop("impairment_artifact_digests", None)
    expected = _json_digest(expected_payload)
    if not hmac.compare_digest(expected, provisional.bundle_digest):
        raise ConsolidationError("Close bundle digest verification failed.")
    return provisional


def build_consolidation_close_bundle(run: Mapping[str, object]) -> ConsolidationCloseBundle:
    """Build a bundle only from a repository's already replay-verified run."""

    if not isinstance(run, Mapping):
        raise ConsolidationError("A replay-verified close run is required.")
    worksheet = run.get("worksheet")
    translation = run.get("translation_evidence")
    statement = run.get("management_statement")
    effects = run.get("effects", [])
    if not isinstance(worksheet, Mapping) or not isinstance(translation, Mapping) or not isinstance(statement, Mapping):
        raise ConsolidationError("Close run evidence is incomplete.")
    if not isinstance(effects, Sequence) or isinstance(effects, (str, bytes, bytearray)):
        raise ConsolidationError("Close run effects are invalid.")

    worksheet_digest = _digest(worksheet.get("result_digest"), "Worksheet result digest")
    if run.get("worksheet_result_digest") is not None:
        run_worksheet_digest = _digest(run.get("worksheet_result_digest"), "Run worksheet digest")
        if not hmac.compare_digest(worksheet_digest, run_worksheet_digest):
            raise ConsolidationError("Close bundle worksheet digest does not match the run header.")
    else:
        # PostgreSQL stores the canonical JSONB payload digest as
        # ``worksheet_digest``; replay verification has already checked it.
        _digest(run.get("worksheet_digest"), "Run worksheet payload digest")
    translation_digest = _digest(translation.get("result_digest"), "Translation result digest")
    if run.get("translation_result_digest") is not None:
        run_translation_digest = _digest(run.get("translation_result_digest"), "Run translation digest")
        if not hmac.compare_digest(translation_digest, run_translation_digest):
            raise ConsolidationError("Close bundle translation digest does not match the run header.")
    statement_digest = _digest(statement.get("artifact_digest"), "Management statement digest")
    statement_worksheet_digest = _digest(statement.get("worksheet_result_digest"), "Management statement worksheet digest")
    if not hmac.compare_digest(statement_worksheet_digest, worksheet_digest):
        raise ConsolidationError("Management statement is bound to a different worksheet.")
    effect_digests = tuple(sorted(_digest(effect.get("effect_digest"), "Effect digest") for effect in effects if isinstance(effect, Mapping)))
    if len(effect_digests) != len(effects):
        raise ConsolidationError("Close run contains an invalid effect.")
    intercompany_evidence = run.get("intercompany_evidence", [])
    if not isinstance(intercompany_evidence, Sequence) or isinstance(
        intercompany_evidence, (str, bytes, bytearray)
    ):
        raise ConsolidationError("Close run intercompany evidence is invalid.")
    intercompany_artifact_digests = tuple(
        sorted(
            _digest(item.get("artifact_result_digest"), "Intercompany artifact digest")
            for item in intercompany_evidence
            if isinstance(item, Mapping)
        )
    )
    if len(intercompany_artifact_digests) != len(intercompany_evidence):
        raise ConsolidationError("Close run contains an invalid intercompany evidence link.")
    impairment_evidence = run.get("impairment_evidence", [])
    if not isinstance(impairment_evidence, Sequence) or isinstance(
        impairment_evidence, (str, bytes, bytearray)
    ):
        raise ConsolidationError("Close run impairment evidence is invalid.")
    impairment_artifact_digests = tuple(
        sorted(
            _digest(item.get("artifact_result_digest"), "Impairment artifact digest")
            for item in impairment_evidence
            if isinstance(item, Mapping)
        )
    )
    if len(impairment_artifact_digests) != len(impairment_evidence):
        raise ConsolidationError("Close run contains an invalid impairment evidence link.")
    payload: dict[str, object] = {
        "algorithm_version": CONSOLIDATION_CLOSE_BUNDLE_ALGORITHM_VERSION,
        "effect_digests": list(effect_digests),
        "evidence_scope": "local-control-journal-and-management-only",
        "intercompany_artifact_digests": list(intercompany_artifact_digests),
        "impairment_artifact_digests": list(impairment_artifact_digests),
        "journal_digest": _digest(run.get("journal_digest"), "Run journal digest"),
        "management_statement_digest": statement_digest,
        "period_id": _identifier(run.get("period_id"), "Run period"),
        "run_id": _identifier(run.get("id"), "Run identifier"),
        "schema_version": CONSOLIDATION_CLOSE_BUNDLE_SCHEMA_VERSION,
        "status": _identifier(run.get("status"), "Run status"),
        "translation_result_digest": translation_digest,
        "worksheet_result_digest": worksheet_digest,
        "workspace": _identifier(run.get("workspace_id") or run.get("workspace"), "Run workspace"),
    }
    bundle_digest = _json_digest(payload)
    return _bundle_from_payload(payload, bundle_digest=bundle_digest)


def verify_consolidation_close_bundle_payload(payload: object) -> ConsolidationCloseBundle:
    """Verify a serialized bundle without accessing a database or network."""

    if not isinstance(payload, Mapping):
        raise ConsolidationError("Close bundle payload must be an object.")
    raw_digest = payload.get("bundle_digest")
    if not isinstance(raw_digest, str):
        raise ConsolidationError("Close bundle digest is missing.")
    body = dict(payload)
    body.pop("bundle_digest", None)
    return _bundle_from_payload(body, bundle_digest=raw_digest)


__all__ = [
    "CONSOLIDATION_CLOSE_BUNDLE_ALGORITHM_VERSION",
    "CONSOLIDATION_CLOSE_BUNDLE_SCHEMA_VERSION",
    "ConsolidationCloseBundle",
    "build_consolidation_close_bundle",
    "verify_consolidation_close_bundle_payload",
]
