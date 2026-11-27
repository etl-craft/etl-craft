import { useMutation } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { SelectField } from "@/components/common";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "@/components/dropdown";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { useProjectInfo } from "@/hooks";
import { postJson, project } from "@/lib/api";
import type { RunView } from "@/lib/types";

const choices = [
  { id: "RECOVER", label: "Recover failed tasks", effect: "Resume unfinished work under the same run." },
  { id: "TASK", label: "Recover from a task", effect: "Rerun the task and its eligible downstream tasks under the same run." },
  { id: "RESTART", label: "Rerun the whole run", effect: "Prepare a new run. Write actions such as append may write rows again." },
] as const;

type Choice = (typeof choices)[number];
type PlannedTask = { task_code: string; reason: string };
type Preview = { will_run: PlannedTask[]; will_skip: PlannedTask[]; depends_on_upstream: PlannedTask[]; start_condition?: string | null };

export function RunRecovery({ code, run, task, tasks, onDone }: {
  code: string; run: RunView; task: string | null; tasks: string[]; onDone: () => void;
}) {
  const [choice, setChoice] = useState<Choice | null>(null);
  return <>
    <DropdownMenu>
      <DropdownTrigger asChild><Button>Recover <ChevronDown aria-hidden className="size-4" /></Button></DropdownTrigger>
      <DropdownContent align="end">
        {choices.map((option) => <DropdownItem key={option.id} onSelect={() => setChoice(option)}>{option.label}</DropdownItem>)}
      </DropdownContent>
    </DropdownMenu>
    {choice ? <RecoveryDialog code={code} run={run} initialTask={task} tasks={tasks} choice={choice} onClose={() => setChoice(null)} onDone={onDone} /> : null}
  </>;
}

function RecoveryDialog({ code, run, initialTask, tasks, choice, onClose, onDone }: {
  code: string; run: RunView; initialTask: string | null; tasks: string[]; choice: Choice; onClose: () => void; onDone: () => void;
}) {
  const [task, setTask] = useState(initialTask ?? "");
  const [plan, setPlan] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const info = useProjectInfo(code).project;
  const toast = useToast();
  const fromTask = choice.id === "TASK";
  const endpoint = `${project(code)}/${fromTask ? "runs" : "controls"}`;
  const submit = useMutation({
    mutationFn: async (reason: string) => {
      const scope = { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, reason };
      const request = fromTask ? { ...scope, task_code: task, rerun: true, with_downstream: true } : { ...scope, action: choice.id };
      setError(null);
      if (!plan) {
        setPlan(await postJson<Preview>(endpoint, { ...request, dry_run: true }));
      } else {
        const result = await postJson<{ message: string }>(endpoint, request);
        toast(result.message);
        onDone();
        onClose();
      }
    },
    onError: (failure) => {
      setPlan(null);
      setError(failure.message);
    },
  });
  function clearPreview() {
    setPlan(null);
    setError(null);
  }
  return <ConfirmDialog open title={choice.label} action={plan ? choice.label : "Preview recovery"}
    effect={choice.effect} projectCode={code} env={info && { type: info.environment_type, name: info.environment_name }}
    canSubmit={!!info && (!fromTask || !!task)} busy={submit.isPending} error={error}
    onReasonChange={clearPreview} onConfirm={(reason) => submit.mutate(reason)} onClose={onClose}>
    {fromTask ? <SelectField label="Start from task" value={task} disabled={submit.isPending}
      onChange={(value) => { setTask(value); clearPreview(); }}>
      <option value="">Choose a task</option>
      {tasks.map((name) => <option key={name} value={name}>{name}</option>)}
    </SelectField> : null}
    {plan ? <div className="grid max-h-[42dvh] gap-2 overflow-auto">
      {plan.start_condition ? <p className="break-words text-sm">The new run starts when <code className="break-all" translate="no">{plan.start_condition}</code> is met.</p> : null}
      <PlanGroup label="Will run" tasks={plan.will_run} />
      <PlanGroup label="Will skip" tasks={plan.will_skip} />
      <PlanGroup label="Depends on upstream" tasks={plan.depends_on_upstream} />
      {plan.depends_on_upstream.length ? <p className="text-xs text-muted">These decisions resolve as the run proceeds.</p> : null}
    </div> : null}
  </ConfirmDialog>;
}

function PlanGroup({ label, tasks }: { label: string; tasks: PlannedTask[] }) {
  return <section className="grid gap-1">
    <h3 className="text-sm font-semibold">{label}</h3>
    {tasks.length ? <ul className="grid gap-1 text-sm">
      {tasks.map((task) => <li key={task.task_code} className="break-words"><strong>{task.task_code}</strong> · {task.reason}</li>)}
    </ul> : <p className="text-sm text-muted">None</p>}
  </section>;
}
