# Maintainer Automation Roadmap

This roadmap summarizes the automation that already supports ReconForge ERP and the next steps that would improve maintainability, security credibility, and support-program readiness.

## Current Automation

## CI

The CI workflow runs on pull requests and pushes to the default branches. It installs the package, runs Ruff, mypy, pytest, CLI smoke checks, and package build.

How Codex can help:

- review failing CI logs
- propose focused test fixes
- identify stale CLI commands in docs
- keep package build failures tied to release changes

## CodeQL

CodeQL analyzes Python on pull requests, pushes, and a weekly schedule.

How Codex can help:

- explain alerts in plain English
- propose focused remediations
- add regression tests where alerts map to reachable behavior

## Bandit And pip-audit

The security workflow runs Bandit and `pip-audit` to catch common Python security issues and vulnerable dependencies.

How Codex can help:

- triage findings
- distinguish false positives from real risks
- update dependencies conservatively
- improve tests around file handling and generated output

## Docker Build

The Docker workflow builds the image and runs a container `reconforge doctor` smoke check in CI. Local Docker runtime verification remains a release-gate item unless the documented build and run commands pass in a live Docker environment.

How Codex can help:

- keep Docker docs aligned with observed CI behavior
- propose minimal smoke checks
- avoid runtime claims that are not backed by evidence

## OpenSSF Scorecard

The OpenSSF Scorecard workflow runs on a schedule and on manual dispatch. It is a repository security maturity check, not a guarantee of secure software. Future maintainer work should focus on reviewing findings, prioritizing fixes, and avoiding score claims until a run has generated evidence.

How Codex can help:

- review Scorecard findings
- prioritize maintainable fixes
- keep permissions narrow
- avoid claiming a score until a run has generated one

## SBOM Workflow

The tag-only candidate definition generates one exact-subject CycloneDX 1.7 document for the source, wheel, sdist, and image and defines separate attestations. Local package/source fixtures are deterministic, but no hosted signed result exists. Future maintainer work should review all subject/SBOM digests during release checks and compare dependency changes over time.

How Codex can help:

- check workflow failures
- compare SBOM changes across releases
- update docs when dependency posture changes

## Future Release Artifact Signing

Release signing should be considered only after a clear artifact strategy exists. Do not claim signed artifacts until signing is implemented and verified.

How Codex can help:

- evaluate Sigstore or similar options
- draft release checklist updates
- add verification docs after implementation

## Future Screenshot Refresh Workflow

Generated screenshot previews should be refreshed from synthetic outputs only. A future workflow could run the demo, generate local reports, capture screenshots, and flag visual drift.

How Codex can help:

- keep screenshot commands reproducible
- check that no live data appears
- compare changed images against docs

## Future Demo Smoke Tests

Demo smoke tests should confirm that synthetic workflows still produce expected report, evidence, review, client pack, and mapping outputs.

How Codex can help:

- add focused assertions
- update expected synthetic outputs
- detect accidental report regressions

## Future Dependency Update Policy

Dependabot already supports dependency awareness. A documented policy should define when to merge dependency updates, when to run full tests, and when to hold changes for release windows.

How Codex can help:

- summarize dependency changes
- suggest compatibility tests
- review changelog risk

## Funding And Support Relevance

These automation steps directly support OSS support applications because they show a path toward:

- safer AI-assisted maintenance
- better supply-chain visibility
- more reliable releases
- transparent security posture
- reproducible local workflows for finance and audit users
