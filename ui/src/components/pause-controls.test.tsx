import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, afterEach, expect, it, vi } from "vitest";
import { Task } from "@/pages/task";
import { PipelinePause } from "@/components/pipeline-pause";
import { Paused } from "@/pages/paused";
import { ToastProvider } from "@/components/toast";
import { postJson } from "@/lib/api";
import type { Pipeline } from "@/lib/types";
vi.mock("@/lib/api",async original=>{const actual=await original<typeof import("@/lib/api")>();return {...actual,postJson:vi.fn()};});
beforeAll(()=>{
  HTMLDialogElement.prototype.showModal=function(){this.setAttribute("open","");};
  HTMLDialogElement.prototype.close=function(){this.removeAttribute("open");};
});
afterEach(()=>vi.mocked(postJson).mockReset());
const pipeline={pipeline_code:"OPS",run_schedule:null,paused:null,task_pauses:[]} as unknown as Pipeline;
async function show(task=false) {
 const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
 client.setQueryData(["action-availability","default","OPS",task ? {task_code:"load"} : undefined],{actions:[
  {endpoint:"/api/v1/controls",method:"POST",control:"PAUSE",available:true,reason:""},
  {endpoint:"/api/v1/controls",method:"POST",control:"RESUME",available:false,reason:"OPS is not paused."},
 ]});
 client.setQueryData(["health"],{projects:[{project:"default",environment_type:"CUSTOM",environment_name:null,governance:"STRICT"}]});
 client.setQueryData(["pipeline","default","OPS"],pipeline);
 client.setQueryData(["task","default","OPS","load"],{task_code:"load",handler:"PYTHON",parameters:{},merge_key:[],merge_columns:[]});
 client.setQueryData(["offset","default","OPS","load"],{kind:null});
 client.setQueryData(["task-runs","default","OPS","load"],{entries:[]});
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/ui/projects/default/pipelines/OPS/tasks/load"]}><ToastProvider>{task?<Routes><Route path="/ui/projects/:project/pipelines/:pipeline/tasks/:task" element={<Task/>}/></Routes>:<PipelinePause code="default" pipeline={pipeline}/>}</ToastProvider></MemoryRouter></QueryClientProvider>);
}
async function pick(name:string, label="OPS"){
 fireEvent.keyDown(screen.getByRole("button",{name:`Pause options for ${label}`}),{key:"Enter"});
 fireEvent.keyDown(await screen.findByRole("menuitem",{name}),{key:"Enter"});
}
it("offers DRAIN by default and sends the selected FINISH policy",async()=>{
 vi.mocked(postJson).mockResolvedValue({message:"Paused"});await show();
 fireEvent.keyDown(screen.getByRole("button",{name:"Pause options for OPS"}),{key:"Enter"});
 const resume=await screen.findByRole("menuitem",{name:"Resume"});
 expect(resume).toHaveAttribute("aria-disabled","true");
 expect(resume).toHaveAccessibleDescription("OPS is not paused.");
 fireEvent.keyDown(screen.getByRole("menuitem",{name:"Pause"}),{key:"Enter"});
 const dialog=screen.getByRole("dialog");
 const mode=within(dialog).getByRole("combobox",{name:"Active runs"});
 expect(mode).toHaveValue("DRAIN");
 expect(within(mode).getByRole("option",{name:"Stop active runs at the next task"})).toHaveValue("DRAIN");
 fireEvent.change(mode,{target:{value:"FINISH"}});
 fireEvent.change(within(dialog).getByLabelText(/Reason/),{target:{value:"finish admitted loads"}});
 fireEvent.click(within(dialog).getByRole("button",{name:"Pause"}));
 await waitFor(()=>expect(postJson).toHaveBeenCalledWith("/api/v1/projects/default/controls",expect.objectContaining({action:"PAUSE",active_runs:"FINISH"})));
 await waitFor(()=>expect(screen.queryByRole("dialog")).toBeNull());
 await pick("Pause");
 expect(within(screen.getByRole("dialog")).getByRole("combobox",{name:"Active runs"})).toHaveValue("DRAIN");
});
it("always submits a visible task outcome with SKIPPED preselected",async()=>{
 vi.mocked(postJson).mockResolvedValue({message:"Task paused"});await show(true);
 fireEvent.click(screen.getByRole("button",{name:"Pause task"}));
 const dialog=screen.getByRole("dialog");
 expect(within(dialog).getByRole("combobox",{name:"Task outcome"})).toHaveValue("SKIPPED");
 fireEvent.change(within(dialog).getByLabelText(/Reason/),{target:{value:"omit unavailable source"}});
 fireEvent.click(within(dialog).getByRole("button",{name:"Pause task"}));
 await waitFor(()=>expect(postJson).toHaveBeenCalledWith("/api/v1/projects/default/controls",expect.objectContaining({task_code:"load",outcome:"SKIPPED"})));
 const body=vi.mocked(postJson).mock.lastCall?.[1];
 expect(body).not.toHaveProperty("active_runs");
});

it("keeps an open pause form and its chosen mode during a live list refresh", async()=>{
 const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
 client.setQueryData(["action-availability","default","OPS",undefined],{actions:[
  {endpoint:"/api/v1/controls",method:"POST",control:"PAUSE",replacement:true,available:true,reason:""},
 ]});
 client.setQueryData(["health"],{projects:[{project:"default",environment_type:"CUSTOM",environment_name:null,governance:"STRICT"}]});
 const paused={...pipeline,paused:{active_runs:"DRAIN",drained_runs:[],paused_by:"owner",paused_at:"2026-11-16T12:00:00Z",reason:"maintenance"}};
 client.setQueryData(["pipelines","default"],{pipelines:[paused]});
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/ui/projects/default/paused"]}><ToastProvider><Routes><Route path="/ui/projects/:project/paused" element={<Paused/>}/></Routes></ToastProvider></MemoryRouter></QueryClientProvider>);
 await pick("Replace pause", "OPS");
 const dialog=screen.getByRole("dialog");
 fireEvent.change(within(dialog).getByRole("combobox",{name:"Active runs"}),{target:{value:"FINISH"}});
 fireEvent.change(within(dialog).getByLabelText(/Reason/),{target:{value:"keep this input"}});
 act(()=>{client.setQueryData(["pipelines","default"],{pipelines:[{...paused,paused:{...paused.paused,reason:"updated by another operator"}}]});});
 await waitFor(()=>expect(screen.getByText("updated by another operator")).toBeInTheDocument());
 expect(screen.getByRole("dialog")).toBe(dialog);
 expect(within(dialog).getByRole("combobox",{name:"Active runs"})).toHaveValue("FINISH");
 expect(within(dialog).getByLabelText(/Reason/)).toHaveValue("keep this input");
});
