# MASTER PROMPT — Transform ReconForge into a World-Class Finance Controls Platform

Repository:

https://github.com/amrzainmubarak/reconforge-erp

You are acting as the founding Principal Software Architect, Staff Backend Engineer, FinTech Domain Expert, Security Engineer, Data Engineer, DevOps Engineer, QA Architect, Open-Source Maintainer, and Product Engineering Lead for ReconForge.

Your mission is to transform this repository into the most reliable, technically excellent, secure, scalable, extensible, and developer-friendly open-source reconciliation and finance-controls platform in its category.

This is not a cosmetic refactor.

This is not a demo.

This is not a documentation-only task.

Do not stop after producing recommendations.

Inspect the repository, design the correct architecture, implement the improvements, run tests, benchmark the system, update documentation, and leave the repository in a demonstrably better state.

The product should compete in engineering quality and product clarity with leading financial close, reconciliation, audit, data-quality, and ERP-adjacent platforms, while remaining genuinely open-source and technically honest.

Do not make false claims such as “enterprise-ready,” “compliant,” “AI-powered,” “distributed,” or “DuckDB-backed” unless the implementation and tests prove those claims.

---

# 1. PRODUCT POSITIONING

The platform must be positioned accurately as:

**ReconForge — Open-Source ERP Reconciliation, Financial Controls, Close Management, and Audit Evidence Platform**

Do not market it as a complete ERP unless it actually implements the core modules of a full ERP.

Its primary value is to work beside existing ERP, accounting, inventory, banking, payroll, e-commerce, and operational systems.

The platform should progressively support:

* Stock-to-General-Ledger reconciliation
* Bank reconciliation
* Accounts payable reconciliation
* Accounts receivable reconciliation
* Intercompany reconciliation
* Revenue reconciliation
* Payroll reconciliation
* Fixed-assets reconciliation
* Tax and VAT reconciliation
* WIP and work-order reconciliation
* Payment-gateway reconciliation
* Cash and POS reconciliation
* E-commerce order-to-payment reconciliation
* Subledger-to-General-Ledger reconciliation
* Balance-sheet account certification
* Financial-close workflows
* Exception investigation
* Control execution
* Audit evidence generation
* Risk-based prioritization
* Data-quality validation
* Reconciliation templates and reusable control packs

Preserve local-first operation while designing a clean path toward an optional hosted and multi-tenant edition.

---

# 2. WORKING RULES

Follow these rules throughout the work:

1. Inspect the actual repository before making architectural decisions.
2. Do not assume documentation is correct; verify it against the implementation.
3. Do not create fake backends, empty abstractions, misleading wrappers, dead code, placeholder implementations, or TODO-only features.
4. Do not label a backend as DuckDB, PostgreSQL, distributed, streaming, or asynchronous unless it truly uses those technologies.
5. Do not silently convert invalid financial data into zero.
6. Do not discard records silently.
7. Do not produce reconciliation results that depend on input-row order.
8. Every financial result must be explainable, reproducible, traceable, and deterministic.
9. Preserve backward compatibility where practical.
10. Where compatibility cannot be preserved, introduce migrations and documented deprecation paths.
11. Keep commits focused, reviewable, and logically separated.
12. Avoid unnecessary dependencies.
13. Prefer typed, testable, composable modules.
14. Never weaken security to simplify development.
15. Never use production customer data in fixtures or benchmarks.
16. Never expose secrets in logs, exceptions, examples, tests, or documentation.
17. Do not claim completion unless tests and acceptance criteria pass.
18. When a large feature cannot safely be completed in the current iteration, implement the correct foundation and document the remaining work honestly.
19. Remove obsolete code only after proving it is unused or properly migrated.
20. Treat financial correctness as more important than UI appearance.

---

# 3. FIRST ACTION: BASELINE AUDIT

Before modifying the code, perform a complete baseline assessment.

Inspect:

