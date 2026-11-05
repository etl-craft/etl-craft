import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "@/components/confirm-dialog";

beforeAll(() => {
  // jsdom has no modal <dialog>; the platform behaviour is covered by the browser suite.
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
  };
});

function show(type: string, onConfirm = vi.fn()) {
  render(
    <ConfirmDialog
      open
      title="Recover run #7"
      action="Recover run"
      effect="Reopens OPS run #7."
      projectCode="sales"
      env={{ type, name: null }}
      error={null}
      busy={false}
      onConfirm={onConfirm}
      onClose={() => undefined}
    />,
  );
  return onConfirm;
}

describe("ConfirmDialog", () => {
  it("names the project and environment and needs a reason", () => {
    const confirm = show("UAT");
    expect(screen.getByText("sales")).toBeInTheDocument();
    expect(screen.getByText("UAT")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Recover run" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "  retry after fix " } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(confirm).toHaveBeenCalledWith("retry after fix");
  });

  it("in production also needs the project code typed exactly", () => {
    const confirm = show("PROD");
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "urgent" } });
    const submit = screen.getByRole("button", { name: "Recover run" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "sale" } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "sales" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(confirm).toHaveBeenCalledWith("urgent");
    expect(screen.getByText("PRODUCTION")).toBeInTheDocument();
  });

  it("shows the server's refusal verbatim", () => {
    render(
      <ConfirmDialog
        open
        title="t"
        action="Go"
        effect="e"
        projectCode="p"
        env={{ type: "DEV", name: null }}
        error="run_id=7: RECOVER needs ended ownership"
        busy={false}
        onConfirm={() => undefined}
        onClose={() => undefined}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("run_id=7: RECOVER needs ended ownership");
  });
});
