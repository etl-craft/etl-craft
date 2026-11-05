import { useQueries } from "@tanstack/react-query";
import { CircleCheck, CircleX, Clock, Hourglass, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { EnvironmentBadge } from "@/components/environment-badge";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader } from "@/components/ui/card";
import { useHealth, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatAgo, formatTime } from "@/lib/format";
import type { History, ProjectCounts } from "@/lib/types";
import { useDocumentTitle } from "@/title";
import { cn } from "@/lib/utils";

const PAGES = 6;

/** Page back through the project's runs until the window starts, so a busy project still lists its failures. */
async function failuresSince(code: string, since: string): Promise<History> {
  const entries: History["entries"] = [];
  let before: number | undefined;
  for (let page = 0; page < PAGES; page += 1) {
    const batch = await getJson<History>(`${project(code)}/history`, { all: true, limit: 100, before });
    entries.push(...batch.entries);
    const oldest = batch.entries[batch.entries.length - 1];
    const next = batch.before ?? (batch.entries.length >= 100 ? oldest?.pipeline_run_id : undefined);
    if (next === undefined || !oldest || (oldest.start_date ?? "") < since) break;
    before = next;
  }
  return { entries, before: null };
}

function Metric({ label, value, icon: Icon, tone }: { label: string; value: number; icon: typeof CircleX; tone: string }) {
  const quiet = value === 0;
  return (
    <div className="grid gap-1">
      <dt className="flex items-center gap-1.5 text-xs text-muted">
        <Icon aria-hidden className="size-3.5" /> {label}
      </dt>
      <dd className={cn("num m-0 font-semibold", quiet ? "text-xl text-muted" : cn("text-3xl", tone))}>{value}</dd>
    </div>
  );
}

function ProjectCard({ p, failures, since }: { p: ProjectCounts; failures: History["entries"]; since: string }) {
  const tz = useTimezone();
  const loud = p.failed > 0;
  return (
    <Card className={cn(loud && "border-bad/60")}>
      <CardHeader>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Link to={`/projects/${encodeURIComponent(p.project)}/runs`} className="truncate text-base font-semibold hover:underline">
            {p.project}
          </Link>
          <EnvironmentBadge env={{ type: p.environment_type, name: p.environment_name }} />
        </div>
        <span className="text-xs text-muted">{p.governance}</span>
      </CardHeader>
      <dl className="m-0 grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
        <Metric label="Failed" value={p.failed} icon={CircleX} tone="text-bad" />
        <Metric label="Running" value={p.running} icon={LoaderCircle} tone="text-run" />
        <Metric label="SLA misses" value={p.sla_misses} icon={Clock} tone="text-warn" />
        <Metric label="Queued tasks" value={p.queued_tasks} icon={Hourglass} tone="text-fg" />
      </dl>
      {loud ? (
        <div className="border-t border-border">
          <p className="px-4 pt-3 text-xs font-semibold uppercase tracking-wide text-muted">Recent failures</p>
          <ul className="m-0 list-none p-2">
            {failures.slice(0, 5).map((run) => (
              <li key={run.pipeline_run_id}>
                <Link
                  to={`/projects/${encodeURIComponent(p.project)}/runs/${encodeURIComponent(run.pipeline_code)}/${run.pipeline_run_id}`}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-1.5 hover:bg-surface-2"
                >
                  <StatusBadge status={run.status} />
                  <span className="font-medium">{run.pipeline_code}</span>
                  <span className="num text-muted">#{run.pipeline_run_id}</span>
                  <span className="ml-auto text-xs text-muted" title={formatTime(run.end_date ?? run.start_date, tz)}>
                    {formatAgo(run.end_date ?? run.start_date)}
                  </span>
                </Link>
              </li>
            ))}
            {failures.length === 0 ? <li className="px-2 py-1.5 text-muted">Failures since {formatTime(since, tz)} are in the runs list.</li> : null}
          </ul>
        </div>
      ) : (
        <p className="flex items-center gap-2 border-t border-border px-4 py-3 text-sm text-muted">
          <CircleCheck aria-hidden className="size-4 text-ok" /> No failures in the last 24 hours.
        </p>
      )}
    </Card>
  );
}

export function Home() {
  useDocumentTitle("Home");
  const health = useHealth();
  const projects = health.data?.projects ?? [];
  const since = health.data?.window_start ?? "";
  const failing = projects.filter((p) => p.failed > 0);
  const histories = useQueries({
    queries: failing.map((p) => ({
      queryKey: ["failures", p.project, since],
      queryFn: () => failuresSince(p.project, since),
    })),
  });
  const byProject = new Map(
    failing.map((p, index) => [
      p.project,
      (histories[index]?.data?.entries ?? []).filter((run) => run.status === "FAILED" && (run.end_date ?? run.start_date ?? "") >= since),
    ]),
  );
  const totalFailed = projects.reduce((sum, p) => sum + p.failed, 0);
  return (
    <div className="grid grid-cols-1 gap-6">
      <div>
        <h1 className="m-0 text-2xl font-semibold">Home</h1>
        <p className="mt-1 text-sm text-muted">
          {health.isError
            ? "The project list could not be read."
            : totalFailed > 0
              ? `${totalFailed} failed run${totalFailed === 1 ? "" : "s"} in the last 24 hours across ${failing.length} project${failing.length === 1 ? "" : "s"}.`
              : "Everything that ran in the last 24 hours succeeded."}
        </p>
      </div>
      {health.isError ? (
        <p role="alert" className="rounded-md bg-bad-bg p-3 text-sm text-bad">
          {(health.error as Error).message}
        </p>
      ) : null}
      {health.isPending ? <p className="text-muted">Loading projects…</p> : null}
      <div className="grid gap-4 xl:grid-cols-2">
        {[...projects]
          .sort((a, b) => b.failed - a.failed || b.running - a.running || a.project.localeCompare(b.project))
          .map((p) => (
            <ProjectCard key={p.project} p={p} failures={byProject.get(p.project) ?? []} since={since} />
          ))}
      </div>
      {health.isSuccess && projects.length === 0 ? <p className="text-muted">No project is visible to this account.</p> : null}
    </div>
  );
}
