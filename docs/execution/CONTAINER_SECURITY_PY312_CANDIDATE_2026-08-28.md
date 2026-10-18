# Python 3.12 container candidate evidence

This is local candidate evidence for E-884. It is not a publication or hosted
release artifact.

| Subject | Observed value |
| --- | --- |
| Dockerfile base | `python:3.12-alpine@sha256:d09d15e60962ca365d1cd544a48773bac9d33f2fb1b00f2aa0deec78ade7dc31` |
| Platform | `linux/amd64` |
| Candidate image digest | `sha256:a96d87d994852b9fc7b9f647977413e37f5959a95f0e7d36bc66584a8b529e52` |
| Image config digest | `sha256:08723531122c50615c42860fd299b9bb797ba67c231b7f1cb5b1cc8b3822cf0f` |
| Runtime | CPython `3.12.14`, Alpine 3.24 |
| Docker Engine | `29.7.2` |
| Docker Scout | `1.24.0`, 82 packages, 0 Critical/High/Medium/Low, exit 0 |

## Reproduction commands

```text
docker build --pull --no-cache --platform linux/amd64 -t reconforge:python312-candidate .
docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges reconforge:python312-candidate reconforge doctor
docker run --rm --network=none --read-only --tmpfs /tmp --cap-drop=ALL --security-opt=no-new-privileges reconforge:python312-candidate reconforge validate examples/sample_data
docker run --rm --network=none --read-only --tmpfs /tmp --cap-drop=ALL --security-opt=no-new-privileges reconforge:python312-candidate reconforge demo run --output /tmp/demo-output
docker scout cves --only-severity critical,high --format packages image://reconforge:python312-candidate
```

All four commands completed with exit 0. Doctor and validation reported zero
errors; the sample data deliberately reports ten warnings. Demo output was
written under the disposable `/tmp/demo-output` mount.

The same locked all-extra test command passed on Python 3.11 and 3.12. Web
typecheck, 75 web tests, production build, package build, API/parity tests, and
air-gap rollback drills also passed on this source revision.

## Scanner boundary

The local Docker Scout result and the exact release-integrated Syft/Grype result
are both available. Grype 0.117.0 imported a fresh official v6.1.9 database in
an isolated cache, verified it as valid, scanned the candidate SBOM, and the
repository validator returned `status=passed` with zero blockers and zero
active exceptions. The raw database payload SHA-256 is
`4304a9eb9165b8ffd0613b0b60b0379444e1a9b5ef0882ca80547775f3bef054`.

E-824 is closed for the local exact-image disposition. Hosted clean-build,
registry publication, signed provenance, legal license review, and production
security effectiveness remain open under the release gates.
