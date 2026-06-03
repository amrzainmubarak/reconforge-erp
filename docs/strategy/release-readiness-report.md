# Release Readiness Report

Date: 2026-06-03

## Recommended Version Decision

Recommendation: keep as Unreleased under v0.6.x for now, or release as v0.6.1 only after CI confirms the Docker build workflow and the full Python quality gates pass.

Do not release v0.7.0 yet. Docker runtime verification was not completed locally, and enterprise-grade controls such as authentication, role-based access, formal support boundaries, and pilot validation remain open.

## Release Gate Status

| Gate | Status | Notes |
| --- | --- | --- |
| Ruff | Passed | `python3 -m ruff check .` passed. |
| Mypy | Passed | `python3 -m mypy reconforge` passed. |
| Pytest | Passed | `python3 -m pytest` passed: 150 tests, 1 existing FastAPI TestClient deprecation warning. |
| Bandit | Passed | `python3 -m bandit -q -r reconforge` passed. |
| `reconforge doctor` | Passed | `PYTHONPATH=. reconforge doctor` passed for local package version 0.6.0. |
| Docker build | Not locally verified | Docker daemon unavailable in this environment. CI workflow added. |
| Redaction controls | Passed tests | Text/CSV/JSON/HTML redaction only; binary workbooks excluded when redaction requested. |
| Evidence checksums | Passed tests | SHA-256 integrity manifests, not legal signatures. |
| Documentation links | Updated | README and docs index include new pilot, security, deployment, commercial, and profile materials. |
| Claim review | Completed | Docs use synthetic/pilot language and avoid adoption, savings, certification, audit-opinion, and direct-connector claims. |

## Known Limitations

- No direct ERP connectors are implemented.
- No cloud/SaaS workflow is added.
- No authentication is added to local Studio/dashboard.
- No audit opinion, legal advice, tax advice, or compliance certification is provided.
- Docker runtime commands require validation in a live Docker environment.

## Decision Rationale

The project is credible for consultant demos and controlled company pilots, especially with synthetic/sample data and local export workflows. It is not yet enterprise production software and should not be marketed as such.