* Repository structure
* Package boundaries
* Dependency graph
* Core domain models
* Matching algorithms
* Reconciliation workflows
* Risk-scoring logic
* Exception handling
* Control-pack system
* Database schema
* Migration strategy
* Authentication
* Authorization
* Separation of duties
* Session handling
* Audit logging
* Hash-chain implementation
* API design
* CLI design
* Studio UI architecture
* Configuration handling
* File ingestion
* Export formats
* Testing quality
* CI workflows
* Packaging
* Release automation
* Container support
* Documentation accuracy
* Performance characteristics
* Memory usage
* Security posture
* Accessibility
* Developer experience
* Contributor experience

Create or update:

* `docs/engineering-audit.md`
* `docs/architecture/current-state.md`
* `docs/architecture/target-state.md`
* `docs/roadmap.md`
* `docs/risk-register.md`

The audit must classify findings as:

* Critical
* High
* Medium
* Low
* Enhancement

Each finding must contain:

* Evidence
* Affected files
* Technical risk
* Financial or operational risk
* Recommended fix
* Implementation status
* Tests required
* Migration impact

After the audit, begin implementation immediately.

Do not stop at the audit report.

---

# 4. PRIORITY ZERO: FINANCIAL CORRECTNESS

Financial correctness is the highest priority.

## 4.1 Replace Greedy Row-Order Matching

Inspect the existing reconciliation algorithm.

Replace any row-order-dependent greedy matching with a deterministic matching architecture.

Implement:

* Candidate generation
* Configurable hard constraints
* Configurable soft constraints
* Weighted scoring
* Stable tie-breaking
* Global assignment optimization
* One-to-one matching
* One-to-many matching
* Many-to-one matching
* Many-to-many matching where explicitly enabled
* Partial matching
* Split transactions
* Aggregated journal entries
* Tolerance-based matching
* Currency-aware matching
* Date-window matching
* Reference-based matching
* Entity and account constraints
* Duplicate detection
* Reversal detection

Use an appropriate algorithm such as:

* Hungarian assignment
* Minimum-cost maximum-flow
* Bipartite graph matching
* Constraint optimization
* Partitioned optimization for large datasets

Select the algorithm based on reconciliation type and dataset size.

Document the algorithmic trade-offs.

The same input records must produce the same results regardless of row order.

Add property-based tests proving row-order invariance.

## 4.2 Stable Identifiers

Do not generate match IDs from DataFrame row numbers.

Generate deterministic identifiers using stable business keys and canonical hashes.

Identifiers must remain stable when:

* Rows are reordered
* Files are reloaded
* Non-material metadata changes
* The same reconciliation is rerun

Preserve source identifiers and maintain lineage from:

* Source file
* Source system
* Original row
* Normalized row
* Candidate set
* Selected match
* Reconciliation run
* Review decision
* Approval decision

## 4.3 Financial Number Handling

Introduce a strict monetary value type.

Do not rely on binary floating-point values for financial amounts where exact decimals are required.

Use:

* `Decimal`
* Explicit currency codes
* Configurable decimal precision
* Currency-specific rounding
* Defined tolerance policies
* Explicit debit and credit signs
* Null-state differentiation
* Invalid-value differentiation

Never convert invalid values to `0`.

Invalid financial values must create data-quality exceptions with:

* Source record
* Field name
* Original value
* Parsing error
* Severity
* Suggested remediation

## 4.4 Reconciliation Invariants

Create invariant tests proving:

* No record disappears.
* No source transaction is used more times than allowed.
* No target transaction is used more times than allowed.
* Matched plus unmatched records equal input records.
* Aggregate debit and credit totals remain explainable.
* Reconciliation totals balance according to configured rules.
* Match scores stay within valid ranges.
* Every exception has a reason code.
* Every manually overridden result records actor, timestamp, old value, new value, and reason.
* Rerunning an unchanged dataset produces an equivalent result.
* Reordering input rows produces an equivalent result.
* Failed parsing never becomes a valid zero amount.
* Evidence exports reproduce the approved result.

---

# 5. FIX KNOWN CORRECTNESS RISKS

Inspect and fix all related implementations, including the following likely problem classes:

## 5.1 Empty Exception Concatenation

Ensure that combining exception DataFrames never fails when no exceptions exist.

