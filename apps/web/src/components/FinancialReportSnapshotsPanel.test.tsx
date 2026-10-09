import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { snapshotFixture } from "../financial-reporting-snapshot-fixture";
import { capturedEvidenceSeed } from "../financial-reporting-snapshots";
import FinancialReportSnapshotsPanel from "./FinancialReportSnapshotsPanel";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const mapping = { ...scope, id: "map", name: "Reviewed chart", map_digest: "a".repeat(64), status: "Reviewed" as const, preparer_actor_id: "maker", reviewer_actor_id: "checker", review_digest: "d".repeat(64), accounts: [] };
const session = { tenantId: "synthetic", csrfToken: "synthetic-csrf", expiresAt: "2099-01-01T00:00:00Z" };
afterEach(() => { vi.unstubAllGlobals(); });
describe("captured report workflow", () => {
  it("retains exact command under lost acknowledgement and sends current scope and CSRF", async () => {
    const bodies: string[] = [], scopes: HeadersInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => { bodies.push(String(init?.body)); scopes.push(init?.headers ?? {}); throw new TypeError("network interrupted"); }));
    const lock = vi.fn();
    render(<FinancialReportSnapshotsPanel locale="en" session={session} scope={scope} mapping={mapping} periodId="period" asOfDate="2026-10-31" locked={false} onLock={lock} onError={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Capture statements" }));
    await screen.findByRole("button", { name: "Retry exact capture" });
    fireEvent.click(screen.getByRole("button", { name: "Retry exact capture" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[0]).toBe(bodies[1]); expect(new Headers(scopes[0]).get("X-ReconForge-CSRF")).toBe("synthetic-csrf");
    expect(new Headers(scopes[0]).get("X-ReconForge-Legal-Entity")).toBe("entity"); expect(lock).toHaveBeenLastCalledWith(true);
  });
  it("renders Arabic exact large statement from authorized snapshot response", async () => {
    const snapshot = snapshotFixture();
    const previous = capturedEvidenceSeed;
    const chain = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([previous, 1, "effect", "f".repeat(64)]))))).map(value => value.toString(16).padStart(2, "0")).join("");
    const evidence = { snapshot_id: snapshot.id, report_digest: snapshot.report_digest, evidence_digest: snapshot.evidence_digest, effect_count: snapshot.effect_count, after: 0, previous_digest: previous, items: [{ ordinal: 1, effect_id: "effect", validation_digest: "f".repeat(64), previous_digest: previous, chain_digest: chain, effect: { ...scope, id: "effect", entry_id: "entry", validation_digest: "f".repeat(64), snapshot: { entry: { posting_date: "2026-10-01" }, lines: [{ line_number: 1, account_id: "cash", debit_minor: "100", credit_minor: "0" }, { line_number: 2, account_id: "income", debit_minor: "0", credit_minor: "100" }] } } }], next_after: 1 };
    const fetch = vi.fn(async (url: string) => new Response(JSON.stringify({ api_contract_version: "financial-reporting-api-v1", ...(url.includes("/evidence") ? { evidence } : { snapshot }) }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    render(<FinancialReportSnapshotsPanel locale="ar" session={session} scope={scope} mapping={mapping} periodId="period" asOfDate="2026-10-31" locked={false} onLock={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "حفظ القوائم" }));
    expect(await screen.findByRole("heading", { name: "الأصول" })).toBeInTheDocument();
    expect(screen.getByText(/الآثار المالية: 1001/)).toBeInTheDocument();
  });
});
