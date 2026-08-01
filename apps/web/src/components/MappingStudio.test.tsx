import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MessageKey } from "../i18n";
import { MappingStudio } from "./MappingStudio";

const translate = (key: MessageKey) => key;

describe("MappingStudio", () => {
  it("exposes a labelled keyboard-native mapping flow and visible quality errors", () => {
    render(<MappingStudio translate={translate} />);

    expect(screen.getByRole("heading", { name: "mappingTitle" })).toBeInTheDocument();
    expect(screen.getByLabelText("chooseCsv")).toHaveAttribute("type", "file");
    const mappings = screen.getAllByRole("combobox");
    expect(mappings).toHaveLength(4);
    mappings.forEach((select) => expect(select).toBeEnabled());

    fireEvent.change(mappings[0], { target: { value: "txn_id" } });
    fireEvent.change(mappings[1], { target: { value: "amount_text" } });
    fireEvent.change(mappings[2], { target: { value: "currency_code" } });
    fireEvent.change(mappings[3], { target: { value: "posting_date" } });

    expect(screen.getByText("2 issues")).toBeInTheDocument();
    expect(screen.getByText(/Row 2: amount — missing value/)).toBeInTheDocument();
    expect(screen.getByText(/Row 3: amount — malformed amount/)).toBeInTheDocument();
    expect(screen.getAllByText("missingValue")).toHaveLength(1);
  });

  it("rejects oversized local files before reading their contents", () => {
    render(<MappingStudio translate={translate} />);
    const file = new File([new Uint8Array(256 * 1024 + 1)], "oversized.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("chooseCsv"), { target: { files: [file] } });
    expect(screen.getByRole("alert")).toHaveTextContent("256 KiB");
  });

  it("rejects a non-tabular upload even when selected programmatically", () => {
    render(<MappingStudio translate={translate} />);
    const file = new File(["{}"], "payload.json", { type: "application/json" });
    fireEvent.change(screen.getByLabelText("chooseCsv"), { target: { files: [file] } });
    expect(screen.getByRole("alert")).toHaveTextContent("unsupportedMappingFile");
  });
});
