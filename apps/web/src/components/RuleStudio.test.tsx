import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MessageKey } from "../i18n";
import { RuleStudio } from "./RuleStudio";

const translate = (key: MessageKey) => key;

describe("RuleStudio", () => {
  it("binds approval to a passed draft and revokes it on a new version", async () => {
    render(<RuleStudio translate={translate} />);
    expect(screen.queryByText(/publish/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "runTests" }));
    await waitFor(() => expect(screen.getByText("2/2")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("reviewer"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByLabelText("approvalReason"), { target: { value: "Evidence reviewed" } });
    fireEvent.click(screen.getByRole("button", { name: "approveDraft" }));
    expect(screen.getByRole("status")).toHaveTextContent("approvedBy reviewer");
    fireEvent.click(screen.getByRole("button", { name: "newVersion" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(/v2/)).toBeInTheDocument();
  });

  it("fails closed on self-approval and invalid edits clear test evidence", async () => {
    render(<RuleStudio translate={translate} />);
    fireEvent.click(screen.getByRole("button", { name: "runTests" }));
    await waitFor(() => expect(screen.getByText("2/2")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("reviewer"), { target: { value: "PREPARER" } });
    fireEvent.change(screen.getByLabelText("approvalReason"), { target: { value: "Emergency" } });
    fireEvent.click(screen.getByRole("button", { name: "approveDraft" }));
    expect(screen.getByRole("alert")).toHaveTextContent("cannot approve their own");
    fireEvent.change(screen.getByLabelText("ruleJson"), { target: { value: "{}" } });
    expect(screen.queryByText("2/2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "runTests" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("schema_version"));
  });
});
