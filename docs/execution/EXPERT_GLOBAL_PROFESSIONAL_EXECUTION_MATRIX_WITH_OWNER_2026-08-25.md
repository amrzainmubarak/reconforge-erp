# Expert Execution Matrix (Owners / Evidence / Exit Commands) — 2026-08-25

## الهدف التنفيذي

تحديد ماذا يفعل فريق التنفيذ خلال كل Slice المفتوح حتى تتحول حالة المشروع إلى **Go-Ready** بشكل موثق.

> هذا الملف يقصد منه الاختصار التنفيذي، وليس تنفيذًا تقنيًا. جميع الشروط يجب أن تُثبت بآثار evidence وملفات gate ذاتها المذكورة في `BACKLOG`, `STATE`, `EVIDENCE`, وملفات الـdashboard/DoD.

## مصفوفة الإغلاق (No-Go → Go)

| Slice | أولوية | الحالة الآن | Owner مقترح | دليل إثبات مرجعي | شرط القبول | Command/Check مقترح | مخرجات الحالة المطلوبة |
|---|---:|---|---|---|---|---|---|
| E-824 | P0 | blocked | Container/Release | `DEPENDENCY_RISK.md`, `BASELINE.md`, `SECURITY_BASELINE.md` | لا يوجد أي High CVE متبقٍ في المسار المعتمد للحاوية؛ CVE-2026-14456 مغلق/معوض بشكل موثق | `docker build`, `docker scout cves`, `python -m pip_audit`, `python -m build --no-isolation` (على نفس صورة/الوسيط الموصوف) | `BACKLOG.yaml` = completed + تحديث evidence in `BASELINE`/`DEPENDENCY_RISK` |
| E-1000 | P0 | in_progress | Program Management + Architecture | `ADR 0531`, `BACKLOG.yaml`, `STATE.md`, `CLAIMS_EVIDENCE_MATRIX.md` | نهاية "Global Expansion Track" مع boundary لكل ادعاء global | مراجعة `docs/adr/0531-global-expansion-program-framework.md` + تحديث claim boundaries | تحديث حالة البند + سجل exit-evidence في `STATE.md` |
| E-1001 | P0 | in_progress | Architecture + Finance + Security + Ops | `BACKLOG.yaml`, `STATE.md`, `GAP_MATRIX.md` | سلاسل integrity/matching/connectors/identity/deployment متماسكة بلا drift | تحديث جميع sub-slices المرتبطة وإعادة بناء matrix للحواف | تحديث `BACKLOG.yaml` مع `depends_on` مكتمل + أدلة exit لكل sub-slice |
| E-1002 | P0 | in_progress | Finance Platform | `GAP_MATRIX.md`, `BACKLOG.yaml`, `EVIDENCE.md` | close lifecycle كامل: lock/reopen/rollback/restore + replay + immutable closure | تشغيل/توثيق اختبارات close المعلنة وملفات evidence المرتبطة | `P4-FIN-002` transition proof محدث + evidence entry جديدة |
| E-1003 | P0 | in_progress | Matching Engine | `CLAIMS_EVIDENCE_MATRIX.md`, `STATE.md` | parity مقيد عبر engine/host + ambiguity policy + deterministic budget/constraints | إعادة تشغيل suites المطابقة المعلن عنها + حفظ مقارنة cross-engine/head | إغلاق claims ذات الصياغة المحكومة عبر `state`/`evidence` |
| E-1004 | P0 | in_progress | Connectors + Security | `GAP_MATRIX.md`, `BACKLOG.yaml` | فصل read/write بالكامل + conformance + compensation proof + hardening | تنفيذ/توثيق write-back boundary tests + replay + provider transport fences | لا توجد claim مكتوبة بأنها production-write-back بدون هذه الشروط |
| E-1005 | P0 | in_progress | IAM/Platform Governance | `STATE.md`, `EVIDENCE.md`, `GAP_MATRIX.md` | SoD وdeny-by-default و actor-conflict تغطية كل المسارات الحساسة | مراجعة policy tests + audit graph assertions للحالات الحساسة | `P4-IAM-001` لا يتحرك لـ defer without explicit risk rationale |
| E-884 | P1 | planned | Platform/Release | `QUALITY_BASELINE.md`, `SECURITY_BASELINE.md`, `BASELINE.md` | ترقية base image + rollback + إعادة فحص كاملة (security/dependency/doctor/doctor-like checks) | تنفيذ الأدلة المتسلسلة المذكورة في البلوكين | `BACKLOG.yaml` في completed + تحديث دليل البلوك |
| E-1006 | P1 | in_progress | Deployment | `DEPLOYMENT_READINESS_MATRIX.v1.yaml`, `STATE.md`, `BACKLOG.yaml` | لكل وضع community/team/enterprise/regulated manifest/runbook/rollback | تنفيذ command checks لكل gate في matrix وتحديث الدليل | readiness لكل وضع = verified_scoped أو partial مع justification |
| E-1007 | P1 | in_progress | Deployment + Security | `STATE.md`, `BACKLOG.yaml` | fail-closed edition profile لا يقبل أي profile ناقص | تحديث profile validation عبر claim digest والفحص الموحد | منع claim للـedition غير مكتملة من خلال runtime guard |
| P4-FIN-002 | P4 | in_progress | Finance + Platform | `GAP_MATRIX.md`, `BACKLOG.yaml`, `STATE.md` | statutory/legal/equity/intercompany/restore boundaries مكتملة + evidence-bounded | تشغيل test sets + توثيق migration/runtime/playback boundaries | كل bounded context ضمن P4-FIN-002 إما completed أو deferred بمبرر |
| P4-CON-001 | P4 | in_progress | Connectors | `GAP_MATRIX.md`, `BACKLOG.yaml`, `STATE.md` | write-back حقيقي محكوم بقواعد الشبكة + credentials + recovery/compensation | تشغيل conformance suites (read/write/schemas/cursor/idempotency) + audit replay | أي ادعاء live connector بدون conformance يُبقي item open |
| P4-SCL-001 | P4 | in_progress | Operations + Backend | `STATE.md`, `BACKLOG.yaml` | soak throughput/queue/backpressure/retry/cancellation مع no-duplicate effect | إعادة تشغيل benchmark profiles عبر 100K+ عند الإمكان + قياسات hardware+wall time | إدراج دليل repeatability + limits وboundary honesty |
| P4-REL-001 | P4 | in_progress | SRE/Infra | `STATE.md`, `BACKLOG.yaml`, `GAP_MATRIX.md` | multi-domain HA/DR مستقل، split-brain refusal، RPO/RTO repeatable، failback proof | إعادة تنفيذ HA/DR drill على failure domains متنوعة (أدنى): two-domain לפחות | تحديث matrix/claims إلى bounded wording وليس production-ready |
| P4-IAM-001 | P4 | in_progress | IAM/Platform | `STATE.md`, `BACKLOG.yaml` | policy administration + emergency + cache invalidation + conflict analysis + trace audit كامل | تنفيذ/تحديث اختبارات استثناءات السياسة وإضافة أدلة غير قابلة للتحريف | أي self-approval/overbroad grant يحتاج رفض فوري |
| P4-PLAT-001 | P4 | in_progress | Platform Engineering | `GAP_MATRIX.md`, `BACKLOG.yaml`, `STATE.md` | كل bounded context له manifest/adapters/migrations/rollback/tests مكتملة | مراجعة modules كاملة وإغلاق manifest gaps داخل P4-PLAT-001 | أي context مفتوح يمنع ادعاء modular completeness |

