# Disposable MinIO source fixture

This fixture exists only to run ReconForge's synthetic S3 and Object Lock CI
contracts. MinIO's upstream repository is archived and unmaintained. The fixture
does not designate a supported production provider, enter the ReconForge product
image, or change ReconForge's MIT license.

The previous `minio/minio` image became unavailable from its public registry.
The official annotated release tag `RELEASE.2025-09-07T16-13-09Z` resolves to
commit `07c3a429bfed433e49018cb0f78a52145d4bedeb`. The closed `fixture.v1.json`
contract pins that source archive's SHA256 and the Docker Official Go builder's
digest. The runner verifies the archive before processing it; the recipe also
verifies it, checks the Go version, verifies module checksums, and refuses changes
to `go.mod` or `go.sum`. The static server and its AGPL license are copied into a
separate nonroot `scratch` image.

```sh
python .github/scripts/build_minio_ci_fixture.py \
  --output output/minio-ci-build-provenance.json \
  --iidfile output/minio-ci.iid
```

`--source-archive` permits reuse of a previously downloaded archive and retains
the exact SHA256 check. CI executes the built image by its **OCI config digest**,
and asserts its version, source commit, and Go runtime before starting the
server. The build provenance records the manifest, recipe, source archive,
license, module-lock hashes, and actual image identity. The S3 report explicitly
sets `image_digest_kind: oci-config`; historical reports without that field
retain their original manifest-digest interpretation.

The runtime binds only localhost and uses a read-only root filesystem, no Linux
capabilities, and disposable tmpfs data. The complete existing real-provider
checks remain mandatory: hierarchical isolation, overwrite refusal, checksum
tamper refusal, Object Lock deletion refusal, and cleanup. Neither a mock S3
implementation nor a skipped retention check can satisfy this fixture.

Upstream references:

- [MinIO archive and source-only distribution notice](https://github.com/minio/minio)
- [Official release](https://github.com/minio/minio/releases/tag/RELEASE.2025-09-07T16-13-09Z)
- [Pinned upstream build flags](https://github.com/minio/minio/blob/07c3a429bfed433e49018cb0f78a52145d4bedeb/Makefile)
- [Pinned upstream license](https://github.com/minio/minio/blob/07c3a429bfed433e49018cb0f78a52145d4bedeb/LICENSE)
