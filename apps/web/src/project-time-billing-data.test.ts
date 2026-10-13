import { expect, it } from "vitest";
import { billingAmount, billingRoot, parseBillingAcknowledgement, parseBillingEvidence, parseBillingPlan, parseBillingPrice } from "./project-time-billing-data";
import { billingEvidenceFixture, billingPlanFixture, billingScope } from "./project-time-billing-test-fixture";
import type { PreparedScopedCommand, ScopedJsonValue } from "./scoped-command";

function command(path: string, body: Record<string, unknown>): PreparedScopedCommand {
  return { path: billingRoot + path, body: { ...body, command_id: "original-nonce" } as Record<string, ScopedJsonValue> & { command_id: string } };
}

it("verifies the actual native invoice and collection SHA snapshots without approximate money", async () => {
  const proof = billingEvidenceFixture();
  expect((await parseBillingPlan(proof.invoice, billingScope, proof.native_effects as unknown[])).amount_minor).toBe("6236");
  for (const collection of proof.collections as unknown[]) expect((await parseBillingPlan(collection, billingScope, proof.native_effects as unknown[])).phase).toBe(2);
  for (const price of proof.prices as Record<string, unknown>[]) expect((await parseBillingPrice({ ...(price.source_json as object), source_digest: price.source_digest, approver_id: price.approver_id, status: "Approved" }, billingScope)).id).toBe(price.id);
});
it.each([0, 1, 3])("verifies phase %s source without fabricating a native posting", async phase => {
  expect((await parseBillingPlan(billingPlanFixture(phase), billingScope)).phase).toBe(phase);
});
it("requires the exact actual native effect rather than trusting a Posted source label", async () => {
  const plan = billingPlanFixture(2), proof = billingEvidenceFixture();
  await expect(parseBillingPlan(plan, billingScope)).rejects.toThrow();
  await expect(parseBillingPlan(plan, billingScope, [...proof.native_effects as unknown[], ...(proof.native_effects as unknown[]).slice(0, 1)])).rejects.toThrow();
  await expect(parseBillingPlan(plan, billingScope, (proof.native_effects as Record<string, unknown>[]).map(row => ({ ...row, posted_actor_id: "maker" })))).rejects.toThrow();
});
it("refuses foreign scope, amounts, original seals, self posting and detached AR", async () => {
  const value = billingPlanFixture(2), proof = billingEvidenceFixture();
  const mutations = [{ ...value, workspace_id: "foreign" }, { ...value, amount_minor: "6237" }, { ...value, plan_digest: "0".repeat(64) },
    { ...value, posted_actor_id: value.preparer_id }, { ...value, validation_digest: "0".repeat(64) }, { ...value, ar_invoice_id: "detached" },
    { ...value, monetary_policy: { ...(value.monetary_policy as object), currency_rounding_policy: "HALF_EVEN" } }, { ...value, amount_minor: 6236 },
    { ...value, calculation: { ...(value.calculation as object), project_minor: { P1: "6236" } } }];
  for (const mutation of mutations) await expect(parseBillingPlan(mutation, billingScope, proof.native_effects as unknown[])).rejects.toThrow();
});
it("formats captured precision and the native cap without Number conversion", () => {
  expect(billingAmount("6236", 2, "en")).toBe("62.36");
  expect(billingAmount("4500000000000000000", 0, "en")).toBe("4,500,000,000,000,000,000");
  expect(billingAmount("1", 8, "en")).toBe("0.00000001");
  expect(() => billingAmount("1.1", 2, "en")).toThrow();
});
it("binds downloaded evidence to selected tenant and every exact source/native effect", async () => {
  const value = billingEvidenceFixture(), tenant = (value.qualified_scope as Record<string, string>).tenant_id;
  expect(await parseBillingEvidence(value, billingScope, tenant)).toBe(value);
  await expect(parseBillingEvidence(value, billingScope, "foreign")).rejects.toThrow();
  await expect(parseBillingEvidence({ ...value, native_effects: [...value.native_effects as unknown[], (value.native_effects as unknown[])[0]] }, billingScope, tenant)).rejects.toThrow();
  await expect(parseBillingEvidence({ ...value, collections: [...value.collections as unknown[], (value.collections as unknown[])[0]] }, billingScope, tenant)).rejects.toThrow();
});
it("binds a phase acknowledgement to the original path, digest, phase and acting human", async () => {
  const original = billingPlanFixture(2), cmd = command(`/plans/${original.id}/post`, { expected_plan_digest: original.plan_digest });
  expect((await parseBillingAcknowledgement(cmd, { plan: original }, billingScope, "poster")).kind).toBe("plan");
  for (const plan of [billingPlanFixture(2, true), billingPlanFixture(1), { ...original, plan_digest: "0".repeat(64) }]) {
    await expect(parseBillingAcknowledgement(cmd, { plan }, billingScope, "poster")).rejects.toThrow();
  }
  await expect(parseBillingAcknowledgement(cmd, { plan: original }, billingScope, "another-poster")).rejects.toThrow();
  await expect(parseBillingAcknowledgement(command(`/plans/${original.id}/post`, { expected_plan_digest: "0".repeat(64) }), { plan: original }, billingScope, "poster")).rejects.toThrow();
  const reviewed = billingPlanFixture(1);
  expect((await parseBillingAcknowledgement(command(`/plans/${reviewed.id}/review`, { expected_plan_digest: reviewed.plan_digest }), { plan: reviewed }, billingScope, "checker")).kind).toBe("plan");
  const cancelled = billingPlanFixture(3);
  expect((await parseBillingAcknowledgement(command(`/plans/${cancelled.id}/cancel`, { expected_plan_digest: cancelled.plan_digest }), { plan: cancelled }, billingScope, "maker")).kind).toBe("plan");
});
it("binds invoice and collection creation acknowledgements to the exact retained request", async () => {
  for (const collection of [false, true]) {
    const plan = billingPlanFixture(0, collection), request = plan.command_request as Record<string, unknown>;
    const path = collection ? `/invoices/${plan.parent_id}/collections` : "/invoices";
    expect((await parseBillingAcknowledgement(command(path, request), { plan }, billingScope, "maker")).kind).toBe("plan");
    for (const changed of [{ ...request, posting_date: "2026-10-06" }, { ...request, ...(collection ? { amount_minor: "5237" } : { customer_code: "ANOTHER" }) }]) {
      await expect(parseBillingAcknowledgement(command(path, changed), { plan }, billingScope, "maker")).rejects.toThrow();
    }
    await expect(parseBillingAcknowledgement(command(path, request), { plan }, billingScope, "another-maker")).rejects.toThrow();
  }
});
it("verifies price acknowledgements against captured customer, rate, original id and approver", async () => {
  const row = (billingEvidenceFixture().prices as Record<string, unknown>[])[0];
  const price = { ...(row.source_json as Record<string, unknown>), source_digest: row.source_digest, approver_id: null, status: "Submitted" };
  const fields = ["customer_code", "project_id", "valid_from", "valid_through", "currency_code", "hourly_price_minor", "reason"];
  const body = Object.fromEntries(fields.map(key => [key, price[key as keyof typeof price]]));
  expect((await parseBillingAcknowledgement(command("/prices", body), { price }, billingScope, "maker")).kind).toBe("price");
  await expect(parseBillingAcknowledgement(command("/prices", { ...body, hourly_price_minor: "3002" }), { price }, billingScope, "maker")).rejects.toThrow();
  const approved = { ...price, approver_id: row.approver_id, status: "Approved" };
  const approval = command(`/prices/${row.id}/approve`, { expected_digest: row.source_digest });
  expect((await parseBillingAcknowledgement(approval, { price: approved }, billingScope, String(row.approver_id))).kind).toBe("price");
  await expect(parseBillingAcknowledgement(approval, { price: approved }, billingScope, "another-approver")).rejects.toThrow();
  await expect(parseBillingAcknowledgement(command(`/prices/PBP-${"0".repeat(32)}/approve`, { expected_digest: row.source_digest }), { price: approved }, billingScope, String(row.approver_id))).rejects.toThrow();
});
