# Global Professional 14-Day Critical Execution Pack — 2026-08-25

## الهدف

تحويل حالة المشروع من `No-Go` إلى `Go-Ready` من منظور evidence-first عبر إغلاق السلاسل الحرجة ذات الأثر العالمي أولًا، ثم سلاسل الاستقرار والتوسع.

## قاعدة القبول العليا للـSprint

1. لا أي عنصر أحمر في `E-824`.
2. جميع عناصر `P0` من `E-824..E-1007` تتحول إلى `completed`.
3. عناصر `P1` الحرجة (`E-884`, `E-1006`, `E-1007`) مكتملة.
4. عناصر `P4` في المسار الحرج (`P4-CON-001`, `P4-SCL-001`, `P4-REL-001`, `P4-IAM-001`) مكتملة أو معللة `deferred` بنص واضح في:
   - `docs/execution/STATE.md`
   - `docs/execution/GAP_MATRIX.md`
   - `docs/execution/BACKLOG.yaml`
5. تحديث `GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md` بعد كل مغادرة يومية (Red/Amber/Green).

## Pack Execution (14 يوم)

> جميع المهام تنفّذ بالترتيب التالي: **Gate A → Financial/Matching integrity → Write-back/Connectors → Deployment/Operations.**

### 1. أيام 1–2 (البوابات الأولية الأمنية والبنية الأساسية)

1. **E-824 — Security blocker: Base image / CVE-2026-14456**
   - **Owner:** Container/Release
   - **القرار المطلوب اليوم:** إغلاق blocker نهائي في مسار الصورة المعتمدة.
   - **Acceptance:**
     - لا High/critical CVE متبقي في مسار release المحدد.
     - تحديث `DEPENDENCY_RISK.md` و`BASELINE.md` و`SECURITY_BASELINE.md`.
   - **Commands المقترحة:**
     - إعادة بناء الصورة المعتمدة.
     - `docker scout cves` (أو أداة معادلة في pipeline).
     - `python -m pip_audit` بعد تحديث التبعية.
     - تحديث SBOM وVEX ذات صلة.
   - **مخرج اليوم:** `docs/execution/BACKLOG.yaml` (`E-824` => `completed`).

2. **E-884 — Python base migration + rollback envelope**
   - **Owner:** Platform/Release
   - **القرار المطلوب اليوم:** تنفيذ الترقية مع مسار rollback معتمد.
   - **Acceptance:**
     - صورة جديدة تعمل على البناء القياسي للمشروع.
     - تم توثيق خطة التراجع (rollback) بنجاح.
     - أية اختلافات في الأداء/الاعتمادات موثقة.
   - **Commands المقترحة:**
     - `python -m build --no-isolation`
     - إعادة تشغيل `python -m ruff check .`, `python -m mypy reconforge`, `python -m pytest`
     - إعادة فحوصات security/dependency.
   - **مخرج اليوم:** تحديث `E-884` وملحقات الدليل ذات الصلة.

3. **E-1000 + E-1001 — Global expansion / slice orchestration**
   - **Owner:** Product/Architecture/Finance
   - **القرار المطلوب اليومين:** تثبيت حدود `claim` واضحة لكل Slice ومنع كل دعوى تتجاوز الأدلة.
   - **Acceptance:**
     - تحديث مصفوفة claims boundaries في `CLAIMS_EVIDENCE_MATRIX.md`.
     - إزالة/تصنيف أي wording غير مدعوم إلى bounded-local.
     - تحديث `STATE.md` و`BACKLOG.yaml` للحالات المترتبة مباشرة.

### 2. أيام 3–6 (إغلاق مالي-محاسبي ومالية-تشغيلية)

4. **E-1002 — Close/consolidation lifecycle**
   - **Owner:** Finance Platform
   - **القرار المطلوب:** إغلاق lifecycle كامل.
   - **Acceptance:**
     - lock/reopen/rollback/restore موثقة بنسق مدعوم.
     - replay proof واضح مع أثر غير قابل للتحريف.
   - **مخرجات:**
     - اختبارات close lifecycle.
     - evidence entry في `EVIDENCE.md`.

5. **E-1003 — Deterministic Matching parity**
   - **Owner:** Matching
   - **القرار المطلوب:** parity عبر host/engine مع ambiguity handling مقيد.
   - **Acceptance:**
     - proof مستقل لـ deterministic output تحت permutations.
     - سياسة tie-break و ambiguity واضحة ومخطوطة.
     - قياس حدود التعقيد والوقت ضمن الحدود المعلنة.

6. **E-1005 — IAM + SoD critical paths**
   - **Owner:** IAM/Governance
   - **القرار المطلوب:** غلق partial policies الحساسة.
   - **Acceptance:**
     - self-approval / conflict paths مرفوضة صراحة بالأدلة.
     - كل route عالي المخاطر يثبت ربطه بـ audit/evidence graph.

