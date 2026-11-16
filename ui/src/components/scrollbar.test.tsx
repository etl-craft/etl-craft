import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Scrollbar } from "@/components/scrollbar";

afterEach(cleanup);
it.each(["horizontal","vertical"] as const)("%s scrollbar exposes its range and supports keyboard endpoints and pages",axis=>{
  const change=vi.fn();
  render(<Scrollbar axis={axis} label="View" controls="content" value={100} maximum={800} page={200} onChange={change}/>);
  const bar=screen.getByRole("scrollbar",{name:"View"});
  expect(bar).toHaveAttribute("aria-controls","content");
  expect(bar).toHaveAttribute("aria-orientation",axis);
  expect(bar).toHaveAttribute("aria-valuenow","100");
  for(const [key,value] of [["Home",0],["End",800],["PageDown",300],["PageUp",0],["ArrowRight",140],["ArrowLeft",60]] as const){
    fireEvent.keyDown(bar,{key});expect(change).toHaveBeenLastCalledWith(value);
  }
});
it("wheel input is contained, normalizes line units, and clamps the range",()=>{
  const change=vi.fn();render(<Scrollbar axis="vertical" label="View" controls="content" value={100} maximum={800} page={200} onChange={change}/>);
  const event=new WheelEvent("wheel",{deltaY:3,deltaMode:1,cancelable:true,bubbles:true});
  fireEvent(screen.getByRole("scrollbar"),event);
  expect(event.defaultPrevented).toBe(true);expect(change).toHaveBeenLastCalledWith(148);
  fireEvent.wheel(screen.getByRole("scrollbar"),{deltaY:1000});expect(change).toHaveBeenLastCalledWith(800);
});
it("an empty range keeps its visible track without a keyboard stop",()=>{
  render(<Scrollbar axis="vertical" label="View" controls="content" value={0} maximum={0} page={200} onChange={()=>{}}/>);
  expect(screen.getByRole("scrollbar")).toHaveAttribute("aria-disabled","true");
  expect(screen.getByRole("scrollbar")).toHaveAttribute("tabindex","-1");
});
