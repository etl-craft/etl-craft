import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { SplitPane } from "@/components/split-pane";

const pane = () => render(<SplitPane id="test" initial={0.4} left={<p>Left</p>} right={<p>Right</p>} />);
const width = () => Number(screen.getByRole("separator").getAttribute("aria-valuenow"));

describe("the split pane", () => {
  beforeEach(() => window.localStorage.clear());

  it("moves its divider with the arrow keys, resets with Home and stays within bounds", () => {
    pane();
    const divider = screen.getByRole("separator", { name: "Resize the panes" });
    expect(width()).toBe(40);
    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(width()).toBe(42);
    fireEvent.keyDown(divider, { key: "Home" });
    expect(width()).toBe(40);
    for (let i = 0; i < 40; i++) fireEvent.keyDown(divider, { key: "ArrowLeft" });
    expect(width()).toBe(20);
    for (let i = 0; i < 60; i++) fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(width()).toBe(80);
  });

  it("remembers the width in this browser", () => {
    const { unmount } = pane();
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    unmount();
    pane();
    expect(width()).toBe(42);
  });

  it("falls back to its default when storage is blocked", () => {
    const get = window.localStorage.getItem;
    window.localStorage.getItem = () => {
      throw new Error("blocked");
    };
    pane();
    window.localStorage.getItem = get;
    expect(width()).toBe(40);
  });
});
