import { useNavigate, useSearchParams } from "react-router-dom";
import { Notice, PageHeader, SelectField } from "@/components/common";
import { Tabs } from "@/components/tabs";
import { useHealth, useRoleAtLeast } from "@/hooks";
import { adminPath } from "@/lib/routes";
import { useDocumentTitle } from "@/title";
import { AccessTab } from "./admin/access";
import { AccountsTab } from "./admin/accounts";
import { AnnouncementsTab } from "./admin/announcements";
import { ErasureTab } from "./admin/erasure";
import { GroupsTab } from "./admin/groups";
import { PoolsTab, ProjectsTab } from "./admin/projects";
import { TokensTab } from "./admin/tokens";

const TABS = ["accounts", "groups", "tokens", "access", "projects", "pools", "announcements", "erasure"];

export function Admin() {
  const admin = useRoleAtLeast("admin");
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const health = useHealth();
  const tab = TABS.includes(params.get("tab") ?? "") ? (params.get("tab") as string) : "accounts";
  const codes = (health.data?.projects ?? []).map((p) => p.project);
  const project = params.get("project") ?? codes[0] ?? "";
  useDocumentTitle(`Administration · ${tab}`);
  if (!admin) return <Notice>The administration page needs the admin role; ask an administrator.</Notice>;
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Administration" subtitle="Accounts, access, projects and platform settings" />
      <Tabs tabs={TABS.map((t) => ({ id: t, label: t.charAt(0).toUpperCase() + t.slice(1) }))} value={tab} onChange={(t) => navigate(adminPath(t, project))} />
      {tab === "access" || tab === "erasure" ? (
        <SelectField label="Project" compact value={project} onChange={(p) => navigate(adminPath(tab, p))}>
          {codes.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </SelectField>
      ) : null}
      <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="grid grid-cols-1">
        {tab === "accounts" ? <AccountsTab /> : null}
        {tab === "groups" ? <GroupsTab /> : null}
        {tab === "tokens" ? <TokensTab /> : null}
        {tab === "access" ? <AccessTab project={project} projects={codes} /> : null}
        {tab === "projects" ? <ProjectsTab /> : null}
        {tab === "pools" ? <PoolsTab /> : null}
        {tab === "announcements" ? <AnnouncementsTab /> : null}
        {tab === "erasure" ? <ErasureTab code={project} /> : null}
      </div>
    </div>
  );
}
