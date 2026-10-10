import type { Locale } from "./types";

const en = {
  title: "Foreign receivables, historical FX and tax", intro: "Recognize a foreign service invoice, retain its original tax policies and settle partial receipts into the functional ledger with exact realized FX.",
  boundary: "Three independent humans approve each effect. Tax fractions and rates are retained manual observations; review their applicability before posting.",
  tenant: "Tenant", username: "Username", password: "Password", signIn: "Sign in", signOut: "Sign out", stepUp: "Confirm current human authority",
  workspace: "Workspace", organization: "Organization", entity: "Legal entity", apply: "Apply authorized scope", refresh: "Refresh retained state", next: "Next invoice page",
  invoices: "Foreign receivable register", empty: "No foreign receivables in this authorized scope.", prepare: "Prepare foreign invoice", settle: "Prepare partial foreign receipt",
  invoice_number: "Invoice number", customer_code: "Foreign customer code", foreign_currency_code: "Foreign currency code", net_minor: "Net invoice amount (foreign minor units)",
  posting_date: "Posting date", due_date: "Due date", period_id: "Open accounting period", journal_code: "Functional journal", country_code: "Tax country code", transaction_class: "Transaction class",
  rate: "Functional units per foreign unit", source: "Rate observation source", effective_at: "Observed UTC timestamp", originalRate: "Original historical spot rate", settlementRate: "Settlement spot rate",
  taxes: "Applied net-exclusive tax components", addTax: "Add tax component", removeTax: "Remove tax component", policy_id: "Tax policy identity", version: "Tax policy version", taxRate: "Tax fraction of original net",
  effective_from: "Tax effective from", effective_to: "Tax effective to", account_code: "Tax liability account", taxSource: "Tax policy source",
  receivable_account_code: "Functional receivable account", revenue_account_code: "Revenue account", cash_account_code: "Functional cash account", gain_account_code: "Realized FX gain account", loss_account_code: "Realized FX loss account",
  reason: "Reason", foreign_minor: "Receipt amount (foreign minor units)", originalGross: "Original foreign gross", functionalGross: "Original functional gross", foreignResidual: "Foreign outstanding", functionalResidual: "Historical functional outstanding",
  tax: "Retained applied tax", plan: "Retained operation", plans: "Operation history", Prepared: "Prepared", Reviewed: "Reviewed", Posted: "Posted", recognize: "Recognition", settlement: "Settlement", review: "Independently review exact plan", post: "Post as third human",
  debit: "Debit", credit: "Credit", nativeAccount: "Native account", historical: "Historical AR released", cash: "Functional cash received", realized: "Realized FX gain / loss", effect: "Native posting effect", receipt: "Native foreign receipt",
  verify: "Verify source, operation and native journal", verified: "Three canonical financial hashes and native human audit references verified in this browser.", download: "Download verified FX evidence",
  actor: "Human actor", audit: "Audit event", outbox: "Outbox event", action: "Evidence action", retry: "Retry the same command", unknown: "The response is unknown. Retain this exact command and retry it before changing the proposal.",
  denied: "Current human permission, amount or scope authority does not allow this operation.", conflict: "The source, residual or accounting period changed. Refresh its retained state.", unavailable: "The FX service or its verified response is unavailable.", invalid: "Enter exact minor units, rates, UTC observations and complete effective tax policy fields.",
};
const ar: Record<keyof typeof en, string> = {
  title: "الذمم الأجنبية والعملات التاريخية والضرائب", intro: "إثبات فاتورة خدمة بعملة أجنبية مع حفظ سياسات الضريبة الأصلية وتسوية المقبوضات الجزئية في الدفتر الوظيفي بفروق صرف محققة دقيقة.",
  boundary: "يعتمد كل أثر ثلاثة مستخدمين مستقلين. نسب الضريبة وأسعار الصرف ملاحظات يدوية محفوظة؛ راجع انطباقها قبل الترحيل.",
  tenant: "المستأجر", username: "اسم المستخدم", password: "كلمة المرور", signIn: "تسجيل الدخول", signOut: "تسجيل الخروج", stepUp: "تأكيد الصلاحية البشرية الحالية",
  workspace: "مساحة العمل", organization: "المؤسسة", entity: "الكيان القانوني", apply: "تطبيق النطاق المصرح", refresh: "تحديث الحالة المحفوظة", next: "صفحة الفواتير التالية",
  invoices: "سجل الذمم الأجنبية", empty: "لا توجد ذمم أجنبية في هذا النطاق المصرح.", prepare: "إعداد فاتورة أجنبية", settle: "إعداد قبض أجنبي جزئي",
  invoice_number: "رقم الفاتورة", customer_code: "رمز العميل الأجنبي", foreign_currency_code: "رمز العملة الأجنبية", net_minor: "صافي الفاتورة بوحدات العملة الأجنبية الصغرى",
  posting_date: "تاريخ القيد", due_date: "تاريخ الاستحقاق", period_id: "الفترة المحاسبية المفتوحة", journal_code: "دفتر اليومية الوظيفي", country_code: "رمز دولة الضريبة", transaction_class: "تصنيف المعاملة",
  rate: "وحدات وظيفية لكل وحدة أجنبية", source: "مصدر ملاحظة سعر الصرف", effective_at: "التوقيت المرصود بتوقيت UTC", originalRate: "سعر الصرف الفوري التاريخي", settlementRate: "سعر الصرف الفوري للتسوية",
  taxes: "مكونات الضريبة المطبقة على الصافي", addTax: "إضافة مكون ضريبي", removeTax: "إزالة مكون ضريبي", policy_id: "معرف السياسة الضريبية", version: "إصدار السياسة الضريبية", taxRate: "نسبة الضريبة من الصافي الأصلي",
  effective_from: "بداية سريان الضريبة", effective_to: "نهاية سريان الضريبة", account_code: "حساب الالتزام الضريبي", taxSource: "مصدر السياسة الضريبية",
  receivable_account_code: "حساب الذمة الوظيفي", revenue_account_code: "حساب الإيراد", cash_account_code: "حساب النقد الوظيفي", gain_account_code: "حساب ربح الصرف المحقق", loss_account_code: "حساب خسارة الصرف المحققة",
  reason: "السبب", foreign_minor: "مبلغ القبض بوحدات العملة الأجنبية الصغرى", originalGross: "الإجمالي الأجنبي الأصلي", functionalGross: "الإجمالي الوظيفي الأصلي", foreignResidual: "الرصيد الأجنبي المستحق", functionalResidual: "الرصيد الوظيفي التاريخي المستحق",
  tax: "الضريبة المطبقة المحفوظة", plan: "العملية المحفوظة", plans: "سجل العمليات", Prepared: "معد", Reviewed: "مراجع", Posted: "مرحل", recognize: "الإثبات", settlement: "التسوية", review: "مراجعة المخطط الدقيق باستقلال", post: "الترحيل كمستخدم ثالث",
  debit: "المدين", credit: "الدائن", nativeAccount: "الحساب الأصلي", historical: "الذمة التاريخية المسواة", cash: "النقد الوظيفي المقبوض", realized: "ربح أو خسارة الصرف المحققة", effect: "أثر القيد الأصلي", receipt: "إيصال القبض الأجنبي الأصلي",
  verify: "التحقق من المصدر والعملية والقيد الأصلي", verified: "تم التحقق داخل المتصفح من ثلاث بصمات مالية معيارية ومراجع التدقيق البشرية الأصلية.", download: "تنزيل أدلة العملة المتحقق منها",
  actor: "المستخدم البشري", audit: "حدث التدقيق", outbox: "حدث صندوق الإرسال", action: "إجراء الدليل", retry: "إعادة المحاولة بنفس الأمر", unknown: "نتيجة الرد غير معلومة. احتفظ بهذا الأمر الدقيق وأعد إرساله قبل تغيير المقترح.",
  denied: "لا تسمح الصلاحية البشرية أو صلاحية المبلغ أو النطاق الحالية بهذه العملية.", conflict: "تغير المصدر أو الرصيد أو الفترة المحاسبية. حدّث الحالة المحفوظة.", unavailable: "خدمة العملات أو ردها المتحقق منه غير متاح.", invalid: "أدخل وحدات صغرى وأسعارًا دقيقة وملاحظات بتوقيت UTC وسياسة ضريبة مكتملة السريان.",
};
export type FxMessage = keyof typeof en;
export const fxTranslate = (locale: Locale, key: FxMessage): string => (locale === "ar" ? ar : en)[key];
