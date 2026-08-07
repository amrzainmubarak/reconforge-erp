import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { translate } from "../i18n";
import { RetailSettlementStudio } from "./RetailSettlementStudio";

const contract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_RETAIL_SETTLEMENT_UI_ONLY",
  generated_at: "2026-08-04T00:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  algorithm_version: "retail-pos-settlement-v1",
  decision_digest: "7a651eee16c1e376b9e66edd670f0d0aa2ae80c6f29f2f1d82ab293e14b123ac",
  artifact_digest: "076b83f8b20088e10161c268f22d995229a7c04edc3f2ce670547378d4eb5c35",
  tolerance: "0.01",
  currency: "USD",
  summary: { total: 2, matched: 1, exceptions: 1, unmatched: 0, ambiguous: 0 },
  decisions: [
    { batch_id: "POS-100", store_id: "STORE-01", status: "matched", settlement_ids: ["SET-100"], expected_card_net: "93.00", settlement_net: "93.00", net_variance: "0.00", currency: "USD", reason_code: "POS_SETTLEMENT_RECONCILED" },
    { batch_id: "POS-101", store_id: "STORE-01", status: "exception", settlement_ids: ["SET-101"], expected_card_net: "49.00", settlement_net: "48.50", net_variance: "-0.50", currency: "USD", reason_code: "POS_SETTLEMENT_VARIANCE_ABOVE_TOLERANCE" },
  ],
  notices: [],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => contract }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RetailSettlementStudio", () => {
  test("renders exact decision values and filters without arithmetic", async () => {
    render(<RetailSettlementStudio translate={(key) => translate("en", key)} />);

    expect(await screen.findByRole("heading", { name: "Retail settlement control center" })).toBeInTheDocument();
    expect(screen.getByText("POS_SETTLEMENT_VARIANCE_ABOVE_TOLERANCE")).toBeInTheDocument();
    expect(screen.getByText("-0.50")).toBeInTheDocument();
    expect(screen.getByText("7a651eee16c1e376b9e66edd670f0d0aa2ae80c6f29f2f1d82ab293e14b123ac")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Settlement status" }), { target: { value: "matched" } });
    expect(screen.getByText("POS-100")).toBeInTheDocument();
    expect(screen.queryByText("POS-101")).not.toBeInTheDocument();
  });

  test("rejects an expanded or malformed projection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...contract, artifact_digest: "unsafe" }) }));
    render(<RetailSettlementStudio translate={(key) => translate("en", key)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  });

  test("supports Arabic labels in the same read-only view", async () => {
    render(<RetailSettlementStudio translate={(key) => translate("ar", key)} />);
    expect(await screen.findByRole("heading", { name: "مركز رقابة تسويات التجزئة" })).toBeInTheDocument();
    expect(screen.getByText("دليل الإعادة")).toBeInTheDocument();
  });
});
