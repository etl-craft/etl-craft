import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Field, inputClass, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { failureText, useHealth, useIdentity, useTimezone } from "@/hooks";
import { postJson } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { applyDensity, applyTheme, storedDensity, type Density } from "@/lib/theme";
import { readWrap, saveWrap } from "@/components/data-table";
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
  const [density, setDensity] = React.useState<Density>(storedDensity);
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
          <fieldset className="m-0 grid gap-1.5 border-0 p-0">
            <legend className="mb-1 text-sm font-medium">Theme</legend>
            <div className="flex flex-wrap gap-4">
              {[["system", "Match my system"], ["light", "Light"], ["dark", "Dark"]].map(([value, label]) => (
                <label key={value} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="theme" value={value} checked={form.theme === value} onChange={() => set({ theme: value })} />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="m-0 grid gap-1.5 border-0 p-0">
            <legend className="mb-1 text-sm font-medium">Table density (this browser)</legend>
            <div className="flex flex-wrap gap-4">
              {(["compact", "default", "comfortable"] as Density[]).map((value) => (
                <label key={value} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="density" value={value} checked={density === value} onChange={() => { setDensity(value); applyDensity(value, true); }} />
                  {value.charAt(0).toUpperCase() + value.slice(1)}
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Timezone">
            <input required list="timezones" className={inputClass} value={form.timezone} onChange={(e) => set({ timezone: e.target.value })} placeholder="UTC, Europe/London, Asia/Kolkata" />
          </Field>
          <datalist id="timezones">
            {(typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC"]).map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
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
      <Card className="max-w-xl p-5">
        <h2 className="mt-0 text-base font-semibold">In this browser</h2>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" defaultChecked={readWrap()} onChange={(event) => saveWrap(event.target.checked)} />
          Wrap long text in tables to two lines
        </label>
        <p className="mb-0 mt-1 text-xs text-muted">Takes effect when a page is opened. Off shows one line per row.</p>
      </Card>
      <p className="m-0 text-sm text-muted">Last sign-in: {formatTime(identity.data?.last_signin ?? null, tz)}</p>
    </div>
  );
}
