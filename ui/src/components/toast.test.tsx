import { fireEvent, render, screen } from "@testing-library/react";
import * as React from "react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "@/components/toast";

function Asker() {
  const toast = useToast();
  const [gone, setGone] = React.useState(false);
  // Like a Recover button that disappears once the run it acted on has changed state.
  return gone ? null : (
    <button
      type="button"
      onClick={() => {
        toast("Recover accepted: control #4.");
        setGone(true);
      }}
    >
      Ask
    </button>
  );
}

describe("toasts", () => {
  it("keep showing the answer after the component that asked has gone", () => {
    render(
      <ToastProvider>
        <Asker />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("Ask"));
    expect(screen.queryByText("Ask")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Recover accepted: control #4.");
  });

  it("can be dismissed", () => {
    render(
      <ToastProvider>
        <Asker />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("Ask"));
    fireEvent.click(screen.getByLabelText("Dismiss"));
    expect(screen.getByRole("status")).not.toHaveTextContent("Recover accepted");
  });

  it("keep the answer until it is dismissed, including while focused", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Asker />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("Ask"));
    expect(screen.getByRole("status")).toHaveTextContent("Recover accepted");
    screen.getByLabelText("Dismiss").focus();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Recover accepted");
    expect(screen.getByLabelText("Dismiss")).toHaveFocus();
    fireEvent.click(screen.getByLabelText("Dismiss"));
    expect(screen.getByRole("status")).not.toHaveTextContent("Recover accepted");
  });

  afterEach(() => vi.useRealTimers());
});
