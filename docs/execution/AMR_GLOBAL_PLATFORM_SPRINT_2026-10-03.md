# Amr Global Financial & Operations Platform sprint

Checkpoint: `25a7adab932d45175e73a496fe158bbf7d36db60`.
Integration branch: `amr/global-platform-sprint`.
Architecture and acceptance order: [ADR0828](../adr/0828-amr-global-platform-sprint.md).

| Owner | Branch | Exclusive capability |
| --- | --- | --- |
| Amr / lead | `amr/global-platform-sprint` | Shared registration, migrations, backup, navigation, acceptance |
| Agent1 / Platform Core | `amr/global-platform-core` | Persistent user notification inbox |
| Agent2 / Business & Finance | `amr/global-business-finance` | Approved operational budgets and commitments |
| Agent3 / Enterprise/Quality | `amr/global-enterprise-quality` | Outbox fencing, crash-at-ceiling recovery and evidence |

Agents use independent managed worktrees from the checkpoint. Existing adapters,
actor identities, scope grants, exact money/currency policy, audit and outbox
contracts are reused. Shared files have one lead owner. Each slice must have a
real persisted use case and tests before integration; no placeholder module is
accepted. The previous reviewed Inventory receipt feature lane stays paused.

The fresh acceptance runtime is `.venv-amr-sprint`, created by
`uv sync --locked --all-extras --no-editable --python 3.12` with uv0.11.32.
The older `.venv-baseline-20261003` result is retained separately: its urllib3 and
virtualenv differ from the current lock and its audit fails. Disposable PG16
fixtures use synthetic data, unique owned databases and a nonowner application
role. Raw command logs and hashes are retained in
`output/amr-global-sprint-2026-10-03/`; published acceptance must identify source,
runtime, executed commands, failures/skips, measured duration and evidence hashes.

Status: implementation and exact source acceptance in progress. No completed
global platform or production/banking readiness claim is made.