A perfectly reconciled dataset must return a valid empty exception result rather than raising an error.

## 5.2 Complete Exception Classification

Ensure all exception categories are handled consistently, including:

* Amount differences
* Date differences
* Reference mismatches
* Currency mismatches
* Missing records
* Duplicate records
* Invalid records
* Partial matches
* Ambiguous matches
* Reversals
* Out-of-period entries
* Unauthorized manual overrides
* Mapping failures
* Control failures

Every exception type must have:

* Stable type code
* Human-readable title
* Explanation
* Severity
* Risk score
* Suggested action
* Supporting evidence
* Ownership
* Workflow status

## 5.3 Reference Normalization

Implement configurable reference normalization:

* Whitespace trimming
* Unicode normalization
* Case normalization
* Separator normalization
* Leading-zero rules
* Prefix and suffix rules
* Invoice-number normalization
* Configurable regex transformations
* Original-value preservation

Never destroy the original source value.

Display both original and normalized references in evidence and investigation screens.

## 5.4 Independent Risk Evaluation

Do not blindly inherit match risk scores for newly generated exception types.

Each exception must be scored according to its own:

* Financial magnitude
* Age
* Account risk
* Entity risk
* Control severity
* Frequency
* Duplicate pattern
* Reviewer history
* Materiality threshold
* Confidence level

The risk model must be explainable and deterministic.

---

# 6. BUILD A REAL EXECUTION ENGINE ARCHITECTURE

Create a formal engine interface for data processing.

Supported engines should include:

* Pandas for small and medium local workloads
* DuckDB for SQL-based analytical execution
* Polars where beneficial
* Optional PostgreSQL execution for server deployments

Do not retain an engine that merely delegates to another engine while pretending to be independent.

## 6.1 Real DuckDB Backend

Implement actual DuckDB execution using:

* DuckDB relations
* SQL queries
* Parquet scanning
* Predicate pushdown
* Projection pushdown
* Efficient joins
* Partition processing
* Temporary tables where appropriate
* Deterministic result ordering

Add engine parity tests proving that Pandas and DuckDB produce semantically equivalent reconciliation results.

## 6.2 Large Dataset Strategy

Support:

* Chunked ingestion
* Streaming validation
* Parquet intermediate storage
* Memory-aware execution
* Dataset partitioning
* Candidate pruning
* Incremental reconciliation
* Resumable jobs
* Progress reporting
* Cancellation
* Failure recovery

Benchmark at minimum:

* 10,000 records
* 100,000 records
* 1,000,000 records

Document:

* Hardware
* Dataset characteristics
* Runtime
* Peak memory
* Engine
* Configuration
* Result counts
* Correctness verification

Do not publish unverifiable benchmark claims.

---

# 7. DATA INGESTION AND DATA QUALITY

Build a resilient ingestion layer.

Support:

* CSV
* TSV
* XLSX
* JSON
* JSON Lines
* Parquet
* ZIP packages
* Configurable delimiters
* Multiple encodings
* Large files
* Multi-sheet workbooks

Add schema detection and explicit mapping.

Create a mapping workflow supporting:

* Source columns
* Canonical fields
* Transformation rules
* Required fields
* Optional fields
* Defaults
* Data types
* Validation constraints
* Date formats
* Decimal separators
* Currency mapping
* Debit and credit mapping
* Account mapping
* Entity mapping

Add data-quality checks for:

* Missing required fields
* Invalid dates
* Invalid amounts
* Duplicate identifiers
* Unbalanced journals
* Unknown currencies
* Unknown accounts
* Invalid period dates
* Unexpected signs
* Encoding problems
* Truncated identifiers
* Excel serial dates
* Scientific-notation corruption
* Leading-zero loss
* Mixed locale formats

Every ingestion run must generate a data-quality report.

---

# 8. CONNECTOR SDK

Create a clean connector SDK rather than embedding vendor-specific code in the core.

The connector interface should support:

