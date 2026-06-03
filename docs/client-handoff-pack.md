# Client Handoff Pack

The client handoff pack is a local folder for consultants, internal audit teams, and controllers who need to share ReconForge outputs inside an engagement or close process.

## Command

```bash
reconforge report client-pack --input output/demo --output output/demo/client_pack
```

## Included Files

When available, the command copies:

- `executive_report.html`
- `management_pack.xlsx`
- `review_register.xlsx`
- `dashboard.html`
- `summary.md`
- `evidence/index.html`
- `evidence/evidence_register.xlsx`
- `evidence/evidence_index.json`
- generated evidence case files under `evidence/`

It also writes:

- `summary.md`
- `next_steps.md`
- `data_privacy_note.md`
- `files_manifest.json`

Missing optional files are listed in the summary and manifest. Hidden files and system folders are not included.

## Recommended Use

1. Run the demo or management-pack workflow.
2. Update review statuses in Studio or with the CLI.
3. Export the review register.
4. Generate evidence binder outputs.
5. Create the client pack.
6. Review the privacy note before sharing the folder outside the company or engagement team.

## Local-First Limitation

The pack is a file-based handoff folder. It does not add authentication, a database, approvals, or cloud storage. Treat it as a structured local output for review meetings, audit preparation, and consultant handover.

Evidence case folders can contain generated source-record extracts. Review the manifest and privacy note before external sharing.