## أولوية التنفيذ الأسبوعية (تركيز Gate-First)

1. **اليوم 1–4**: Gate A (أمن) وP0 الأساسي (E-824 → E-1001)
2. **اليوم 5–10**: close/matching/IAM/write-back (E-1002 → E-1005)
3. **اليوم 11–14**: E-884 + mode/readiness (E-1006, E-1007)
4. **اليوم 15–21**: P4 sweep النهائي (SCL/REL/CON/IAM/PLAT/FIN)

## معايير الإنذار (Red/Amber)

- **Red**: أي فشل أو drift في Gate A أو أي شرط `P0`.
- **Amber**: `P1` أو `P4` متقدم لكن غير مكتمل مع قبول defer واضح.
- **Green**: جميع شروط Go-Ready في `GLOBAL_PROFESSIONAL_PRE_MERGE_GATE.md` تحققها.

## ملاحظة إجرائية

هذا الجدول ليس بديلاً عن الأدلة الحالية؛ هو طريقة تشغيلية لدمج:
- [GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD](F:/reconforge-erp/docs/execution/GLOBAL_PROFESSIONAL_EXECUTION_DASHBOARD.md)
- [GLOBAL_PROFESSIONAL_READINESS_DOD](F:/reconforge-erp/docs/execution/GLOBAL_PROFESSIONAL_READINESS_DOD.md)
- [GLOBAL_PROFESSIONAL_PRE_MERGE_GATE](F:/reconforge-erp/docs/execution/GLOBAL_PROFESSIONAL_PRE_MERGE_GATE.md)

وتُحدّث هذه الخريطة عند أي تغيير فعلّي في ownership أو نتائج evidence.