* Authentication configuration
* Schema discovery
* Incremental extraction
* Pagination
* Retry policies
* Rate limits
* Checkpointing
* Idempotency
* Secret references
* Connection testing
* Source metadata
* Data lineage
* Error classification

Provide production-quality local connectors for:

* CSV
* Excel
* JSON
* Parquet
* Folder ingestion
* SFTP where safely implementable

Create documented connector templates for:

* Odoo
* SAP
* Oracle NetSuite
* Microsoft Dynamics 365
* QuickBooks
* Xero
* Stripe
* Shopify
* WooCommerce

Do not claim official support for proprietary systems unless a tested connector exists.

Keep credentials outside source code and configuration files committed to Git.

---

# 9. DATABASE AND PERSISTENCE ARCHITECTURE

Support two deployment modes:

## Local Mode

Use SQLite safely with:

* WAL mode
* Busy timeout
* Foreign keys
* Explicit transactions
* Proper indexes
* Migration support
* Backup validation
* Restore validation
* Database integrity checks
* Reduced write contention

Avoid updating session metadata on every request when unnecessary.

Throttle session activity updates or use a safe write strategy.

## Server Mode

Introduce a clean persistence abstraction supporting PostgreSQL.

Do not scatter SQL across unrelated modules.

Use a formal migration tool.

Design all future-hosted tables with tenant scoping from the start.

Every tenant-owned table must have explicit tenant boundaries.

Add tests proving tenant isolation.

No query in hosted mode may return another tenant’s records.

---

# 10. DOMAIN-DRIVEN MODULAR ARCHITECTURE

Refactor toward clear bounded contexts.

Recommended high-level structure:

```text
reconforge/
  api/
  application/
  auth/
  audit/
  close/
  controls/
  connectors/
  data_quality/
  domain/
  engines/
  evidence/
  exceptions/
  ingestion/
  infrastructure/
  matching/
  persistence/
  reconciliation/
  reporting/
  risk/
  studio/
  workflows/
```

Separate:

* Domain entities
* Application services
* Infrastructure
* Persistence
* API schemas
* UI presentation
* External integrations

Avoid giant modules.

Break the Studio application into modular routes, services, templates, forms, and view models.

No single UI module should become an uncontrolled monolith.

Add architecture-dependency tests preventing forbidden imports between layers.

Use Architecture Decision Records in:

```text
docs/adr/
```

---

# 11. WORKFLOW AND CLOSE MANAGEMENT

Implement a robust workflow state machine.

Suggested states:

* Draft
* Data loaded
* Validation failed
* Ready for preparation
* Prepared
* Under review
* Changes requested
* Reviewed
* Awaiting approval
* Approved
* Certified
* Locked
* Reopened
* Archived

Enforce:

* Separation of duties
* Role-based transitions
* Required comments
* Required evidence
* Approval limits
* Reopen permissions
* Period locking
* Immutable approved snapshots
* Full transition history
* Escalation rules
* Due dates
* Ownership
* Delegation
* Reviewer independence

Users must not be able to approve their own work where separation-of-duties rules prohibit it.

All manual adjustments must be traceable.

---

# 12. SECURITY HARDENING

Create:

* `docs/security/threat-model.md`
* `docs/security/security-architecture.md`
* `SECURITY.md`
* Secure deployment guidance
* Incident-response guidance

Perform threat modeling covering:

* Credential theft
* Session hijacking
* Brute-force login
* Broken authorization
* Cross-tenant data access
* SQL injection
* CSV injection
* Formula injection in Excel
* Path traversal
* Malicious file upload
* ZIP bombs
* Denial of service
* Dependency compromise
* Secret leakage
* Audit-log tampering
* Backup theft
* Evidence modification
* Privilege escalation
* Insecure exports
* Unsafe deserialization

Implement where relevant:

* Secure password hashing with modern configurable parameters
* Token hashing
* Token rotation
* Session revocation
* Login throttling
* Account lockout protections
* CSRF protection
* Security headers
* CORS policies
* Request-size limits
* Upload limits
* MIME validation
* File-content validation
* Safe temporary-file handling
* Spreadsheet formula-injection protection
* Constant-time secret comparisons
* Structured security events
* Secret redaction
* Principle of least privilege

