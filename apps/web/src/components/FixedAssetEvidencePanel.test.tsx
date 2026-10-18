import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../fixed-asset-evidence-fixture.json";
import { parseAssetPlan } from "../fixed-assets-data";
import FixedAssetEvidencePanel from "./FixedAssetEvidencePanel";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const session = { tenantId: "synthetic", csrfToken: "synthetic-csrf", expiresAt: "2099-01-01T00:00:00Z" };
afterEach(() => vi.unstubAllGlobals());
describe("source to native GL drill-down", () => {
  it("verifies actual proof and renders exact large Arabic amounts and human provenance", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ evidence: fixture }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    render(<FixedAssetEvidencePanel locale="ar" session={session} scope={scope} plan={parseAssetPlan(fixture.plan, scope)} locked={false} isCurrent={() => true} onError={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "التحقق من أدلة المصدر والقيد" }));
    await screen.findByRole("status");
    expect(screen.getAllByText("poster")).toHaveLength(2);
    expect(screen.getByText("audit-3")).toBeInTheDocument();
    expect(String(fetch.mock.calls[0])).toContain("/fixed-assets/plans/plan/evidence");
    expect(screen.getAllByText(/٩٠٬٠٧١٬٩٩٢٬٥٤٧٬٤٠٩٫٩٣/)).toHaveLength(2);
  });
  it("fails closed on a forged response and renders no verified status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ evidence: { ...fixture, canonical_asset_json: "{}" } }), { status: 200 })));
    const error = vi.fn();
    render(<FixedAssetEvidencePanel locale="en" session={session} scope={scope} plan={parseAssetPlan(fixture.plan, scope)} locked={false} isCurrent={() => true} onError={error} />);
    fireEvent.click(screen.getByRole("button", { name: "Verify source and ledger evidence" }));
    await waitFor(() => expect(error).toHaveBeenCalledOnce());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
