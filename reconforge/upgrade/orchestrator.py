"""Fail-closed upgrade orchestration with durable receipts and reverse rollback.

Adapters own one bounded resource.  The orchestrator never assumes a database,
filesystem, object store, configuration, or pack mutation is transactionally
atomic with another resource.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reconforge import __version__

StepKind = Literal["application", "database", "object_store", "configuration", "pack"]
STEP_ORDER: tuple[StepKind, ...] = ("application", "database", "object_store", "configuration", "pack")


class UpgradeError(RuntimeError):
    """Stable upgrade failure safe for operator logs."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class UpgradeStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: StepKind
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=100)
    from_version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    to_version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rollback_required: Literal[True] = True
    compatibility_reader: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def version_changes(self) -> UpgradeStep:
        if self.from_version == self.to_version:
            raise ValueError("upgrade step versions must differ")
        return self


class UpgradePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_schema: Literal["reconforge-upgrade-plan-v1"] = Field(
        default="reconforge-upgrade-plan-v1", alias="schema"
    )
    plan_id: str = Field(pattern=r"^UPG-[A-Z0-9][A-Z0-9-]{5,63}$")
    operator_application_version: str = __version__
    current_application_version: str
    target_application_version: str
    release_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    steps: tuple[UpgradeStep, ...] = Field(min_length=1, max_length=100)

    @field_validator("operator_application_version", "current_application_version", "target_application_version")
    @classmethod
    def exact_semver(cls, value: str) -> str:
        parts = value.split(".")
        if len(parts) != 3 or any(not part.isdigit() or (len(part) > 1 and part.startswith("0")) for part in parts):
            raise ValueError("application version must be exact semantic version")
        return value

    @model_validator(mode="after")
    def closed_order_and_application_identity(self) -> UpgradePlan:
        if self.operator_application_version != __version__:
            raise ValueError("upgrade plan operator application version differs from runtime")
        order = [STEP_ORDER.index(step.kind) for step in self.steps]
        identities = [(step.kind, step.resource_id) for step in self.steps]
        if order != sorted(order) or len(identities) != len(set(identities)):
            raise ValueError("upgrade steps must be ordered and uniquely identify resources")
        application = [step for step in self.steps if step.kind == "application"]
        if len(application) != 1 or application[0].from_version != self.current_application_version or application[0].to_version != self.target_application_version:
            raise ValueError("one application step must bind plan versions")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.model_dump(mode="json", by_alias=True)).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class PreflightEvidence:
    source_digest: str
    rollback_digest: str
    compatibility_digest: str

    def __post_init__(self) -> None:
        for digest in (self.source_digest, self.rollback_digest, self.compatibility_digest):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise UpgradeError("upgrade_preflight_digest_invalid")


@dataclass(frozen=True)
class ApplyReceipt:
    output_digest: str
    rollback_token: str

    def __post_init__(self) -> None:
        if len(self.output_digest) != 64 or any(char not in "0123456789abcdef" for char in self.output_digest):
            raise UpgradeError("upgrade_output_digest_invalid")
        if not self.rollback_token or len(self.rollback_token) > 4096:
            raise UpgradeError("upgrade_rollback_token_invalid")


class UpgradeAdapter(Protocol):
    kind: StepKind
    resource_id: str

    def preflight(self, step: UpgradeStep) -> PreflightEvidence: ...
    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt: ...
    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None: ...
    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str: ...
    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str: ...


