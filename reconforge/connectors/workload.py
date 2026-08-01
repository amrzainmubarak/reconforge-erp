"""Durable connector-page workload over existing fenced jobs and immutable object storage."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from reconforge.application.jobs import DurableJobWorkerService, LeasedJob
from reconforge.connectors.network import (
    MAX_CURSOR_BYTES,
    ConnectorNetworkError,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
)
from reconforge.domain.jobs import DurableJob, JobOutputManifest
from reconforge.infrastructure.object_storage import ObjectStorageConflictError


class ConnectorStoredObject(Protocol):
    content: bytes
    sha256: str


class ConnectorObjectStore(Protocol):
    def put_bytes(
        self,
        tenant_id: object,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, object] | None = None,
    ) -> ConnectorStoredObject: ...

    def get_bytes(self, tenant_id: object, object_name: str) -> ConnectorStoredObject: ...


class ConnectorCheckpointArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_schema: str = Field(pattern=r"^connector-checkpoint-artifact-v1$")
    registration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_base64: str = Field(max_length=22_369_624)
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_BYTES)
    attempts: int = Field(ge=1, le=10)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    def decoded_response(self) -> bytes:
        try:
            content = base64.b64decode(self.response_base64, validate=True)
        except ValueError as exc:
            raise ConnectorNetworkError("connector_checkpoint_response_invalid") from exc
        if hashlib.sha256(content).hexdigest() != self.response_digest:
            raise ConnectorNetworkError("connector_checkpoint_response_digest_invalid")
        return content


@dataclass(frozen=True)
class ConnectorPageCommit:
    job: DurableJob | LeasedJob
    artifact_name: str
    artifact_digest: str
    next_cursor: str | None


@dataclass
class DurableConnectorWorkload:
    executor: NetworkConnectorExecutor
    object_store: ConnectorObjectStore

    def run_page(
        self,
        worker: DurableJobWorkerService,
        leased_job: LeasedJob,
        registration: NetworkConnectorRegistration,
        *,
        ordinal: int,
        idempotency_key: str,
        cursor: str | None,
        occurred_at: str,
        final: bool,
    ) -> ConnectorPageCommit:
        if leased_job.job.config_digest != registration.digest:
            raise ConnectorNetworkError("connector_job_registration_digest_mismatch")
        if ordinal != leased_job.job.completed_units + 1:
            raise ConnectorNetworkError("connector_job_partition_ordinal_invalid")
        if final != (ordinal == leased_job.job.total_units):
            raise ConnectorNetworkError("connector_job_final_partition_invalid")
        result = self.executor.read(registration, idempotency_key=idempotency_key, cursor=cursor)
        artifact = ConnectorCheckpointArtifact(
            artifact_schema="connector-checkpoint-artifact-v1",
            registration_digest=registration.digest,
            request_digest=result.request_digest,
            response_digest=result.response_digest,
            response_base64=base64.b64encode(result.response_body).decode("ascii"),
            next_cursor=result.next_cursor,
            attempts=result.attempts,
        )
        content = artifact.canonical_bytes()
        object_name = f"connector-jobs/{leased_job.job.id}/page-{ordinal:08d}.json"
        try:
            stored = self.object_store.put_bytes(
                leased_job.job.tenant_id,
                object_name,
                content,
                content_type="application/json",
                metadata={
                    "connector-id": registration.manifest.connector_id,
                    "job-id": leased_job.job.id,
                    "registration-digest": registration.digest,
                },
            )
        except ObjectStorageConflictError:
            stored = self.object_store.get_bytes(leased_job.job.tenant_id, object_name)
        if stored.content != content or stored.sha256 != hashlib.sha256(content).hexdigest():
            raise ConnectorNetworkError("connector_checkpoint_storage_integrity_failed")
        if final:
            prior = worker.completed_effects(leased_job)
            chain_payload = [effect.output_digest for effect in prior] + [stored.sha256]
            chain_digest = hashlib.sha256("".join(chain_payload).encode("ascii")).hexdigest()
            completed = worker.complete_partition(
                leased_job,
                partition_key=f"page/{ordinal:08d}",
                ordinal=ordinal,
                input_digest=result.request_digest,
                output_digest=stored.sha256,
                effect_reference=object_name,
                occurred_at=occurred_at,
                output_manifest=JobOutputManifest(1, chain_digest, object_name),
            )
            return ConnectorPageCommit(completed, object_name, stored.sha256, result.next_cursor)
        changed = worker.commit_partition(
            leased_job,
            partition_key=f"page/{ordinal:08d}",
            ordinal=ordinal,
            completed_units=ordinal,
            input_digest=result.request_digest,
            output_digest=stored.sha256,
            effect_reference=object_name,
            occurred_at=occurred_at,
        )
        return ConnectorPageCommit(changed, object_name, stored.sha256, result.next_cursor)

    def resume_cursor(self, worker: DurableJobWorkerService, leased_job: LeasedJob) -> str | None:
        effects = worker.completed_effects(leased_job)
        if not effects:
            return None
        latest = effects[-1]
        if latest.ordinal != leased_job.job.completed_units:
            raise ConnectorNetworkError("connector_checkpoint_progress_mismatch")
        stored = self.object_store.get_bytes(leased_job.job.tenant_id, latest.effect_reference)
        if stored.sha256 != latest.output_digest or hashlib.sha256(stored.content).hexdigest() != latest.output_digest:
            raise ConnectorNetworkError("connector_checkpoint_storage_integrity_failed")
        try:
            artifact = ConnectorCheckpointArtifact.model_validate_json(stored.content)
        except ValueError as exc:
            raise ConnectorNetworkError("connector_checkpoint_invalid") from exc
        if artifact.registration_digest != leased_job.job.config_digest:
            raise ConnectorNetworkError("connector_job_registration_digest_mismatch")
        artifact.decoded_response()
        return artifact.next_cursor
