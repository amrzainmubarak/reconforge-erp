import { CheckCircle2, Diff, FlaskConical, LockKeyhole, RotateCcw, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import type { MessageKey } from "../i18n";
import { approveTestedRule, diffRuleSpecs, runRuleTests, type ApprovalResult, type RuleTestResult } from "../ruleStudio";

const baseline = JSON.stringify({
  schema_version: 1,
  reconciliation_id: "cash_daily",
  strategy: "exact",
  amount_tolerance: "0",
  test_cases: [
    { id: "equal_amounts", left_amount: "100.00", right_amount: "100.00", expected_match: true },
    { id: "different_amounts", left_amount: "100.00", right_amount: "100.01", expected_match: false },
  ],
}, null, 2);

export function RuleStudio({ translate }: { translate: (key: MessageKey) => string }) {
  const [version, setVersion] = useState(1);
  const [draft, setDraft] = useState(baseline);
  const [testResult, setTestResult] = useState<RuleTestResult | null>(null);
  const [approval, setApproval] = useState<ApprovalResult | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);
  const changes = useMemo(() => {
    try { return diffRuleSpecs(baseline, draft); } catch { return []; }
  }, [draft]);
  const status = approval ? "approved" : testResult?.passed ? "tested" : "draft";

  const editDraft = (value: string) => {
    setDraft(value);
    setTestResult(null);
    setApproval(null);
    setError("");
  };

  return <main id="main-content" className="workbench-content rule-studio">
    <section className="workbench-hero workbench-hero--rules" aria-labelledby="rule-title">
      <div><p className="eyebrow">{translate("ruleStudio")}</p><h1 id="rule-title">{translate("ruleTitle")}</h1><p>{translate("ruleIntro")}</p></div>
      <div className="contract-badge"><LockKeyhole size={20} aria-hidden="true" /><span>{translate("rulePublication")}<strong>{translate("disabled")}</strong></span></div>
    </section>

    <section className="rule-status" aria-label={translate("ruleWorkflow")}>
      {(["draft", "tested", "approved"] as const).map((step) => <div className={`rule-step ${status === step ? "rule-step--active" : ""}`} key={step}><span>{step === "draft" ? version : step === "tested" ? testResult?.passedCount ?? 0 : approval ? "✓" : "—"}</span><strong>{translate(step)}</strong></div>)}
    </section>

    <div className="rule-layout">
      <section className="panel rule-editor" aria-labelledby="editor-title">
        <div className="rule-panel-heading"><div><h2 id="editor-title">{translate("ruleDraft")}</h2><p>v{version} · {translate("author")}: preparer</p></div>{approval ? <button type="button" className="secondary-button" onClick={() => { setVersion((value) => value + 1); setApproval(null); setTestResult(null); setReviewer(""); setReason(""); }}><RotateCcw size={15} aria-hidden="true" />{translate("newVersion")}</button> : null}</div>
        <label className="sr-only" htmlFor="rule-json">{translate("ruleJson")}</label>
        <textarea id="rule-json" spellCheck={false} value={draft} onChange={(event) => editDraft(event.target.value)} aria-describedby="rule-editor-boundary" />
        <p id="rule-editor-boundary" className="rule-boundary">{translate("ruleBoundary")}</p>
      </section>

      <aside className="rule-side">
        <section className="panel" aria-labelledby="diff-title"><div className="rule-panel-heading"><h2 id="diff-title"><Diff size={17} aria-hidden="true" />{translate("ruleDiff")}</h2><strong>{changes.length}</strong></div>{changes.length ? <ul className="rule-change-list">{changes.slice(0, 20).map((path) => <li key={path}><code>{path}</code></li>)}</ul> : <p className="rule-empty">{translate("noRuleChanges")}</p>}</section>
        <section className="panel" aria-labelledby="test-title"><div className="rule-panel-heading"><h2 id="test-title"><FlaskConical size={17} aria-hidden="true" />{translate("ruleTests")}</h2>{testResult ? <strong className={testResult.passed ? "rule-pass" : "rule-fail"}>{testResult.passedCount}/{testResult.total}</strong> : null}</div><button className="primary-button rule-action" type="button" disabled={testing || Boolean(approval)} onClick={() => { setTesting(true); setError(""); void runRuleTests(draft).then((result) => setTestResult(result)).catch((caught: unknown) => { setTestResult(null); setError(caught instanceof Error ? caught.message : translate("ruleTestError")); }).finally(() => setTesting(false)); }}><FlaskConical size={16} aria-hidden="true" />{testing ? translate("testing") : translate("runTests")}</button>{testResult?.failures.length ? <p className="mapping-error" role="alert">{testResult.failures.join(", ")}</p> : null}</section>
        <section className="panel" aria-labelledby="approval-title"><h2 id="approval-title">{translate("humanApproval")}</h2><label>{translate("reviewer")}<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} disabled={Boolean(approval)} /></label><label>{translate("approvalReason")}<textarea value={reason} onChange={(event) => setReason(event.target.value)} disabled={Boolean(approval)} /></label><button className="primary-button rule-action" type="button" disabled={Boolean(approval)} onClick={() => { try { if (!testResult) throw new Error("The current rule draft must pass its tests before approval."); setApproval(approveTestedRule({ version, author: "preparer", reviewer, reason, currentDigest: testResult.digest, testResult })); setError(""); } catch (caught) { setError(caught instanceof Error ? caught.message : translate("ruleApprovalError")); } }}><CheckCircle2 size={16} aria-hidden="true" />{translate("approveDraft")}</button>{approval ? <p className="rule-approved" role="status"><CheckCircle2 size={16} aria-hidden="true" />{translate("approvedBy")} {approval.reviewer}</p> : null}</section>
      </aside>
    </div>
    {error ? <p className="mapping-error rule-global-error" role="alert"><ShieldAlert size={16} aria-hidden="true" />{error}</p> : null}
  </main>;
}
