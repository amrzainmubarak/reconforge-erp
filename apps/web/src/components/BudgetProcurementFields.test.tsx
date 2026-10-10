import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ProcurementScope } from "../procurement-data";
import { BudgetProcurementFields } from "./BudgetProcurementFields";

afterEach(() => vi.unstubAllGlobals());
it("loads and selects an actual approved envelope using a procurement scope with additional display fields", async () => {
  const scope: ProcurementScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENT", organization_name: "Organization", entity_name: "Entity", currency_code: "USD" };
  const envelope = { id: "budget", ...scope, period_id: "period", budget_code: "PURCHASE", name: "Purchase appropriation", status: "Approved", created_by: "maker", submitted_by: "maker", approved_by: "checker", reason: "Review", created_at: "2026-10-10", updated_at: "2026-10-10", row_version: 3, limit_minor: "20000", reserved_minor: "0", consumed_minor: "0", available_minor: "20000", monetary_policy: { precision: 2, rounding_policy: "ROUND_HALF_UP", registry_version: "v1", registry_digest: "a".repeat(64) } };
  const { organization_code: _o, entity_code: _e, organization_name: _on, entity_name: _en, ...wire } = envelope;
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ envelopes: [wire], pagination: { limit: 25, offset: 0, has_more: false } }))));
  const onChange = vi.fn(), onError = vi.fn();
  render(<BudgetProcurementFields session={{ tenantId: "tenant", csrfToken: "csrf", expiresAt: "2026-10-10T12:00:00Z" }} scope={scope} periodId="period" locked={false} locale="en" value={null} onChange={onChange} onError={onError} />);
  await screen.findByRole("option", { name: "PURCHASE · 20000 USD · v3" });
  fireEvent.change(screen.getByRole("combobox", { name: "Appropriation" }), { target: { value: "budget" } });
  await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: "budget", row_version: 3 })));
  expect(onError).not.toHaveBeenCalled();
});
