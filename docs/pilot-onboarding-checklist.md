# Pilot Onboarding Checklist

Use this checklist for a conservative local pilot using synthetic, anonymized, or approved export-based ERP data. It is not a production deployment guide, audit opinion process, compliance certification plan, or SaaS onboarding path.

## Pilot Boundaries

- Local-first and export-based only.
- No direct ERP connector, ERP credential handling, writeback, sync, cloud upload, telemetry, or hosted storage.
- No live customer data sharing in public issues, public demos, pull requests, screenshots, or training material.
- No audit opinion, assurance conclusion, legal signature, compliance certification, ROI claim, adoption claim, or vendor-replacement claim.
- Pilot outputs are decision-support and review-preparation artifacts.

## Local Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate the virtual environment with `.venv\Scripts\Activate.ps1`.

## First Checks

```bash
python -m reconforge.cli doctor
reconforge validate examples/sample_data
```

Record the ReconForge version, Python version, operating system, and any validation warnings in the pilot notes.

## Run The Standard Demo

```bash
reconforge demo run --output output/demo
```

Review:

- `output/demo/executive_report.html`
- `output/demo/management_pack.xlsx`
- `output/demo/review_register.xlsx`
- `output/demo/evidence/index.html`
- `output/client_pack/handoff_summary.md`

## Run The Synthetic Enterprise Demo

```bash
reconforge demo enterprise --output output/enterprise_demo
reconforge demo enterprise --output output/enterprise_demo --db output/enterprise_demo/reconforge.db
```

Use this package to review DB-backed platform foundations without using live client data. Confirm that the generated manifest states that all data is synthetic.

## Prepare Exported ERP Data Safely

- Define the pilot scope: ERP/export source, period, entities, accounts, workflows, and rule packs.
- Export CSV/XLSX files to a local folder controlled by the pilot team.
- Remove or mask unneeded personal data, bank details, confidential notes, tax IDs, and commercial terms.
- Keep source exports out of git.
- Use sanitized header samples for public support requests.
- Use anonymized or synthetic data for public issues, docs, demos, and training.
- Document who is allowed to access input exports, generated reports, evidence folders, client packs, backups, and SQLite databases.

## Anonymization Guidance

For public or maintainer-shared reproductions, start from local copies and run:

```bash
reconforge anonymize --input examples/sample_data --output output/pilot-anonymized --profile public-demo --amount-noise-percent 5
```

Review anonymized output before sharing. Anonymization is a risk-reduction aid, not a guarantee that data is safe to publish.

## Suggested Pilot Success Criteria

- Installation and `doctor` complete on the target local environment.
- Sample demo and synthetic enterprise demo regenerate successfully.
- Agreed export files validate or produce understandable mapping gaps.
- Management pack, executive report, evidence binder, and review register are generated locally.
- Exceptions are explainable and traceable to source rows.
- Pilot users can identify which outputs are useful, confusing, missing, or too noisy.
- No live customer data is shared outside approved local channels.
- Pilot notes include limitations, gaps, and any blocked workflows.

## Data Handling Rules

- Treat ERP exports and generated outputs as sensitive unless the data owner classifies them otherwise.
- Do not upload source exports, evidence binders, client packs, backups, or SQLite databases to public services.
- Do not paste real transaction rows into public issues or chats.
- Use local folders with access controls appropriate to the pilot environment.
- Delete temporary reproductions when no longer needed.
- Keep a simple data log: source file, owner, purpose, retention decision, and deletion date where applicable.

## Exit Review

At the end of a pilot, produce a short local summary:

- Scope covered.
- Commands run.
- Outputs generated.
- Validation issues and exceptions reviewed.
- Data handling decisions.
- Product gaps.
- Support/documentation gaps.
- Decision: continue, pause, narrow scope, or stop.
