"""Run the digest-pinned live S3-compatible object-store contract.

The command is intentionally provider-neutral at the adapter boundary.  CI
supplies a disposable MinIO endpoint and synthetic credentials; the report
records only the endpoint shape, image digest, observed invariants, and
explicit limitations.  Credentials and object contents never enter the
report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import boto3

from reconforge.infrastructure.object_storage import (
    ObjectStorageConflictError,
    ObjectStorageConnectionFactory,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStorageOperationError,
    ObjectStorageScope,
    ObjectStorageSettings,
    S3ObjectStore,
)

REPORT_ID = "s3-compatible-object-store-live-v1"
IMAGE_DIGEST_PATTERN = "sha256:"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required live object-storage setting is missing: {name}")
    return value


def _endpoint_shape(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("Live object-storage endpoint must be an HTTP(S) URL without credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


def _ensure_bucket(client: object, bucket: str, *, object_lock: bool) -> None:
    try:
        client.head_bucket(Bucket=bucket)  # type: ignore[attr-defined]
        return
    except Exception:
        kwargs: dict[str, object] = {"Bucket": bucket}
        if object_lock:
            kwargs["ObjectLockEnabledForBucket"] = True
        client.create_bucket(**kwargs)  # type: ignore[attr-defined]


def _canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_contract() -> dict[str, object]:
    endpoint = _required("RECONFORGE_TEST_S3_ENDPOINT")
    bucket = _required("RECONFORGE_TEST_S3_BUCKET")
    lock_bucket = _required("RECONFORGE_TEST_S3_LOCK_BUCKET")
    image_digest = _required("RECONFORGE_S3_IMAGE_DIGEST")
    if not image_digest.startswith(IMAGE_DIGEST_PATTERN) or len(image_digest) != len(IMAGE_DIGEST_PATTERN) + 64:
        raise RuntimeError("RECONFORGE_S3_IMAGE_DIGEST must be a full sha256 digest")
    endpoint_shape = _endpoint_shape(endpoint)
    started = time.perf_counter()
    client = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1")
    _ensure_bucket(client, bucket, object_lock=False)
    _ensure_bucket(client, lock_bucket, object_lock=True)
    lock_config = client.get_object_lock_configuration(Bucket=lock_bucket)
    if lock_config.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled") != "Enabled":
        raise RuntimeError("Live lock bucket is not configured for object lock")

    normal_factory = ObjectStorageConnectionFactory(
        ObjectStorageSettings(
            bucket=bucket,
            endpoint_url=endpoint,
            require_tls=endpoint.startswith("https://"),
            allow_delete=True,
            server_side_encryption=None,
        )
    )
    lock_factory = ObjectStorageConnectionFactory(
        ObjectStorageSettings(
            bucket=lock_bucket,
            endpoint_url=endpoint,
            require_tls=endpoint.startswith("https://"),
            allow_delete=True,
            server_side_encryption=None,
            object_lock_mode="GOVERNANCE",
        )
    )
    normal_store = S3ObjectStore(normal_factory)
    lock_store = S3ObjectStore(lock_factory)
    scope_a = ObjectStorageScope("live-tenant", "workspace-a", "entity-a")
    scope_b = ObjectStorageScope("live-tenant", "workspace-b", "entity-a")
    object_name = f"integration/live-report-{uuid4().hex}.txt"
    lock_name = f"integration/live-retained-{uuid4().hex}.txt"
    normal_uploaded = None
    sibling_uploaded = None
    lock_uploaded = None
    observed = {
        "hierarchical_scope_isolation": False,
        "immutable_conflict_refusal": False,
        "checksum_tamper_refusal": False,
        "object_lock_delete_refusal": False,
        "cleanup": False,
    }
    try:
        normal_uploaded = normal_store.put_bytes(scope_a, object_name, b"workspace-a")
        sibling_uploaded = normal_store.put_bytes(scope_b, object_name, b"workspace-b")
        observed["hierarchical_scope_isolation"] = (
            normal_store.get_bytes(scope_a, object_name).content == b"workspace-a"
            and normal_store.get_bytes(scope_b, object_name).content == b"workspace-b"
            and normal_uploaded.key != sibling_uploaded.key
        )
        try:
            normal_store.get_bytes(ObjectStorageScope("live-tenant", "workspace-c", "entity-a"), object_name)
        except ObjectStorageNotFoundError:
            observed["hierarchical_scope_isolation"] = bool(observed["hierarchical_scope_isolation"])
        else:
            raise RuntimeError("Sibling scope unexpectedly read an object")
        try:
            normal_store.put_bytes(scope_a, object_name, b"replacement")
        except ObjectStorageConflictError:
            observed["immutable_conflict_refusal"] = True
        else:
            raise RuntimeError("Immutable object overwrite unexpectedly succeeded")
        client.put_object(
            Bucket=bucket,
            Key=normal_uploaded.key,
            Body=b"tampered",
            ContentType="application/octet-stream",
            Metadata=normal_uploaded.metadata,
        )
        try:
            normal_store.get_bytes(scope_a, object_name)
        except ObjectStorageIntegrityError:
            observed["checksum_tamper_refusal"] = True
        else:
            raise RuntimeError("Checksum tampering unexpectedly passed verification")

        lock_uploaded = lock_store.put_bytes(
            "live-tenant",
            lock_name,
            b"retained",
            retention_until=datetime.now(UTC) + timedelta(hours=1),
        )
        try:
            lock_store.delete("live-tenant", lock_name)
        except ObjectStorageOperationError:
            observed["object_lock_delete_refusal"] = True
        else:
            raise RuntimeError("Object-lock delete unexpectedly succeeded")
    finally:
        cleanup_ok = True
        for uploaded, target_bucket in (
            (normal_uploaded, bucket),
            (sibling_uploaded, bucket),
        ):
            if uploaded is not None:
                try:
                    kwargs: dict[str, object] = {"Bucket": target_bucket, "Key": uploaded.key}
                    if uploaded.version_id is not None:
                        kwargs["VersionId"] = uploaded.version_id
                    client.delete_object(**kwargs)
                except Exception:
                    cleanup_ok = False
        if lock_uploaded is not None:
            try:
                kwargs = {"Bucket": lock_bucket, "Key": lock_uploaded.key, "BypassGovernanceRetention": True}
                if lock_uploaded.version_id is not None:
                    kwargs["VersionId"] = lock_uploaded.version_id
                client.delete_object(**kwargs)
            except Exception:
                cleanup_ok = False
        normal_factory.close()
        lock_factory.close()
        observed["cleanup"] = cleanup_ok

    if not all(bool(value) for value in observed.values()):
        raise RuntimeError(f"Live object-storage invariant failed: {observed!r}")
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "report_id": REPORT_ID,
        "status": "verified",
        "provider": "minio",
        "image_digest": image_digest,
        "endpoint": endpoint_shape,
        "bucket_profile": "synthetic-disposable-normal-and-object-lock-buckets",
        "observed": observed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "limitations": [
            "single-node disposable MinIO process on one CI host",
            "no replication, KMS, cross-site durability, provider interoperability, or object-store HA claim",
            "synthetic credentials, object names, and bytes only",
        ],
    }
    payload["report_digest"] = _canonical_digest(payload)
    return payload


def verify_report(report: dict[str, object]) -> None:
    if report.get("report_id") != REPORT_ID or report.get("status") != "verified":
        raise ValueError("Live object-storage report identity or status is invalid")
    observed = report.get("observed")
    if not isinstance(observed, dict) or set(observed) != {
        "hierarchical_scope_isolation",
        "immutable_conflict_refusal",
        "checksum_tamper_refusal",
        "object_lock_delete_refusal",
        "cleanup",
    } or not all(observed.values()):
        raise ValueError("Live object-storage report has an incomplete invariant set")
    supplied = report.get("report_digest")
    payload = dict(report)
    payload.pop("report_digest", None)
    if not isinstance(supplied, str) or supplied != _canonical_digest(payload):
        raise ValueError("Live object-storage report digest mismatch")
    if any("secret" in key.lower() or "access_key" in key.lower() for key in report):
        raise ValueError("Live object-storage report must not contain credentials")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = _run_contract()
    verify_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
