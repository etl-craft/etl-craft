import { render, screen } from "@testing-library/react";
import { isFailure, StatusBadge, statusMeta } from "@/components/status";

describe("status", () => {
  it("names every status the server sends in words, never its raw code", () => {
    for (const status of ["CANCELLED", "TIMED_OUT", "CLAIMED", "HANDED_OFF", "CANCEL_REQUESTED", "MET", "BREACHED", "LOADED", "REFUSED", "UNCHANGED"]) {
      expect(statusMeta(status).label).not.toMatch(/_|^[A-Z]+$/);
    }
    render(<StatusBadge status="TIMED_OUT" />);
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("keeps red for failures, amber for retries and warnings, and slate for stops", () => {
    expect(statusMeta("TIMED_OUT").tone).toBe("bad");
    expect(statusMeta("REFUSED").tone).toBe("bad");
    expect(statusMeta("LOST").tone).toBe("warn");
    expect(statusMeta("BREACHED").tone).toBe("warn");
    for (const stopped of ["CANCELLED", "STOPPED", "ABORTED", "HELD", "SKIPPED"]) expect(statusMeta(stopped).tone).toBe("idle");
    expect(isFailure("TIMED_OUT")).toBe(true);
    expect(isFailure("CANCELLED")).toBe(false);
  });

  it("turns an unknown code into words without claiming a meaning", () => {
    expect(statusMeta("SOME_NEW_STATE")).toMatchObject({ label: "Some new state", tone: "idle" });
  });
});

it("uses a dot and word in dense lists while retaining failure, warning and detail pills", () => {
  const { container } = render(<><StatusBadge quiet status="SUCCESS" /><StatusBadge quiet status="FAILED" /><StatusBadge quiet status="LOST" /><StatusBadge status="SUCCESS" /></>);
  const [dense, failure, warning, detail] = Array.from(container.children);
  expect(dense!.textContent).toBe("Success");
  expect(dense!.querySelector("svg")).toBeNull();
  expect(dense!.querySelector('[aria-hidden="true"]')).toHaveClass("bg-current");
  expect(dense).not.toHaveClass("rounded-full");
  expect(failure).toHaveClass("bg-bad-bg", "rounded-full");
  expect(warning).toHaveClass("bg-warn-bg", "rounded-full");
  expect(detail).toHaveClass("bg-ok-bg", "rounded-full");
  expect(detail!.querySelector("svg")).not.toBeNull();
});