Do not expose stack traces or sensitive values to end users.

Add security-focused tests.

---

# 13. AUDIT TRAIL AND EVIDENCE INTEGRITY

Design the audit system as an append-only event model.

Each event should include:

* Event ID
* Tenant
* Actor
* Actor role
* Action
* Resource type
* Resource ID
* Timestamp
* Request ID
* Session ID
* Before state hash
* After state hash
* Previous event hash
* Current event hash
* Reason
* Source IP where available
* User agent where appropriate
* Metadata with strict redaction

Provide:

* Audit-chain verification command
* Tamper-detection tests
* Export verification
* Evidence-package manifest
* File hashes
* Reproducibility metadata
* Software version
* Control-pack version
* Configuration version
* Dataset hashes

An Evidence Binder should allow an independent reviewer to understand:

* What data was used
* How it was transformed
* Which controls ran
* Which algorithm ran
* What exceptions occurred
* Who reviewed them
* Who approved them
* Whether anything was overridden
* Whether evidence has changed

---

# 14. CONTROL PACK PLATFORM

Evolve Control Packs into a versioned and validated policy system.

Implement:

* Formal JSON Schema or equivalent validation
* Semantic versioning
* Pack metadata
* Pack dependencies
* Compatibility rules
* Test fixtures
* Expected results
* Digital checksums
* Rule explainability
* Localization-ready labels
* Safe expression evaluation
* Static rule validation
* Duplicate rule detection
* Pack import and export
* Pack signing architecture
* Upgrade migration guidance

Rules must not execute arbitrary Python code.

Provide high-quality built-in packs covering:

* Inventory
* General ledger
* Accounts payable
* Accounts receivable
* Bank
* Revenue
* Payroll
* Tax
* Fixed assets
* Intercompany
* WIP
* Payments
* Period-end close
* Data quality
* User access
* Segregation of duties

Every built-in pack must include tests and example data.

---

# 15. API QUALITY

Create a stable versioned API:

```text
/api/v1/
```

Implement:

* Consistent resource naming
* Consistent pagination
* Filtering
* Sorting
* Search
* Idempotency keys for write operations
* Request IDs
* Structured error responses
* Validation-error details
* Safe error messages
* OpenAPI examples
* Deprecation headers
* API versioning policy
* Rate-limit headers where applicable
* Health endpoints
* Readiness endpoints
* Liveness endpoints
* Metrics endpoints protected appropriately

Add contract tests.

Generate and validate the OpenAPI schema in CI.

Provide example clients in:

* Python
* TypeScript

Do not break public APIs without versioning or migration notes.

---

# 16. CLI QUALITY

The CLI must become a first-class interface.

Provide consistent commands for:

* Initializing a workspace
* Importing data
* Validating data
* Running reconciliation
* Running controls
* Listing exceptions
* Exporting reports
* Verifying evidence
* Managing users
* Managing tokens
* Checking database integrity
* Creating backups
* Restoring backups
* Running benchmarks
* Checking configuration
* Migrating databases

Requirements:

* Helpful error messages
* Non-zero exit codes on failure
* Machine-readable JSON mode
* Quiet mode
* Verbose mode
* Progress reporting
* Safe confirmation for destructive operations
* Shell completion
* Examples in help output

Add CLI integration tests.

---

# 17. STUDIO USER EXPERIENCE

Refactor the Studio UI into a professional, accessible finance-operations interface.

Prioritize:

* Clarity
* Speed
* Keyboard accessibility
* Screen-reader compatibility
* WCAG-aware contrast
* Responsive layouts
* Large dataset usability
* Clear financial formatting
* Explainable match results
* Clear exception ownership
* Review and approval workflows
* Evidence visibility
* Audit history
* Search and filtering
* Saved views
* Bulk actions with safeguards
* Empty states
* Loading states
* Error states

Create screens for:

* Executive close dashboard
* Reconciliation workspace
* Data-quality report
* Candidate match explanation
* Exception queue
* Exception details
* Control results
* Review workflow
* Approval workflow
* Evidence binder
* Audit trail
* User and role administration
* Connector configuration
* Control-pack management
* System health
* Benchmark and diagnostics

