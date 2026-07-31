"""Authenticated data-only pack admission and reversible local lifecycle.

The envelope contains closed JSON documents.  It never names or loads Python
entry points; conformance reuses the existing declarative rule models.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reconforge import __version__
from reconforge.connectors.package import TrustedPublisherRegistry
from reconforge.rules.loader import _rule_pack_digest, _validate_condition_operators
from reconforge.rules.models import PackMetadata, RuleDefinition
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

MAX_SIGNED_PACK_BYTES = 2 * 1024 * 1024


class PackLifecycleError(ValueError):
    """A stable, non-sensitive pack lifecycle failure."""


def _semver(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise PackLifecycleError("pack_semver_invalid") from exc
    if len(parts) != 3 or any(part < 0 for part in parts) or ".".join(map(str, parts)) != value:
        raise PackLifecycleError("pack_semver_invalid")
    return cast(tuple[int, int, int], parts)


def _matches(version: str, constraint: str) -> bool:
    current = _semver(version)
    clauses = constraint.split(",")
    if not clauses or len(clauses) > 4:
        raise PackLifecycleError("pack_constraint_invalid")
    for clause in clauses:
        operator = next((op for op in (">=", "<=", ">", "<", "==") if clause.startswith(op)), None)
        if operator is None:
            raise PackLifecycleError("pack_constraint_invalid")
        target = _semver(clause[len(operator) :])
        if not {">=": current >= target, "<=": current <= target, ">": current > target, "<": current < target, "==": current == target}[operator]:
            return False
    return True


class PackDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pack_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=80)
    version_constraint: str = Field(min_length=3, max_length=100)

    @field_validator("version_constraint")
    @classmethod
    def valid_constraint(cls, value: str) -> str:
        _matches("0.0.0", value)
        return value


class GoldenExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_count: int = Field(ge=1, le=10_000)
    rule_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    manifest_schema: Literal["signed-data-pack-manifest-v1"] = Field(
        default="signed-data-pack-manifest-v1", alias="schema"
    )
    pack_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=80)
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    kind: Literal["control", "industry"]
    reconforge_version: str = Field(min_length=3, max_length=100)
    dependencies: tuple[PackDependency, ...] = Field(default=(), max_length=100)
    metadata: dict[str, object]
    rules: dict[str, object]
    golden: GoldenExpectation

    @model_validator(mode="after")
    def validate_closed_identity(self) -> PackManifest:
        _matches(__version__, self.reconforge_version)
        ids = [dependency.pack_id for dependency in self.dependencies]
        if ids != sorted(ids) or len(ids) != len(set(ids)) or self.pack_id in ids:
            raise ValueError("pack dependencies must be unique, sorted, and exclude self")
        if self.metadata.get("pack_id") != self.pack_id or self.metadata.get("version") != self.version:
            raise ValueError("embedded metadata identity differs from manifest")
        return self

    @property
    def content_digest(self) -> str:
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class SignedPackEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    package_schema: Literal["signed-data-pack-v1"] = "signed-data-pack-v1"
    publisher_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=80)
    key_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")
    algorithm: Literal["Ed25519"] = "Ed25519"
    manifest: PackManifest
    signature: str = Field(min_length=86, max_length=88)


@dataclass(frozen=True)
class VerifiedPack:
    """Authenticated envelope plus the exact operator trust snapshot used."""

    envelope: SignedPackEnvelope
    trust_registry_digest: str
    _verification_marker: bytes

    def __post_init__(self) -> None:
        expected = hashlib.sha256(
            signature_payload(self.envelope) + self.trust_registry_digest.encode("ascii")
        ).digest()
        if self._verification_marker != expected:
            raise PackLifecycleError("pack_verification_proof_invalid")


def signature_payload(envelope: SignedPackEnvelope) -> bytes:
    payload = envelope.model_dump(mode="json", exclude={"signature"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def conform_pack(manifest: PackManifest) -> str:
    """Validate declared rule documents and golden identity without executing code."""

    try:
        metadata = PackMetadata.model_validate(manifest.metadata)
        raw_rules = manifest.rules.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise PackLifecycleError("pack_rules_invalid")
        rules: list[RuleDefinition] = []
        for raw in raw_rules:
            if not isinstance(raw, dict):
                raise PackLifecycleError("pack_rules_invalid")
            _validate_condition_operators(raw.get("condition", {}), str(raw.get("rule_id", "<unknown>")))
            rules.append(RuleDefinition.model_validate(raw, context={"financial_input_policy": STRICT_FINANCIAL_INPUT_POLICY}))
    except PackLifecycleError:
        raise
    except ValueError as exc:
        raise PackLifecycleError("pack_conformance_failed") from exc
    rule_ids = tuple(sorted(rule.rule_id for rule in rules))
    if len(rule_ids) != len(set(rule_ids)) or manifest.golden.rule_count != len(rules) or tuple(sorted(manifest.golden.rule_ids)) != rule_ids:
        raise PackLifecycleError("pack_golden_mismatch")
    return _rule_pack_digest(metadata, rules, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)


def load_verified_pack(path: Path, *, trusted_registry: TrustedPublisherRegistry) -> VerifiedPack:
    try:
        size = path.stat().st_size
        raw = path.read_bytes()
        if size <= 0 or size > MAX_SIGNED_PACK_BYTES or b"\x00" in raw:
            raise PackLifecycleError("pack_package_size_or_content_invalid")
        envelope = SignedPackEnvelope.model_validate(json.loads(raw.decode("utf-8")))
        key = trusted_registry.resolve(envelope.publisher_id, envelope.key_id)
        signature = base64.b64decode(envelope.signature, validate=True)
        if len(signature) != 64:
            raise PackLifecycleError("pack_signature_invalid")
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, signature_payload(envelope))
        except ImportError as exc:
            raise PackLifecycleError("pack_signature_runtime_unavailable") from exc
        except (InvalidSignature, ValueError) as exc:
            raise PackLifecycleError("pack_signature_invalid") from exc
        conform_pack(envelope.manifest)
        trust_digest = trusted_registry.digest
        return VerifiedPack(
            envelope=envelope,
            trust_registry_digest=trust_digest,
            _verification_marker=hashlib.sha256(signature_payload(envelope) + trust_digest.encode("ascii")).digest(),
        )
    except PackLifecycleError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error, ValueError) as exc:
        raise PackLifecycleError("pack_package_invalid") from exc


@dataclass(frozen=True)
class PackState:
    pack_id: str
    version: str
    status: Literal["submitted", "approved", "enabled", "disabled"]
    content_digest: str


class PackLifecycleStore:
    """SQLite-backed immutable package versions with maker-checker activation."""

    def __init__(self, path: Path, *, trusted_registry: TrustedPublisherRegistry) -> None:
        self._trusted_registry = trusted_registry
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pack_versions (
              pack_id TEXT NOT NULL, version TEXT NOT NULL, content_digest TEXT NOT NULL,
              envelope_json TEXT NOT NULL, submitted_by TEXT NOT NULL, approved_by TEXT,
              status TEXT NOT NULL CHECK(status IN ('submitted','approved','enabled','disabled')),
              PRIMARY KEY(pack_id, version), UNIQUE(content_digest)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_enabled_pack ON pack_versions(pack_id) WHERE status='enabled';
            CREATE TABLE IF NOT EXISTS pack_events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, pack_id TEXT NOT NULL, version TEXT NOT NULL,
              action TEXT NOT NULL, actor TEXT NOT NULL, content_digest TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def submit(self, verified: VerifiedPack, *, actor: str) -> PackState:
        actor = self._actor(actor)
        envelope = verified.envelope
        if verified.trust_registry_digest != self._trusted_registry.digest:
            raise PackLifecycleError("pack_trust_snapshot_changed")
        key = self._trusted_registry.resolve(envelope.publisher_id, envelope.key_id)
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            signature = base64.b64decode(envelope.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, signature_payload(envelope))
        except ImportError as exc:
            raise PackLifecycleError("pack_signature_runtime_unavailable") from exc
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise PackLifecycleError("pack_signature_invalid") from exc
        conform_pack(envelope.manifest)
        manifest = envelope.manifest
        payload = json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO pack_versions VALUES (?,?,?,?,?,NULL,'submitted')",
                    (manifest.pack_id, manifest.version, manifest.content_digest, payload, actor),
                )
                self._event(manifest.pack_id, manifest.version, "submitted", actor, manifest.content_digest)
        except sqlite3.IntegrityError as exc:
            raise PackLifecycleError("pack_version_already_exists") from exc
        return self.get(manifest.pack_id, manifest.version)

    def approve(self, pack_id: str, version: str, *, actor: str) -> PackState:
        actor = self._actor(actor)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE pack_versions SET status='approved', approved_by=? WHERE pack_id=? AND version=? AND status='submitted' AND submitted_by<>?",
                (actor, pack_id, version, actor),
            )
            if cursor.rowcount != 1:
                raise PackLifecycleError("pack_approval_requires_distinct_actor_and_submitted_state")
            self._event(pack_id, version, "approved", actor, str(self._row(pack_id, version)["content_digest"]))
        return self.get(pack_id, version)

    def install(self, pack_id: str, version: str, *, actor: str) -> PackState:
        actor = self._actor(actor)
        row = self._row(pack_id, version)
        if row["status"] != "approved":
            raise PackLifecycleError("pack_install_requires_approval")
        envelope = SignedPackEnvelope.model_validate_json(row["envelope_json"])
        self._check_compatibility(envelope.manifest)
        conform_pack(envelope.manifest)
        with self._connection:
            self._connection.execute("UPDATE pack_versions SET status='disabled' WHERE pack_id=? AND status='enabled'", (pack_id,))
            self._connection.execute("UPDATE pack_versions SET status='enabled' WHERE pack_id=? AND version=? AND status='approved'", (pack_id, version))
            self._event(pack_id, version, "installed", actor, str(row["content_digest"]))
        return self.get(pack_id, version)

    def disable(self, pack_id: str, *, actor: str) -> PackState:
        actor = self._actor(actor)
        row = self._connection.execute("SELECT version FROM pack_versions WHERE pack_id=? AND status='enabled'", (pack_id,)).fetchone()
        if row is None:
            raise PackLifecycleError("pack_not_enabled")
        with self._connection:
            self._connection.execute("UPDATE pack_versions SET status='disabled' WHERE pack_id=? AND status='enabled'", (pack_id,))
            self._event(pack_id, str(row["version"]), "disabled", actor, str(self._row(pack_id, str(row["version"]))["content_digest"]))
        return self.get(pack_id, str(row["version"]))

    def rollback(self, pack_id: str, *, target_version: str, actor: str) -> PackState:
        actor = self._actor(actor)
        target = self._row(pack_id, target_version)
        if target["status"] != "disabled" or target["approved_by"] is None:
            raise PackLifecycleError("pack_rollback_target_invalid")
        self._check_compatibility(SignedPackEnvelope.model_validate_json(target["envelope_json"]).manifest)
        with self._connection:
            self._connection.execute("UPDATE pack_versions SET status='disabled' WHERE pack_id=? AND status='enabled'", (pack_id,))
            self._connection.execute("UPDATE pack_versions SET status='enabled' WHERE pack_id=? AND version=? AND status='disabled'", (pack_id, target_version))
            self._event(pack_id, target_version, "rolled_back", actor, str(target["content_digest"]))
        return self.get(pack_id, target_version)

    def events(self, pack_id: str) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            "SELECT sequence,version,action,actor,content_digest FROM pack_events WHERE pack_id=? ORDER BY sequence",
            (pack_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def get(self, pack_id: str, version: str) -> PackState:
        row = self._row(pack_id, version)
        return PackState(pack_id=str(row["pack_id"]), version=str(row["version"]), status=row["status"], content_digest=str(row["content_digest"]))

    def _row(self, pack_id: str, version: str) -> sqlite3.Row:
        row = self._connection.execute("SELECT * FROM pack_versions WHERE pack_id=? AND version=?", (pack_id, version)).fetchone()
        if row is None:
            raise PackLifecycleError("pack_version_not_found")
        return row

    def _event(self, pack_id: str, version: str, action: str, actor: str, digest: str) -> None:
        self._connection.execute(
            "INSERT INTO pack_events(pack_id,version,action,actor,content_digest) VALUES (?,?,?,?,?)",
            (pack_id, version, action, actor, digest),
        )

    def _check_compatibility(self, manifest: PackManifest) -> None:
        if not _matches(__version__, manifest.reconforge_version):
            raise PackLifecycleError("pack_platform_incompatible")
        for dependency in manifest.dependencies:
            active = self._connection.execute(
                "SELECT version FROM pack_versions WHERE pack_id=? AND status='enabled'",
                (dependency.pack_id,),
            ).fetchone()
            if active is None or not _matches(str(active["version"]), dependency.version_constraint):
                raise PackLifecycleError("pack_dependency_unsatisfied")

    @staticmethod
    def _actor(actor: str) -> str:
        value = actor.strip()
        if not value or len(value) > 160:
            raise PackLifecycleError("pack_actor_invalid")
        return value
