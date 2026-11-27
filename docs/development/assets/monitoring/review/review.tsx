import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, useSearchParams } from "react-router-dom";
import { Moon, Sun } from "lucide-react";
import "@fontsource-variable/inter/index.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./review.css";
import { EnvironmentBadge } from "@/components/environment-badge";
import { PageHeader, Fact, FactList, SelectField, Notice, EmptyState } from "@/components/common";
import { StatusBadge } from "@/components/status";
import { Tabs } from "@/components/tabs";
import { Table, Th, Td } from "@/components/ui/table";
import { DailyRuns, KpiTile, Panel } from "@/components/charts";
import { Logo } from "@/components/logo";
import { useActionReason } from "@/components/action-reason";
import { Button } from "@/components/ui/button";
import { applyTheme, initialTheme } from "@/lib/theme";

const production = { type: "PROD", name: null };
const stage = { type: "STAGE", name: null };
const incidents = [
  { project: "finance", env: production, pipeline: "NIGHTLY_LEDGER", run: "#18422", state: "FAILED", facet: "Failing", evidence: "merge_ledger · TARGET_WRITE_FAILED", time: "03:02 UTC", task: "sql" },
  { project: "retail", env: production, pipeline: "INVENTORY_EXPORT", run: "#18424", state: "BREACHED", facet: "Late", evidence: "SLA due 03:00 UTC · still running", time: "03:00 UTC", task: "running" },
  { project: "finance", env: production, pipeline: "BANK_STATEMENTS", run: "", state: "BREACHED", facet: "Late", evidence: "Missed start · 5 min grace exceeded", time: "03:00 UTC", task: "" },
  { project: "finance", env: production, pipeline: "NIGHTLY_LEDGER", run: "#18422", state: "OPEN", facet: "Waiting", evidence: "rebuild_totals · pool warehouse-heavy", time: "02:58 UTC", task: "waiting" },
  { project: "retail", env: stage, pipeline: "CATALOG_LOAD", run: "#18423", state: "RUNNING", facet: "Running", evidence: "load_products · worker-east-02", time: "02:57 UTC", task: "running" },
  { project: "private", env: production, pipeline: "PRIVATE_RECON", run: "#18425", state: "FAILED", facet: "Failing", evidence: "Restricted to a separate fixture role", time: "03:01 UTC", task: "" },
];
const days = [11, 7, 10, 8, 12, 6, 7].map((runs, i) => ({
  day: `2026-11-${21 + i}`, runs, succeeded: runs - (i === 6 ? 3 : 0),
  failed: i === 6 ? 1 : 0, average_seconds: 124 + i * 2,
}));
const views = ["Home", "Monitor", "Task", "Statistics", "Agents", "Alert"];
const tasks = {
  sql: { name: "merge_ledger", handler: "SQL", state: "FAILED", duration: "24 s", rss: "212 MiB", cpu: "0.32 cores" },
  python: { name: "verify_manifest", handler: "PYTHON", state: "SUCCESS", duration: "3 s", rss: "78 MiB", cpu: "0.18 cores" },
  running: { name: "load_products", handler: "SQL", state: "RUNNING", duration: "6 min", rss: "—", cpu: "—" },
  waiting: { name: "rebuild_totals", handler: "SQL", state: "OPEN", duration: "—", rss: "—", cpu: "—" },
};
const tasksTabs = ["Logs", "SQL / script", "Mapping", "Details", "Attempts"];
const panel = "rounded-md border border-border bg-surface";
const events = [
  { time: "03:01:37.109", severity: "Info", step: "Admission", message: "Condition evaluated: stage_ledger.SUCCESS AND stage_ledger.ROWS_WRITTEN > 0 → true." },
  { time: "03:01:37.902", severity: "Info", step: "Read", message: "Opened the source snapshot. Source rows read: 84,320." },
  { time: "03:01:58.304", severity: "Warning", step: "Merge", message: "12 rows failed validation and were rejected." },
  { time: "03:02:01.188", severity: "Error", step: "Merge", message: "TARGET_WRITE_FAILED · Merge rolled back after a warehouse lock timeout." },
  { time: "03:02:01.210", severity: "Error", step: "Outcome", message: "Attempt 2 failed. Target transaction rolled back." },
];

function Grid({ headings, rows }: { headings: string[]; rows: React.ReactNode[][] }) {
  return <div className={panel}>
    <Table unwrapped className="w-full text-left text-sm max-sm:block">
      <thead className="bg-surface-2 text-muted max-sm:hidden"><tr>{headings.map((h) => <Th key={h} className="px-4 py-2 font-medium">{h}</Th>)}</tr></thead>
      <tbody className="max-sm:block">{rows.map((row, i) => <tr key={i} className="border-t border-border first:border-t-0 max-sm:grid max-sm:grid-cols-2 max-sm:gap-y-2 max-sm:p-3">
        {row.map((cell, j) => <Td key={j} className="px-4 py-3 align-top max-sm:min-w-0 max-sm:break-words max-sm:border-0 max-sm:p-0"><span className="hidden text-xs text-muted max-sm:block">{headings[j]}</span>{cell}</Td>)}
      </tr>)}</tbody>
    </Table>
  </div>;
}

