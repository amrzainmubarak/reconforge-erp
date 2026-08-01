# Air-gapped installation boundary

`reconforge.sovereign.verify_offline_bundle` verifies a local
`offline-bundle.v1.json` before any installation process starts. The bundle root is a
closed inventory: every non-manifest file must be declared and no declared file may be
missing. Each entry is a regular, non-linked file with an exact size and SHA-256.

The requirements lock accepts only one exact requirement plus one SHA-256 hash per
non-comment line. URLs, indexes, editable installs, local paths, environment markers,
continuations, and unhashed requirements are rejected. Successful verification returns
an argument vector for `python -m pip install --no-index --disable-pip-version-check
--find-links <local-wheelhouse> --require-hashes -r <local-lock>`; it does not execute it.

This contract is the first P3-ENT-011 slice. The later Docker installation drill proves
one complete Linux dependency mirror and logical no-network install. Local-identity
recovery, backup/restore, upgrade/rollback composition, repetition, another platform,
and physical transfer controls remain required before task exit.

The reproducibility drill is `python .github/scripts/verify_airgap_install.py`. Its
connected assembly stage exports the locked runtime extras and downloads only hashed
Linux wheels. It then creates a closed manifest and a one-hash-per-selected-wheel lock.
A distinct installation container runs with `--network none`, a read-only root, a
read-only bundle mount, bounded tmpfs paths, `--no-index`, `--no-deps`, and
`--require-hashes`. The 2026-07-30 run installed 60 declared files (98,913,160 bytes)
and `reconforge doctor` exited zero on digest-pinned Python 3.14.1 slim. This proves one
logical no-network runtime, not a physical air gap or the remaining task gates.

## Disconnected attestation verification

`.github/scripts/verify_offline_attestations.py` accepts an already transferred release
evidence directory, a pinned `gh` binary, and a pinned Sigstore trusted-root snapshot.
It rejects traversal, links, malformed/duplicate checksum entries, digest drift,
unexpected release identities, and an incomplete artifact set. It then invokes `gh`
without a shell and requires repository, workflow, signer commit, source tag, source
commit, and GitHub-hosted-runner constraints for every verified attestation.

The 2026-07-30 Docker drill ran with network mode `none`, read-only root/evidence mounts,
and exact verifier/trusted-root hashes. It verified 15 checksum subjects, all six bundle
file hashes, provenance for 11 regular-file subjects, and CycloneDX attestations for the
source archive, wheel, and sdist. `gh 2.78.0` still resolves an `oci://` subject against
its registry even when a local bundle is supplied. Therefore the image provenance and
image-SBOM bundle bytes are integrity-checked, but their OCI subject identities are not
claimed as offline-verified. Do not enable temporary egress to turn this boundary green;
perform connected OCI verification as a separate gate or adopt a future verifier that
can validate the digest-addressed OCI subject entirely from local material.

## Local identity and recovery

The installation drill also runs `.github/scripts/verify_airgap_identity_recovery.py`
from the installed wheel. It generates credentials and an operator backup key only in
bounded tmpfs, creates two local users, checks local authentication and the admin role,
creates a session, and verifies the source audit chain. It then creates an AES-256-GCM
backup, proves a wrong key is rejected without leaving a partial restore, restores into
a new database, and proves both local credentials and the audit chain survive while the
old bearer session does not. The container and tmpfs are removed after the run.

This is fallback through pre-provisioned local identities plus authenticated backup. It
is not forgotten-password recovery, hardware-backed key custody, or authorization to
create an undocumented break-glass account. Operators must provision and test distinct
local identities before isolation and keep the backup key separate from the ciphertext.

## Upgrade, rollback, and signed-subject composition

The extended drill builds supported v0.7.0/v0.7.1 wheels during connected preparation,
mounts them read-only, and performs the adapter's no-index/no-deps cutover and exact
rollback while Docker networking is disabled. This verifies the application resource;
database/object/configuration/pack transitions retain their separate P3-ENT-009 evidence.

For release consumption, pass `--application-wheel`, its mandatory
`--expected-application-sha256`, and `--base-install-only`. The installer checks the
external wheel's digest and package/version metadata before it enters the closed mirror.
E-219 used the exact wheel subject already verified by E-216, avoiding the invalid
assumption that a locally rebuilt wheel inherits the signed candidate's identity.
