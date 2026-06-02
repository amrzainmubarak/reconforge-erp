# Trust And Security Leadership

ReconForge ERP handles sensitive ERP exports. Trust is a product feature.

## 1. Local-First Design Principles

- Core workflows read local files and write local outputs.
- No cloud upload is required for reconciliation, rules, reports, anonymization, evidence binder, or benchmarking.
- Generated outputs are treated as sensitive because they can contain source values.
- Optional future collaboration features should support self-hosted deployment before SaaS.

## 2. No Cloud Upload By Default

ReconForge should never upload ERP exports by default. Documentation, CLI help, and README positioning should repeat this boundary. Any future network feature must be opt-in, documented, and testable.

## 3. Data Anonymization Workflow

Recommended workflow before sharing data:

```bash
reconforge anonymize --input live_exports --output anonymized_exports --profile public-demo --amount-noise-percent 5 --seed 42
```

Rules:

- Preserve referential integrity.
- Mask customer, supplier, employee, work-order, invoice, and asset identifiers.
- Review generated files before public sharing.
- Prefer sharing headers and row patterns instead of full datasets.

## 4. Secure Parser Guidelines

- Use structured parsers for CSV, XLSX, YAML, and JSON.
- Use `yaml.safe_load`.
- Do not execute formulas, macros, scripts, or user-supplied code from input files.
- Normalize paths through safe path helpers.
- Fail closed on missing required files.
- Keep parsing deterministic.

## 5. YAML Rule Safety

- YAML rules are declarative.
- Operators are allowlisted.
- Rule validation should reject unknown operators.
- Rules should not execute Python, SQL, shell commands, or network calls.
- Contributor review should check evidence fields for sensitive overexposure.

## 6. Download Route Safety

Studio and dashboard download routes should use registry-based allowlists or safe path resolution. Do not construct filesystem paths directly from route parameters. Tests should cover traversal attempts.

## 7. CodeQL Workflow

CodeQL should run on pull requests, pushes to main/master, and schedule. Security findings should block releases until reviewed.

## 8. Bandit Workflow

Bandit should run on `reconforge/` in CI and before release:

```bash
python -m bandit -q -r reconforge
```

Findings should be triaged with code references and either fixed or explicitly justified.

## 9. Dependency Auditing

Use:

- Dependabot for Python and GitHub Actions.
- `pip-audit` in security workflow.
- Conservative dependency additions.
- Release notes for material dependency changes.

Future improvement: generate SBOM artifacts during release.

## 10. Contributor Security Checklist

- No live ERP data.
- No credentials, tokens, API keys, or connection strings.
- No unsafe YAML/object loading.
- No shell execution from user data.
- No path joins that bypass safe path helpers.
- No cloud upload in core workflows.
- Tests for file handling and user-facing security behavior.
- Documentation for new data handling behavior.

## 11. Secure Plugin Policy

Plugin and connector work must:

- Be read-only by default.
- Declare network behavior.
- Avoid storing secrets in pack or mapping files.
- Map data into canonical schemas before controls run.
- Include tests.
- Include security notes.
- Keep direct ERP connectors separate from export profiles.

## 12. Security Review Checklist For PRs

Reviewers should ask:

- Does this touch file reading, writing, download routes, archive extraction, or path handling?
- Does it parse YAML, Excel, CSV, JSON, or user-supplied config?
- Does it add a dependency?
- Does it add network behavior?
- Does it affect anonymization?
- Does it expose generated evidence or reports?
- Does it change control-pack validation?
- Are tests and docs updated?

## 13. Threat Model

| Threat | Impact | Current controls | Needed improvements |
| --- | --- | --- | --- |
| Live ERP data committed publicly | Confidentiality breach | SECURITY guidance, anonymizer | Pre-commit secret/data scans; contributor reminders in issue templates |
| Path traversal in local Studio downloads | Unauthorized local file read | Safe path utilities and tests | Continue route-specific tests |
| Unsafe YAML parsing | Code execution or object injection | `yaml.safe_load` | Schema validation for mapping/risk model files |
| Malicious plugin | Data exfiltration | Plugin foundation is limited | Plugin permissions, review policy, network declaration |
| Dependency vulnerability | Exploit through dependency | Dependabot, pip-audit, Bandit | SBOM and release gating |
| Over-trusting generated reports | Bad audit decisions | Docs and deterministic explanations | Reviewer workflow and sign-off controls |
| Sharing generated reports externally | Sensitive data leakage | Security and privacy docs | Output classification warnings |
| Formula injection in CSV/Excel outputs | Spreadsheet risk | Limited explicit controls | Escape dangerous cell prefixes in exported CSV/Excel where relevant |

## 14. What Codex Security Could Help With

Codex Security could help review:

- File path and download route safety.
- YAML schema validation and allowlists.
- Formula injection handling.
- Dependency and SBOM workflow.
- Plugin threat model.
- Secure release checklist.
- Test cases for malicious input files.

It should not be used to imply automated security certification.
