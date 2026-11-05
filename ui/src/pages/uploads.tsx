import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Upload } from "lucide-react";
import * as React from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Field, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { failureText, useProjectInfo, useTimezone } from "@/hooks";
import { getJson, postForm, project } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { UploadReceipt, UploadRow } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<UploadRow>();

/** The state of a file as its owner understands it: loaded, refused, failed, in a run, or waiting. */
const stateOf = (f: UploadRow): { status: string; label: string } =>
  f.status === "LOADED"
    ? { status: "SUCCESS", label: "Loaded" }
    : f.status === "REFUSED" || f.status === "FAILED"
      ? { status: "FAILED", label: f.status.charAt(0) + f.status.slice(1).toLowerCase() }
      : f.pipeline_run_id
        ? { status: "IN-PROGRESS", label: "In run" }
        : { status: "QUEUED", label: "Queued" };

export function Uploads() {
  const { project: code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tz = useTimezone();
  const toast = useToast();
  const client = useQueryClient();
  const info = useProjectInfo(code);
  useDocumentTitle("Uploads", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const eligible = useQuery({ queryKey: ["upload-pipelines", code], queryFn: () => getJson<{ pipelines: { pipeline_code: string; pipeline_name: string }[] }>(`${project(code)}/uploads/pipelines`) });
  const pipelines = eligible.data?.pipelines ?? [];
  const chosen = params.get("pipeline") ?? pipelines[0]?.pipeline_code ?? "";
  const files = useQuery({
    queryKey: ["uploads", code, chosen],
    queryFn: () => getJson<{ uploads: UploadRow[] }>(`${project(code)}/uploads`, { pipeline_code: chosen }),
    enabled: chosen !== "",
    refetchInterval: 10_000,
  });
  const [file, setFile] = React.useState<File | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const send = useMutation({
    mutationFn: (selected: File) => {
      const form = new FormData();
      form.append("file", selected);
      return postForm<UploadReceipt>(`${project(code)}/uploads`, form, { pipeline_code: chosen });
    },
    onSuccess: (receipt) => {
      toast(
        receipt.pipeline_run_id
          ? `Upload ${receipt.upload_id} received; run ${receipt.pipeline_run_id} validates and loads it.`
          : `Upload ${receipt.upload_id} received; it waits for run ${receipt.waiting_behind_run_id} to end, then runs.`,
      );
      setFile(null);
      if (input.current) input.current.value = "";
      void client.invalidateQueries({ queryKey: ["uploads"] });
    },
  });

  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Uploads" subtitle={code} />
      {eligible.isError ? <Notice>{(eligible.error as Error).message}</Notice> : null}
      {eligible.isPending ? <Loading what="your pipelines" /> : null}
      {eligible.isSuccess && pipelines.length === 0 ? (
        <Card className="p-4 text-muted">No pipeline takes uploads from you here. A developer marks a pipeline for uploads, and an administrator or the pipeline&apos;s manager grants CAN_UPLOAD on it.</Card>
      ) : null}
      {pipelines.length ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Upload a file</CardTitle>
            </CardHeader>
            <form
              className="grid gap-4 p-4 sm:max-w-xl"
              onSubmit={(event) => {
                event.preventDefault();
                if (file) send.mutate(file);
              }}
            >
              <p className="m-0 text-[13px] text-muted">One pipe-delimited CSV or TXT file, or an XLSX workbook. The pipeline&apos;s validation script checks it before anything is loaded.</p>
              <SelectField label="Pipeline" value={chosen} onChange={(value) => setParams({ pipeline: value })}>
                {pipelines.map((p) => (
                  <option key={p.pipeline_code} value={p.pipeline_code}>
                    {p.pipeline_code}
                    {p.pipeline_name && p.pipeline_name !== p.pipeline_code ? ` · ${p.pipeline_name}` : ""}
                  </option>
                ))}
              </SelectField>
              <Field label="File">
                <input ref={input} type="file" required accept=".csv,.txt,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="text-sm file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-fg hover:file:bg-surface-2" />
              </Field>
              {send.isError ? <Notice>{failureText(send.error)}</Notice> : null}
              <Button type="submit" variant="primary" className="w-fit" disabled={!file || send.isPending}>
                <Upload className="size-4" aria-hidden /> {send.isPending ? "Uploading…" : "Upload"}
              </Button>
            </form>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Recent files for {chosen}</CardTitle>
            </CardHeader>
            <DataTable
              label="Recent files"
              data={files.data?.uploads ?? []}
              empty={files.isSuccess ? `No files uploaded to ${chosen} yet.` : undefined}
              columns={[
                columns.accessor("upload_id", { header: "Upload", cell: (c) => <span className="num">{c.getValue()}</span> }),
                columns.accessor("file_name", { header: "File", cell: (c) => <span className="break-all font-medium">{c.getValue()}</span> }),
                columns.accessor("size_bytes", { header: "Size", cell: (c) => <span className="num whitespace-nowrap">{c.getValue().toLocaleString("en-GB")} bytes</span> }),
                columns.accessor("stored_name", { header: "Stored name", cell: (c) => <span className="break-all text-muted">{c.getValue() ?? "—"}</span> }),
                columns.accessor("account", { header: "Uploaded by" }),
                columns.accessor("uploaded_at", { header: "Uploaded", cell: (c) => <span className="num whitespace-nowrap">{formatTime(c.getValue(), tz)}</span> }),
                columns.display({ id: "state", header: "State", cell: (c) => <StatusBadge {...stateOf(c.row.original)} /> }),
                columns.display({
                  id: "run",
                  header: "Run",
                  cell: (c) => {
                    const f = c.row.original;
                    return f.pipeline_run_id ? (
                      <span className="flex items-center gap-2">
                        <Link className="num text-accent hover:underline" to={runPath(code, chosen, f.pipeline_run_id)}>
                          #{f.pipeline_run_id}
                        </Link>
                        {f.run_status ? <StatusBadge status={f.run_status} /> : null}
                      </span>
                    ) : (
                      <span className="text-muted">Waiting</span>
                    );
                  },
                }),
                columns.accessor("reason", { header: "Reason", cell: (c) => <span className="break-words">{c.getValue() ?? ""}</span> }),
              ]}
            />
          </Card>
        </>
      ) : null}
    </div>
  );
}
