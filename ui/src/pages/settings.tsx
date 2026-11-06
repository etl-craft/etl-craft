import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Field, inputClass, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { failureText, useHealth, useIdentity, useTimezone } from "@/hooks";
import { postJson } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { applyTheme } from "@/lib/theme";
import type { PersonalSettings } from "@/lib/types";
import { useDocumentTitle } from "@/title";

export function Settings() {
  useDocumentTitle("Personal settings");
  const identity = useIdentity();
  const health = useHealth();
  const tz = useTimezone();
  const toast = useToast();
  const client = useQueryClient();
  const [edit, setEdit] = React.useState<PersonalSettings | null>(null);
  const saved = identity.data?.settings;
  const form = edit ?? saved;
  const save = useMutation({
    mutationFn: (body: PersonalSettings) => postJson<PersonalSettings>("/api/v1/account/settings", { theme: body.theme, timezone: body.timezone, default_project: body.default_project ?? "", page_size: body.page_size, time_display: body.time_display }),
    onSuccess: (result) => {
      if (result.theme === "light" || result.theme === "dark") applyTheme(result.theme, true);
      toast("Settings saved.");
      setEdit(null);
      void client.invalidateQueries({ queryKey: ["whoami"] });
    },
  });
  if (!form) return <Loading what="settings" />;
  const set = (patch: Partial<PersonalSettings>) => setEdit({ ...form, ...patch });
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Personal settings" subtitle="These settings belong to your account and follow you across browsers." />
      <Card className="max-w-xl p-5">
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(form);
          }}
        >
          <SelectField label="Theme" value={form.theme} onChange={(theme) => set({ theme })}>
            {["system", "light", "dark"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </SelectField>
          <Field label="Timezone (IANA name, such as UTC, Europe/London or Asia/Kolkata)">
            <input required className={inputClass} value={form.timezone} onChange={(e) => set({ timezone: e.target.value })} />
          </Field>
          <SelectField label="Default project (opened after sign-in)" value={form.default_project ?? ""} onChange={(p) => set({ default_project: p || null })}>
            <option value="">All visible projects</option>
            {(health.data?.projects ?? []).map((p) => (
              <option key={p.project}>{p.project}</option>
            ))}
          </SelectField>
          <Field label="Page size (1 to 100)">
            <input required type="number" min={1} max={100} className={inputClass} value={form.page_size} onChange={(e) => set({ page_size: Number(e.target.value) })} />
          </Field>
          <SelectField label="Time display" value={form.time_display} onChange={(time_display) => set({ time_display })}>
            {["relative", "absolute"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </SelectField>
          {save.isError ? <Notice>{failureText(save.error)}</Notice> : null}
          <div>
            <Button type="submit" variant="primary" disabled={!edit || save.isPending}>
              {save.isPending ? "Saving…" : "Save settings"}
            </Button>
          </div>
        </form>
      </Card>
      <p className="m-0 text-sm text-muted">Last sign-in: {formatTime(identity.data?.last_signin ?? null, tz)}</p>
    </div>
  );
}