class UpgradeOrchestrator:
    """Execute one plan with durable per-step evidence and resumable rollback."""

    def __init__(self, journal_path: Path, adapters: tuple[UpgradeAdapter, ...]) -> None:
        self._adapters = {(adapter.kind, adapter.resource_id): adapter for adapter in adapters}
        if len(self._adapters) != len(adapters):
            raise UpgradeError("upgrade_adapter_identity_duplicate")
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(journal_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS upgrade_runs(
              plan_id TEXT PRIMARY KEY, plan_digest TEXT NOT NULL UNIQUE,
              plan_json TEXT NOT NULL, prepared_by TEXT NOT NULL, approved_by TEXT,
              executed_by TEXT, status TEXT NOT NULL CHECK(status IN ('prepared','approved','running','rolling_back','rolled_back','completed','failed'))
            );
            CREATE TABLE IF NOT EXISTS upgrade_steps(
              plan_id TEXT NOT NULL, position INTEGER NOT NULL, kind TEXT NOT NULL,
              resource_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('prepared','applying','applied','verified','rolled_back')),
              preflight_json TEXT NOT NULL, receipt_json TEXT,
              PRIMARY KEY(plan_id,position), FOREIGN KEY(plan_id) REFERENCES upgrade_runs(plan_id)
            );
            CREATE TABLE IF NOT EXISTS upgrade_events(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL,
              action TEXT NOT NULL, actor TEXT NOT NULL, evidence_digest TEXT NOT NULL,
              FOREIGN KEY(plan_id) REFERENCES upgrade_runs(plan_id)
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def prepare(self, plan: UpgradePlan, *, release_manifest_bytes: bytes, actor: str) -> str:
        actor = self._actor(actor)
        if hashlib.sha256(release_manifest_bytes).hexdigest() != plan.release_manifest_sha256:
            raise UpgradeError("upgrade_release_manifest_digest_mismatch")
        existing = self._connection.execute("SELECT plan_digest FROM upgrade_runs WHERE plan_id=?", (plan.plan_id,)).fetchone()
        if existing is not None:
            if existing["plan_digest"] != plan.digest:
                raise UpgradeError("upgrade_plan_identity_conflict")
            return plan.digest
        evidence: list[PreflightEvidence] = []
        for step in plan.steps:
            adapter = self._adapter(step)
            try:
                evidence.append(adapter.preflight(step))
            except Exception as exc:
                raise UpgradeError("upgrade_preflight_failed") from exc
        with self._connection:
            self._connection.execute(
                "INSERT INTO upgrade_runs VALUES (?,?,?, ?,NULL,NULL,'prepared')",
                (plan.plan_id, plan.digest, _canonical(plan.model_dump(mode="json", by_alias=True)), actor),
            )
            for position, (step, proof) in enumerate(zip(plan.steps, evidence, strict=True)):
                self._connection.execute(
                    "INSERT INTO upgrade_steps VALUES (?,?,?,?, 'prepared', ?, NULL)",
                    (plan.plan_id, position, step.kind, step.resource_id, _canonical(proof.__dict__)),
                )
            self._event(plan.plan_id, "prepared", actor, plan.digest)
        return plan.digest

    def approve(self, plan: UpgradePlan, *, actor: str) -> None:
        actor = self._actor(actor)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE upgrade_runs SET status='approved',approved_by=? WHERE plan_id=? AND plan_digest=? AND status='prepared' AND prepared_by<>?",
                (actor, plan.plan_id, plan.digest, actor),
            )
            if cursor.rowcount != 1:
                raise UpgradeError("upgrade_approval_requires_distinct_actor_and_prepared_state")
            self._event(plan.plan_id, "approved", actor, plan.digest)

    def execute(self, plan: UpgradePlan, *, actor: str) -> str:
        actor = self._actor(actor)
        run = self._run(plan)
        if run["status"] == "completed":
            return self.output_digest(plan.plan_id)
        if run["status"] in {"rolling_back", "rolled_back", "failed"}:
            raise UpgradeError("upgrade_run_not_executable")
        with self._connection:
            if run["status"] == "approved":
                cursor = self._connection.execute(
                    "UPDATE upgrade_runs SET status='running',executed_by=? WHERE plan_id=? AND status='approved'",
                    (actor, plan.plan_id),
                )
                if cursor.rowcount != 1:
                    raise UpgradeError("upgrade_execution_claim_conflict")
                self._event(plan.plan_id, "started", actor, plan.digest)
            elif run["status"] != "running" or run["executed_by"] != actor:
                raise UpgradeError("upgrade_execution_requires_approval_or_same_actor_resume")
        try:
            for position, step in enumerate(plan.steps):
                row = self._step(plan.plan_id, position)
                if row["status"] == "verified":
                    continue
                proof = PreflightEvidence(**json.loads(row["preflight_json"]))
                if row["status"] == "applying":
                    recovered = self._adapter(step).recover(step, proof)
                    if recovered is None:
                        raise UpgradeError("upgrade_uncertain_step_requires_isolation")
                    if recovered == "not_applied":
                        with self._connection:
                            self._connection.execute(
                                "UPDATE upgrade_steps SET status='prepared' WHERE plan_id=? AND position=? AND status='applying'",
                                (plan.plan_id, position),
                            )
                        row = self._step(plan.plan_id, position)
                    else:
                        with self._connection:
                            self._connection.execute(
                                "UPDATE upgrade_steps SET status='applied',receipt_json=? WHERE plan_id=? AND position=? AND status='applying'",
                                (_canonical(recovered.__dict__), plan.plan_id, position),
                            )
                        row = self._step(plan.plan_id, position)
                if row["status"] == "applied":
                    receipt = ApplyReceipt(**json.loads(row["receipt_json"]))
                    verified = self._adapter(step).verify(step, receipt)
                    if verified != receipt.output_digest:
                        raise UpgradeError("upgrade_step_verification_mismatch")
                    with self._connection:
                        self._connection.execute("UPDATE upgrade_steps SET status='verified' WHERE plan_id=? AND position=? AND status='applied'", (plan.plan_id, position))
                    continue
                with self._connection:
                    self._connection.execute("UPDATE upgrade_steps SET status='applying' WHERE plan_id=? AND position=?", (plan.plan_id, position))
                try:
                    receipt = self._adapter(step).apply(step, proof)
                except Exception:
                    recovered = self._adapter(step).recover(step, proof)
                    if isinstance(recovered, ApplyReceipt):
                        with self._connection:
                            self._connection.execute(
                                "UPDATE upgrade_steps SET status='applied',receipt_json=? WHERE plan_id=? AND position=? AND status='applying'",
                                (_canonical(recovered.__dict__), plan.plan_id, position),
                            )
                    raise
                with self._connection:
                    self._connection.execute(
                        "UPDATE upgrade_steps SET status='applied',receipt_json=? WHERE plan_id=? AND position=? AND status='applying'",
                        (_canonical(receipt.__dict__), plan.plan_id, position),
                    )
                verified = self._adapter(step).verify(step, receipt)
                if verified != receipt.output_digest:
                    raise UpgradeError("upgrade_step_verification_mismatch")
                with self._connection:
                    self._connection.execute("UPDATE upgrade_steps SET status='verified' WHERE plan_id=? AND position=? AND status='applied'", (plan.plan_id, position))
        except Exception as exc:
            self._rollback(plan)
            raise UpgradeError("upgrade_execution_failed_and_rolled_back") from exc
        with self._connection:
            self._connection.execute("UPDATE upgrade_runs SET status='completed' WHERE plan_id=?", (plan.plan_id,))
            self._event(plan.plan_id, "completed", actor, self.output_digest(plan.plan_id))
        return self.output_digest(plan.plan_id)

    def _rollback(self, plan: UpgradePlan) -> None:
        with self._connection:
            self._connection.execute("UPDATE upgrade_runs SET status='rolling_back' WHERE plan_id=?", (plan.plan_id,))
        try:
            for position in reversed(range(len(plan.steps))):
                row = self._step(plan.plan_id, position)
                if row["status"] == "applying":
                    proof = PreflightEvidence(**json.loads(row["preflight_json"]))
                    recovered = self._adapter(plan.steps[position]).recover(plan.steps[position], proof)
                    if recovered is None:
                        raise UpgradeError("upgrade_uncertain_step_requires_isolation")
                    if recovered == "not_applied":
                        with self._connection:
                            self._connection.execute(
                                "UPDATE upgrade_steps SET status='rolled_back' WHERE plan_id=? AND position=? AND status='applying'",
                                (plan.plan_id, position),
                            )
                        continue
                    with self._connection:
                        self._connection.execute(
                            "UPDATE upgrade_steps SET status='applied',receipt_json=? WHERE plan_id=? AND position=? AND status='applying'",
                            (_canonical(recovered.__dict__), plan.plan_id, position),
                        )
                    row = self._step(plan.plan_id, position)
                if row["status"] not in {"applied", "verified"}:
                    continue
                receipt = ApplyReceipt(**json.loads(row["receipt_json"]))
                digest = self._adapter(plan.steps[position]).rollback(plan.steps[position], receipt)
                proof = PreflightEvidence(**json.loads(row["preflight_json"]))
                if digest != proof.source_digest:
                    raise UpgradeError("upgrade_rollback_verification_mismatch")
                with self._connection:
                    self._connection.execute("UPDATE upgrade_steps SET status='rolled_back' WHERE plan_id=? AND position=?", (plan.plan_id, position))
        except Exception as exc:
            with self._connection:
                self._connection.execute("UPDATE upgrade_runs SET status='failed' WHERE plan_id=?", (plan.plan_id,))
            raise UpgradeError("upgrade_rollback_failed_isolate_resources") from exc
        with self._connection:
            self._connection.execute("UPDATE upgrade_runs SET status='rolled_back' WHERE plan_id=?", (plan.plan_id,))

    def output_digest(self, plan_id: str) -> str:
        rows = self._connection.execute(
            "SELECT position,kind,resource_id,receipt_json FROM upgrade_steps WHERE plan_id=? AND status='verified' ORDER BY position",
            (plan_id,),
        ).fetchall()
        return hashlib.sha256(_canonical([dict(row) for row in rows]).encode("ascii")).hexdigest()

    def status(self, plan_id: str) -> str:
        row = self._connection.execute("SELECT status FROM upgrade_runs WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            raise UpgradeError("upgrade_plan_not_prepared")
        return str(row["status"])

    def events(self, plan_id: str) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            "SELECT sequence,action,actor,evidence_digest FROM upgrade_events WHERE plan_id=? ORDER BY sequence",
            (plan_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def _run(self, plan: UpgradePlan) -> sqlite3.Row:
        row = self._connection.execute("SELECT * FROM upgrade_runs WHERE plan_id=? AND plan_digest=?", (plan.plan_id, plan.digest)).fetchone()
        if row is None:
            raise UpgradeError("upgrade_plan_not_prepared_or_digest_changed")
        return row

    def _step(self, plan_id: str, position: int) -> sqlite3.Row:
        row = self._connection.execute("SELECT * FROM upgrade_steps WHERE plan_id=? AND position=?", (plan_id, position)).fetchone()
        if row is None:
            raise UpgradeError("upgrade_journal_step_missing")
        return row

    def _adapter(self, step: UpgradeStep) -> UpgradeAdapter:
        adapter = self._adapters.get((step.kind, step.resource_id))
        if adapter is None:
            raise UpgradeError("upgrade_adapter_missing")
        return adapter

    def _event(self, plan_id: str, action: str, actor: str, digest: str) -> None:
        self._connection.execute(
            "INSERT INTO upgrade_events(plan_id,action,actor,evidence_digest) VALUES (?,?,?,?)",
            (plan_id, action, actor, digest),
        )

    @staticmethod
    def _actor(actor: str) -> str:
        value = actor.strip()
        if not value or len(value) > 160:
            raise UpgradeError("upgrade_actor_invalid")
        return value
