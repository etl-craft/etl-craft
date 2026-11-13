import { useQuery, useQueryClient } from "@tanstack/react-query";
import { When } from "@/components/when";
import * as React from "react";
import { useParams } from "react-router-dom";
import { EmptyState, Loading, Notice, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { failureText, useProjectInfo } from "@/hooks";
import { getJson, postJson, project } from "@/lib/api";
import type { AuditAction, ConsoleResult } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useDocumentTitle } from "@/title";

interface Line {
  kind: "command" | "output" | "error" | "note";
  text: string;
}

/** One etl-craft command line, run as the signed-in person through the same actions as the CLI. */
export function Console() {
  const { project: code = "" } = useParams();
  const client = useQueryClient();
  const info = useProjectInfo(code);
  useDocumentTitle("Console", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const commands = useQuery({ queryKey: ["console-commands", code], queryFn: () => getJson<{ available: boolean; commands: Record<string, string[]> }>(`/ui/projects/${encodeURIComponent(code)}/console/commands`) });
  const recent = useQuery({ queryKey: ["console-history", code], queryFn: () => getJson<{ actions: AuditAction[] }>(`${project(code)}/audit`, { mine: true }) });
  const [lines, setLines] = React.useState<Line[]>([{ kind: "note", text: `etl-craft console · project ${code} · type help for the commands you can run` }]);
  const [value, setValue] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [failure, setFailure] = React.useState<string | null>(null);
  const recalled = React.useRef<string[]>([]);
  const position = React.useRef(0);
  const output = React.useRef<HTMLDivElement>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const known = commands.data?.commands ?? {};
  const print = (...added: Line[]) => setLines((now) => [...now, ...added]);

  React.useEffect(() => {
    output.current?.scrollTo({ top: output.current.scrollHeight });
  }, [lines]);

  const run = async (line: string) => {
    print({ kind: "command", text: `$ etl-craft ${line}` });
    recalled.current.push(line);
    position.current = recalled.current.length;
    setBusy(true);
    setFailure(null);
    try {
      const result = await postJson<ConsoleResult>(`/ui/projects/${encodeURIComponent(code)}/console`, { line });
      const added: Line[] = [];
      if (result.output) added.push({ kind: "output", text: result.output });
      if (result.error) added.push({ kind: "error", text: result.error });
      if (result.exit_code) added.push({ kind: "note", text: `exit ${result.exit_code}` });
      print(...added);
      void client.invalidateQueries({ queryKey: ["console-history"] });
    } catch (error) {
      setFailure(failureText(error));
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  };

  const complete = () => {
    const words = value.split(/\s+/);
    const last = words[words.length - 1] ?? "";
    const options = words.length === 1 ? Object.keys(known) : (known[words[0] ?? ""] ?? []);
    const matches = options.filter((option) => option.startsWith(last)).sort();
    if (matches.length === 1) setValue([...words.slice(0, -1), matches[0]].join(" ") + " ");
    else if (matches.length > 1) print({ kind: "note", text: matches.join("  ") });
  };

  if (commands.data && !commands.data.available) {
    return (
      <div className="grid gap-4">
        <PageHeader title="Command console" />
        <Notice>The console runs in servers started with etl-craft ui or etl-craft controller.</Notice>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader
        title="Command console"
        subtitle={`Type an etl-craft command as you would in a terminal; it runs in project ${code} as you, through the same actions as the CLI, and prints the CLI's output (--format json for JSON). Tab completes commands and flags; ↑ and ↓ recall lines. Host commands, config files, sign-in and server files stay in the CLI.`}
      />
      {failure ? <Notice>{failure}</Notice> : null}
      <Card>
        <CardHeader>
          <CardTitle>Console</CardTitle>
          <span className="text-xs text-muted">Example: status --pipeline-code ORDERS</span>
        </CardHeader>
        <div ref={output} role="log" aria-label="Console output" aria-live="polite" tabIndex={0} className="h-80 overflow-auto whitespace-pre-wrap break-words bg-surface-2 p-3 font-mono text-xs leading-5">
          {lines.map((line, i) => (
            <div key={i} className={cn(line.kind === "command" && "font-semibold", line.kind === "error" && "text-bad", line.kind === "note" && "text-muted")}>
              {line.text}
            </div>
          ))}
        </div>
        <form
          className="flex items-center gap-2 border-t border-border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            const line = value.trim();
            setValue("");
            if (line) void run(line);
          }}
        >
          <label htmlFor="console-input" className="font-mono text-xs text-muted">
            $ etl-craft
          </label>
          <input
            id="console-input"
            ref={input}
            value={value}
            disabled={busy}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Tab" && value) {
                event.preventDefault();
                complete();
              } else if (event.key === "ArrowUp" && position.current > 0) {
                event.preventDefault();
                setValue(recalled.current[--position.current] ?? "");
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                position.current = Math.min(recalled.current.length, position.current + 1);
                setValue(recalled.current[position.current] ?? "");
              }
            }}
            className="h-control min-w-0 flex-1 rounded-md border border-border-strong bg-surface px-2 font-mono text-sm"
          />
          <Button type="submit" variant="primary" disabled={busy || !value.trim()}>
            Run
          </Button>
        </form>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Commands you can run here</CardTitle>
          </CardHeader>
          {commands.isPending ? <Loading what="commands" className="p-4" /> : null}
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-4">
            {Object.keys(known)
              .sort()
              .map((name) => (
                <li key={name}>
                  <button type="button" onClick={() => { setValue(name + " "); input.current?.focus(); }} className="cursor-pointer rounded-sm border border-border bg-surface px-2 py-1 font-mono text-xs hover:bg-surface-2">
                    {name}
                  </button>
                </li>
              ))}
          </ul>
        </Card>
        <Card>
          <CardHeader>
            <div className="grid">
              <CardTitle>Your recent requests</CardTitle>
              <span className="text-xs text-muted">Requests that changed something, from the audit; reads are not recorded.</span>
            </div>
          </CardHeader>
          <ul className="m-0 grid list-none gap-1 p-4 text-[13px]">
            {(recent.data?.actions ?? []).slice(-15).reverse().map((a) => (
              <li key={a.action_id}>
                <span className="text-muted"><When iso={a.at} /></span> · <span className="font-mono text-xs">{a.command}</span> · {a.outcome}
              </li>
            ))}
            {recent.isSuccess && recent.data.actions.length === 0 ? <li><EmptyState title="No requests yet." nextStep="Run a change command above; completed requests appear here." /></li> : null}
            {recent.isError ? <li className="text-muted">Your requests could not be read.</li> : null}
          </ul>
        </Card>
      </div>
    </div>
  );
}
