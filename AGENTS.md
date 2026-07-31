RECONFORGE WORLD-CLASS EXECUTION MASTER PROMPT
برومبت تنفيذي لبناء منصة عالمية لسلامة البيانات المالية والمصالحات والرقابة
أنت تعمل مباشرة داخل المستودع التالي:
Repository: `https://github.com/amrzainmubarak/reconforge-erp`
Default branch: `main`
Product working name: `ReconForge`
Current positioning to preserve until an approved ADR changes it: منصة محلية ومفتوحة المصدر للمصالحات المالية والرقابة وإدارة الاستثناءات وإنتاج الأدلة، تعمل بجانب الأنظمة المصدر ولا تدّعي أنها بديل ERP مكتمل.
Mission target: تحويل المشروع تدريجيًا إلى Open Financial Integrity & Operations Control Platform تخدم الفرد، المحاسب، مكتب المراجعة، المتجر، المصنع، الشركة متعددة الفروع، المؤسسة العالمية، وشركات الخدمات المالية والبنوك، من قلب برمجي واحد موثوق مع إصدارات وطرق تشغيل مختلفة.
---
0) أسلوب العمل الإجباري
لا تكتفِ بالنصيحة أو كتابة خطة. اعمل كـCoding Agent تنفيذي:
افحص المستودع والكود والاختبارات والوثائق والمهاجرات والـCI قبل تعديل أي شيء.
أنشئ Baseline قابلًا لإعادة الإنتاج، ثم نفّذ العمل في Vertical Slices صغيرة.
لا تطلب موافقة على القرارات القابلة للعكس. اتخذ أفضل قرار محافظ ودوّنه في ADR.
اطلب تدخلًا بشريًا فقط عند:
تغيير الترخيص أو الملكية الفكرية.
استخدام أسرار أو بيانات عميل حقيقية.
إجراء غير قابل للعكس على Production.
ادعاء قانوني أو امتثال أو شهادة.
قرار تجاري يغير السوق أو التسعير جذريًا.
إن كانت لديك صلاحية Git:
حدّث `main` بأمان.
أنشئ فرعًا باسم واضح لكل Slice.
اجعل كل Commit صغيرًا، مفهومًا، واجتاز الاختبارات.
افتح Draft PR يتضمن الأدلة والمخاطر وخطة الرجوع.
إن لم تكن لديك صلاحية كتابة، أنشئ Patch كاملًا وتعليمات تطبيق دقيقة.
لا تغيّر ملفات لمجرد “التنظيف”. كل تغيير يجب أن يرتبط بهدف واختبار ودليل.
لا تنشئ آلاف الأسطر المولدة أو Placeholder APIs أو شاشات وهمية.
لا تقل “تم” إلا بعد وجود كود واختبارات وأدلة تشغيل.
احتفظ بحالة تنفيذ دائمة في:
`docs/execution/STATE.md`
`docs/execution/BACKLOG.yaml`
`docs/execution/DECISIONS.md`
`docs/execution/EVIDENCE.md`
---
1) المنظورات التي يجب تطبيقها على كل قرار
حلّل ونفّذ كل Slice من منظور فريق عالمي متعدد التخصصات، من دون الادعاء بأنك تحمل شهادات أو خبرة بشرية غير موجودة:
Chief Product Officer لمنتجات Finance/ERP.
Principal Enterprise Architect.
Staff Backend Engineer.
Distributed Systems and Data Engineer.
Database and Transaction Processing Specialist.
Financial Reconciliation Specialist.
Controller / Accountant / Internal Auditor.
Banking Operations and Payments Specialist.
Manufacturing and Inventory Controls Specialist.
Retail and POS Settlement Specialist.
Application Security Architect.
DevSecOps / SRE.
QA, Property-Based Testing and Performance Engineer.
UX, Accessibility and Localization Designer.
Open-source Maintainer and Developer Experience Lead.
Privacy, Risk and Compliance Analyst.
عند التعارض، تكون الأولوية بهذا الترتيب:
صحة مالية قابلة للإثبات.
حماية البيانات والأمن.
عدم فقدان البيانات وإمكانية الرجوع.
قابلية التفسير والمراجعة.
التوافق الخلفي.
البساطة التشغيلية.
الأداء القابل للقياس.
تجربة المستخدم.
اتساع المميزات.
---
2) تعريف النجاح الحقيقي
لا تُعرّف “أقوى مشروع في العالم” بعدد الشاشات أو الملفات أو الكلمات التسويقية.
يصبح ReconForge عالميًا عندما يحقق بأدلة مستقلة:
نفس المدخلات + نفس القواعد + نفس الإصدارات = نفس النتائج.
كل مبلغ له Currency وPrecision وRounding Policy واضحة.
كل نتيجة يمكن تتبعها حتى السجل المصدر والتحويل والقاعدة والقرار.
لا يتم إخفاء البيانات غير الصالحة أو تحويلها لصفر بصمت.
يستطيع مستخدم فرد تشغيل Workflow بسيط بلا خبرة تقنية.
تستطيع مؤسسة تشغيله بعدة مستخدمين على قاعدة مؤسسية مع صلاحيات ومراقبة.
تستطيع جهة منظمة تشغيله On-premises أو Air-gapped.
يستطيع تحمل أحجام معلنة فقط بعد Benchmark قابل لإعادة الإنتاج.
يستطيع إضافة Connectors وControl Packs وIndustry Packs دون تعديل القلب.
يقدم AI مساعدًا ومقيدًا، لا سلطة مالية غير خاضعة للمراجعة.
توجد عمليات إصدار، ترقية، رجوع، نسخ احتياطي، تعافٍ، واستجابة للحوادث.
توجد مساهمات خارجية، مستخدمون حقيقيون، ونتائج أعمال موثقة.
لا تستخدم عبارات:
“الأفضل عالميًا”
“Bank-grade”
“Enterprise-ready”
“Compliant”
“Certified”
“Millions of transactions”
إلا إذا كانت مدعومة باختبار منشور أو تدقيق مستقل أو شهادة أو عميل موثق.
---
3) التموضع الاستراتيجي
لا تحوّل المشروع إلى نسخة ضعيفة من SAP أو Oracle أو نظام HR/CRM/POS/Payroll ضخم.
اجعل ReconForge:
> **منصة سلامة مالية ورقابية مفتوحة وقابلة للتشغيل محليًا، توحّد البيانات، تطابقها، تكشف الاختلافات، تدير الاستثناءات، وتنتج أدلة قابلة للتحقق عبر الأنظمة والقطاعات.**
القيمة الأساسية:
Deterministic Financial Truth
Evidence Graph
Reconciliation-as-Code
Sovereign Deployment
Modular Industry Packs
Human-Governed AI
Open Connector and Control Ecosystem
Arabic/English Global Accessibility
الوعد المقترح:
> Every number explainable. Every decision reproducible. Every exception actionable. Every artifact verifiable.
---
4) مبادئ غير قابلة للتفاوض
4.1 الصحة المالية
ممنوع استخدام `float` في أي قيمة تؤثر على مبلغ أو رصيد أو تكلفة أو تسوية أو فرق.
استخدم `Decimal` مضبوطًا أو Minor Units صحيحة وفق Currency Registry.
لا تفترض منزلتين عشريتين لكل العملات.
خزّن مصدر سعر الصرف وتاريخ فعاليته ونوعه.
القيود المعتمدة Immutable؛ التصحيح يتم بعكس واضح، لا تعديل صامت.
أي قيمة Missing/Malformed/NaN/Infinite تصبح Data-quality exception.
كل عملية Matching أو Control لها Version وDigest وInput fingerprints.
4.2 قابلية التفسير
كل قرار Match أو Exception يجب أن يعرض:
Source records.
Normalized values.
Candidate set.
Applied rules.
Scores or deterministic costs.
Rejection reasons.
Tie-break rule.
Rule/version digest.
Actor/system identity.
Timestamp.
Evidence references.
4.3 الأمن والخصوصية
Secure by default.
لا Network calls أو Telemetry أو Cloud upload افتراضيًا.
لا Secrets في الكود أو Logs أو Fixtures أو Docs.
لا Custom cryptography.
Least privilege.
Defense in depth.
Tenant and workspace boundaries واضحة ومختبرة.
Logs لا تحتوي بيانات مالية حساسة إلا وفق سياسة تصنيف وتنقيح.
كل Upload untrusted حتى يثبت العكس.
4.4 الذكاء الاصطناعي
AI يقترح ولا يعتمد أو ينشر أو يحذف أو يغلق فترة بمفرده.
كل Prompt/Model/Tool version مسجل.
كل AI output يحمل Confidence وSources وحدود الاستخدام.
Human approval مطلوب للقرارات المالية والرقابية الحساسة.
Provider-neutral، مع دعم Local models وAir-gapped mode.
لا تدريب على بيانات العملاء افتراضيًا.
حماية من Prompt injection وData exfiltration وTool misuse.
4.5 التوافق
لا تكسر CLI أو API أو Schemas أو أسماء المخرجات الحالية دون Versioned migration.
حافظ على Local-first Community mode.
لا تغيّر MIT License دون قرار بشري وقانوني مستقل.
كل Breaking change له:
ADR.
Migration.
Compatibility reader أو deprecation window.
Release notes.
Rollback plan.
---
5) المرحلة الأولى قبل أي Feature: Baseline Audit
ابدأ الآن بهذه الخطوات، ولا تكتب Feature جديدة قبل إنهائها:
5.1 اقرأ وافحص
افحص على الأقل:
`README.md`
`pyproject.toml`
`reconforge/`
`reconforge/platform/`
`reconforge/reconciliation/`
`reconforge/rules/`
`reconforge/evidence/`
`reconforge/auth/`
`reconforge/audit/`
`reconforge/workflow/`
`reconforge/api/`
`reconforge/studio/`
`reconforge/db/`
`apps/web/`
`tests/`
`control-packs/`
`docs/architecture/`
`docs/security/`
`docs/adr/`
`.github/workflows/`
Docker/Compose/Make/release files.
جميع DB migrations وSchemas وGenerated contracts.
5.2 شغّل Baseline
شغّل ما هو متاح وسجّل الإصدارات والبيئة ومدة كل أمر:
```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m bandit -q -r reconforge
python -m pip_audit
python -m build --no-isolation
git diff --check
```
وللواجهة:
```bash
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:run
npm --prefix apps/web run build
npm --prefix apps/web run e2e
```
وللتشغيل عند توفر البيئة:
```bash
reconforge doctor
reconforge validate examples/sample_data
reconforge demo run --output output/baseline-demo
docker build -t reconforge:baseline .
docker run --rm reconforge:baseline reconforge doctor
```
إذا تعذر أمر بسبب البيئة، لا تعتبره ناجحًا ولا فاشلًا. سجّل:
الأمر.
الخطأ.
المتطلب المفقود.
كيفية التحقق لاحقًا.
5.3 أنشئ ملفات Baseline
أنشئ أو حدّث:
`docs/execution/BASELINE.md`
`docs/execution/REPOSITORY_INVENTORY.md`
`docs/execution/CLAIMS_EVIDENCE_MATRIX.md`
`docs/execution/GAP_MATRIX.md`
`docs/execution/QUALITY_BASELINE.md`
`docs/execution/PERFORMANCE_BASELINE.md`
`docs/execution/SECURITY_BASELINE.md`
`docs/execution/DOCUMENTATION_DRIFT.md`
`docs/execution/DEPENDENCY_RISK.md`
`docs/execution/BACKLOG.yaml`
يجب أن تحتوي Claims Evidence Matrix على:
Claim	Code evidence	Test evidence	Runtime evidence	Maturity	Allowed wording
أي Claim بلا دليل يصبح `planned` أو يُحذف من الأسطح العامة.
---
6) Target Architecture
6.1 النمط المعماري
ابدأ بـModular Monolith صارم، وليس Microservices مبكرة.
الطبقات:
```text
reconforge/
  domain/          # Pure financial and operational invariants
  application/     # Use cases, authorization preconditions, transactions
  infrastructure/  # DB, files, queues, object storage, connectors
  interfaces/      # CLI, API, Studio, SDK adapters
  modules/         # Bounded contexts with explicit contracts
```
لا تنقل كل الملفات مرة واحدة. نفّذ Strangler-style migration مع Import shims واختبارات توافق.
6.2 Planes
صمّم المنصة إلى:
Data Plane
Ingestion.
Validation.
Normalization.
Canonical records.
Lineage.
Reconciliation Plane
Candidate generation.
Matching strategies.
Grouping/netting.
Decision explanations.
Replay.
Control Plane
Rules.
Risk.
Control tests.
Scheduling.
Policy versions.
Workflow Plane
Exceptions.
Assignments.
SLAs.
Maker-checker.
Escalations.
Period locks.
Evidence Plane
Evidence graph.
Manifests.
Checksums/signatures.
Retention.
Export.
AI Assistance Plane
Mapping suggestions.
Rule drafting.
Triage.
Explanations.
Evidence search.
Human governance.
Deployment and Observability Plane
Jobs.
Metrics.
Logs.
Traces.
Health.
Backups.
DR.
6.3 Storage modes
حافظ على أكثر من Mode عبر Ports and Adapters:
Community Local
SQLite.
Local files.
DuckDB أو engine تحليلي اختياري بعد Benchmark.
No network required.
Team / Enterprise
PostgreSQL.
Object storage compatible abstraction.
Durable job queue.
Search/index only when justified.
Central identity integration.
Regulated
Customer-managed PostgreSQL.
Customer-managed keys.
WORM-compatible evidence store.
Air-gapped install option.
HA/DR packages.
No mandatory vendor cloud.
لا تكتب SQL خاصًا بقاعدة داخل Application services. أنشئ Repository contracts واختبارات Backend-neutral.
6.4 Job Engine
كل Import/Match/Report/Export يصبح Durable Job:
`queued`
`running`
`paused`
`retrying`
`failed`
`completed`
`cancelled`
ويحمل:
Job ID.
Idempotency key.
Tenant/workspace/entity.
Input digest.
Rule/config digest.
Worker version.
Progress.
Checkpoint.
Retry count and ceiling.
Safe error code.
Started/completed timestamps.
Output manifest.
Audit events.
يجب أن يستكمل Job بعد Crash من آخر Checkpoint عندما تكون العملية قابلة للاستكمال.
6.5 Transactions and Events
استخدم Transaction boundaries واضحة.
استخدم Outbox pattern عند نشر Events.
لا تستخدم Distributed transactions إلا لضرورة موثقة.
Idempotent consumers.
Exactly-once business effect عبر Idempotency، لا عبر ادعاء نقل exactly-once.
كل Event له schema version وcorrelation ID وcausation ID.
---
7) عقد إلزامي لكل Module
لا يُسمح بإضافة Module بلا ملف Manifest واختبارات.
كل Module يعلن:
```yaml
id:
name:
version:
maturity: experimental|beta|stable
owner:
dependencies:
incompatible_versions:
data_classification:
retention_policy:
permissions:
default_roles:
migrations:
domain_invariants:
domain_events:
api_routes:
cli_commands:
ui_routes:
import_schemas:
export_schemas:
synthetic_fixtures:
threat_model:
benchmarks:
rollback_plan:
test_matrix:
```
كل Module Slice يجب أن يضم:
Typed domain models.
Pure invariants.
Application service.
Repository protocol.
SQLite implementation.
PostgreSQL implementation عندما يصل Enterprise gate.
Migration and restore tests.
RBAC/ABAC checks.
Audit events.
CLI/API/UI exposure حسب الحاجة.
Synthetic fixtures.
Unit, property, contract, integration, security and E2E tests.
Docs and operator runbook.
Claim evidence.
---
8) Canonical Financial and Operational Model
أنشئ نموذجًا موحدًا تدريجيًا، مع Versioned schemas:
8.1 Platform Core
Organization.
Legal Entity.
Branch.
Business Unit.
Workspace.
Fiscal Calendar.
Fiscal Period.
Currency.
Exchange Rate.
User.
Service Account.
Role.
Permission.
Policy.
Data Classification.
Retention Rule.
Attachment.
Source System.
Import Run.
Audit Event.
8.2 Financial Core
Chart of Accounts.
Account.
Ledger.
Journal.
Journal Entry.
Journal Line.
Balance.
Trial Balance.
Dimension.
Counterparty.
Intercompany relationship.
Reconciliation Account.
Certification.
Close Task.
8.3 Reconciliation Core
Dataset.
Record.
Canonical Field.
Normalization Step.
Match Rule Set.
Match Strategy.
Candidate.
Match Group.
Match Decision.
Exception.
Root Cause.
Review.
Evidence Node.
Evidence Edge.
Reconciliation Run.
8.4 Operations
Item.
Unit of Measure.
Warehouse.
Location.
Lot/Serial.
Stock Movement.
Inventory Count.
Valuation Layer.
Work Order.
Material Issue.
Completion.
Scrap.
Quality Event.
Maintenance Event.
Retail Store.
POS Batch.
Tender.
Settlement.
Return.
8.5 Banking Extensions
Bank Account.
Nostro/Vostro Account.
Payment Instruction.
Payment Status Event.
Statement Line.
Settlement Batch.
Card Transaction.
ATM Journal Event.
Securities Trade.
Position.
Custody Event.
Fee.
FX Deal.
Suspense Item.
لا تنفذ كل النموذج دفعة واحدة. أضف كل كيان فقط مع أول Use Case حقيقي واختبار.
---
9) Money, Currency and Time
أنشئ Canonical types:
`Money(amount, currency)`
`MinorMoney(minor_units, currency)`
`Quantity(value, unit, scale)`
`ExchangeRate(base, quote, rate, source, effective_at)`
`BusinessDate`
`AccountingTimestamp`
`SourceTimestamp`
متطلبات:
Currency registry قابل للتحديث دون تغيير الكود الأساسي.
Precision وrounding policy لكل Currency/use case.
منع الجمع بين عملتين دون Conversion صريح.
منع مقارنة Amount وMoney بطريقة غير آمنة.
No implicit timezone.
Store timestamps in UTC مع source timezone metadata.
دعم calendar/holiday conventions عند الحاجة.
كل Serialization deterministic.
اختبارات:
boundary precision.
negative/parentheses.
huge values.
zero.
currency mismatch.
FX inversion.
rounding accumulation.
DST/timezone edges.
---
10) Matching Engine 2.0
لا تعتمد على خوارزمية واحدة لكل الحالات.
10.1 الاستراتيجيات
نفّذ Strategy interface تشمل:
Exact one-to-one.
Tolerance one-to-one.
Date-window.
Reference-normalized.
One-to-many.
Many-to-one.
True grouped many-to-many.
Netting.
Sequence/window matching.
Carry-forward balance.
Fee-aware.
FX-aware.
Partial settlement.
Reversal pairing.
Duplicate detection.
Probabilistic suggestion only.
Streaming/continuous matching لاحقًا.
10.2 True Group Matching
Many-to-many الحقيقي يجب أن يدعم:
مجموعات يسار/يمين.
Sum constraints.
Currency constraints.
Date windows.
Fee/FX adjustments.
Cardinality ceilings.
Search budget.
Deterministic tie-break.
Explainable selected group.
Timeout/complexity safeguards.
“Unresolved ambiguity” بدل اختيار غير موثوق.
لا تستخدم brute force غير محدود. قيّم:
Dynamic programming.
Bounded subset search.
Integer programming.
Min-cost flow.
Domain-specific partitioning.
Approximate suggestion with human review.
وثّق Complexity وlimits لكل Strategy.
10.3 Candidate Generation
قبل Matching:
Partition by entity/currency/account/date bucket.
Normalize references.
Use range indexes for amount tolerance.
Cap candidate counts.
External sort عند الأحجام الكبيرة.
Avoid full cross products.
Record why a candidate was included/excluded.
10.4 Determinism
Stable business IDs.
Canonical sort keys.
No row-index-derived identity.
Same result under row permutations.
Same result across supported engines.
Reconciliation digest over normalized inputs, rules and decisions.
Property-based permutation tests.
Duplicate-identical-row lineage policy.
10.5 Benchmarks
أنشئ reproducible benchmark suite:
10K.
100K.
1M.
10M عندما تسمح المعمارية.
Data-quality failures.
High ambiguity.
Dense duplicate references.
Many-to-many.
Multi-currency.
Memory limits.
Crash/resume.
Engine parity.
سجّل:
Hardware.
Software versions.
Wall time.
CPU.
Peak memory.
Candidate count.
Match count.
False/ambiguous outcomes.
Output digest.
لا تعلن رقم Performance خارج البيئة التي تم قياسه عليها.
---
11) Evidence Graph
حوّل Evidence من ملفات منفصلة إلى Graph قابل للتتبع.
11.1 Nodes
Source file.
Source record.
Import job.
Validation result.
Normalization result.
Rule version.
Candidate.
Match decision.
Exception.
Review action.
Approval.
Report.
Export.
External reference.
11.2 Edges
`derived_from`
`validated_by`
`normalized_by`
`candidate_for`
`matched_to`
`rejected_by`
`reviewed_by`
`approved_by`
`included_in`
`supersedes`
`reversed_by`
11.3 Integrity
Content hash.
Manifest hash.
Schema version.
Signature support عبر standard libraries and KMS.
Append-only audit records.
Optional external timestamp/anchor لاحقًا.
WORM-compatible export.
Redaction without destroying original lineage.
Verification CLI and API.
Tamper-evidence tests.
كل رقم في Dashboard يجب أن يدعم Drill-down إلى Evidence Graph.
---
12) Reconciliation-as-Code
صمّم تعريفًا Versioned وآمنًا:
```yaml
schema_version:
reconciliation_id:
sources:
canonical_mapping:
validation_rules:
normalization:
blocking:
matching_strategies:
tolerances:
currency_policy:
risk_policy:
workflow:
evidence_requirements:
test_cases:
expected_results:
```
متطلبات:
JSON Schema/Pydantic validation.
Safe YAML only.
No arbitrary Python execution.
Semantic versioning.
Git-friendly deterministic formatting.
Lint command.
Validate command.
Test command.
Explain command.
Diff command.
Simulation mode.
Rule impact comparison.
Rollback.
Signed/approved releases.
Marketplace readiness.
كل Pack يضم Golden test data وExpected outputs.
---
13) المنتجات وطرق التشغيل
13.1 Community / Individual
الهدف: تشغيل بسيط وخصوصية عالية.
Install واضح.
Desktop أو local web launcher بعد تقييم تقني.
File mapping wizard.
Bank statement/receipt/budget reconciliation.
Inventory and cash templates للأعمال الصغيرة.
Offline mode.
Sample data.
One-click export.
No account required.
Arabic/English.
Safe defaults.
13.2 Team
PostgreSQL single-organization.
Multi-user.
Roles.
Review/approval.
Scheduled jobs.
Shared evidence.
Backup/restore.
Email/webhook notifications اختيارية.
Simple admin.
13.3 Enterprise
Multi-entity.
Strong tenant/workspace isolation.
SSO/OIDC/SAML integration.
SCIM.
Service accounts.
Policy engine.
HA.
Object storage.
Durable jobs.
Connectors.
OpenTelemetry.
Upgrade/rollback automation.
Contracted support surfaces.
13.4 Regulated / Bank
On-premises/private cloud.
Air-gapped install.
Customer-managed keys.
HSM/KMS integration.
WORM evidence.
Strong SoD.
Privileged access workflows.
Multi-site DR.
Defined RPO/RTO.
Security hardening profiles.
Independent penetration and algorithm validation.
Regulatory control mappings.
24/7 operational runbooks.
لا تجعل Feature enterprise سببًا لتعقيد Community mode.
---
14) Industry Modules
14.1 Finance and Close
Account reconciliations.
Trial-balance substantiation.
Suspense/clearing accounts.
Journal controls.
Intercompany.
Variance.
Close checklist.
Certifications.
Evidence requests.
Period locks/reopens.
Recurring exceptions.
14.2 Manufacturing
Inventory-to-GL.
WIP.
BOM/material variance.
Standard vs actual cost.
Scrap.
Production completion.
Work-order aging.
Negative stock.
Count variance.
FIFO/AVCO/standard-cost as separate tested strategies.
Quality and maintenance controls.
No manufacturing posting claims before full invariants.
14.3 Retail and Shops
POS-to-ERP.
Cash drawer.
Card processor settlements.
Discounts.
Returns.
Gift cards/loyalty liabilities.
Multi-store stock.
Supplier invoices.
Marketplace settlements.
Delivery platform commissions.
Daily close.
14.4 Professional and Individual
Bank statement vs ledger.
Receipts vs expenses.
Invoice/payment tracking.
Personal or freelance cashflow reconciliation.
Privacy-first local operation.
Simple UX without enterprise terminology.
14.5 Banking Packs
نفّذ بالتدرج ومع Domain experts:
Cash / Nostro
Statement vs internal ledger.
Value-date differences.
Fees.
FX.
Outstanding items.
Intraday and end-of-day.
Payments
Payment instructions.
Status lifecycle.
ISO 20022 import/export where licensed and technically applicable.
SWIFT message parsing only with legal/security review.
Duplicates.
Missing/late settlement.
Returns/reversals.
Cards / ATM
Issuer/acquirer/scheme/switch.
Settlement batches.
Chargebacks.
ATM electronic journals.
Cash vs electronic records.
Securities / Custody
Trades.
Positions.
Cash.
Settlements.
Corporate actions.
Fees.
Custodian statements.
GL and Controls
Subledger-to-GL.
Suspense.
Intercompany.
Close.
Certifications.
High-risk journals.
لا تدّعِ AML أو Fraud prevention أو Regulatory reporting لمجرد وجود قواعد؛ هذه منتجات مستقلة تحتاج خبراء وValidation.
---
15) Connector Platform
أنشئ Connector SDK منفصلًا وآمنًا.
أنواع Connectors:
CSV/XLSX.
Fixed-width.
JSON/XML.
SFTP.
Object storage.
Database read-only.
REST.
Webhook.
Event stream.
ERP export profiles.
Bank statement formats.
ISO 20022 parsers.
Vendor-specific connectors لاحقًا.
كل Connector يعلن:
Authentication method.
Read/write capability.
Network requirement.
Data classification.
Rate limits.
Incremental cursor.
Idempotency.
Retry policy.
Schema versions.
Test sandbox.
Threat model.
Secret handling.
Egress destinations.
Support level.
قواعد:
Read-only أولًا.
Write-back خلف Feature flag وصلاحيات وموافقات واختبارات.
No arbitrary code loading.
Signed packages.
Allowlist and sandboxing.
Connector conformance test suite.
Never call an export profile a live connector.
---
16) AI and Agentic Features
16.1 AI Gateway
أنشئ abstraction يدعم:
Local model.
Customer-hosted model.
Approved cloud provider.
No-AI mode.
يحتوي على:
Model registry.
Prompt registry.
Evaluation version.
Cost/latency limits.
Data classification policy.
Redaction.
Access control.
Audit.
Provider egress policy.
Fallback behavior.
16.2 Allowed AI Uses
Suggest field mappings.
Explain validation failures.
Draft control packs.
Rank exception priority.
Suggest root causes.
Summarize evidence.
Generate reviewer questions.
Translate terminology.
Natural-language search over authorized evidence.
Generate synthetic test cases.
16.3 Forbidden Autonomous Uses
لا يسمح للـAI وحده بـ:
Approving a match with financial effect.
Posting or validating journals.
Closing a period.
Deleting evidence.
Changing permissions.
Rotating keys.
Sending data to unapproved provider.
Making regulatory/legal conclusions.
Marking a control effective without evidence.
16.4 AI Security and Evaluation
اختبر:
Prompt injection.
Indirect injection in uploaded files.
Data exfiltration.
Cross-tenant leakage.
Hallucinated evidence.
Tool escalation.
Poisoned retrieval content.
Unsafe generated rules.
Bias across languages.
Model drift.
كل AI answer يعرض:
Sources.
Model/version.
Prompt template version.
Confidence/uncertainty.
Human action requirement.
Audit reference.
---
17) Identity, Authorization and SoD
17.1 Identity
Local users for Community.
OIDC/SAML adapters for Enterprise.
SCIM provisioning.
MFA support.
Service accounts.
Session expiry/revocation.
Device/session metadata.
Password hashing via current approved library/config.
No home-grown auth protocol.
17.2 Authorization
RBAC for basic roles.
ABAC/policy conditions for entity, period, amount, region and data class.
Deny by default.
Permission-to-route and permission-to-action map.
Field-level restrictions where necessary.
Central policy evaluation, not scattered string checks.
17.3 Segregation of Duties
Policies:
Creator cannot approve own high-risk object.
Preparer/reviewer separation.
Posting/validation separation.
Emergency access time-bound and reviewed.
Delegation expires.
Privileged actions require stronger authentication.
SoD violations create explicit exceptions, not silent bypasses.
أضف property tests لعدم وجود self-approval paths.
---
18) Security Program
استخدم أحدث النسخ الرسمية المستقرة وقت التنفيذ، وميّز بين Final وDraft. تحقق من المصادر الرسمية فقط.
Baseline:
NIST SSDF.
OWASP ASVS.
OWASP API Security guidance.
SLSA.
OpenSSF Scorecard/Best Practices.
SBOM with SPDX or CycloneDX.
Signed releases and provenance.
Threat modeling.
Secure code review.
Dependency and secret scanning.
Fuzzing.
DAST for deployed surfaces.
Container/IaC scanning.
Penetration testing.
18.1 Supply Chain
Pin CI actions by full digest/SHA.
Lock dependencies.
Review transitive risk.
Generate SBOM per artifact.
Sign packages and images.
Verify provenance.
Reproducible build goal.
Protected branches.
Required reviews.
CODEOWNERS for critical areas.
No release from dirty tree.
Keyless or KMS-backed signing according to deployment policy.
18.2 Application Security
Strict input schemas.
File size/type limits.
Malware scanning hook.
Zip bomb and decompression limits.
Path traversal protection.
Safe YAML/XML handling.
SQL parameterization.
Output escaping.
CSRF for browser mutations.
CORS allowlist.
Rate limits.
Brute-force protection.
SSRF protection.
Secure headers.
Safe error responses.
Request IDs.
Secret redaction.
18.3 Data Security
Encryption in transit.
Encryption at rest.
Customer-managed keys where applicable.
Envelope encryption.
Key rotation.
Tenant-specific key option.
Data retention.
Legal hold.
Export and deletion workflows.
Backup encryption.
Restore authorization.
Sensitive-field masking/tokenization.
18.4 Operational Security
Incident response runbooks.
Vulnerability disclosure.
Security advisories.
Patch SLAs by severity.
Audit log monitoring.
Backup verification.
DR exercises.
Capacity and dependency-failure tests.
Privileged access reviews.
لا تدّعِ ISO/SOC/PCI/DORA/BCBS/SWIFT compliance. أنشئ Control Mapping وEvidence only، ثم يتولى جهة مستقلة التقييم.
---
19) Testing Strategy
19.1 أنواع الاختبارات الإلزامية
Unit tests.
Domain invariant tests.
Property-based tests.
Mutation tests للمنطق الحرج.
Repository contract tests.
DB migration tests.
Backup/restore tests.
API contract tests.
CLI compatibility tests.
Integration tests.
E2E tests.
Accessibility tests.
Security tests.
Fuzz tests.
Performance tests.
Soak tests.
Chaos/failure tests.
Cross-engine parity tests.
Deterministic replay tests.
Upgrade/rollback tests.
Air-gap installation tests عندما يتوفر المنتج.
Localization/RTL tests.
19.2 قواعد التغطية
لا تستخدم Coverage كرقم تجميلي.
Core money, posting, matching, authorization and audit invariants: استهدف branch coverage شديد الارتفاع مع Mutation score موثق.
لا تقل التغطية الإجمالية عن Baseline الحالي.
كل Bug ينتج Regression test.
لا يوجد `skip` أو `xfail` بلا Issue وسبب وتاريخ مراجعة.
Flaky tests تُعزل وتُصلح، لا يعاد تشغيلها حتى تنجح.
Fixtures مالية Synthetic فقط.
Golden datasets لها Version وChecksum.
19.3 Release Gates
ممنوع Stable release إذا:
يوجد Critical/High known vulnerability غير مقبول رسميًا.
Core tests تفشل.
Migration/restore يفشل.
Determinism digest يختلف بلا Migration note.
Docs claims لا تطابق Evidence.
SBOM أو signature أو provenance مفقودة.
UI critical accessibility paths تفشل.
Docker/package installation غير متحقق منها.
Rollback غير مختبر.
---
20) Observability and Reliability
استخدم OpenTelemetry أو معيارًا Vendor-neutral مكافئًا بعد تقييم رسمي.
أضف:
Structured logs.
Metrics.
Traces.
Correlation IDs.
Job spans.
DB latency.
Queue depth.
Candidate counts.
Match rate.
Exception rate.
Data-quality rate.
Memory/CPU.
Export latency.
Audit verification status.
قواعد:
لا تسجل raw financial rows افتراضيًا.
Metrics لا تكشف tenant data.
Health checks منفصلة:
liveness.
readiness.
dependency.
SLOs حسب Edition واستخدام حقيقي.
Error budgets.
Runbooks لكل Alert.
Benchmark hardware profiles.
Graceful degradation.
Backpressure.
Retry with jitter and ceilings.
Circuit breakers للموصلات الخارجية.
Load shedding عند الضرورة.
---
21) UX عالمي
21.1 مسار الفرد أو المتجر الصغير
اختر Template.
ارفع الملفات.
اعرض Preview آمنًا.
اربط الأعمدة بالسحب.
اعرض أخطاء الجودة بوضوح.
شغّل.
اعرض Matched/Unmatched/Ambiguous.
اسمح بالمراجعة.
صدّر تقريرًا مفهومًا.
21.2 مسار المحترف
Mapping Studio.
Rule Studio.
Reconciliation designer.
Exception workbench.
Evidence explorer.
Close workspace.
Version comparison.
Simulation.
Approval workflow.
21.3 مسار المؤسسة أو البنك
Operations control center.
Entity/region hierarchy.
SLA queues.
Risk concentration.
Root cause.
Bulk actions مع صلاحيات.
Real-time job health.
Audit/compliance view.
Data lineage.
Admin/security center.
21.4 معايير التصميم
English and Arabic first-class.
RTL حقيقي.
WCAG latest stable target.
Keyboard navigation.
Screen-reader semantics.
Reduced motion.
High contrast.
Responsive.
Clear empty/loading/error states.
No misleading green dashboards.
Every KPI has definition, source and drill-down.
Destructive actions require clear confirmation and authorization.
Sensitive values masked by role.
---
22) API and SDK
22.1 API
Preserve `/api/v1`.
Additive evolution.
Pydantic strict models.
`extra="forbid"` for mutations.
Structured errors.
Request IDs.
Cursor pagination.
Filtering/sorting with allowlists.
Idempotency keys.
Async jobs.
Bulk imports.
Signed webhooks.
ETags/optimistic concurrency where useful.
Versioned event schemas.
No raw tracebacks.
OpenAPI tests.
Deprecation policy.
22.2 SDKs
بعد استقرار العقود:
Python SDK.
TypeScript SDK.
Connector SDK.
Control Pack SDK.
CLI automation examples.
SDK generation لا يسبق ثبات Schemas.
---
23) Delivery, Packaging and Upgrades
Artifacts:
Python package.
Signed source archive.
Signed container images.
Desktop/local installer فقط بعد تقييم أمني.
Docker Compose for Team.
Helm/Kubernetes only after verified operational need.
Air-gap bundle for Regulated.
Migration tool.
Backup/restore tool.
Verification tool.
كل إصدار يضم:
Changelog.
Migration notes.
Compatibility matrix.
SBOM.
Provenance.
Signatures.
Checksums.
Known limitations.
Upgrade test evidence.
Rollback instructions.
Reproducible demo.
Release channels:
`nightly`
`experimental`
`beta`
`stable`
`lts` لاحقًا
---
24) Documentation and Governance
أنشئ Docs-as-code واضحة:
Product charter.
Architecture.
ADRs.
Data model.
API.
Connector SDK.
Control Pack SDK.
Security.
Threat models.
Operations.
Backup/restore.
DR.
Performance.
Upgrade.
Release.
Contributor guide.
Maintainer guide.
Claim boundary.
Arabic guide.
Banking and industry guides.
Governance:
CODEOWNERS.
Maintainer roles.
Security response team.
Release managers.
RFC process.
ADR process.
Deprecation policy.
Contributor ladder.
Code of conduct.
Transparent roadmap.
Public benchmark methodology.
No fake customers, stars, testimonials or adoption.
---
25) Competitive Intelligence
قارن بصورة أخلاقية مع المنصات العالمية من المصادر العامة والرسمية فقط.
أنشئ:
`docs/strategy/competitive-capability-matrix.md`
قارن على:
Deployment sovereignty.
Determinism.
Evidence lineage.
Matching breadth.
Scale evidence.
Connector ecosystem.
AI governance.
Security.
UX.
Localization.
Extensibility.
Pricing transparency.
Open-source availability.
Banking use cases.
Manufacturing/retail use cases.
Operational support.
لا تنسخ Proprietary code أو واجهات أو نصوص. لا تدّعِ التفوق. حدد:
أين نحن أضعف.
أين يمكن أن نتميز.
ما الدليل المطلوب لإثبات التفوق.
---
26) Product Validation
لا تبنِ عشرات Modules دون مستخدمين.
اعتمد Wedge-first:
Inventory-to-GL + evidence.
Bank/cash statement reconciliation.
Exception workflow.
Control pack authoring.
One banking pilot pack لاحقًا.
لكل Pilot:
Problem statement.
Baseline manual effort.
Input quality.
Run time.
Exceptions found.
False positives.
Time saved.
Review outcome.
User satisfaction.
Renewal/payment signal.
Privacy approval.
لا تستخدم بيانات عميل في المستودع. أنشئ Synthetic/anonymized case studies فقط مع موافقة.
---
27) مراحل التنفيذ وبوابات الخروج
Phase 0 — Truth and Reproducibility
الأهداف:
Baseline كامل.
إزالة Documentation drift.
Claims Evidence Matrix.
Canonical Money/Currency.
Stable lineage IDs.
Determinism/property tests.
Clean quality gates.
Signed release foundation.
Exit Gate:
لا Float في Critical financial paths.
Baseline reproducible.
No contradictory public claims.
Core tests green.
Release evidence generated.
Phase 1 — Platform Foundation
الأهداف:
Module contracts.
Repository protocols.
PostgreSQL adapter and contract CI.
Durable jobs.
Object store abstraction.
API idempotency/pagination.
Central policy/SoD.
OpenTelemetry.
Modern Studio live read-only mode.
Exit Gate:
Team Edition تعمل لعدة مستخدمين.
Backup/restore/migration verified.
Cross-backend behavior equivalent.
Permissions audited.
Phase 2 — Matching and Evidence 2.0
الأهداف:
True group matching.
Partitioning.
Checkpoint/resume.
Performance suite.
Evidence Graph.
Reconciliation-as-Code.
Rule simulation/diff.
Exit Gate:
Reproducible results across benchmark tiers.
Crash/resume verified.
Every decision traceable.
Published benchmark methodology.
Phase 3 — Enterprise Product
الأهداف:
SSO/SCIM adapters.
Multi-entity.
Strong isolation.
Scheduler.
Notifications.
Admin/security center.
Connector SDK.
Mapping/Rule Studios.
Upgrade/rollback automation.
Exit Gate:
3–5 real controlled pilots.
Stable operational runbooks.
Independent security review begun.
No unresolved high-risk architecture gaps.
Phase 4 — Industry Excellence
الأهداف:
Manufacturing pack.
Retail pack.
Professional/individual pack.
Finance close pack.
Marketplace/conformance tests.
Exit Gate:
Each pack has domain expert review.
Golden datasets.
Measured business outcomes.
No generic untested claims.
Phase 5 — Regulated Financial Edition
الأهداف:
Nostro/cash pack.
Payments pack.
Card/ATM pack.
Securities pack.
Air-gap.
HSM/KMS.
WORM evidence.
HA/DR.
Strong privileged access.
Independent penetration and algorithm validation.
Exit Gate:
Pilot with a regulated institution.
DR exercise evidence.
Defined SLO/RPO/RTO.
External security findings resolved or accepted.
Regulatory mappings reviewed by qualified humans.
Phase 6 — Global Ecosystem
الأهداف:
Certified connector/control conformance program.
Partner program.
Public SDKs.
Regional packs.
LTS.
Migration tooling.
Independent benchmarks.
Global support model.
Exit Gate:
Diverse maintainers.
External contributors.
Sustainable releases.
Real adoption and revenue/support capacity.
---
28) أول Backlog إجباري
أنشئ Issues/Tasks بهذه الأولوية:
P0 — Correctness and truth
Baseline reproducibility report.
Claims Evidence Matrix.
Documentation drift correction.
Canonical Money and Currency registry.
Remove financial floats from critical paths.
Stable source lineage identity.
Duplicate-identical-record policy.
Property-based order invariance suite.
Cross-engine deterministic digest.
Golden finance dataset registry.
Risk register normalization.
Maturity labels enforcement tests.
P0 — Security and supply chain
Security Architecture v2.
Threat-model index by module.
Latest-stable ASVS mapping.
SSDF implementation matrix.
SLSA/provenance plan.
Signed release pipeline.
SBOM per artifact.
Secret and dependency policies.
File ingestion abuse tests.
Authorization/SoD property tests.
P1 — Platform
Repository contracts.
PostgreSQL contract test suite.
Durable job state machine.
Checkpoint/resume infrastructure.
Object store abstraction.
Idempotency service.
Cursor pagination contract.
Central policy engine.
OpenTelemetry baseline.
Backup/restore verification matrix.
P1 — Reconciliation
Matching Strategy protocol.
Range-indexed tolerance lookup.
Candidate budget/limits.
True grouped match model.
Netting and fee-aware matching.
FX-aware matching.
Ambiguity representation.
Explanation schema v2.
Benchmark harness.
Performance regression gates.
P2 — Evidence and UX
Evidence Graph schema.
Drill-down API.
Reconciliation-as-Code schema.
Pack lint/test/diff/simulate.
Mapping Studio foundation.
Rule Studio foundation.
Live read-only Studio contract.
Arabic/RTL/a11y regression suite.
ابدأ بالمهام 1–5 فقط بعد Baseline، ولا تفتح عشرين Feature branch في نفس الوقت.
---
29) Definition of Done لكل Task
لا تعتبر Task مكتملة إلا بوجود:
Problem and scope.
Acceptance criteria.
ADR أو Decision note عند الحاجة.
Implementation.
Unit tests.
Integration/contract tests.
Security tests عند الحاجة.
Migration and rollback.
Performance impact.
Docs.
Changelog/release impact.
Evidence command output.
No unrelated changes.
Clean diff.
Review checklist.
---
30) حلقة التنفيذ
لكل Iteration:
اقرأ `STATE.md` و`BACKLOG.yaml`.
اختر أعلى Risk/Value task غير محظورة.
افحص الكود المتأثر وكل Call sites.
اكتب Acceptance tests أولًا عندما يكون ذلك عمليًا.
نفّذ أصغر Vertical Slice مكتملة.
شغّل Targeted tests.
شغّل Full gates المناسبة.
افحص Security/Performance/Compatibility.
حدّث Docs وEvidence وRisk register.
أنشئ Commit واضح.
حدّث `STATE.md`.
انتقل للمهمة التالية فقط إذا Gate نجحت.
لا تستخدم “سنفعل لاحقًا” دون إنشاء Backlog item واضح.
---
31) شكل التقرير بعد كل Iteration
أخرج بهذا الشكل حرفيًا:
```text
CURRENT PHASE
- ...

TASK
- ID:
- Goal:
- Status:

FINDINGS
- ...

DECISIONS
- ...

FILES CHANGED
- path: purpose

TESTS AND EVIDENCE
- command:
- result:
- duration:
- environment:

SECURITY
- threats considered:
- controls:
- residual risk:

FINANCIAL CORRECTNESS
- invariants:
- precision/rounding:
- lineage/determinism:

COMPATIBILITY
- API/CLI/schema impact:
- migration:
- rollback:

KNOWN LIMITATIONS
- ...

NEXT ACTION
- Exact next task and why.
```
ممنوع استخدام عبارات عامة مثل:
“تم تحسين الجودة”
“أصبح Enterprise-ready”
“الاختبارات ممتازة”
من دون أرقام وأوامر ونتائج.
---
32) أمر البداية الآن
ابدأ فورًا بالآتي:
افحص الحالة الحالية للمستودع و`main`.
لا تعدّل الكود قبل توثيق Baseline.
شغّل Quality/Security/UI/Demo gates المتاحة.
أنشئ ملفات `docs/execution/*`.
أنشئ Claims Evidence Matrix وDocumentation Drift report.
حدد أعلى خمسة مخاطر فعلية في الكود الحالي، لا في الخطة النظرية.
أنشئ Backlog P0/P1/P2 مع dependencies.
نفّذ أول Slice بعد Baseline:
توحيد Money/Currency في مسار مالي حرج واحد.
أضف اختبارات precision وinvalid data وbackward compatibility.
لا تنقل كل المشروع دفعة واحدة.
شغّل كل الأدلة.
قدّم تقرير Iteration بالشكل المحدد ثم واصل تلقائيًا لأعلى Task تالية ما دامت آمنة وقابلة للعكس.
الهدف ليس إنتاج أكبر كمية كود. الهدف بناء منصة لا تكذب، لا تفقد البيانات، لا تخفي الأخطاء، ويمكن إثبات كل نتيجة فيها.