import type { InboxTopic } from "./notification-inbox-data";
import type { Locale } from "./types";

const en = {
  title: "Notification inbox", description: "Operational notices for your account and authorized workspaces.",
  tenant: "Tenant", username: "Username", password: "Password", signIn: "Sign in", signOut: "Sign out",
  workspace: "Workspace", chooseWorkspace: "Choose a workspace", noWorkspaces: "No canonical workspaces are available to this account.",
  refresh: "Refresh inbox", unreadOnly: "Unread only", loading: "Loading notifications…", empty: "No notifications in this view.",
  unread: "Unread", read: "Read", markRead: "Mark as read", previous: "Previous page", next: "Next page",
  denied: "Your account does not have access to the notification inbox.", unavailable: "The notification inbox is unavailable. Refresh to retry.",
  signedIn: "Signed in as", scopeHint: "References identify operational records. Open the authorized business workspace to review the underlying record.",
  digest: "Publication digest", createdAt: "Published", readAt: "Read acknowledgement", evidence: "Notification evidence", total: "Notifications", resource: "Reference",
  "workflow.review_required": "Review required", "job.failed": "Job failed", "control.exception_opened": "Control exception opened", "evidence.available": "Evidence available",
};
export type InboxMessage = keyof typeof en;
const ar: Record<InboxMessage, string> = {
  title: "صندوق الإشعارات", description: "إشعارات تشغيلية لحسابك ومساحات العمل المصرح بها.",
  tenant: "المؤسسة", username: "اسم المستخدم", password: "كلمة المرور", signIn: "تسجيل الدخول", signOut: "تسجيل الخروج",
  workspace: "مساحة العمل", chooseWorkspace: "اختر مساحة العمل", noWorkspaces: "لا توجد مساحات عمل مسجلة ومتاحة لهذا الحساب.",
  refresh: "تحديث الإشعارات", unreadOnly: "غير المقروءة فقط", loading: "جار تحميل الإشعارات…", empty: "لا توجد إشعارات في هذا العرض.",
  unread: "غير مقروء", read: "مقروء", markRead: "تحديد كمقروء", previous: "الصفحة السابقة", next: "الصفحة التالية",
  denied: "حسابك غير مصرح له بالوصول إلى صندوق الإشعارات.", unavailable: "صندوق الإشعارات غير متاح. حدّث العرض لإعادة المحاولة.",
  signedIn: "تم الدخول باسم", scopeHint: "المراجع تحدد سجلات تشغيلية. افتح مساحة العمل المصرح بها لمراجعة السجل الأصلي.",
  digest: "بصمة النشر", createdAt: "وقت النشر", readAt: "إقرار القراءة", evidence: "دليل الإشعار", total: "الإشعارات", resource: "المرجع",
  "workflow.review_required": "مراجعة مطلوبة", "job.failed": "فشلت المهمة", "control.exception_opened": "تم فتح استثناء رقابي", "evidence.available": "الأدلة متاحة",
};
export function inboxTranslate(locale: Locale, key: InboxMessage | InboxTopic): string { return (locale === "ar" ? ar : en)[key]; }
