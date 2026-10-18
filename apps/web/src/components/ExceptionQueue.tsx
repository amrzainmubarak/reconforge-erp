import { ExceptionReviewWorkspace } from "./ExceptionReviewWorkspace";

import type { MessageKey } from "../i18n";
import type { Locale } from "../types";

interface ExceptionQueueProps {
  translate: (key: MessageKey) => string;
  locale: Locale;
}

/**
 * Keeps the existing Studio route contract while rendering the governed
 * PostgreSQL-backed review surface. The legacy local synthetic queue remains
 * available only through its explicit fixture path, never as a fallback here.
 */
export function ExceptionQueue({ locale }: ExceptionQueueProps) {
  return <ExceptionReviewWorkspace locale={locale} />;
}
