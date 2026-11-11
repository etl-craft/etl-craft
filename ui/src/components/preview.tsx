import { useMutation } from "@tanstack/react-query";
import { Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { failureText } from "@/hooks";

/** A read-only dry run: shows what a change would do, changes nothing, and so needs no confirmation. */
export function Preview({ label, run, disabled }: { label: string; run: () => Promise<unknown>; disabled?: boolean }) {
  const preview = useMutation({ mutationFn: run });
  return (
    <div className="grid gap-2">
      <Button disabled={disabled || preview.isPending} onClick={() => preview.mutate()}>
        {preview.isPending ? "Working…" : label}
      </Button>
      {preview.isError ? <Notice>{failureText(preview.error)}</Notice> : null}
      {preview.isSuccess ? <pre className="m-0 max-h-72 overflow-auto rounded-md bg-idle-bg p-3 font-mono text-xs">{JSON.stringify(preview.data, null, 2)}</pre> : null}
    </div>
  );
}
