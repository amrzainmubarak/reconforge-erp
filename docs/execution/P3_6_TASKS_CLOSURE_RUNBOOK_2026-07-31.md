# 6-Task Closure Runbook for Phase 1–3 Publication-Safe Exit

## الهدف

تفعيل نشر نهائي آمن لمرحلة 1–3 بعد تحقق جميع الأدلة المطلوبة، بدون claims غير مبرهنة.

## الحالة اللحظية (2026-08-01)

- إجمالي المهام في `docs/execution/BACKLOG.yaml`: **65**
- مكتملة: **62**
- `in_progress`: **3**

القائمة غير المكتملة الآن:

- `P3-ENT-013` (in_progress)
- `P3-EXT-001` (in_progress)
- `P3-EXT-002` (in_progress)

## لماذا الهدف متوقف الآن رغم نجاح الاختبارات الداخلية؟

`python -m pytest tests/test_phase_1_exit_audit.py` و `python -m pytest tests/test_phase_2_exit_audit.py` يمران بنجاح، لكن:

`tests/test_phase_1_3_execution_contract.py::test_phase_three_has_no_unsupported_completion_shortcut` يفشل لأن:

- `PHASE_1_3_EXECUTION_MATRIX.yaml`:
  - `closure_policy.all_tasks_completed` = `false`
  - `closure_policy.all_required_gates_verified` = `false`
- `external_gate_policy`:
  - `p3_external_pilots.status = engaged` بدون artifacts
  - `p3_independent_security_review.status = engaged` بدون artifacts

## 6 غلق نهائي يجب إنجازه فعليًا

### 3 عناصر backlog/خروج (منطقية)

1) `P3-ENT-013`  
   الحالة الحالية: in_progress  
   المتطلب: `P3_EXT_001` و `P3_EXT_002` يجب أن تكون verified قبل إغلاقه.

2) `P3-EXT-001`  
   الحالة الحالية: in_progress  
   المتطلب: 3–5 pilots **خارجية/حقيقية** وفق:
   - `docs/execution/P3_EXT_001_CONTROLLED_PILOT_EVIDENCE_TEMPLATE.md`
   - ملفات `docs/execution/P3_EXT_001_PILOT_###.md`

3) `P3-EXT-002`  
   الحالة الحالية: in_progress  
   المتطلب: تقرير مراجعة مستقل كامل في:
   - `docs/execution/P3_EXT_002_REVIEW_REPORT.md`
   باستخدام `docs/execution/P3_EXT_002_INDEPENDENT_SECURITY_REVIEW_TEMPLATE.md`

### 3 عناصر Gate/Matrix (مسمى “all 6 required before publish”)

4) تحديث `P3_EXT_001`:
   - في `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml`:
     - `external_gate_policy.gates.p3_external_pilots.status = verified`
     - `evidence_artifacts` يجب أن تتضمن ملفات pilot الحقيقية

5) تحديث `P3_EXT_002`:
   - في `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml`:
     - `external_gate_policy.gates.p3_independent_security_review.status = verified`
     - `evidence_artifacts` يجب أن تشمل `docs/execution/P3_EXT_002_REVIEW_REPORT.md` + أي مرفقات مراجعة مرتبطة

6) إغلاق مصفوفة الإغلاق:
   - `all_tasks_completed = true`
   - `all_required_gates_verified = true`
   - `docs/execution/P3_ENT_013_EXIT_AUDIT.yaml`:
     - `status: verified`
     - dependency gates داخلية إلى `verified`
     - `publication_block: false`

## أوامر التحقق النهائية قبل الإقفال والنشر

- `python -m pytest tests/test_phase_1_exit_audit.py`
- `python -m pytest tests/test_phase_2_exit_audit.py`
- `python -m pytest tests/test_phase_1_3_execution_contract.py`
- مرجع: `docs/execution/PHASE_1_3_PUBLICATION_READINESS.md`

## قرار No-Go الحالي

No-Go حتى تستكمل العناصر الـ 6 أعلاه (خصوصًا أي أدلة خارجية غير محاكاة).  
عند اكتمالها، يكون النشر على GitHub (push/pull/PR/Release) هو الخطوة التالية مباشرة.

إصلاحات CI الخاصة بـPR #66 موثقة محليًا في `E-247`، لكنها لا تغيّر هذا القرار:
الإصلاح التقني ليس بديلًا عن 3–5 طيارين خارجيين حقيقيين أو تقرير مراجعة أمنية مستقلة.
