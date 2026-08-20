# Live S3-compatible object-storage gate

The CI `object-storage` job exercises the optional `S3ObjectStore` against a
disposable MinIO process pinned to:

```text
minio/minio@sha256:13582eff79c6605a2d315bdd0e70164142ea7e98fc8411e9e10d089502a6d883
```

It creates synthetic normal and object-lock buckets, runs the report verifier,
runs the two live `test_object_storage_foundation.py` cases, uploads the
digest-bound report, and removes the container even after failure.

Run the same profile locally with Docker and synthetic environment variables:

```powershell
python .github/scripts/verify_s3_object_storage_live.py --output $env:TEMP\reconforge-s3-live-report.json
```

The endpoint, bucket names, AWS-compatible credentials, and image digest must
be supplied by the disposable environment. The report must not contain
credentials or object bytes. The profile is provider-runtime evidence only:
single-node MinIO does not establish replication, KMS, cross-site durability,
provider interoperability, object-store HA/DR, or production availability.