### 3. أيام 7–10 (Write-back وConnectors وDeployment readiness)

7. **E-1004 — Write-back governed**
   - **Owner:** Connectors + Security
   - **القرار المطلوب:** فصل واضح بين Read/Write مع compensation.
   - **Acceptance:**
     - conformance كامل لـ read/write profiles.
     - replay + compensation proof.
     - provider-neutral transport وhardening محدث.

8. **P4-CON-001 — Live connectors + production safety**
   - **Owner:** Connectors
   - **القرار المطلوب:** رفع من local/fixture إلى conformance قابلة للإنتاج.
   - **Acceptance:**
     - tests ل idempotency, cursor consistency, retry/backoff, audit trails.
     - لا data-loss paths بدون evidence rollback.

9. **E-1006 — Mode-specific deployment readiness**
   - **Owner:** Deployment
   - **القرار المطلوب:** لكل mode runbook + rollback قابل للتنفيذ.
   - **Acceptance:**
     - تحديث `DEPLOYMENT_READINESS_MATRIX.v1.yaml`.
     - دليل verified لكل mode.

10. **E-1007 — Fail-closed edition profile**
    - **Owner:** Deployment/Security
    - **القرار المطلوب:** منع بدء أي edition ناقص.
    - **Acceptance:**
      - guard + manifest validation.
      - ربط claim digest لكل إصدار edition.

### 4. أيام 11–14 (P4 stability & platform completeness)

11. **P4-SCL-001 — High-volume & backpressure**
    - **Owner:** Operations/Backend
    - **القرار المطلوب:** توسيع من local soak إلى سيناريوهات scale معلنة.
    - **Acceptance:**
      - soak per 10K/100K benchmarks (أو الحجم المعلن).
      - no duplicate effects، queue drained، bounded retry، fairness/penalty boundaries.

12. **P4-REL-001 — HA/DR repeatability**
    - **Owner:** SRE/Infra
    - **القرار المطلوب:** دليل RPO/RTO قابل لإعادة التشغيل.
    - **Acceptance:**
      - site loss simulation.
      - recovery repeatability عبر 2+ تكرارات.
      - تحديث runbook والتصنيف في STATE/GAP.

13. **P4-IAM-001 — Policy administration + emergency/security traces**
    - **Owner:** IAM/Platform
    - **القرار المطلوب:** إغلاق مسارات admin/emergency/exception.
    - **Acceptance:**
      - لا self-approval path.
      - policy trace كامل مع conflict logs ومراجعة دورية.

14. **P4-PLAT-001 و P4-FIN-002 — Platform/platform breadth**
    - **Owner:** Platform Engineering + Finance
    - **القرار المطلوب:** توحيد manifests/adapters/migrations لكل bounded context ضمن الطريق المحدد.
    - **Acceptance:**
      - لكل context: manifest + rollback + migration evidence + tests.
      - تحديث واضح في `GAP_MATRIX.md` حول الحدود المتبقية إن وُجدت.

## صيغة إغلاق يومية (Daily close template)

في نهاية كل يوم يجب تحديث:
1. `docs/execution/BACKLOG.yaml` للحالة الجديدة.
2. `docs/execution/STATE.md` بإثبات السبب/المخرجات.
3. `docs/execution/EVIDENCE.md` بالروابط الجديدة (الأوامر + نتائج).
4. `GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md`:
   - إزالة/تخفيض red markers المفتوحة.
   - تحديث RAG Snapshot والحالة.
5. `docs/execution/QUALITY_BASELINE.md` و`SECURITY_BASELINE.md` إذا تغيّرت الأدلة.

## معيار التوقف قبل "Go"

- لا تُغلق أي claim عالية أولوية قبل توفر Evidence chain كاملة (code + test + runtime + runbook).
- أي item لا يملك ممر قبول مكتوب في ملفي `STATE.md` و`BACKLOG.yaml` يبقى `planned` أو `in_progress` مهما كان.
- `Go-Ready` لا يتحقق إلا بعد اجتياز البوابة الرسمية:
  - [GLOBAL_PROFESSIONAL_PRE_MERGE_GATE.md](./GLOBAL_PROFESSIONAL_PRE_MERGE_GATE.md)
  - [GLOBAL_PROFESSIONAL_EXECUTION_CHECKLIST.md](./GLOBAL_PROFESSIONAL_EXECUTION_CHECKLIST.md)

### مخرجات جاهزة للاستيراد (Issue Tracker)

- لتحويل هذا الـPack إلى Board مباشرة في تنسيق JSON/YAML:
  [EXPERT_GLOBAL_PROFESSIONAL_ISSUE_TRACKER_2026-08-25.yaml](./EXPERT_GLOBAL_PROFESSIONAL_ISSUE_TRACKER_2026-08-25.yaml)
