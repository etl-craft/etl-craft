import { RunLabel } from "@/components/run-label";
import { useQueries } from "@tanstack/react-query";
import { words } from "@/lib/labels";
import { When } from "@/components/when";
import { CircleCheck, CircleX, Clock, Hourglass, LoaderCircle, type LucideIcon } from "lucide-react";
import { Link, Navigate } from "react-router-dom";
import { EmptyState, Eyebrow, Fact, FactList, Loading, Notice, PageHeader } from "@/components/common";
import { EnvironmentBadge } from "@/components/environment-badge";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader } from "@/components/ui/card";
import { useActiveProject, useHealth } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { projectHomePath, runPath, runsPath, settingsPath } from "@/lib/routes";
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

function Metric({ label, value, icon, tone }: { label: string; value: number; icon: LucideIcon; tone: string }) {
  return (
    <Fact label={label} icon={icon} valueClassName={value === 0 ? "text-xl font-semibold text-muted" : cn("text-3xl font-semibold", tone)}>
      {value}
    </Fact>
  );
}

function ProjectCard({ p, failures, since }: { p: ProjectCounts; failures: History["entries"]; since: string }) {
  const loud = p.failed > 0;
  return (
    <Card className={cn(loud && "border-bad/60")}>
      <CardHeader>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Link to={runsPath(p.project)} className="truncate text-base font-semibold hover:underline">
            {p.project}
          </Link>
          <EnvironmentBadge env={{ type: p.environment_type, name: p.environment_name }} />
        </div>
        <span className="text-xs text-muted">{words(p.governance)} governance</span>
      </CardHeader>
      <FactList className="gap-4 p-4 sm:grid-cols-4 lg:grid-cols-4">
        <Metric label="Failed" value={p.failed} icon={CircleX} tone="text-bad" />
        <Metric label="Running" value={p.running} icon={LoaderCircle} tone="text-run" />
        <Metric label="SLA misses" value={p.sla_misses} icon={Clock} tone="text-warn" />
        <Metric label="Queued tasks" value={p.queued_tasks} icon={Hourglass} tone="text-fg" />
      </FactList>
      {loud ? (
        <div className="border-t border-border">
          <Eyebrow className="px-4 pt-3">Recent failures</Eyebrow>
          <ul className="m-0 list-none p-2">
            {failures.slice(0, 5).map((run) => (
              <li key={run.pipeline_run_id}>
                <Link
                  to={runPath(p.project, run.pipeline_code, run.pipeline_run_id)}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-1.5 hover:bg-surface-2"
                >
                  <StatusBadge status={run.status} />
                  <span className="font-medium">{run.pipeline_code}</span>
                  <RunLabel id={run.pipeline_run_id} label={run.run_label} />
                  <span className="ml-auto text-xs text-muted">
                    <When iso={run.end_date ?? run.start_date} />
                  </span>
                </Link>
              </li>
            ))}
            {failures.length === 0 ? <li className="px-2 py-1.5 text-muted">Failures since <When iso={since} /> are in the runs list.</li> : null}
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

/** Home opens the project in use; the list is only for choosing when no project is known. */
export function HomeEntry() {
  const { code, ready } = useActiveProject();
  if (!ready) return <Loading what="projects" />;
  return code ? <Navigate to={projectHomePath(code)} replace /> : <ProjectList choose />;
}

/** Every project the account can see, as cards; ``choose`` says why when none is open yet. */
export function ProjectList({ choose = false }: { choose?: boolean }) {
  useDocumentTitle("Projects");
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
      <PageHeader back={null}
        title="Projects"
        subtitle={
          health.isError
            ? "The project list could not be read."
            : totalFailed > 0
              ? `${totalFailed} failed run${totalFailed === 1 ? "" : "s"} in the last 24 hours across ${failing.length} project${failing.length === 1 ? "" : "s"}.`
              : "Everything that ran in the last 24 hours succeeded."
        }
      />
      {health.isError ? <Notice>{(health.error as Error).message}</Notice> : null}
      {choose && projects.length > 1 ? (
        <Notice>
          Several projects are available and none is chosen. Open one, or set a default project in <Link to={settingsPath} className="underline">Personal settings</Link> so Home opens it.
        </Notice>
      ) : null}
      {health.isPending ? <Loading what="projects" /> : null}
      <div className="grid gap-4 xl:grid-cols-2">
        {[...projects]
          .sort((a, b) => b.failed - a.failed || b.running - a.running || a.project.localeCompare(b.project))
          .map((p) => (
            <ProjectCard key={p.project} p={p} failures={byProject.get(p.project) ?? []} since={since} />
          ))}
      </div>
      {health.isSuccess && projects.length === 0 ? <EmptyState title="No project is visible to this account.">Ask an administrator to register a project or grant you access.</EmptyState> : null}
    </div>
  );
}
