import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { receiptFixture } from "../inventory-receipt-fixtures";
import { InventoryReceiptPosting } from "./InventoryReceiptPosting";
function Session() { const auth = useBrowserSession(); useEffect(() => { auth.begin({ tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, "maker", 0); }, []); return <InventoryReceiptPosting />; }
afterEach(() => vi.restoreAllMocks());
it("recovers a retained plan, keeps an uncertain review command identical and posts retained digest", async () => {
 const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ receipt: receiptFixture() }), { status: 200 })).mockRejectedValueOnce(new TypeError("lost reply")).mockResolvedValueOnce(new Response(JSON.stringify({ receipt: receiptFixture("Reviewed") }), { status: 200 })).mockResolvedValueOnce(new Response(JSON.stringify({ receipt: receiptFixture("Committed") }), { status: 200 }));
 render(<BrowserSessionProvider><Session /></BrowserSessionProvider>);
 fireEvent.change(screen.getByLabelText("Workspace ID"), { target: { value: "work" } }); fireEvent.change(screen.getByLabelText("Organization ID"), { target: { value: "org" } }); fireEvent.change(screen.getByLabelText("Legal entity ID"), { target: { value: "entity" } }); fireEvent.change(screen.getByLabelText("Plan ID"), { target: { value: "IRP1-PLAN-123" } }); fireEvent.click(screen.getByRole("button", { name: "Recover retained receipt" }));
 await screen.findByText("REC — Prepared"); expect(screen.getAllByText("90071992547409.93").length).toBe(2);
 const reasons = screen.getAllByLabelText("Reason"); fireEvent.change(reasons[reasons.length - 1], { target: { value: "Independent review" } }); fireEvent.click(screen.getByRole("button", { name: "Review exact plan" })); await screen.findByRole("alert"); fireEvent.click(screen.getByRole("button", { name: "Retry identical command" })); await screen.findByText("REC — Reviewed");
 const first = fetcher.mock.calls[1][1], retry = fetcher.mock.calls[2][1]; expect(first?.body).toBe(retry?.body); expect(JSON.parse(first?.body as string).expected_plan_digest).toBe("a".repeat(64)); expect(first?.credentials).toBe("same-origin"); expect(first?.headers).toMatchObject({ "X-ReconForge-CSRF": "csrf" });
 fireEvent.click(screen.getByRole("button", { name: "Commit reviewed stock and GL" })); await screen.findByText("REC — Committed"); expect(JSON.parse(fetcher.mock.calls[3][1]?.body as string).expected_review_digest).toBe("b".repeat(64));
});
it("presents the Arabic flow with RTL and required identity guidance", async () => { render(<BrowserSessionProvider><InventoryReceiptPosting locale="ar" /></BrowserSessionProvider>); expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl"); expect(screen.getByText("سجّل الدخول وأعد التحقق من هويتك في إدارة الهوية قبل الترحيل.")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "تجهيز الاستلام" })).toBeDisabled(); await waitFor(() => expect(screen.getByLabelText("معرّف مساحة العمل")).toBeInTheDocument()); });
