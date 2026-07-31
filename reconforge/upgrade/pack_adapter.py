"""Upgrade-saga adapter for the existing signed pack lifecycle store."""

from __future__ import annotations

from typing import Literal

from reconforge.packs.lifecycle import PackLifecycleError, PackLifecycleStore
from reconforge.upgrade.orchestrator import ApplyReceipt, PreflightEvidence, StepKind, UpgradeError, UpgradeStep


class SignedPackUpgradeAdapter:
    kind: StepKind = "pack"

    def __init__(self, *, resource_id: str, store: PackLifecycleStore, actor: str) -> None:
        self.resource_id = resource_id
        self._store = store
        self._actor = actor.strip()
        if not self._actor:
            raise UpgradeError("pack_upgrade_actor_invalid")

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        self._validate_step(step)
        try:
            source = self._store.get(self.resource_id, step.from_version)
            target = self._store.get(self.resource_id, step.to_version)
        except PackLifecycleError as exc:
            raise UpgradeError("pack_upgrade_version_missing") from exc
        if source.status != "enabled" or target.status != "approved":
            raise UpgradeError("pack_upgrade_lifecycle_state_invalid")
        if target.content_digest != step.target_sha256:
            raise UpgradeError("pack_upgrade_target_digest_mismatch")
        return PreflightEvidence(source.content_digest, source.content_digest, target.content_digest)

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        self._validate_step(step)
        source = self._store.get(self.resource_id, step.from_version)
        target = self._store.get(self.resource_id, step.to_version)
        if source.status != "enabled" or source.content_digest != evidence.source_digest or target.content_digest != evidence.compatibility_digest:
            raise UpgradeError("pack_upgrade_state_changed_after_preflight")
        try:
            installed = self._store.install(self.resource_id, step.to_version, actor=self._actor)
        except PackLifecycleError as exc:
            raise UpgradeError("pack_upgrade_install_failed") from exc
        return ApplyReceipt(installed.content_digest, step.from_version)

    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None:
        self._validate_step(step)
        try:
            source = self._store.get(self.resource_id, step.from_version)
            target = self._store.get(self.resource_id, step.to_version)
        except PackLifecycleError:
            return None
        if source.status == "enabled" and source.content_digest == evidence.source_digest and target.status == "approved":
            return "not_applied"
        if source.status == "disabled" and target.status == "enabled" and target.content_digest == evidence.compatibility_digest:
            return ApplyReceipt(target.content_digest, step.from_version)
        return None

    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        target = self._store.get(self.resource_id, step.to_version)
        if receipt.rollback_token != step.from_version or target.status != "enabled" or target.content_digest != receipt.output_digest:
            raise UpgradeError("pack_upgrade_verification_failed")
        return target.content_digest

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        if receipt.rollback_token != step.from_version:
            raise UpgradeError("pack_upgrade_receipt_invalid")
        try:
            restored = self._store.rollback(self.resource_id, target_version=step.from_version, actor=self._actor)
        except PackLifecycleError as exc:
            raise UpgradeError("pack_upgrade_rollback_failed") from exc
        return restored.content_digest

    def _validate_step(self, step: UpgradeStep) -> None:
        if step.kind != self.kind or step.resource_id != self.resource_id:
            raise UpgradeError("pack_upgrade_step_identity_mismatch")
        if step.compatibility_reader != "signed-pack-v1-reader":
            raise UpgradeError("pack_upgrade_compatibility_reader_unsupported")
