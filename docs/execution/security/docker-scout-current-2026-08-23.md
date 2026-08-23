# Docker Scout vulnerability scan — 2026-08-23

## Result

- Tool: Docker Scout `v1.24.0`.
- Input: local image `reconforge:current`, digest prefix
  `e86d4871981c`, platform `linux/amd64`.
- Indexed packages: 82.
- Vulnerabilities reported: `0C 0H 0M 0L`.
- Exit code: 0.

A separate base-layer-only run also returned exit code 0 with `0C 0H 0M 0L`:

```text
docker scout cves local://reconforge:current --only-base --format packages --output output/docker-scout-current-base.txt
```

Verification command:

```text
docker scout cves local://reconforge:current --only-severity critical,high --format packages --output output/docker-scout-current-high-critical.txt
```

The raw local report is retained at
`output/docker-scout-current-high-critical.txt` when the run workspace keeps
generated output. The command used `local://` deliberately, so Docker Scout did
not resolve a registry image.

## Boundary

This is a local Docker Scout package scan against the image as built on one
workstation. It does not prove registry signing/provenance, hosted scanner
parity, source reachability, malware detection, license policy, runtime
behavior, or production security.
