import { arTranslate } from "../receivables-i18n";
import { hasCapturedPolicy, type ArMoneyRecord } from "../receivables-money";
import type { Locale } from "../types";

export function ReceivablesPolicy({ record, locale, id }: { record: ArMoneyRecord; locale: Locale; id?: string }) {
  const t = (key: Parameters<typeof arTranslate>[1]) => arTranslate(locale, key);
  if (!hasCapturedPolicy(record)) return <p id={id} className="ar-hint" role="status">{t("policyUnverified")}</p>;
  const policy = record.monetary_policy!;
  return <div className="ar-hint"><p id={id}>{t("policyAmountHint")} <bdi>{record.currency_code}</bdi> · {t("policyPrecision")}: <bdi>{policy.precision}</bdi>. {t("policyNoRounding")}</p>
    <details className="ar-evidence"><summary>{t("policyEvidence")}</summary><dl className="ar-record">
      <div><dt>{t("policySource")}</dt><dd><bdi>{policy.source || "—"}</bdi></dd></div>
      <div><dt>{t("version")}</dt><dd><bdi>{policy.registry_version}</bdi></dd></div>
      <div><dt>{t("policyRounding")}</dt><dd><bdi>{policy.rounding_policy}</bdi></dd></div>
      <div><dt>{t("policyDigest")}</dt><dd><bdi>{policy.registry_digest}</bdi></dd></div>
    </dl></details>
  </div>;
}
