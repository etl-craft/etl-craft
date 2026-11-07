import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Table, Td, Th } from "@/components/ui/table";

let seen: ((entries: { isIntersecting: boolean }[]) => void) | null = null;

class FakeObserver {
  constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
    seen = callback;
  }
  observe() {}
  disconnect() {}
}

function list(more?: { hasMore: boolean; loading: boolean; load: () => void }) {
  return render(
    <Table aria-label="Runs" more={more}>
      <thead>
        <tr>
          <Th>Run</Th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <Td>1</Td>
        </tr>
      </tbody>
    </Table>,
  );
}

describe("the scrolling table", () => {
  afterEach(() => {
    seen = null;
    vi.unstubAllGlobals();
  });

  it("scrolls inside a bounded box and keeps its header in view", () => {
    list();
    expect(screen.getByRole("table").parentElement?.className).toContain("overflow-auto");
    expect(screen.getByRole("table").parentElement?.className).toContain("max-h-");
    expect(screen.getByText("Run").className).toContain("sticky");
  });

  it("loads the next rows when its end is scrolled into view, and not before", () => {
    vi.stubGlobal("IntersectionObserver", FakeObserver);
    const load = vi.fn();
    list({ hasMore: true, loading: false, load });
    expect(screen.getByText("Scroll for more")).toBeTruthy();
    seen?.([{ isIntersecting: false }]);
    expect(load).not.toHaveBeenCalled();
    seen?.([{ isIntersecting: true }]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("says when every row is loaded and does not ask for more", () => {
    vi.stubGlobal("IntersectionObserver", FakeObserver);
    const load = vi.fn();
    list({ hasMore: false, loading: false, load });
    expect(screen.getByText("All rows loaded")).toBeTruthy();
    expect(seen).toBeNull();
  });
});
