# AI-Ready Architecture

ReconForge ERP is AI-ready but not AI-dependent. Core reconciliation, rule evaluation, risk scoring, evidence generation, and reporting are deterministic and run locally without API keys.

## Offline Explanation

```bash
reconforge explain exception --input output/management_pack.json --exception-id EXC-0001
```

If no AI provider is configured, ReconForge uses deterministic offline explanations.

## Future Optional AI Uses

- Executive summaries.
- Audit notes.
- Recommended action wording.
- Exception explanations.
- Release note summaries.
- PR review assistance.

## Guardrails

- No cloud upload by default.
- No paid API dependency for core functionality.
- AI output should never replace source evidence or deterministic control results.
- Human reviewers remain responsible for conclusions.
