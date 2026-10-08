import { afterEach, expect, test, vi } from "vitest";
import { budgetInputMinor, budgetMoney, executeBudgetCommand, loadBudgetDetail, loadBudgetPage, parseBudgetDetail, parseBudgetEnvelope, prepareBudgetCommand } from "./budget-control-data";
import { budgetDetail, budgetEvidence, budgetRecord, budgetResponse, budgetScope, budgetSession } from "./budget-control-test-fixtures";

afterEach(() => vi.unstubAllGlobals());
test("exact retained policy renders large amounts and accepts Arabic precision without floating conversion", () => {
  const record = { ...budgetRecord, currency_code: "KWD", limit_minor: "9000000000000000000", available_minor: "9000000000000000000", monetary_policy: { ...budgetRecord.monetary_policy, precision: 3 } };
  expect(parseBudgetEnvelope(record, budgetScope).limit_minor).toBe("9000000000000000000");
  expect(budgetMoney(record.limit_minor, record.monetary_policy, "KWD", "en")).toBe("9,000,000,000,000,000.000 KWD");
  expect(budgetInputMinor("١٣٫٧٦٥", 3)).toBe("13765");
  expect(budgetInputMinor("13", 0)).toBe("13");
  for (const value of ["1.0001", "1e3", "-1", "NaN", "0", "01", "9000000000000000.001"]) expect(() => budgetInputMinor(value, 3)).toThrow();
});
test("closed projection refuses scope leak, inconsistent balances, numeric money, unsafe versions and self approval", () => {
  for (const mutation of [{ workspace_id: "foreign" }, { reserved_minor: "1" }, { limit_minor: 10000 }, { row_version: 9007199254740993 }, { internal_secret: "untrusted" }, { approved_by: "maker-a" }, { monetary_policy: undefined }]) expect(() => parseBudgetEnvelope({ ...budgetRecord, ...mutation }, budgetScope)).toThrow("budget_contract_invalid");
});
test("history refuses a foreign budget, reordered events and unbounded history", () => {
  const event = { id: "EV-1", budget_id: "BUD-A", commitment_id: "COM-1", operation: "Reserve", amount_minor: "100", remaining_minor: "100", operation_date: "2026-10-08", source_reference: "PO-1", reason: "Synthetic", actor_id: "maker-a", created_at: "2026-10-08T01:02:00Z", budget_version: 4, audit_event_id: "AUD-E", outbox_event_id: "OUT-E", request_digest: "3".repeat(64) };
  const current = { ...budgetDetail, row_version: 4, events: [event] };
  expect(parseBudgetDetail(current, budgetScope, "BUD-A").events[0].id).toBe("EV-1");
  expect(() => parseBudgetDetail({ ...current, events: [{ ...event, budget_id: "BUD-B" }] }, budgetScope, "BUD-A")).toThrow();
  expect(() => parseBudgetDetail({ ...current, events: [event, { ...event, id: "EV-2" }] }, budgetScope, "BUD-A")).toThrow();
});
test("transport retries reuse exact frozen command, expected version, scope and CSRF proof", async () => {
  const command = prepareBudgetCommand(budgetScope, "submit", { expected_version: 1, reason: "Review" }, "BUD-A");
  const response = { ...budgetRecord, status: "Submitted", row_version: 2, approved_by: null, evidence: budgetEvidence };
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("lost response")).mockResolvedValue(budgetResponse(response)); vi.stubGlobal("fetch", fetcher);
  await expect(executeBudgetCommand(budgetSession, budgetScope, command)).rejects.toThrow("lost response");
  expect((await executeBudgetCommand(budgetSession, budgetScope, command)).evidence.audit_event_id).toBe("AUD-A");
  expect(Object.isFrozen(command.body)).toBe(true);
  expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", headers: { "X-ReconForge-Tenant": "tenant-a", "X-ReconForge-Workspace": "work-a", "X-ReconForge-Organization": "org-a", "X-ReconForge-Legal-Entity": "entity-a", "X-ReconForge-CSRF": "synthetic-csrf" } });
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({ ...budgetScope, expected_version: 1, command_id: command.body.command_id });
});
test("reads carry complete hierarchy, enforce pagination and command scope cannot change on retry", async () => {
  const fetcher = vi.fn(async (_path: RequestInfo | URL, _options?: RequestInit) => budgetResponse({ envelopes: [budgetRecord], pagination: { limit: 25, offset: 0, has_more: false } })); vi.stubGlobal("fetch", fetcher);
  expect((await loadBudgetPage(budgetSession, budgetScope)).envelopes).toHaveLength(1);
  expect(fetcher.mock.calls[0][0]).toContain("organization_id=org-a");
  expect(fetcher.mock.calls[0][1]?.headers).toMatchObject({ "X-ReconForge-Legal-Entity": "entity-a" });
  const command = prepareBudgetCommand(budgetScope, "submit", { expected_version: 1, reason: "Review" }, "BUD-A");
  await expect(executeBudgetCommand(budgetSession, { ...budgetScope, legal_entity_id: "foreign" }, command)).rejects.toThrow("budget_contract_invalid");
  expect(fetcher).toHaveBeenCalledTimes(1);
});
test("invalid financial/date request is refused before transport and HTTP errors preserve safe code", async () => {
  const fetcher = vi.fn(async () => budgetResponse({ error: { code: "budget_scope_denied", message: "untrusted detail" } }, 403)); vi.stubGlobal("fetch", fetcher);
  expect(() => prepareBudgetCommand(budgetScope, "Reserve", { expected_version: 3, reason: "Review", amount_minor: "1", operation_date: "2026-02-30", source_reference: "PO-1" }, "BUD-A")).toThrow();
  expect(() => prepareBudgetCommand(budgetScope, "create", { budget_code: "bad code", name: "Synthetic", currency_code: "EGP", period_id: "P", limit_minor: "1" })).toThrow();
  expect(fetcher).not.toHaveBeenCalled();
  await expect(loadBudgetDetail(budgetSession, budgetScope, "BUD-A")).rejects.toMatchObject({ status: 403, code: "budget_scope_denied" });
});