function DriftMark() {
  const { anchor, annotation, show } = useActionReason("3.4× median of 7 s · 20 successful runs");
  return <><button type="button" className="text-warn" aria-label="Warning: 3.4 times median" {...anchor} onClick={show}>▲</button>{annotation}</>;
}

function Review() {
  const [query, set] = useSearchParams();
  const view = query.get("view") ?? "Home";
  const taskKey = (query.get("task") ?? "sql") as keyof typeof tasks;
  const task = tasks[taskKey] ?? tasks.sql;
  const tab = query.get("tab") ?? "Logs";
  const facet = query.get("facet") ?? "All";
  const [theme, setTheme] = useState(initialTheme);
  const [severity, setSeverity] = useState("All");
  const [step, setStep] = useState("All");
  const [first, setFirst] = useState(false);
  const [attempt, setAttempt] = useState("2");
  const [sort, setSort] = useState("Task");
  const scoped = incidents.filter((item) => item.project !== "private");
  const url = (page: string, extra = {}) => "?" + new URLSearchParams({ view: page, ...extra });
  const go = (page: string, extra = {}) => set({ view: page, ...extra });
  const facets = [["Failing", "FAILED"], ["Running", "RUNNING"], ["Late", "BREACHED"], ["Waiting", "OPEN"]];
  const matches = (item: typeof incidents[number], label: string) => item.facet === label || (label === "Running" && item.run === "#18424");
  const strip = <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{facets.map(([label, state]) => <Link className={panel + " flex items-center justify-between gap-2 p-3"} key={label} to={url("Monitor", { facet: label })}><StatusBadge status={state} label={label}/><strong>{scoped.filter((r) => matches(r, label)).length}</strong></Link>)}</div>;
  const header = (title: string, subtitle?: string) => <PageHeader title={title} subtitle={subtitle}/>;
  let content: React.ReactNode;
  if (view === "Home") content = <>
    {header("Home", "finance · Runs started in the last 7 days")}
    {strip}
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <Panel title="1 of 61 runs failed"><DailyRuns days={days}/></Panel>
      <Panel title="Needs attention"><div className="p-4 text-sm">
        <Link to={url("Task")} className="text-accent">NIGHTLY_LEDGER #18422</Link>
        <p className="mt-2 text-muted">merge_ledger failed at 03:02 UTC</p>
      </div></Panel>
    </div>
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <KpiTile label="Runs" value={61} hint="59 finished"/>
      <KpiTile label="Average duration" value="2 min 14 s"/>
      <KpiTile label="Retries" value={3} hint="186 attempts"/>
      <KpiTile label="Rows written" value="1.4M"/>
    </div>
  </>;
  else if (view === "Monitor") content = <>{header("Monitor", "All authorized projects · active and last 24 hours")}{strip}<Tabs value={facet} onChange={(value) => go("Monitor", { facet: value })} tabs={["All", ...facets.map(([label]) => label)].map((id) => ({ id, label: id }))}/><div className="text-xs text-muted">Updated 03:06 UTC</div><Grid headings={["Project / environment", "Pipeline / run", "State", "Evidence", "Since"]} rows={scoped.filter((r) => facet === "All" || matches(r, facet)).map((r) => [<>{r.project} <EnvironmentBadge env={r.env}/></>, r.task ? <Link className="text-accent" to={url("Task", { task: r.task })}>{r.pipeline} {r.run}</Link> : r.pipeline, <StatusBadge status={r.state} label={r.facet === "Late" ? (r.run ? "SLA overdue" : "Missed start") : undefined}/>, r.evidence, r.time])}/></>;
  else if (view === "Task") {
    const listed = taskKey === "sql" && attempt === "2" ? events.filter((e) => (severity === "All" || severity === e.severity) && (step === "All" || step === e.step)) : [];
    content = <>{header(task.name, `${taskKey === "running" ? "CATALOG_LOAD #18423" : "NIGHTLY_LEDGER #18422"} · ${task.handler} · Try ${taskKey === "sql" ? attempt : "1"}`)}
      <div className="flex flex-wrap gap-2">{Object.entries(tasks).map(([key, value]) => <Button key={key} variant={key === taskKey ? "primary" : "outline"} onClick={() => { go("Task", { task: key }); setFirst(false); setSeverity("All"); setStep("All"); }}>{value.name}</Button>)}</div>
      <StatusBadge status={taskKey === "sql" && attempt === "1" ? "TIMED_OUT" : task.state}/>
      {taskKey === "sql" && attempt === "2" && <section className="rounded-md border border-bad bg-bad-bg p-4"><h2 className="font-semibold text-bad">TARGET_WRITE_FAILED</h2><p className="my-2 text-sm">WarehouseWriteError · Transient · Merge rolled back after a warehouse lock timeout.</p><p className="mb-3 text-sm">Check the warehouse lock and open the recovery preview after it clears.</p><Button variant="outline" onClick={() => { setSeverity("All"); setStep("All"); setFirst(true); go("Task", { task: taskKey, tab: "Logs" }); requestAnimationFrame(() => document.getElementById("first-error")?.scrollIntoView({ block: "nearest" })); }}>First error · line 143</Button> <span className="text-xs text-muted">Last error · line 151</span></section>}
      {taskKey === "waiting" && <Notice info>Waiting for a slot in warehouse-heavy since 02:58 UTC. All 4 eligible slots are busy.</Notice>}
      <section className={panel + " p-3"} aria-label="Task statistics"><FactList inline>
        {taskKey === "sql" && attempt === "2" && <><Fact label="Source rows">84,320</Fact><Fact label="Applied">0</Fact><Fact label="Rejected">12</Fact><Fact label="Rows / second">3,513</Fact></>}
        <Fact label="Duration">{taskKey === "sql" && attempt === "1" ? "60 s" : task.duration} {taskKey === "sql" && attempt === "2" && <DriftMark/>}</Fact>
        {task.rss !== "—" && !(taskKey === "sql" && attempt === "1") && <Fact label="Peak RSS">{task.rss}</Fact>}
        {task.cpu !== "—" && !(taskKey === "sql" && attempt === "1") && <Fact label="Average cores">{task.cpu}</Fact>}
      </FactList></section>
      <Tabs tabs={tasksTabs.map((id) => ({ id, label: id }))} value={tab} onChange={(value) => go("Task", { task: taskKey, tab: value })}/>
      <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "Logs" && (taskKey === "sql" && attempt === "1" ? <Notice info>Attempt 1 log was archived.</Notice> : <><div className="mb-3 flex flex-wrap gap-3"><SelectField label="Severity" value={severity} onChange={setSeverity}>{["All", "Info", "Warning", "Error"].map((e) => <option key={e}>{e}</option>)}</SelectField><SelectField label="Step" value={step} onChange={setStep}>{["All","Admission","Read","Merge","Outcome"].map((e) => <option key={e}>{e}</option>)}</SelectField><a className="self-end pb-2 text-sm text-accent" download="attempt.log" href={"data:text/plain," + encodeURIComponent(events.map(e => e.message).join("\n"))}>Download raw log</a></div>{listed.length ? <Grid headings={["Time (UTC)", "Severity", "Step", "Event"]} rows={listed.map((e) => [e.time, e.severity === "Error" ? <StatusBadge status="FAILED" label="Error"/> : e.severity === "Warning" ? <StatusBadge status="BREACHED" label="Warning"/> : "Info", e.step, <span id={e.message.startsWith("TARGET") ? "first-error" : undefined} className={first && e.message.startsWith("TARGET") ? "font-semibold text-bad" : ""}>{e.message}</span>])}/> : <EmptyState title="No matching events" nextStep="Change the filters or select another attempt."/>}</>)}
        {tab === "SQL / script" && <pre className={panel + " overflow-auto p-4 text-sm"}>{task.handler === "PYTHON" ? "python_scripts/verify_manifest.py" : "SELECT entry_id, account_id, amount\nFROM staging.ledger_entries\nWHERE posting_date = :run_date"}</pre>}
        {tab === "Mapping" && <Grid headings={["Source", "Target", "Columns"]} rows={task.handler === "SQL" ? [["staging.ledger_entries", "finance.ledger", "entry_id, account_id, amount"]] : [["Object storage", "Manifest check", "No declared columns"]]}/>}
        {tab === "Details" && <section className={panel + " p-4"}><FactList><Fact label="Handler">{task.handler}</Fact><Fact label="Definition">v284</Fact><Fact label="Pool">warehouse-heavy</Fact><Fact label="Source">nightly finance batch</Fact></FactList></section>}
        {tab === "Attempts" && <Grid headings={["Attempt", "State", "Duration", "Evidence"]} rows={taskKey === "sql" ? [["2", <StatusBadge status="FAILED"/>, "24 s", <Button variant="outline" onClick={() => { setAttempt("2"); go("Task", { task: taskKey, tab: "Logs" }); }}>Open log</Button>], ["1", <StatusBadge status="TIMED_OUT"/>, "60 s", <Button variant="outline" onClick={() => { setAttempt("1"); go("Task", { task: taskKey, tab: "Logs" }); }}>Open archived log</Button>]] : [["1", <StatusBadge status={task.state}/>, task.duration, "Current attempt"]]}/>}
      </div></>;
  } else if (view === "Statistics") {
    const rows = [["merge_ledger", "FAILED", 84320, 0, 12, 24], ["stage_ledger", "SUCCESS", 84320, 84320, 0, 19], ["verify_manifest", "SUCCESS", null, null, null, 3], ["rebuild_totals", "OPEN", null, null, null, null]] as const;
    content = <>{header("Run #18422", "NIGHTLY_LEDGER · finance · 27 Nov 2026")}<StatusBadge status="FAILED"/><Tabs tabs={["Graph","List","Gantt","Events","Statistics"].map((id) => ({id, label: id}))} value={query.get("tab") ?? "Statistics"} onChange={(value) => go("Statistics", { tab: value })}/>{(query.get("tab") ?? "Statistics") === "Statistics" ? <><SelectField label="Sort by" value={sort} onChange={setSort}><option>Task</option><option>Duration</option><option>Source rows</option></SelectField><Grid headings={["Task","State","Source rows","Applied","Rejected","Duration"]} rows={[...rows].sort((a,b) => sort === "Task" ? a[0].localeCompare(b[0]) : (b[sort === "Duration" ? 5 : 2] ?? -1) - (a[sort === "Duration" ? 5 : 2] ?? -1)).map(([name, state, read, applied, rejected, duration]) => [<Link className="text-accent" to={url("Task", {task: name === "verify_manifest" ? "python" : name === "rebuild_totals" ? "waiting" : "sql"})}>{name}</Link>, <StatusBadge status={state}/>, read?.toLocaleString() ?? "—", applied?.toLocaleString() ?? "—", rejected ?? "—", duration === null ? "—" : duration + " s"])}/></> : <Notice info>Existing run view · select Statistics to review the new tab.</Notice>}</>;
  } else if (view === "Agents") {
    content = <>{header("Agents", "Worker processes that claim tasks, by pool · updated 03:06 UTC")}{[["worker-east-01","warehouse-heavy","0 of 4 free","Linux","rebuild_totals waiting for an eligible slot"],["worker-east-02","default","2 of 4 free","Linux","CATALOG_LOAD #18423 · load_products · PID 29104 · 285 MiB · 0.72 cores"],["worker-lab-01","validation","1 of 2 free","macOS","verify_manifest · PID 8740 · Not sampled"]].map(([name,pool,free,os,detail]) => <details key={name} className={panel + " p-4"} open={name === "worker-east-02" || undefined}><summary className="cursor-pointer"><strong>{name}</strong> <StatusBadge status="ACTIVE"/> <span className="text-sm text-muted">{pool} · {free}</span></summary><div className="mt-3 border-t border-border pt-3 text-sm"><p className="mb-1 text-muted">{os} · heartbeat 03:05:55 UTC</p>{detail}</div></details>)}</>;
  } else {
    content = <>{header("Alert content", "Delivery preview · on-call email")}<article className={panel + " space-y-4 p-4 sm:max-w-2xl"}><EnvironmentBadge env={production}/><h2 className="text-lg font-semibold">[PROD] NIGHTLY_LEDGER #18422 failed</h2><FactList><Fact label="Project">finance</Fact><Fact label="Task / attempt">merge_ledger / 2</Fact><Fact label="Failure class">Transient</Fact><Fact label="Error code">TARGET_WRITE_FAILED</Fact><Fact label="SLA deadline">03:20 UTC</Fact></FactList><Link className="text-accent underline" to={url("Task")}>Open run #18422</Link></article></>;
  }
  return <div className="min-h-dvh bg-bg text-fg"><header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-surface px-4 py-2"><Link to={url("Home")} className="flex items-center gap-2 font-semibold"><Logo className="size-7"/>etl-craft</Link><Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={() => { const next = theme === "light" ? "dark" : "light"; setTheme(next); applyTheme(next, true); }}>{theme === "light" ? <Moon/> : <Sun/>}</Button></header><div className="md:grid md:grid-cols-[208px_minmax(0,1fr)]"><nav aria-label="Review screens" className="flex flex-wrap gap-1 border-b border-border bg-sidebar p-2 md:min-h-[calc(100dvh-49px)] md:flex-col md:border-r"><div className="hidden px-3 py-2 text-xs text-muted md:block">Operations</div>{views.map((page) => <Link key={page} to={url(page)} aria-current={view === page ? "page" : undefined} className={`rounded px-3 py-2 text-sm hover:bg-sidebar-active ${view === page ? "bg-sidebar-active font-semibold" : ""}`}>{page}</Link>)}</nav><main className="grid min-w-0 content-start gap-4 p-4 md:p-6">{content}</main></div></div>;
}
applyTheme(initialTheme());
createRoot(document.getElementById("root")!).render(<BrowserRouter><Review/></BrowserRouter>);
