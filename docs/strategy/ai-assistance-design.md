# Safe AI Assistance Design

Status: design direction with deterministic local defaults. No LLM dependency is required by default.

Allowed assistance:

- Draft exception explanations from already computed deterministic results.
- Suggest evidence checklist text.
- Summarize exception queue records locally when no external model is configured.

Boundaries:

- No automatic approvals.
- No black-box matching decisions.
- No sensitive data leaves the local environment unless a future user explicitly configures an external model.
- AI output is never source evidence, audit assurance, or compliance certification.

Implementation note:

- Existing deterministic explanation helpers remain the default pattern.
