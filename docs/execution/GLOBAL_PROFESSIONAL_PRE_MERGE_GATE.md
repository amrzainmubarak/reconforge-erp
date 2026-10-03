# Professional Readiness Pre-Merge / Pre-Release Gate

## هدف البوابة

تمنع هذا الملف اعتماد أي branch أو إصدار أو وثيقة نشر تحتوي على claims أعلى من scope الموثق.

## قواعد الحكم العامة

1. **لا ادعاء production/enterprise/global دون إغلاق No-Go.**
2. كل claim عالي (global/enterprise/production-ready) يحتاج:
   - حالة Backlog: `completed` للمسارات ذات الأولوية المرتبطة.
   - دليل acceptance ضمن ملف Evidence مناسب.
   - إثبات من `STATE.md` بآخر حدث إغلاق.
3. `global` و`enterprise` و`banking` أو `regulated` claims تكون محظورة إذا وجد:
   - أي عنصر No-Go في الـRAG Snapshot.
   - أي evidence محلي فقط يدّعي coverage cross-host أو HA-DR.

## Gate A — Security & Dependency (Must Pass First)

- [ ] `E-824` في `docs/execution/BACKLOG.yaml` = `completed`.
- [ ] `docs/execution/DEPENDENCY_RISK.md` لا يذكر outstanding high blocker على مسار release الأساسي.
- [ ] `docs/execution/SECURITY_BASELINE.md` محدث بأحدث SBOM/VEX/License evidence للنطاق المستهدف.
- [ ] تمكين rollback plan واضح قبل أي merge production-targeted.

## Gate B — Scope Control (Claims Governance)

- [ ] لا claims تتجاوز `bounded` إلا بعد إغلاق:
  - `E-1000`, `E-1001`
  - `E-1002`, `E-1003`, `E-1004`, `E-1005`
- [ ] صف `No-Go` غير موجود في `docs/execution/GLOBAL_PROFESSIONAL_READINESS_DOD.md` أو `GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md`.
- [ ] `docs/execution/CLAIMS_EVIDENCE_MATRIX.md` يربط كل ادعاء بـ`code evidence`, `test evidence`, `runtime evidence`.

## Gate C — Functional Completeness (Global Expansion / Close / Matching)

- [ ] `E-1002` close/consolidation lifecycle evidence كامل (lock/reopen/rollback/restore).
- [ ] `E-1003` parity عبر engine/host موثق وreplay envelope قابلة للتحقق.
- [ ] `E-1004` write-back separation + conformance + compensation + idempotency مثبتة.
- [ ] أي claim حول governance أو IAM مرتبط بمسارات حساسة له audit/evidence trail كامل.

## Gate D — Deployment and Operations

- [ ] `E-884` + `E-1006` + `E-1007` معتمدة.
- [ ] لكل mode في matrix: manifest، runbook، run sample، rollback proof.
- [ ] `P4-SCL-001` و`P4-REL-001`:
  - soak/queue/throughput/restart evidence ضمن شروط قابلة للتكرار.
  - RPO/RTO وsplit-brain refusal مثبتين أو مبرر الانسحاب.

## Gate E — Platform Breadth and Governance

- [ ] `P4-IAM-001` يثبت:
  - field restrictions
  - delegation + emergency authority
  - cache invalidation + conflict analysis.
- [ ] `P4-PLAT-001` يثبت لكل bounded context:
  - manifest
  - adapter boundaries
  - migrations أو migration plan
  - rollback/testing pack كامل.
- [ ] `P4-CON-001` يثبت live connector conformance على مستوى provider-neutral.

## Gate F — Evidence Discipline

- [ ] جميع المخرجات التجميعية المحدثة موجودة في:
  - `docs/execution/EVIDENCE.md`
  - `docs/execution/STATE.md`
  - `docs/execution/BASELINE.md`
  - `docs/execution/SECURITY_BASELINE.md`
  - `docs/execution/QUALITY_BASELINE.md`
- [ ] أي تحديث claim غير مشمول بهذه الملفات يُعاد تصنيفه إلى `partial` في الـDoD.

## قرار دمج/إصدار

- **Reject**: إذا فشل أي شرط من Gates A–F.
- **Hold for evidence**: إذا كان أي بند في `in_progress` مع تداخل مالي/أمني/عملياتي.
- **Conditional go**: إذا أُغلق كل شرط مع ربط مباشر في الأدلة أعلاه، وحدثت حالة جميع الملفات المرتبطة.

