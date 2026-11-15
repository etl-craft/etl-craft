import {readFileSync} from "node:fs";
import {describe,it,expect} from "vitest";
import {kindColor} from "@/components/task-symbol";
const css=readFileSync("src/index.css","utf8");
const light=css.slice(css.indexOf(":root {"),css.indexOf('[data-theme="dark"] {'));
const dark=css.slice(css.indexOf('[data-theme="dark"] {'),css.indexOf("@theme inline"));
const tokens=(text:string):Record<string,string>=>Object.fromEntries([...text.matchAll(/--([\w-]+):\s*(#[\da-fA-F]{6})/g)].map(match=>[match[1],match[2]!]));
function luminance(hex:string){const values=[1,3,5].map(start=>parseInt(hex.slice(start,start+2),16)/255).map(value=>value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4);return values[0]!*0.2126+values[1]!*0.7152+values[2]!*0.0722;}
describe.each([["light",light],["dark",dark]])("category palette %s",(_,source)=>{
 it("contrasts at 3:1 with node backgrounds and never aliases status hues",()=>{
  const found=tokens(source!);const kinds=Object.entries(found).filter(([name])=>name.startsWith("kind-"));
  expect(kinds.map(([name])=>name)).toEqual(expect.arrayContaining(["kind-in","kind-mid","kind-out"]));
  const status=Object.entries(found).filter(([name])=>/^(ok|bad|run|warn)-/.test(name)).map(([,value])=>value);
  kinds.forEach(([,value])=>{const foreground=luminance(value),background=luminance(found.surface!);expect((Math.max(foreground,background)+0.05)/(Math.min(foreground,background)+0.05)).toBeGreaterThanOrEqual(3);expect(status).not.toContain(value);});
 });
});

it.each([["light",light],["dark",dark]])("keeps %s control boundaries distinguishable from their surface",(_,source)=>{
 const found=tokens(source!);
 const border=luminance(found["border-strong"]!);
 for(const name of ["surface","surface-2","bg"]){
  const surface=luminance(found[name]!);
  expect((Math.max(border,surface)+0.05)/(Math.min(border,surface)+0.05)).toBeGreaterThanOrEqual(3);
 }
});

it("gives mapping stages distinct non-status colour identities",()=>{
 const stages=["source","join","filter","expression","write"];
 const colours=stages.map(kindColor);
 expect(new Set(colours).size).toBe(stages.length);
 for(const source of [light,dark]){
  const found=tokens(source);
  const values=colours.map(colour=>found[colour.slice(6,-1)]);
  expect(values.every(Boolean)).toBe(true);
  expect(new Set(values).size).toBe(stages.length);
 }
});
