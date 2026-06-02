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

## Evidence Binder

When `output/review_state.json` exists, evidence binder outputs include review status, reviewer, note, update time, decision reason, accepted risk reason, and escalation owner where available.

## Studio

ReconForge Studio reads `output/review_state.json` and shows review status on the Exceptions page. Filters include severity/risk level, exception type, review status, source file, search text, minimum amount, and sort order.
