import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TagFilter } from "@/components/tag-filter";

const open = () => fireEvent.click(screen.getByRole("button", { name: /^Tags/ }));

describe("the tag filter", () => {
  it("ticks and unticks tags in a checklist and says how many are selected", () => {
    const toggle = vi.fn();
    render(<TagFilter known={["kind:steward", "client:alpha"]} selected={["client:alpha"]} onToggle={toggle} onClear={() => undefined} />);
    open();
    expect((screen.getByRole("checkbox", { name: "client:alpha" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: "kind:steward" }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: "kind:steward" }));
    expect(toggle).toHaveBeenCalledWith("kind:steward");
    expect(screen.getByRole("button", { name: "Tags (1 selected)" })).toBeTruthy();
  });

  it("is one button over a searchable list however many tags there are", () => {
    render(<TagFilter known={Array.from({ length: 1000 }, (_, i) => `team:t${i}`)} selected={[]} onToggle={() => undefined} onClear={() => undefined} />);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    open();
    expect(screen.getAllByRole("checkbox")).toHaveLength(300);
    expect(screen.getByRole("status").textContent).toBe("300 of 1000 shown; type to narrow.");
    fireEvent.change(screen.getByLabelText("Search tags"), { target: { value: "T99" } });
    expect(screen.getAllByRole("checkbox")).toHaveLength(11); // t99, t990 to t999
    fireEvent.change(screen.getByLabelText("Search tags"), { target: { value: "nothing" } });
    expect(screen.getByRole("status").textContent).toBe("No tag matches.");
  });

  it("clears every selection and closes on Escape", () => {
    const clear = vi.fn();
    render(<TagFilter known={["a", "b"]} selected={["a", "b"]} onToggle={() => undefined} onClear={clear} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(clear).toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByLabelText("Search tags")).toBeNull();
  });

  it("says where tags come from when no pipeline has one", () => {
    render(<TagFilter known={[]} selected={[]} onToggle={() => undefined} onClear={() => undefined} />);
    expect(screen.getByText(/PIPELINE_PARAMETERS\.TAGS/)).toBeTruthy();
  });
});
