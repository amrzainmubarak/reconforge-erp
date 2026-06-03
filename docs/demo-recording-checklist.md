# Demo Recording Checklist

## Before Recording

- Run `reconforge demo run --output output/demo`.
- Confirm `output/demo/management_pack.xlsx` exists.
- Confirm `output/demo/dashboard.html` exists.
- Confirm `output/demo/executive_report.html` exists.
- Confirm `output/demo/evidence/index.html` exists.
- Confirm `output/demo/review_register.xlsx` exists.
- Generate a client pack:

```bash
reconforge report client-pack --input output/demo --output output/client_pack --summary-only
```

## Screen Sequence

1. Repository README.
2. Terminal demo command.
3. Demo output folder.
4. Executive report.
5. Dashboard.
6. Management pack workbook.
7. Evidence binder index.
8. Studio review status update.
9. Review register export.
10. Client handoff pack.

## Recording Notes

- Keep terminal font large enough for non-technical viewers.
- Avoid showing local usernames or unrelated folders.
- Use sample data only.
- Do not claim customer adoption, savings, certification, or direct ERP connectors.
- Say “export-based local workflow” and “synthetic/sample data.”

## Common Questions

**Does this connect directly to my ERP?**  
No. The current workflow uses local CSV/XLSX exports.

**Does this replace an auditor?**  
No. It organizes reconciliation and evidence outputs for review by qualified personnel.

**Does it upload data?**  
Core workflows run locally and do not require cloud upload.

**Can I share the client pack externally?**  
Only after reviewing privacy, redaction, and sharing approvals.
