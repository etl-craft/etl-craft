import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { Highlight, Notice, Pager, Stat } from "@/components/common";
import { BackButton } from "@/components/navigation";

describe("Stat", () => {
  it("says an absent value quietly and a number loudly", () => {
    render(
      <dl>
        <Stat label="Rows written" value="Not measured" />
        <Stat label="Runs" value={361} />
      </dl>,
    );
    expect(screen.getByText("Not measured").className).toContain("text-muted");
    expect(screen.getByText("361").className).toContain("text-2xl");
  });
});

describe("Notice", () => {
  it("is an alert for a failure and a status for plain information", () => {
    render(
      <>
        <Notice>refused</Notice>
        <Notice info>nothing built yet</Notice>
      </>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("refused");
    expect(screen.getByRole("status")).toHaveTextContent("nothing built yet");
  });
});

describe("BackButton", () => {
  function Shell() {
    return (
      <Routes>
        <Route path="*" element={<><BackButton fallback="/projects/demo" /><p>{useLocation().pathname}</p><Link to="/projects/demo/runs">Runs</Link></>} />
      </Routes>
    );
  }
  it("goes to the previous page, up to the fallback when opened directly, and is disabled at the fallback", () => {
    window.history.replaceState(null, "", "/projects/demo/pipelines/OPS");
    render(<BrowserRouter><Shell /></BrowserRouter>);
    fireEvent.click(screen.getByRole("link", { name: "Runs" }));
    expect(screen.getByText("/projects/demo/runs")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    return screen.findByText("/projects/demo/pipelines/OPS").then(() => {
      fireEvent.click(screen.getByRole("button", { name: "Back" }));
      expect(screen.getByText("/projects/demo")).toBeTruthy();
      expect((screen.getByRole("button", { name: "Back" }) as HTMLButtonElement).disabled).toBe(true);
    });
  });
});

describe("Highlight and Pager", () => {
  it("marks every occurrence of the words, whatever their case, and treats them as plain text", () => {
    const { container } = render(<Highlight text="Orders and orders (a.b)" words="orders" />);
    expect(container.querySelectorAll("mark").length).toBe(2);
    const dotted = render(<Highlight text="a.b axb" words="a.b" />);
    expect(dotted.container.querySelectorAll("mark").length).toBe(1);
  });

  it("shows the range, and moves a page at a time", () => {
    const seen: number[] = [];
    render(<Pager page={2} size={25} total={60} onPage={(p) => seen.push(p)} />);
    expect(screen.getByText("26 to 50 of 60")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(seen).toEqual([3, 1]);
  });
});

it("renders the caller's next step in the shared empty state", async () => {
  const { EmptyState } = await import("@/components/common");
  render(<EmptyState title="No scheduled runs" nextStep="Set a schedule in the project config files." />);
  expect(screen.getByRole("status")).toHaveTextContent("Set a schedule in the project config files.");
});
