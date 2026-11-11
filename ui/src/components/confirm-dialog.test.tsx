import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

function show(type: string, onConfirm = vi.fn(), governance = "STRICT") {
  render(
    <ConfirmDialog
      open
      governance={governance}
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

it("matches STRICT and RELAXED governance independently of environment", () => {
  for (const [type, governance] of [["DEV", "RELAXED"], ["DEV", "STRICT"], ["PROD", "STRICT"]]) {
    const confirm = vi.fn();
    render(<ConfirmDialog open governance={governance} title="Run now" action="Run" effect="Starts this pipeline." projectCode="sales" env={{ type: type!, name: null }} error={null} busy={false} onConfirm={confirm} onClose={() => undefined} />);
    const reason = screen.getByLabelText(/Reason/);
    const submit = screen.getByRole("button", { name: "Run" });
    if (type === "PROD") fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "sales" } });
    if (governance === "RELAXED") {
      expect(reason).not.toBeRequired();
      expect(submit).toBeEnabled();
      fireEvent.click(submit);
      expect(confirm).toHaveBeenCalledWith("");
    } else {
      expect(reason).toBeRequired();
      expect(submit).toBeDisabled();
      fireEvent.change(reason, { target: { value: "run the approved data load" } });
      expect(submit).toBeEnabled();
    }
    cleanup();
  }
});
