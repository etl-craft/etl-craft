import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { HBars, KpiTile, StackedBars, Trend } from "@/components/charts";

const days = [
  { day: "2026-11-05", runs: 4, succeeded: 3, failed: 1, average_seconds: 30 },
  { day: "2026-11-06", runs: 2, succeeded: 2, failed: 0, average_seconds: null },
  { day: "2026-11-07", runs: 8, succeeded: 8, failed: 0, average_seconds: 90 },
];

describe("the dashboard charts", () => {
  it("names the day under focus in a readout, and says what the colours mean otherwise", () => {
    render(<StackedBars days={days} />);
    expect(screen.getByText("Succeeded")).toBeTruthy();
    fireEvent.focus(screen.getByRole("button", { name: "2026-11-05: 4 runs, 3 succeeded, 1 failed" }));
    expect(screen.getByRole("status").textContent).toContain("1 failed");
    expect(screen.getByRole("status").textContent).toContain("2026-11-05");
  });

  it("reads a trend day by day and says so when nothing finished", () => {
    const { unmount } = render(<Trend days={days} value={(d) => d.average_seconds} format={(n) => `${n} s`} />);
    expect(screen.getByRole("status").textContent).toBe("Highest 90 s");
    fireEvent.focus(screen.getByRole("button", { name: "2026-11-06: no finished runs" }));
    expect(screen.getByRole("status").textContent).toContain("no finished runs");
    unmount();
    render(<Trend days={days} value={() => null} format={(n) => String(n)} />);
    expect(screen.getByText("No finished runs in this window.")).toBeTruthy();
  });

  it("ranks bars, links a name and draws no bar for a zero", () => {
    render(
      <MemoryRouter>
        <HBars label="Rows" empty="Nothing." rows={[{ label: "a", value: 10, to: "/a" }, { label: "b", value: 0 }]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "a" }).getAttribute("href")).toBe("/a");
    const bars = screen.getAllByRole("listitem").map((li) => (li.querySelector("span span") as HTMLElement).style.width);
    expect(bars).toEqual(["100%", "0px"]);
  });

  it("says why there is nothing to rank", () => {
    render(<HBars label="Rows" empty="Nothing ran." rows={[]} />);
    expect(screen.getByText("Nothing ran.")).toBeTruthy();
  });

  it("shows a headline with its context", () => {
    render(<KpiTile label="Success rate" value="97%" hint="2 failed" tone="bad" />);
    expect(screen.getByText("97%").className).toContain("text-bad");
    expect(screen.getByText("2 failed")).toBeTruthy();
  });
});