Do not prioritize animation over usability.

---

# 18. EXPLAINABLE MATCHING

Every match must explain why it was selected.

Show:

* Match type
* Candidate count
* Selected score
* Alternative candidates
* Amount difference
* Date difference
* Reference similarity
* Account consistency
* Currency consistency
* Entity consistency
* Applied tolerances
* Applied rules
* Confidence level
* Rejection reasons for alternatives

Manual overrides must require a reason.

Store the previous automated result and the manual decision.

Never allow an opaque score without explanation.

---

# 19. OPTIONAL INTELLIGENCE LAYER

Only after deterministic controls and matching are reliable, introduce an optional intelligence layer.

Potential capabilities:

* Exception clustering
* Suggested exception categories
* Duplicate-pattern detection
* Anomaly prioritization
* Suggested owners
* Narrative summaries
* Root-cause suggestions
* Control recommendations

Rules:

* AI must never silently approve financial results.
* AI output must be labeled as a suggestion.
* Deterministic controls remain the source of authority.
* Record the model, version, prompt, timestamp, and confidence when AI features are used.
* Provide a fully functional non-AI mode.
* Do not send financial data to external services without explicit configuration and consent.

---

# 20. OBSERVABILITY AND OPERATIONS

Implement structured observability.

Add:

* Structured logs
* Correlation IDs
* Request IDs
* Job IDs
* Reconciliation run IDs
* Metrics
* Traces where appropriate
* Performance timers
* Error categorization
* Health checks
* Dependency checks
* Storage checks
* Database checks
* Queue checks if queues are introduced

Metrics should include:

* Reconciliation duration
* Records processed
* Match rate
* Exception rate
* Invalid-record rate
* Memory usage
* Engine used
* Control execution time
* API latency
* Error rate
* Login failures
* Database lock events
* Evidence-generation time

Ensure logs do not leak sensitive financial data or credentials.

---

# 21. TESTING STRATEGY

Create a serious layered test strategy.

Include:

* Unit tests
* Integration tests
* API contract tests
* Database migration tests
* CLI tests
* UI route tests
* Security tests
* Permission tests
* Tenant-isolation tests
* Property-based tests
* Mutation testing for critical algorithms
* Golden dataset tests
* Regression tests
* Performance tests
* Load tests
* Backup and restore tests
* Evidence reproducibility tests
* Cross-engine parity tests
* Row-order invariance tests
* Failure-recovery tests

Use realistic synthetic finance datasets.

Golden datasets must include known expected results for:

* Perfect one-to-one matching
* Date differences
* Amount differences
* Reference differences
* Duplicate transactions
* Reversals
* Split payments
* Aggregated journals
* Missing transactions
* Currency mismatches
* Invalid numeric values
* Invalid dates
* Large ambiguous candidate sets
* Period cutoff issues
* Intercompany mismatches

Establish meaningful coverage thresholds.

Critical financial algorithms should have extremely high branch coverage.

Do not optimize for coverage percentage alone; test behavior and invariants.

---

# 22. PERFORMANCE ENGINEERING

Build a reproducible benchmark suite.

Create:

```text
benchmarks/
docs/performance/
```

Measure:

* Parsing
* Normalization
* Candidate generation
* Matching
* Exception classification
* Control execution
* Report generation
* Evidence generation
* Database writes
* API response times

Compare engines fairly.

Record hardware and software versions.

Add performance regression checks to CI for stable benchmark subsets.

Optimize based on profiling rather than assumptions.

Use:

* CPU profiling
* Memory profiling
* Query plans
* Allocation analysis
* I/O analysis

Avoid premature micro-optimizations that damage clarity.

---

# 23. CI/CD AND SUPPLY-CHAIN SECURITY

Create a world-class GitHub Actions pipeline.

Include:

