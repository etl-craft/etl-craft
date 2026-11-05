import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Notice, Stat } from "@/components/common";

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
