# Architecture

ReconForge ERP is a local-first ERP reconciliation and audit intelligence platform. It is designed around export-driven workflows and deterministic control logic.

## 1. System Architecture

```mermaid
flowchart TB
    CLI[Typer CLI] --> API[Local API Layer]
    Studio[ReconForge Studio] --> API
    API --> Config[Config Layer]
    API --> Registry[Schema Registry]
    API --> Ingestion[File Ingestion]
    Ingestion --> Profiler[Data Profiler]
    Profiler --> Mapper[Mapping Engine]
    Mapper --> Reconcile[Reconciliation Engine]
    Reconcile --> Matching[Matching Engine]
    Matching --> Rules[Rule Engine]
    Rules --> Risk[Risk Engine]
    Risk --> Exceptions[Exception Classification]
    Exceptions --> Evidence[Evidence Binder]
    Evidence --> Reports[Report Writer]
    Reports --> Studio
    Reports --> AuditPack[Audit Pack]
    Anon[Anonymizer] --> Ingestion
    Synthetic[Synthetic Data Generator] --> Ingestion
    Benchmark[Benchmark Engine] --> Reconcile
    Plugins[Plugin System] --> Adapters[Export Adapter Interface]
    Adapters --> Mapper
    Security[Security Layer] --> Ingestion
    Observability[Observability / Logging] --> API
    AI[Future AI Assistant Layer] --> Exceptions
```

## 2. Data Pipeline

```mermaid
flowchart LR
    A[ERP Exports] --> B[Ingestion]
    B --> C[Schema Validation]
    C --> D[Data Mapping]
    D --> E[Reconciliation Engine]
    E --> F[Rule Engine]
    F --> G[Risk Scoring]
    G --> H[Exception Classification]
    H --> I[Evidence Binder]
    I --> J[Review Workflow]
    J --> K[Management Reports]
    K --> L[Audit Pack]
    L --> M[Continuous Improvement]
```

## 3. Rule Engine Flow

```mermaid
flowchart TB
    Pack[Control Pack] --> Load[Load pack.yml and rules.yml]
    Load --> Validate[Validate schema and operators]
    Validate --> Sources[Load source CSV files]
    Sources --> Eval[Evaluate row and cross-file conditions]
    Eval --> Trigger[Triggered RuleResult]
    Trigger --> Risk[Risk Impact]
    Trigger --> EvidenceFields[Evidence Fields]
    Risk --> Output[CSV / JSON Rule Output]
    EvidenceFields --> Output
```

## 4. Evidence Binder Flow

```mermaid
flowchart LR
    Exceptions[High/Critical Exceptions] --> Case[Evidence Case]
    Case --> Summary[summary.md]
    Case --> Source[source_records.csv]
    Case --> Candidates[match_candidates.csv]
    Case --> Rules[triggered_rules.yml]
    Case --> Action[recommended_action.md]
    Case --> Review[review_form.md]
    Case --> Trail[audit_trail.json]
    Case --> Register[evidence_register.xlsx]
    Case --> Index[index.html]
```

## 5. Control Pack Architecture

```mermaid
flowchart TB
    PackFolder[control-packs/name] --> Meta[pack.yml]
    PackFolder --> Rules[rules.yml]
    PackFolder --> Mapping[mapping.yml]
    PackFolder --> RiskModel[risk_model.yml]
    PackFolder --> Readme[README.md]
    PackFolder --> Expected[expected-exceptions.md]
    PackFolder --> Command[sample-command.md]
    Rules --> Operators[Rule Operators]
    Mapping --> Canonical[Canonical Schema]
    RiskModel --> RiskEngine[Risk Engine]
```

## 6. Local-First Deployment Model

```mermaid
flowchart LR
    User[Finance / Audit / ERP User] --> LocalFolder[Local ERP Exports]
    LocalFolder --> CLI[ReconForge CLI]
    CLI --> Outputs[Local Output Folder]
    Outputs --> Excel[Excel Pack]
    Outputs --> HTML[HTML Reports]
    Outputs --> Evidence[Evidence Binder]
    Outputs --> Studio[Local Studio]
    Studio --> Browser[Local Browser]
```

No cloud upload is required for core functionality.

## 7. Future SaaS / Open-Core Architecture

```mermaid
flowchart TB
    OSS[Open-Source Core] --> CLI[CLI + Reports]
    OSS --> Packs[Control Packs]
    OSS --> Evidence[Evidence Binder]
    OSS --> Anon[Anonymizer]
    OSS --> Studio[Local Studio]
    Pro[Self-Hosted Pro] --> Workflow[Review Workflow]
    Pro --> Users[User Management]
    Pro --> Attachments[Evidence Attachments]
    SaaS[Future SaaS] --> Collaboration[Team Collaboration]
    SaaS --> Scheduling[Scheduled Runs]
    SaaS --> ManagedPacks[Managed Rule Packs]
    CLI --> Pro
    Studio --> Pro
    Pro --> SaaS
```

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| CLI | Command orchestration |
| Studio web UI | Local review interface |
| API layer | FastAPI app boundaries |
| Config layer | Tolerances, mappings, risk settings |
| Schema registry | Canonical ERP file schemas |
| File ingestion | CSV/XLSX reading and normalization |
| Data profiler | Row counts, validation, quality warnings |
| Mapping engine | ERP export-to-canonical mapping |
| Reconciliation engine | Stock/GL, work orders, WIP |
| Matching engine | Strategies, confidence, explanations |
| Rule engine | YAML controls and cross-file checks |
| Risk engine | Scores, levels, escalation, audit notes |
| Control packs | Domain-specific controls |
| Evidence binder | Audit case folders and register |
| Report writer | Excel, JSON, CSV, Markdown, HTML |
| Anonymizer | Local risk reduction with referential linkage and mandatory review boundary |
| Synthetic generator | Demo and benchmark datasets |
| Benchmark engine | Runtime and output metrics |
| Plugin system | Export adapter/profile interface |
| Security layer | Local-first processing and disclosure-risk guidance |
| Observability/logging | Future run logs and diagnostics |
| Future AI assistant | Optional explanation layer, never required for core reconciliation |