* Formatting
* Linting
* Type checking
* Unit tests
* Integration tests
* Security tests
* Coverage
* API schema validation
* Documentation build
* Package build
* Container build
* Container scan
* Dependency audit
* License audit
* Secret scanning
* CodeQL
* SBOM generation
* Migration tests
* Cross-platform tests
* Python-version matrix
* Reproducible release checks

Support at least:

* Linux
* Windows
* macOS where practical

Use dependency pinning and automated updates responsibly.

Create signed or attestable releases where possible.

Add:

* Release notes
* Changelog automation
* Semantic versioning
* Artifact checksums
* SBOM
* Provenance information

Do not publish a release when critical checks fail.

---

# 24. CONTAINER AND DEPLOYMENT QUALITY

Create verified deployment paths for:

* Local Python installation
* Docker
* Docker Compose
* Development container
* Production-style reverse-proxy deployment
* Optional PostgreSQL deployment

Test container builds in CI.

Provide:

* Non-root containers
* Read-only filesystem where practical
* Health checks
* Minimal base images
* Explicit persistent volumes
* Safe environment-variable handling
* Resource limits
* Secure defaults
* Upgrade guidance
* Backup guidance
* Restore guidance

Do not expose the application publicly with insecure development settings.

---

# 25. DOCUMENTATION EXCELLENCE

The repository should become understandable to:

* Finance professionals
* Auditors
* Developers
* Security engineers
* Contributors
* System administrators
* Product evaluators

Create or improve:

* README
* Quick start
* Product overview
* Architecture overview
* Domain glossary
* Reconciliation concepts
* Matching algorithm documentation
* Risk-scoring documentation
* Control-pack authoring guide
* Connector SDK guide
* API guide
* CLI guide
* Deployment guide
* Backup and restore guide
* Security guide
* Threat model
* Performance guide
* Contribution guide
* Governance guide
* Release policy
* Compatibility policy
* Migration guide
* Troubleshooting guide
* FAQ

The README must clearly distinguish:

* Implemented features
* Experimental features
* Planned features
* Unsupported features

Avoid marketing claims unsupported by implementation.

---

# 26. OPEN-SOURCE PROJECT QUALITY

Add or improve:

* `CONTRIBUTING.md`
* `CODE_OF_CONDUCT.md`
* `SECURITY.md`
* `GOVERNANCE.md`
* `SUPPORT.md`
* `CHANGELOG.md`
* Issue templates
* Pull-request template
* Bug-report template
* Feature-request template
* Security-reporting process
* Good-first-issue labels
* Contributor setup
* Maintainer guide
* Review checklist
* Definition of done

Create example extensions and starter templates for contributors.

Make the repository easy to run within minutes.

---

# 27. CODE QUALITY STANDARDS

Adopt and enforce:

* Strict typing for core modules
* Consistent formatting
* Linting
* Clear module boundaries
* Small focused functions
* Explicit error types
* Domain-specific exceptions
* No broad exception swallowing
* No hidden global mutable state
* No silent data loss
* No duplicate business logic
* No circular imports
* No unexplained magic numbers
* No security-sensitive defaults
* No giant monolithic modules

Use docstrings for public APIs and complex financial logic.

Comments should explain why, not restate the code.

---

# 28. REQUIRED DELIVERABLES

The work must produce:

1. A complete engineering audit.
2. A prioritized technical roadmap.
3. A documented target architecture.
4. Correct deterministic reconciliation logic.
5. Stable record and match identifiers.
6. Strict financial data handling.
7. Comprehensive exception classification.
8. A real DuckDB execution backend or removal of misleading claims.
9. Cross-engine parity tests.
10. Golden accounting datasets.
11. Property-based financial invariants.
12. Database safety improvements.
13. Modular Studio architecture.
14. Security hardening.
15. A threat model.
16. Improved audit and evidence integrity.
17. Versioned Control Packs.
18. API and CLI improvements.
19. Reproducible benchmarks.
20. CI/CD and supply-chain improvements.
21. Verified container builds.
22. Updated documentation.
23. A migration guide.
24. A clear changelog.
25. A final validation report.

---

# 29. EXECUTION PHASES

Execute the transformation in controlled phases.

