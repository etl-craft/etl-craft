import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { HBars, KpiTile } from "@/components/charts";

describe("the dashboard charts", () => {
  it("uses numbers for sparse series and keeps names linked", () => {
    render(
      <MemoryRouter>
        <HBars label="Rows" empty="Nothing." rows={[{ label: "a", value: 10, to: "/a" }, { label: "b", value: 0 }]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "a" }).getAttribute("href")).toBe("/a");
    expect(screen.queryByRole("listitem")).toBeNull();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
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
