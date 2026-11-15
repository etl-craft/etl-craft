import { Database } from "lucide-react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DiagramNode } from "@/components/diagram-node";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
function Location() { return <output aria-label="Current address">{useLocation().pathname}</output>; }
function example(expanded=false) {
  const expand = vi.fn(), open = vi.spyOn(window,"open").mockImplementation(()=>null);
  render(<MemoryRouter><Location/><DiagramNode title="Orders" icon={Database} expanded={expanded} onExpanded={expand}
    details={{to:"/projects/demo/catalog/tables/orders"}}/></MemoryRouter>);
  return {expand, open, header: screen.getByRole("button", {name:`${expanded?"Collapse":"Expand"} Orders`})};
}
it("expands a header once after a solitary mouse click", () => {
  vi.useFakeTimers(); const {expand,open,header} = example();
  fireEvent.click(header, {detail:1});
  expect(expand).not.toHaveBeenCalled();
  act(() => { vi.advanceTimersByTime(500); });
  expect(expand).toHaveBeenCalledTimes(1); expect(open).not.toHaveBeenCalled();
});
it.each([false,true])("double-click opens details without changing expansion from %s", expanded => {
  vi.useFakeTimers(); const {expand,open,header} = example(expanded);
  fireEvent.click(header, {detail:1});
  act(() => { vi.advanceTimersByTime(100); });
  fireEvent.click(header, {detail:2}); fireEvent.doubleClick(header);
  act(() => { vi.advanceTimersByTime(500); });
  expect(expand).not.toHaveBeenCalled(); expect(open).toHaveBeenCalledWith("/projects/demo/catalog/tables/orders","_blank","noopener,noreferrer");
});
it("expands keyboard activation immediately and cancels pending expansion on unmount", () => {
  vi.useFakeTimers(); const {expand,header} = example();
  fireEvent.click(header, {detail:0}); expect(expand).toHaveBeenCalledTimes(1);
  fireEvent.click(header, {detail:1}); cleanup();
  act(() => { vi.advanceTimersByTime(500); }); expect(expand).toHaveBeenCalledTimes(1);
});
it("offers a real current-tab catalog link through the keyboard menu", async () => {
  const {expand,open} = example();
  const menu = screen.getByRole("button", {name:"Node actions for Orders"});
  fireEvent.keyDown(menu,{key:"Enter"});
  const item = await screen.findByRole("menuitem",{name:"Open catalog details"});
  expect(item.getAttribute("href")).toBe("/projects/demo/catalog/tables/orders");
  expect(item.getAttribute("target")).toBeNull();
  expect(expand).not.toHaveBeenCalled(); expect(open).not.toHaveBeenCalled();
  expect(await screen.findByRole("menuitem",{name:"Expand"})).toBeVisible();
  const newTab=screen.getByRole("menuitem",{name:/Open in new tab/});
  expect(newTab).toHaveAttribute("target","_blank");
  fireEvent.keyDown(item,{key:"ArrowDown"});
  const expandItem=screen.getByRole("menuitem",{name:"Expand"});
  await waitFor(()=>expect(expandItem).toHaveFocus());
  fireEvent.keyDown(expandItem,{key:"Enter"});
  expect(expand).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(menu,{key:"Enter"});
  const again=await screen.findByRole("menuitem",{name:"Open catalog details"});
  fireEvent.keyDown(again,{key:"Escape"});
  expect(screen.queryByRole("menuitem",{name:"Open catalog details"})).toBeNull();
  fireEvent.keyDown(menu,{key:"Enter"});
  const destination=await screen.findByRole("menuitem",{name:"Open catalog details"});
  await waitFor(()=>expect(destination).toHaveFocus());
  fireEvent.keyDown(destination,{key:"Enter"});
  await waitFor(()=>expect(screen.getByLabelText("Current address")).toHaveTextContent("/projects/demo/catalog/tables/orders"));
});