## Phase 0 — Baseline

* Run existing tests.
* Record failures.
* Record coverage.
* Record benchmark baseline.
* Inspect architecture.
* Produce audit documents.
* Identify compatibility constraints.

## Phase 1 — Financial Correctness

* Fix data-loss and parsing risks.
* Fix empty-exception behavior.
* Normalize references safely.
* Introduce stable IDs.
* Implement invariants.
* Improve exception classification.
* Replace row-order-dependent behavior.

## Phase 2 — Matching Engine

* Introduce candidate graph.
* Implement deterministic global assignment.
* Add one-to-many and many-to-one modes.
* Add explainability.
* Add golden datasets.
* Add cross-order and property-based tests.

## Phase 3 — Execution Engines

* Build a real DuckDB backend.
* Add engine parity tests.
* Add memory-aware processing.
* Add performance benchmarks.

## Phase 4 — Architecture and Persistence

* Establish domain boundaries.
* Modularize Studio.
* Improve SQLite operation.
* Add migrations.
* Introduce PostgreSQL-compatible persistence boundaries.
* Prepare tenant-safe schemas.

## Phase 5 — Security and Auditability

* Complete threat model.
* Harden authentication.
* Harden sessions.
* Strengthen authorization.
* Improve audit events.
* Improve evidence integrity.
* Add security tests.

## Phase 6 — Platform Expansion

* Build connector SDK.
* Expand reconciliation templates.
* Version Control Packs.
* Improve workflow and close management.
* Improve API and CLI.

## Phase 7 — Product and Developer Experience

* Improve Studio UX.
* Improve documentation.
* Improve onboarding.
* Improve examples.
* Improve contributor experience.

## Phase 8 — Production Validation

* Run full tests.
* Run security scans.
* Run migration tests.
* Run benchmarks.
* Run container tests.
* Verify documentation.
* Produce final readiness assessment.

Do not begin a later phase while critical failures in an earlier phase remain unresolved.

---

# 30. ACCEPTANCE CRITERIA

The work is accepted only when:

* All existing valid tests pass.
* New tests pass.
* Reconciliation results do not change when input rows are reordered.
* Invalid amounts never silently become zero.
* No input record disappears.
* Every unmatched or invalid record becomes visible.
* Match identifiers are stable.
* Matches are explainable.
* DuckDB execution is genuine if advertised.
* Pandas and DuckDB results are equivalent for supported cases.
* Empty exception sets do not crash.
* Manual overrides are fully audited.
* Separation of duties is enforced.
* Security checks contain no unresolved critical findings.
* Database migrations are tested.
* Backup and restore are tested.
* Container builds pass in CI.
* OpenAPI generation passes.
* Documentation matches implementation.
* Benchmarks are reproducible.
* Every implemented claim is backed by code and tests.

---

# 31. REPORTING FORMAT DURING EXECUTION

At the start, provide:

1. Current-state assessment.
2. Critical findings.
3. Implementation plan.
4. Files expected to change.
5. Risks and compatibility concerns.

Then begin modifying the repository.

After each phase, report:

* Work completed
* Files changed
* Tests added
* Tests executed
* Test results
* Benchmarks
* Security impact
* Remaining risks
* Next phase

At the end, provide:

* Executive summary
* Architecture changes
* Correctness improvements
* Security improvements
* Performance results
* Test summary
* Migration instructions
* Breaking changes
* Remaining limitations
* Recommended next milestones
* Exact commands to verify the repository locally

---

# 32. FINAL DIRECTIVE

Be ambitious but technically honest.

The objective is not to make the repository merely look sophisticated.

The objective is to make it:

* Correct
* Deterministic
* Secure
* Explainable
* Auditable
* Testable
* Extensible
* Performant
* Maintainable
* Easy to deploy
* Easy to contribute to
* Trusted by finance teams
* Trusted by auditors
* Respected by senior engineers

Start by inspecting the repository and executing Phase 0.

Then immediately implement Phase 1 and Phase 2.

Do not respond with only a plan.

Make real changes, run the relevant tests, and show evidence for every major claim.
