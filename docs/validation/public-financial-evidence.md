# Public Financial Evidence Protocol

Status: governed candidate; maintainer execution is not external validation

Protocol version: 1

Manifest: `docs/validation/public-financial-evidence-manifest.v1.yaml`

## Purpose and claim boundary

This protocol runs ReconForge against pinned, real, openly licensed public
financial data without committing the raw records. It tests exact ingestion,
cross-format parity, financial equations, deterministic matching, permutation
stability, tamper detection, and report redaction.

One successful maintainer run proves only that the named code revision processed
the pinned public inputs as reported. It does not automatically close
`P3-EXT-001`, establish a customer deployment, or support a production-readiness
claim. The same workflow must be run by at least three distinct independent
operators, and each result must pass the human acceptance procedure below before
it may count as a controlled public-data pilot. Automated runs do not satisfy
`P3-EXT-002`; that gate still requires a qualified independent human reviewer.

## Official sources

| Publisher | Governed slice | Open-data basis | Test purpose |
|---|---|---|---|
| U.S. Department of the Treasury, Bureau of the Fiscal Service | Debt to the Penny, 2025-07-01 through 2025-07-31, JSON and CSV | [Fiscal Service dataset](https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/) and [Open Data Policy](https://fiscaldata.treasury.gov/data/about-us/901-1%20Open%20Data%20Policy.pdf) | 22-row cross-format parity, exact USD parsing, and `debt held by public + intragovernmental holdings = total public debt` |
| World Bank Group | IBRD Commitments and Disbursements country/economy summary, all 2,890 rows over three API pages, with FY24 selected | [Dataset](https://financesone.worldbank.org/ibrd-commitments-and-disbursements-country-economy-summary/DS01556) and [API](https://financesone.worldbank.org/api-explorer?id=DS01556), CC BY 4.0 | Pagination completeness, JSON/CSV parity, 382-row FY24 component-total equation, and stable business identities |
| Northern Ireland Department for the Economy via OpenDataNI | Payments over GBP 25,000, January-March 2026 | [UK government catalogue record](https://ckan.publishing.service.gov.uk/dataset/department-for-the-economy-departmental-spend-over-f25-000-may-2023), UK Open Government Licence | Mixed CP1252/UTF-8 ingestion, 563 exact GBP rows, one negative reversal, nine repeated invoice-reference groups, and deterministic replay |

The repository retains only source URLs, attribution, bounded statistics, and
SHA-256/canonical digests. It does not retain supplier or invoice identifiers
from the downloaded files.

## Governed expected result

| Experiment | Matched | Unmatched | Exceptions | Canonical SHA-256 | Decision SHA-256 |
|---|---:|---:|---:|---|---|
| Treasury JSON/CSV | 22 | 0 | 0 | `05156b90be73daddf72b232808c2648083cbd6e52d52109fa564f3250f0685b5` | `0dff24f6f1916af9f1fdb39f99b1b8ccb77974217e5a88cc35ff599ad4ba201d` |
| World Bank FY24 | 382 | 0 | 0 | `0ca6bf2395f36737bdf679a81405a0de1054a393c59cd3f4d42a7544015d4dbc` | `24ce4556f66a310ea161dbe8e68cdbb0a6cc5de85f812cf4c466d02046998bda` |
| UK DfE Q1 2026 | 563 | 0 | 0 | `ab0e9930b1195419837e1abd9762b47f6973dc74b765d02a7ee3c4d6f08ed153` | `2e4a3a84ee14ca6e1f942a457bda66c76a83ee0f21049a2c589a268c954f823e` |

The combined governed reproducibility SHA-256 is
`890a4aa8f7b362981bfdd1f0f333d3bad55a886d842c0ff0a82ff165c48e26c5`.
This digest excludes runtime timestamp and machine metadata so independent
environments can compare the financial result exactly.

## Security and integrity controls

- Network access is disabled unless `--allow-network` is explicit.
- Only three exact HTTPS publisher hosts and one exact OpenDataNI object-store
  redirect host are accepted; credentials, non-443 ports, fragments, ambient
  proxies, cookies, and arbitrary redirects are not used.
- Every response has an exact content-type allowlist, a byte ceiling, and a
  pinned raw SHA-256. Any publisher drift fails closed.
- JSON duplicate keys, non-finite constants, schema expansion, missing CSV
  cells, NUL bytes, malformed dates, excess decimal precision, and inconsistent
  pagination are rejected.
- Financial values use `Decimal`; no binary float participates in amounts,
  equations, totals, or matching.
- The report contains counts and digests, not raw supplier/invoice identities.
- The runner refuses a dirty Git tree and records the exact 40-character commit.
- The GitHub workflow uses SHA-pinned actions, least privilege, a GitHub-hosted
  runner, SHA-256 inventories, and a provenance attestation verified against the
  exact repository, workflow, ref, and source commit.

## Maintainer/local reproduction

Run only from a clean committed revision:

```bash
uv sync --locked --extra dev --no-editable --python 3.12
uv run --no-sync python -m pytest tests/test_public_financial_evidence.py tests/test_public_financial_evidence_workflow.py -q
uv run --no-sync python .github/scripts/verify_public_financial_evidence.py \
  --allow-network \
  --execution-scope maintainer-local \
  --output public-financial-evidence-report.json
```

For a no-network replay, place the exact eleven responses in one directory as
`<artifact-id>.<format>` and run with `--artifact-dir` plus
`--execution-scope offline-replay`. Extra, missing, or changed files are rejected.

## Independent operator procedure

1. Use a personal fork or independently controlled public fork and retain the
   exact source commit. Do not edit the manifest, runner, test, or workflow.
2. Enable GitHub Actions for the fork and manually dispatch
   `.github/workflows/public-financial-evidence.yml` from its default branch.
3. Require the focused tests, live fetch, checksum check, in-workflow provenance
   verification, and artifact upload to pass in the same run.
4. Download the artifact and verify `SHA256SUMS`; verify the attestation with
   `gh attestation verify` against the operator's fork, workflow, source ref, and
   source digest recorded by the run.
5. Compare the report's reproducibility SHA-256 with the governed value above.
6. Complete
   `docs/execution/P3_EXT_001_OPEN_SOURCE_OPERATOR_ATTESTATION_TEMPLATE.md` and
   submit only the redacted report, digests, run URL, environment, failures, and
   candid user feedback. Never attach the downloaded raw public files or a
   security vulnerability.

An upstream maintainer must independently verify the run and record acceptance.
Three runs by one person, a maintainer, a bot, or accounts under common control
do not meet the three-operator condition. A passing workflow candidate is not
self-approving and does not automatically close `P3-EXT-001`.

## Dataset drift and rollback

The fixed date ranges may still be corrected by their publishers. A checksum,
schema, or count change is a failed run, not a reason to overwrite expected
values. Refresh requires a new manifest ID, a documented source comparison,
review of all changed rows and equations, new tests/digests, and retention of the
old manifest as historical evidence. Removing the workflow and protocol is a
complete rollback; it changes no product API, database, or customer data.
