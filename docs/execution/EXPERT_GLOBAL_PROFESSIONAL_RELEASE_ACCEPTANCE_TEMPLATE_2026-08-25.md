# Release Gate Acceptance Template (No-Go → Go-Ready)

> Use this for every governance-review cycle before declaring any global/professional readiness milestone.

## 1) Ticket Header / رأس التذكرة

- **Project:** ReconForge
- **Objective:** Global professional readiness closure package
- **Scope:** [global / team / enterprise / regulated]
- **Cycle ID:** `YYYY-MM-DD`  
- **Target:** `Go-Ready` / `Conditional Go` / `Hold`
- **Requested by:** `[الاسم]`
- **Reviewed by:** `[الاسم]`

## 2) Gate Status Snapshot / لقطة البوابات

| Gate | Condition | Status | Evidence required | Owner | Risk |
|---|---|---|---|---|---|
| A | Security & Dependency (`E-824`) | `[blocked / in_progress / completed]` | `DEPENDENCY_RISK.md` + `SECURITY_BASELINE.md` + `BASELINE.md` | Security/Release | `[Critical / High / Medium]` |
| B | Scope Control (`E-1000`, `E-1001`, `E-1002`, `E-1003`, `E-1004`, `E-1005`) | `[ ... ]` | `BACKLOG.yaml` + `CLAIMS_EVIDENCE_MATRIX.md` + `STATE.md` | Architecture | `[ ]` |
| C | Functional Completeness | `[ ... ]` | `GAP_MATRIX.md` + relevant test evidence + strategy envelopes | Finance/Matching/Connectors | `[ ]` |
| D | Deployment & Ops (`E-884`, `E-1006`, `E-1007`, `P4-REL-001`, `P4-SCL-001`) | `[ ... ]` | `DEPLOYMENT_READINESS_MATRIX.v1.yaml` + ops evidence | Platform/Infra | `[ ]` |
| E | Platform breadth governance (`P4-FIN-002`, `P4-CON-001`, `P4-IAM-001`, `P4-PLAT-001`) | `[ ... ]` | `GAP_MATRIX.md` + `BACKLOG.yaml` + `EVIDENCE.md` | Platform/IAM/Connectors | `[ ]` |
| F | Evidence Discipline (`STATE/EVIDENCE/BASELINE`) | `[ ... ]` | `STATE.md` + `EVIDENCE.md` + `BASELINE.md` + `QUALITY_BASELINE.md` + `SECURITY_BASELINE.md` | Docs/Governance | `[ ]` |

### Decision Rule / قاعدة القرار

- أي خلية بـ **blocked/partial/plan-only/open** في Gate A أو Gate B تعني:
  - `Reject` أو `Hold for evidence`.
- أي `P4` عالي الخطورة:
  - `deferred` فقط مع risk register صريح + تاريخ مراجعة + تأثير التشغيل.
- أي claim أعلى من `bounded/local-first` لا يمكن رفعه حتى تكتمل شروط Gates المذكورة.

## 3) Slice Closure Form / نموذج إغلاق كل Slice

### For each Slice (P0/P1/P4)

- **Slice ID:** `E-XXXX / P4-YYYY`
- **Area:** `[container / matching / iam / connectors / deployment / operations / platform / finance]`
- **Current state:** `[blocked/in_progress/planned/completed/deferred]`
- **Evidence contract:**  
  - code evidence: `[file paths]`  
  - test evidence: `[file paths]`  
  - runtime evidence: `[file paths]`
- **Command/commands:** `[command list]`
- **Acceptance criteria:** `[explicit measurable criteria]`
- **Claim impact:** `[which claims this enables/disables]`
- **Risk introduced if accepted:** `[brief]`
- **Decision timestamp:** `YYYY-MM-DD HH:MM`
- **Reviewer approval:** `[name/signature placeholder]`

## 4) Mandatory check examples / أمثلة شروط إلزامية

### Security Example / مثال أمني
- Slice: `E-824`
- Check: no unremediated High on approved container base.
- Required docs: `DEPENDENCY_RISK.md`, `BASELINE.md`, `BACKLOG.yaml`.
- Failure action: **Do not proceed**.

### Financial Closure Example / مثال إغلاق مالي
- Slice: `E-1002` + `P4-FIN-002`
- Check: lock/reopen/rollback/restore + immutable closure proof + replay evidence.
- Required docs: `GAP_MATRIX.md`, `STATE.md`, `EVIDENCE.md`.

### IAM / SoD Example / مثال IAM و SoD
- Slice: `E-1005` + `P4-IAM-001`
- Check: policy conflicts + emergency + delegation + cache invalidation + exception tracing.
- Required docs: `STATE.md`, `BACKLOG.yaml`.

## 5) Pre-merge Decision Block / عتبة قرار قبل الدمج

- **Reject if:**
  - أي شرط في Gate A أو B فاشل.
  - أي دليل claim أعلى من النطاق المحلي غير مغلق بإثبات cross-boundary.
  - أي slice مفتوح `in_progress` يشتمل على مسارات مالية/أمنية/تشغيلية.
- **Hold for evidence if:**  
  - توجد عناصر `P4` غير مغلقة بدون تعليل واضح أو دون risk register.
- **Conditional Go if:**  
  - `E-824` completed.
  - جميع `P0` المذكورة في `E-824..E-1007` أصبحت `completed/Go`.
  - P1 الأساسية `E-884`, `E-1006`, `E-1007` مكتملة.
  - `P4-*` إما `completed` أو `deferred` بمبرر معلن.
  - ملفات `STATE.md`, `EVIDENCE.md`, `BASELINE.md`, `SECURITY_BASELINE.md`, `QUALITY_BASELINE.md` محدثة بنفس اليوم.

## 6) Final Review Sign-off / اعتماد المراجعة النهائية

- **Release Lead:** `[________________]`
- **Date:** `[_____]`
- **Go Decision:** `[Reject / Hold / Go-Ready / Conditional Go]`
- **Known residuals:** `[short bullets with IDs]`
- **Next review date:** `[_____]`
