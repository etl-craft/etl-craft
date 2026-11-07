import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TagFilter } from "@/components/tag-filter";

describe("the tag filter", () => {
  it("adds a tag from the dropdown and removes a selected one from its chip", () => {
    const toggle = vi.fn();
    render(<TagFilter known={["kind:steward", "client:alpha"]} selected={["client:alpha"]} onToggle={toggle} />);
    const select = screen.getByLabelText("Tag") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["Add a tag (1)", "kind:steward"]); // a selected tag is not offered again
    fireEvent.change(select, { target: { value: "kind:steward" } });
    expect(toggle).toHaveBeenCalledWith("kind:steward");
    fireEvent.click(screen.getByRole("button", { name: "Remove tag client:alpha" }));
    expect(toggle).toHaveBeenCalledWith("client:alpha");
  });

  it("is one control however many tags there are", () => {
    render(<TagFilter known={Array.from({ length: 1000 }, (_, i) => `team:t${i}`)} selected={[]} onToggle={() => undefined} />);
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect((screen.getByLabelText("Tag") as HTMLSelectElement).options).toHaveLength(1001);
  });

  it("says where tags come from when no pipeline has one", () => {
    render(<TagFilter known={[]} selected={[]} onToggle={() => undefined} />);
    expect(screen.getByText(/PIPELINE_PARAMETERS\.TAGS/)).toBeTruthy();
  });
});
