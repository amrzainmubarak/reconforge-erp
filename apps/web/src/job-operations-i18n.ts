import type { Locale } from "./types";
const en = {
  title: "Durable job operations", description: "Inspect execution evidence, cancel unleased work, and requeue recoverable jobs.",
  tenant: "Tenant", username: "Username", password: "Password", signIn: "Sign in", signOut: "Sign out", workspace: "Workspace ID", organization: "Organization ID", entity: "Entity ID",
  chooseScope: "Load execution lane", status: "Status", all: "All statuses", refresh: "Refresh", previous: "Previous", next: "Next", empty: "No jobs in this execution lane.", loading: "Loading jobs…", details: "Inspect job",
  cancel: "Cancel job", requeue: "Requeue job", progress: "Completed units", retries: "Retries", version: "Version", evidence: "Retained transitions", actor: "Actor", reason: "Reason code",
  truncated: "Showing the latest 200 transitions. Earlier evidence remains in storage.", denied: "This job lane or action is not authorized.", conflict: "The job changed or is actively leased. Refresh and review its current state.", unavailable: "Job operations are unavailable. Refresh to reconcile the current state.",
  invalid: "The job response could not be verified.", stepUp: "Reauthenticate before operator actions", continue: "Reauthenticate", signedIn: "Signed in as", unknown: "The command outcome is unknown. Refresh and inspect the retained transition before acting again.",
  scopeHint: "Server scope must match your grants. Running jobs retain their worker lease; cancellation requests for active work are outside this operator surface.",
};
type Message = keyof typeof en;
const ar: Record<Message, string> = {
  title: "إدارة المهام الدائمة", description: "فحص أدلة التنفيذ وإلغاء المهام غير المحجوزة وإعادة وضع المهام القابلة للاستكمال في قائمة التنفيذ.",
  tenant: "المستأجر", username: "اسم المستخدم", password: "كلمة المرور", signIn: "تسجيل الدخول", signOut: "تسجيل الخروج", workspace: "معرّف مساحة العمل", organization: "معرّف المؤسسة", entity: "معرّف الكيان",
  chooseScope: "تحميل نطاق التنفيذ", status: "الحالة", all: "كل الحالات", refresh: "تحديث", previous: "السابق", next: "التالي", empty: "لا توجد مهام في نطاق التنفيذ.", loading: "جارٍ تحميل المهام…", details: "فحص المهمة",
  cancel: "إلغاء المهمة", requeue: "إعادة المهمة للتنفيذ", progress: "الوحدات المكتملة", retries: "المحاولات", version: "الإصدار", evidence: "سجل انتقالات الحالة", actor: "المنفّذ", reason: "رمز السبب",
  truncated: "يُعرض آخر 200 انتقال. الأدلة الأقدم محفوظة في قاعدة البيانات.", denied: "ليس لديك صلاحية على نطاق المهمة أو الإجراء.", conflict: "تغيّرت المهمة أو ما زالت محجوزة لعامل. حدّث وافحص الحالة الحالية.", unavailable: "إدارة المهام غير متاحة. حدّث للتحقق من الحالة الحالية.",
  invalid: "تعذّر التحقق من استجابة المهمة.", stepUp: "أعد المصادقة قبل إجراءات إدارة المهام", continue: "إعادة المصادقة", signedIn: "تم تسجيل الدخول باسم", unknown: "نتيجة الإجراء غير معروفة. حدّث وافحص سجل الانتقالات قبل أي إجراء آخر.",
  scopeHint: "يجب أن يطابق نطاق الخادم الصلاحيات الممنوحة. تحتفظ المهام الجارية بحجز العامل؛ طلبات إلغاء العمل الجاري خارج هذا المسار.",
};
export function jobTranslate(locale: Locale, key: Message): string { return (locale === "ar" ? ar : en)[key]; }
export type JobMessage = Message;
