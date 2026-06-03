# Demo Video Script

This package is for recording ReconForge ERP demos from local sample data. The narration should avoid claims of direct ERP connectors, real customer results, global leadership, or guaranteed savings.

## Setup Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
reconforge doctor
reconforge demo run --output output/demo
reconforge studio --input examples/sample_data --output output/demo
```

Optional follow-up commands:

```bash
reconforge mappings wizard --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/mapping_wizard
reconforge compare periods --inputs output/demo output/demo --output output/period_comparison
reconforge report client-pack --input output/demo --output output/client_pack
```

## Files To Open

- `README.md`
- `output/demo/dashboard.html`
- `output/demo/executive_report.html`
- `output/demo/management_pack.xlsx`
- `output/demo/evidence/index.html`
- `output/demo/review_register.xlsx`
- `output/demo/client_pack/files_manifest.json`
- `output/mapping_wizard/mapping_report.md`
- `output/period_comparison/period_comparison.html`

## 60-Second Demo Script

Narration:

"ReconForge ERP is a local-first reconciliation and audit intelligence tool for ERP exports. In one command, it validates sample data, reconciles stock to GL, checks work-order controls, runs rules, generates a management pack, builds an evidence binder, initializes review state, and exports a review register."

Screen flow:

1. Show README top and maturity note.
2. Run `reconforge demo run --output output/demo`.
3. Open `output/demo/executive_report.html`.
4. Open `output/demo/evidence/index.html`.
5. Open Studio Exceptions and update one status.
6. Show `review_register.xlsx`.
7. End on `client_pack/`.

Key message:

"The value is repeatable local review from export files, not a cloud upload or live connector."

## 3-Minute Demo Script

Narration:

"A finance or audit user starts with exported ERP files. ReconForge keeps the workflow local. The demo command runs validation, reconciliation, work-order checks, rule-pack checks, evidence generation, and review-state initialization."

Screen flow:

1. Show repository landing page and `10-Minute Demo`.
2. Run:

```bash
reconforge demo run --output output/demo
```

3. Open `dashboard.html` and point out exception count, critical risks, and WIP exposure.
4. Open `executive_report.html` and show Control Value Summary.
5. Open `management_pack.xlsx` and show sheets:
   - Executive Summary
   - Control Value Summary
   - Stock vs GL Mismatch
   - Work Order Exceptions
   - Risk Matrix
6. Open `evidence/index.html`.
7. Start Studio:

```bash
reconforge studio --input examples/sample_data --output output/demo
```

8. In Studio, update `EXC-0001` to `Under Review`, add reviewer and note, and filter by status.
9. Open `review_register.xlsx`.
10. Run and show:

```bash
reconforge report client-pack --input output/demo --output output/client_pack
```

Narration close:

"This is pilot-ready for local export-based reviews. It is not claiming direct ERP integration or production adoption."

## 10-Minute Technical Demo Script

1. Repo overview

Narration:

"ReconForge is a Python CLI and local Studio app. The core workflows are file-based and do not require cloud upload."

Show:

- `README.md`
- `docs/security-whitepaper.md`
- `control-packs/`

2. Environment check

```bash
reconforge doctor
```

Narration:

"Doctor confirms the package, config, sample data, and output path."

3. Mapping readiness

```bash
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge mappings wizard --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/mapping_wizard
```

Open `output/mapping_wizard/mapping_report.md`.

4. Demo run

```bash
reconforge demo run --output output/demo
```

Narration:

"This generates the full sample workflow deterministically."

5. Reports and evidence

Open:

- `output/demo/dashboard.html`
- `output/demo/executive_report.html`
- `output/demo/management_pack.xlsx`
- `output/demo/evidence/index.html`

6. Review workflow

```bash
reconforge studio --input examples/sample_data --output output/demo
```

In Studio:

- open Exceptions
- set an exception to `Under Review`
- add reviewer, note, and decision reason
- filter by status

7. Register export

```bash
reconforge review export --input output/demo --output output/demo/review_register.xlsx
```

Open `review_register.xlsx`.

8. Period comparison

```bash
reconforge compare periods --inputs output/demo output/demo --output output/period_comparison
```

Open `output/period_comparison/period_comparison.html`.

9. Client pack

```bash
reconforge report client-pack --input output/demo --output output/client_pack
```

Open:

- `output/client_pack/handoff_summary.md`
- `output/client_pack/data_privacy_note.md`
- `output/client_pack/files_manifest.json`

## Screen-by-Screen Shot List

- README hero and quick start.
- Terminal running `reconforge doctor`.
- Terminal running `reconforge demo run --output output/demo`.
- Static dashboard.
- Executive report Control Value Summary.
- Management pack workbook tabs.
- Evidence binder index.
- Studio Exceptions page before update.
- Studio review update success message.
- Studio status filter after update.
- Review register workbook.
- Mapping report.
- Period comparison report.
- Client pack manifest and privacy note.

## Key Business Messages

- Local-first processing from ERP exports.
- Repeatable stock-to-GL and work-order controls.
- Reviewable exceptions with local status tracking.
- Evidence binder for high and critical exceptions.
- Mapping helper for Odoo/SAP-style export adaptation.
- Multi-period view of recurring and resolved issues.
- Client handoff folder for consulting delivery.

## What Not To Claim

- Do not claim live Odoo or SAP integration.
- Do not claim real customer adoption.
- Do not claim global leadership.
- Do not claim guaranteed savings.
- Do not claim an audit opinion.
- Do not claim hosted enterprise security controls.
- Do not imply evidence folders are safe to share without review.
