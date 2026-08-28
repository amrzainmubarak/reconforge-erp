# ADR 0535: Run the container as a bounded non-root runtime

- Status: Accepted
- Date: 2026-08-22
- Scope: E-822 local container build and runtime boundary

## Context

The prior Dockerfile installed the locked application and its build tool in one
stage, had no `.dockerignore`, and declared no runtime user. A clean local build
sent 53.82 MB to BuildKit and the resulting image executed as UID/GID 0. The
image could pass Doctor, but that did not establish least privilege or keep
local repository history, environments, and output outside the build-context
trust boundary.

## Decision

1. Use the current official Python 3.11 Alpine multi-platform digest and the
   official checksum-pinned uv musl archive. The preceding pinned Debian slim
   runtime is rejected for this revision because an exact-image scan reported
   unresolved High/Critical base findings.
2. Build the locked, non-editable virtual environment in a builder stage and
   copy only runtime dependencies and declared product assets into a separate
   runtime stage. Do not send repository documentation to BuildKit or ship uv,
   project build manifests, documentation, or the source tree in the runtime
   image. Documentation remains available from source/release surfaces.
3. Run as the fixed unprivileged identity `10001:10001` and make only
   `/app/output` writable in the image.
4. Remove the base image's global pip/setuptools/wheel site-packages and pip
   launchers from the runtime after the application venv is built. Package
   installation remains impossible through the application interpreter and
   build tooling is not part of the production execution surface.
5. Make `.dockerignore` deny by default and allow only the exact files and
   directories consumed by Dockerfile. Enforce the two digest-pinned stages and
   the closed context allowlist in the supply-chain policy validator.
6. Verify the CLI with networking disabled and a read-only root filesystem;
   provide bounded writable `tmpfs` mounts only for `/tmp` and `/app/output`.

## Consequences

- The measured context falls from 53.82 MB to 216.25 KB on the final tree, and
  the local image size falls from 149,556,826 to 58,773,988 bytes.
- Docker Scout 1.24.0 indexes 82 final-image packages and reports zero known
  findings at every severity on 2026-08-22. This result is time-bounded and is
  not a substitute for a recurring signed release scan.
- Bind-mounted output must be writable by the container identity. Operators
  retain responsibility for host ownership and disclosure controls.
- Passing on one Docker Desktop host is local runtime evidence, not OCI
  reproducibility, vulnerability assurance, production hardening, or a
  deployment-readiness claim.

## Compatibility

CLI commands and declared runtime assets are unchanged. The musl runtime passed
the complete documented CLI/demo smoke contract; complete cross-engine
numerical parity and performance remain separate gates. The deliberate runtime-
user change can expose host-volume permissions that previously succeeded only
because the container ran as root; the deployment guide documents the required
host permission or user-mapping decision. No API, schema, migration, financial
calculation, or persisted artifact format changes.
The unsupported internal `/app/docs` filesystem layout is intentionally absent;
operators use the version-matched source/release documentation instead.

## Rollback

Revert the multistage/runtime-user/context unit only if an equivalent
digest-pinned non-root boundary replaces it. Do not restore a root default or a
broad build context merely to hide a host-volume permission error.
