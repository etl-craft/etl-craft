import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Highlight, Notice, PageHeader, Pager, Stat } from "@/components/common";

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

describe("PageHeader", () => {
  it("has a back arrow only on a page nested under another", () => {
    const { rerender } = render(
      <MemoryRouter>
        <PageHeader title="Runs" />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link", { name: /Back/ })).toBeNull();
    rerender(
      <MemoryRouter>
        <PageHeader title="OPS" back={{ to: "/projects/demo/pipelines", label: "Pipelines" }} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Back to Pipelines" })).toBeTruthy();
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
