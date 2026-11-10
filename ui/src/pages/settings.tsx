import { useMutation, useQueryClient } from "@tanstack/react-query";
import { When } from "@/components/when";
import * as React from "react";
import { Link } from "react-router-dom";
import { inputClass, Loading, Notice, PageHeader, SelectField, SettingRow } from "@/components/common";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { failureText, useHealth, useIdentity } from "@/hooks";
import { postJson } from "@/lib/api";
import { passwordPath } from "@/lib/routes";
import { applyDensity, applyTheme, storedDensity, type Density } from "@/lib/theme";
import { readWrap, saveWrap } from "@/components/data-table";
import type { PersonalSettings } from "@/lib/types";
import { useDocumentTitle } from "@/title";

export function Settings() {
  useDocumentTitle("Personal settings");
  const identity = useIdentity();
  const health = useHealth();
  const toast = useToast();
  const client = useQueryClient();
  const [edit, setEdit] = React.useState<PersonalSettings | null>(null);
  const [first, setFirst] = React.useState<string | null>(null);
  const [last, setLast] = React.useState<string | null>(null);
  // Only names the person changed are sent, and only where the deployment lets accounts edit them.
  const names = () => ({ ...(first === null ? {} : { first_name: first }), ...(last === null ? {} : { last_name: last }) });
  const [density, setDensity] = React.useState<Density>(storedDensity);
  const saved = identity.data?.settings;
  const form = edit ?? saved;
  const save = useMutation({
    mutationFn: (body: PersonalSettings) => postJson<PersonalSettings>("/api/v1/account/settings", { ...names(), theme: body.theme, timezone: body.timezone, default_project: body.default_project ?? "", page_size: body.page_size, time_display: body.time_display }),
    onSuccess: (result) => {
      if (result.theme === "light" || result.theme === "dark") applyTheme(result.theme, true);
      toast("Settings saved.");
      setEdit(null);
      setFirst(null);
      setLast(null);
      void client.invalidateQueries({ queryKey: ["whoami"] });
    },
  });
  if (!form) return <Loading what="settings" />;
  const set = (patch: Partial<PersonalSettings>) => setEdit({ ...form, ...patch });
  const radios = <T extends string>(name: string, value: string, options: [T, string][], pick: (v: T) => void) => (
    <div className="flex flex-wrap gap-4">
      {options.map(([v, label]) => (
        <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="radio" name={name} value={v} checked={value === v} onChange={() => pick(v)} />
          {label}
        </label>
      ))}
    </div>
  );
  return (
    <div className="flex min-h-full flex-col">
    <PageHeader title="Personal settings" subtitle="These settings belong to your account and follow you across browsers." />
    <form
      className="flex flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(form);
      }}
    >
      {identity.data?.names_editable ? (
        <>
          <SettingRow title="First name" hint="Shown in the account menu.">
            <input aria-label="First name" maxLength={128} className={inputClass} value={first ?? identity.data.first_name ?? ""} onChange={(e) => setFirst(e.target.value)} />
          </SettingRow>
          <SettingRow title="Last name">
            <input aria-label="Last name" maxLength={128} className={inputClass} value={last ?? identity.data.last_name ?? ""} onChange={(e) => setLast(e.target.value)} />
          </SettingRow>
        </>
      ) : (
        <SettingRow title="Name" hint="Set by your administrator or your single sign-on provider.">
          <span className="text-sm">{[identity.data?.first_name, identity.data?.last_name].filter(Boolean).join(" ") || <span className="text-muted">Not set</span>}</span>
        </SettingRow>
      )}
      <SettingRow title="Theme" hint="Light, dark, or follow your system.">
        {radios("theme", form.theme, [["system", "Match my system"], ["light", "Light"], ["dark", "Dark"]], (theme) => set({ theme }))}
      </SettingRow>
      <SettingRow title="Table density" hint="Row height in every table. Kept in this browser.">
        {radios("density", density, [["compact", "Compact"], ["default", "Default"], ["comfortable", "Comfortable"]] as [Density, string][], (value) => {
          setDensity(value);
          applyDensity(value, true);
        })}
      </SettingRow>
      <SettingRow title="Wrap long text" hint="Takes effect when a page is opened. Kept in this browser.">
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" defaultChecked={readWrap()} onChange={(event) => saveWrap(event.target.checked)} />
          Wrap long text in tables to two lines
        </label>
      </SettingRow>
      <SettingRow title="Timezone" hint="Every time on a page is shown in this zone.">
        <input required list="timezones" className={inputClass} value={form.timezone} onChange={(e) => set({ timezone: e.target.value })} placeholder="UTC, Europe/London, Asia/Kolkata" />
        <datalist id="timezones">
          {(typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC"]).map((zone) => (
            <option key={zone} value={zone} />
          ))}
        </datalist>
      </SettingRow>
      <SettingRow title="Time display" hint="Relative shows “5 min ago” with the exact time on hover.">
        {radios("time_display", form.time_display, [["relative", "Relative"], ["absolute", "Exact"]], (time_display) => set({ time_display }))}
      </SettingRow>
      <SettingRow title="Default project" hint="Opened after you sign in.">
        <SelectField label="Default project" hideLabel value={form.default_project ?? ""} onChange={(p) => set({ default_project: p || null })}>
          <option value="">All visible projects</option>
          {(health.data?.projects ?? []).map((p) => (
            <option key={p.project}>{p.project}</option>
          ))}
        </SelectField>
      </SettingRow>
      <SettingRow title="Page size" hint="Rows per page in long lists, 1 to 100.">
        <input required type="number" min={1} max={100} aria-label="Page size" className={inputClass} value={form.page_size} onChange={(e) => set({ page_size: Number(e.target.value) })} />
      </SettingRow>
      <SettingRow title="Password" hint="Forgot it? Ask an administrator to reset it; they cannot read the old one.">
        {identity.data?.local_password === false ? (
          <span className="text-sm text-muted">Managed by your identity provider.</span>
        ) : (
          <Link to={passwordPath} className="inline-flex h-9 items-center rounded-sm border border-border-strong px-3 text-sm hover:bg-surface-2">
            Change password
          </Link>
        )}
      </SettingRow>
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <Button type="submit" variant="primary" disabled={(!edit && first === null && last === null) || save.isPending}>
          {save.isPending ? "Saving…" : "Save settings"}
        </Button>
        {save.isError ? <Notice className="py-1.5">{failureText(save.error)}</Notice> : null}
        <span className="ml-auto text-xs text-muted">Last sign-in: <When iso={identity.data?.last_signin} empty="never" /></span>
      </div>
    </form>
    </div>
  );
}
