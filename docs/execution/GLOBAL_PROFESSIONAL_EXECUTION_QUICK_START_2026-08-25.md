# Global Professional Quick Start Script (Professional Readiness Closure)

## الهدف من الملف

استخدام سريع قبل أي دورة تنفيذية يومية بحيث:
- لا يبدأ الفريق بشكوى أو تفسيرات.
- كل تحديث يُسجّل كـ evidence-backed progress.
- أي خطوة لا تُعدّل حالة `No-Go` دون تحقق واضح في `BACKLOG.yaml` و`STATE.md` و`EVIDENCE.md`.

## 1) أول 20 دقيقة قبل أي تعديل

1. تثبيت سياق الجلسة:
```powershell
Set-Location F:\reconforge-erp
git status --short
Get-Date -Format "yyyy-MM-dd HH:mm:ss"
```

2. تحقق من ملف الـdashboard المفتوح الآن:
```powershell
Get-Content docs/execution/GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md | Select-Object -First 90
```

3. تحقّق من الحالة الحالية للفجوات المفتوحة:
```powershell
rg -n "^\\s*id: (E-824|E-1000|E-1001|E-1002|E-1003|E-1004|E-1005|E-884|E-1006|E-1007|P4-FIN-002|P4-CON-001|P4-SCL-001|P4-REL-001|P4-IAM-001|P4-PLAT-001)" docs/execution/BACKLOG.yaml
```

4. تأكيد مصادر evidence الأساسية:
```powershell
Get-Content docs/execution/CLAIMS_EVIDENCE_MATRIX.md | Select-Object -First 40
Get-Content docs/execution/GAP_MATRIX.md | Select-Object -First 40
```

## 2) جدول البداية اليومي (copy-paste daily)

### العربية
```
اليوم: [YYYY-MM-DD] | صاحب المسؤولية: [Owner]
المهمات المفتوحة الآن: [عدد]
- E-824: [blocked/in_progress]
- E-1000: [status]
- E-1001: [status]
- E-1002: [status]
- P4-FIN-002: [status]
- P4-CON-001: [status]

الهدف المرحلي:
- [ ] تنفيذ أوامر slice اليوم
- [ ] تحديث الـevidence links
- [ ] تحديث BACKLOG.yaml
- [ ] تحديث STATE.md
- [ ] تحديث dashboard RAG snapshot
```

### English
```
Date: [YYYY-MM-DD] | Owner: [Owner]
Open critical slices:
- E-824: [blocked/in_progress]
- E-1000: [status]
- ...

Daily commit checklist:
- [ ] Execute planned slice commands
- [ ] Update evidence references
- [ ] Update BACKLOG.yaml
- [ ] Update STATE.md
- [ ] Update dashboard RAG snapshot
```

## 3) أوامر يومية مقترحة حسب السلسلة

### اليوم 1 (Gate A)
- `E-824`: تنفيذ إعادة بناء صورة release + scan المسار exact-image.
- ربط نتائج scan وSBOM/VEX في:
  - `docs/execution/DEPENDENCY_RISK.md`
  - `docs/execution/SECURITY_BASELINE.md`
  - `docs/execution/BASELINE.md`

### اليوم 2
- `E-884`: تحديث base 3.12 مع rollback verification.

### الأيام 3–4
- `E-1000` + `E-1001`: تثبيت claim boundaries وclosure dependencies.
- تحديث:
  - `docs/adr/0531-global-expansion-program-framework.md`
  - `docs/execution/STATE.md`
  - `docs/execution/BACKLOG.yaml`

### الأيام 5–7
- `E-1002`, `E-1003`, `E-1004`, `E-1005`:
  - `state + test + evidence` لكل slice
  - أي claim غير مغطّى = لا Go

### الأيام 8–10
- `E-1006`, `E-1007`, `P4-CON-001`:
  - mode manifests
  - fail-closed contracts
  - conformance evidence

### الأيام 11–14
- `P4-SCL-001`, `P4-REL-001`, `P4-IAM-001`, `P4-PLAT-001`, `P4-FIN-002`:
  - soak/HA/DR/ops/platform breadth closeout

## 4) نموذج إغلاق Slice (DoD copy-paste)

```text
Slice: [ID]
Action owner: [Name/Team]
Started at: [time]
Commands executed:
- [cmd 1]
- [cmd 2]

Evidence added:
- BACKLOG: [link/path]
- STATE: [link/path]
- EVIDENCE: [link/path]

Evidence type:
- code: [pass/fail + path]
- test: [pass/fail + command]
- runtime: [pass/fail + output summary]
- docs guard: [pass/fail + file]

Decision:
- status update: [in_progress -> completed/deferred]
- reason for hold (if any): [exact reason]
```

## 5) أوامر تحديث الملفات بعد إنجاز Slice

```powershell
# تحديث التقدم
rg -n "id: E-" docs/execution/BACKLOG.yaml | Select-String "E-824|E-1000|E-1001|E-1002|E-1003|E-1004|E-1005|E-884|E-1006|E-1007|P4-FIN-002|P4-CON-001|P4-SCL-001|P4-REL-001|P4-IAM-001|P4-PLAT-001"

# إنشاء snapshot قبل إغلاق اليوم
git -c core.pager=cat diff -- docs/execution/BACKLOG.yaml docs/execution/STATE.md docs/execution/EVIDENCE.md docs/execution/GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md > logs/daily-readiness-snapshot.diff
```

### فحص Claim Drift السريع (قبل اعتماد أي claim جديد)

```powershell
.\docs\execution\CLAIM_DRIFT_FASTCHECK_2026-08-25.ps1
```

## 6) مصفوفة قبول يومية قصيرة (ممنوع تخطيها)

- إذا بقي `E-824` = `blocked`، لا يُقبل أي claim production.
- إذا بقي أي عنصر `P0` = `in_progress` أو `blocked`، لا يُقبل أي Go claim.
- أي claim غير مدعوم يجب أن يكون نصه `bounded/local-first` في `CLAIMS_EVIDENCE_MATRIX.md`.
- بدون Evidence chain (code+test+runtime) لا يوجد تغيير في:
  - `STATE.md`
  - `GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md`

## 7) مصادر الاستيراد

إذا أردت إنشاء issues مباشرة:
- [Issue Tracker YAML](/F:/reconforge-erp/docs/execution/EXPERT_GLOBAL_PROFESSIONAL_ISSUE_TRACKER_2026-08-25.yaml)
- [Issue Board Export](/F:/reconforge-erp/docs/execution/EXPERT_GLOBAL_PROFESSIONAL_ISSUE_BOARD_EXPORT_2026-08-25.md)
- [Issue CSV](/F:/reconforge-erp/docs/execution/EXPERT_GLOBAL_PROFESSIONAL_ISSUE_TRACKER_2026-08-25.csv)
- [14-Day Pack](/F:/reconforge-erp/docs/execution/GLOBAL_PROFESSIONAL_14_DAY_CRITICAL_EXECUTION_PACK_2026-08-25.md)
- [Claim Drift Fastcheck Script](/F:/reconforge-erp/docs/execution/CLAIM_DRIFT_FASTCHECK_2026-08-25.ps1)
- [Executive One-Liner Fastcheck Script](/F:/reconforge-erp/docs/execution/EXECUTIVE_ONE_LINER_FASTCHECK_2026-08-25.ps1)
- [Daily Status Update Template](/F:/reconforge-erp/docs/execution/GLOBAL_PROFESSIONAL_DAILY_STATUS_UPDATE_TEMPLATE_2026-08-25.md)
