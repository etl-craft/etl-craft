import {afterEach,beforeEach,describe,it,expect,vi} from "vitest";
import {render,screen,fireEvent,cleanup} from "@testing-library/react";
import {LegendView,statusEntries} from "@/components/legend";
import {statusMeta} from "@/components/status";
import {mappingStageEntry} from "@/components/diagram-key";
const entries=[{id:"data",group:"Dependencies",name:"Has data",meaning:"Requires written rows",sample:<i/>}];
beforeEach(()=>localStorage.clear());afterEach(()=>{cleanup();vi.restoreAllMocks();});
describe("floating view key",()=>{
 beforeEach(()=>localStorage.setItem("etl-craft-key:local","open"));
 it("lists only entries present in the view",()=>{render(<LegendView entries={entries}><span>Canvas</span></LegendView>);expect(screen.getByRole("region",{name:"View key"})).toHaveTextContent("Requires written rows");expect(screen.queryByText("On failure")).toBeNull();});
 it("uses statusMeta for names and symbols",()=>{const found=statusEntries(["SUCCESS","FAILED","SUCCESS"]);expect(found.map(row=>row.name)).toEqual([statusMeta("SUCCESS").label,statusMeta("FAILED").label]);render(<LegendView entries={found}>Canvas</LegendView>);expect(screen.getByRole("rowheader",{name:statusMeta("FAILED").label})).toBeVisible();expect(document.querySelector(".lucide-x")).not.toBeNull();});
 it("restores the stored closed state and returns focus after Escape",()=>{localStorage.setItem("etl-craft-key:local","closed");render(<LegendView entries={entries}>Canvas</LegendView>);const toggle=screen.getByRole("button",{name:/^Key$/});expect(screen.queryByRole("region")).toBeNull();fireEvent.keyDown(toggle,{key:"?"});expect(screen.getByRole("region")).toBeVisible();fireEvent.keyDown(screen.getByRole("region"),{key:"Escape"});expect(toggle).toHaveFocus();expect(localStorage.getItem("etl-craft-key:local")).toBe("closed");});
 it("works if browser storage is refused",()=>{vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw new DOMException("blocked");});vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw new DOMException("blocked");});render(<LegendView entries={entries}>Canvas</LegendView>);fireEvent.click(screen.getByRole("button",{name:"Key"}));fireEvent.click(screen.getByRole("button",{name:"Close key"}));expect(screen.queryByRole("region")).toBeNull();});
});

describe("key wording and phone default",()=>{
 it("names every mapping stage in sentence case with its own meaning",()=>{
  const found=["source","join","filter","aggregate","set","expression","rules","write","target"].map(kind=>mappingStageEntry(kind,"var(--muted)"));
  expect(found.map(row=>row.name)).toEqual(["Source","Join","Filter","Aggregate","Set operation","Expression","Rules","Write","Target"]);
  for(const row of found)expect(row.meaning.toLowerCase()).not.toContain(`${row.name.toLowerCase()} stage`);
 });
 it("gives each status a meaning that is not its own name repeated",()=>{
  const found=statusEntries(["SUCCESS","FAILED","IN-PROGRESS","LOST","SKIPPED"]);
  for(const row of found){expect(row.meaning).not.toMatch(/run or task$/);expect(row.meaning.toLowerCase()).not.toBe(row.name.toLowerCase());}
 });
 it("starts closed on a phone and desktop when nothing is stored",()=>{
  vi.stubGlobal("matchMedia",(query:string)=>({matches:query.includes("480px"),media:query}));
  render(<LegendView entries={entries}>Canvas</LegendView>);
  expect(screen.queryByRole("region",{name:"View key"})).toBeNull();
  cleanup();vi.stubGlobal("matchMedia",()=>({matches:false}));
  render(<LegendView entries={entries}>Canvas</LegendView>);
  expect(screen.queryByRole("region",{name:"View key"})).toBeNull();
  vi.unstubAllGlobals();
 });
});

it("keeps the workspace clear until its key is requested",()=>{
 vi.stubGlobal("matchMedia",()=>({matches:false}));
 render(<LegendView entries={entries}>Canvas</LegendView>);
 const toggle=screen.getByRole("button",{name:"Key"});
 expect(toggle).toHaveAttribute("aria-expanded","false");
 expect(screen.queryByRole("region",{name:"View key"})).toBeNull();
 fireEvent.click(toggle);
 expect(screen.getByRole("region",{name:"View key"})).toHaveTextContent("Requires written rows");
 vi.unstubAllGlobals();
});

it("shows the real selection outline and line rather than a decorative icon",async()=>{
 const {highlightedEntry}=await import("@/components/diagram-key");
 const {container}=render(<>{highlightedEntry.sample}</>);
 expect(container.querySelector(".lucide-sparkles")).toBeNull();
 expect(container.querySelector("rect")).toHaveAttribute("stroke","var(--accent)");
 expect(container.querySelector("path")).toHaveAttribute("stroke-width","2");
});

it("uses dependency line patterns and the visible repair label",async()=>{
 const {dependencyEntries}=await import("@/components/diagram-key");
 const rows=dependencyEntries([{dependency_type:"FAILURE",consume_repairs:"N"},{dependency_type:"HAS_DATA"}]);
 const {container}=render(<>{rows.map(row=><span key={row.id}>{row.sample}</span>)}</>);
 expect(container.querySelector(".lucide-ban")).toBeNull();
 expect(container.querySelector(".lucide-database")).not.toBeNull();
 expect(container.querySelector(".lucide-x")).not.toBeNull();
 expect(screen.getByText("No repairs")).toBeVisible();
 expect(container.querySelector('path[style*="7 4"]')).not.toBeNull();
});
