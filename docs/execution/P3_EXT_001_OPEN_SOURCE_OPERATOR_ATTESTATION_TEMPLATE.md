# P3-EXT-001 Open-Source Operator Attestation

Status: candidate until accepted by an upstream human reviewer

This form records one real public-data technical pilot. It contains no customer
data and is not a security-review report.

## Operator identity and independence

- Operator's public GitHub identity:
- Operator name or stable pseudonym:
- Organization/affiliation (or `independent individual`):
- Conflict-of-interest declaration:
- Relationship to ReconForge maintainers, sponsors, or vendors:
- Confirmation that this operator does not control another submitted operator account:
- Contact route for verification:

## Exact execution identity

- Workflow run URL:
- Fork/repository URL:
- Workflow artifact URL and artifact ID:
- Source ref:
- Exact 40-character source commit:
- Run ID and attempt:
- Start/end time including timezone:
- GitHub-hosted runner image:
- Python version:

## Cryptographic evidence

- Report SHA-256:
- `SHA256SUMS` SHA-256:
- Provenance bundle SHA-256:
- GitHub artifact storage digest:
- Reproducibility SHA-256:
- `gh attestation verify` command and exit status:
- Confirmation that repository, signer workflow, source ref, source digest, and GitHub-hosted runner constraints matched:

## Observed financial/control outcomes

- Artifact count:
- Treasury matched/unmatched/exceptions and equation violations:
- World Bank source/selected counts, matched/unmatched/exceptions, and equation violations:
- UK record count, matched/unmatched/exceptions, negative count, repeated-reference groups, and threshold violations:
- Cross-format parity result:
- Row-permutation result:
- Report redaction result:

## Operator experience and failures

- Setup time and difficulty:
- What was clear:
- What was confusing:
- Failures, retries, endpoint drift, or warnings observed:
- Recovery steps taken:
- Missing diagnostics or documentation:
- Would you trust the report to reproduce the bounded public-data result? Why or why not?
- Recommended changes:

## Authorization and safe disclosure

- Public-data licences reviewed:
- Confirmation that no customer/private data, credentials, raw downloaded files, or vulnerability details are attached:
- Confirmation that the operator ran the unmodified governed manifest and workflow:
- Allowed public wording proposed by operator:
- Wording that must not be inferred:

## Operator statement

> I personally controlled the named run, reviewed its redacted output, and
> attest that the identifiers and observations above are accurate to the best of
> my knowledge. I understand that this is a bounded public-data technical pilot,
> not a customer deployment, audit opinion, certification, compliance finding,
> production-readiness claim, or independent security review.

- Signed using public GitHub identity (yes/no):
- Signature/statement URL:
- Date and timezone:

## Upstream acceptance (maintainer completes)

- Reviewer identity:
- Review date:
- Operator independence accepted (yes/no and evidence):
- Attestation verification repeated (command/result):
- Report SHA-256 and reproducibility SHA-256 verified (yes/no):
- Workflow/manifest unmodified (yes/no):
- Feedback assessed and follow-up issues linked:
- Acceptance status (`accepted`, `rejected`, `needs-information`):
- Reason:

This record counts toward `P3-EXT-001` only when it is `accepted`. Closure
requires three accepted attestations from three independent operators plus an
upstream review of combined outcomes and allowed wording. It never counts toward
`P3-EXT-002`.
