# Review Workflow

ReconForge ERP stores exception review state locally in `output/review_state.json`. There is no database and no cloud upload.

## Allowed Statuses

- New
- Under Review
- Resolved
- Accepted Risk
- Escalated

## State File

The local JSON file stores entries by `exception_id`:

```json
{
  "version": 1,
  "entries": {
    "EXC-0001": {
      "exception_id": "EXC-0001",
      "status": "Under Review",
      "reviewer": "Amr",
      "note": "Checking source records",
      "updated_at": "2026-06-02T10:00:00Z",
      "decision_reason": "",
      "accepted_risk_reason": "",
      "escalation_owner": ""
    }
  }
}
```

If the file is missing, ReconForge treats all exceptions as `New`. If the file is malformed, commands fall back safely to an empty state.

Supported review fields are:

- `exception_id`
- `status`
- `reviewer`
- `note`
- `decision_reason`
- `accepted_risk_reason`
- `escalation_owner`
- `updated_at`

## Commands

List exceptions with local review status:

```bash
reconforge review list --input output
```

Set review status:

```bash
reconforge review set-status --input output --exception-id EXC-0001 --status "Under Review" --reviewer "Amr" --note "Checking source records"
```

Export a review register:

```bash
reconforge review export --input output --output output/review_register.xlsx
```

## Studio Review Updates

Studio can update the same local state file:

```bash
reconforge studio --input examples/sample_data --output output/demo
```

Open **Exceptions**, enter an `exception_id`, select a status, add reviewer notes or decision fields, and save. The update is written to `output/demo/review_state.json`.

Studio validates the status, escapes rendered values, and uses a simple per-session form token. It is still a local development/review interface, not an authenticated multi-user application.

Run Studio on loopback or another trusted local interface only. Anyone who can access the local Studio URL and write to the output folder can change review state.

## 10-Minute Review Demo

```bash
reconforge demo run --output output/demo
reconforge studio --input examples/sample_data --output output/demo
```

The demo creates `review_state.json`, sets one sample exception to `Under Review`, and exports `review_register.xlsx`. Update another exception in Studio, filter by status, then rerun:

```bash
reconforge review export --input output/demo --output output/demo/review_register.xlsx
```

## Evidence Binder

When `output/review_state.json` exists, evidence binder outputs include review status, reviewer, note, update time, decision reason, accepted risk reason, and escalation owner where available.

## Studio

ReconForge Studio reads and writes `output/review_state.json` on the Exceptions page. Filters include severity/risk level, exception type, review status, source file, search text, minimum amount, and sort order.
