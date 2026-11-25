import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { AccountsTab } from "@/pages/admin/accounts";
import { GroupsTab } from "@/pages/admin/groups";
import { RolesTab } from "@/pages/admin/roles";
import { ProjectsTab, PoolsTab } from "@/pages/admin/projects";
import { TokensTab } from "@/pages/admin/tokens";
import { AnnouncementsTab } from "@/pages/admin/announcements";
import { AlertChannelsTab } from "@/pages/admin/alert-channels";
import { AccessTab } from "@/pages/admin/access";
import { Agents } from "@/pages/agents";
import { Maintenance } from "@/pages/maintenance";
import { AttemptLog } from "@/components/attempt-details";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ScopeControls } from "@/components/scope-controls";
import { Items } from "@/pages/items";
import { TaskDefinitionPanel } from "@/components/task-definition-panel";
import { ActionButton } from "@/components/action-button";
import { ToastProvider } from "@/components/toast";
import { getJson } from "@/lib/api";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getJson: vi.fn() }));
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => vi.mocked(getJson).mockReset());
const endpoints = ["/accounts", "/accounts/role", "/accounts/password", "/groups", "/groups/members", "/roles", "/roles/actions", "/roles/actions/remove", "/access/grants", "/access/revocations", "/access/explain", "/projects", "/projects/set", "/pools", "/pools/set", "/tokens", "/announcements", "/alert-channels", "/purge", "/rehash", "/clones", "/validation"];
const cases = [
  ["accounts", <AccountsTab />, ["Add account", "Change role", "Reset password"]],
  ["groups", <GroupsTab />, ["Add group", "Add member"]],
  ["roles", <RolesTab />, ["Create role", "Add command", "Remove command", "Grant access", "Explain access"]],
  ["projects", <ProjectsTab />, ["Add project", "Change project"]],
  ["pools", <PoolsTab />, ["Add pool", "Change description"]],
  ["tokens", <TokensTab />, ["Create token"]],
  ["announcements", <AnnouncementsTab />, ["Post announcement"]],
  ["channels", <AlertChannelsTab project="default" />, ["Set channel"]],
  ["access", <AccessTab project="default" projects={["default"]} />, ["Grant access"]],
  ["maintenance", <Maintenance />, ["Preview purge", "Purge", "Clone now"]],
] as const;

it("renders every platform and maintenance page action from both server answers", async () => {
  for (const [, page, labels] of cases) {
    for (const available of [false, true]) {
      vi.mocked(getJson).mockImplementation(async path => {
        if (path.endsWith("/capabilities")) return { actions: endpoints.flatMap(endpoint => ["GET", "POST"].map(method => ({ endpoint: "/api/v1" + endpoint, method, available, reason: available ? "" : "admin role is required for this action" }))) };
        return { accounts: [], groups: [], roles: [], projects: [], pools: [], tokens: [], announcements: [], channels: [], bindings: [] };
      });
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "reader", role: "admin", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
      const actions = endpoints.flatMap(endpoint => ["GET", "POST"].map(method => ({ endpoint: "/api/v1" + endpoint, method, available, reason: available ? "" : "admin role is required for this action" })));
      client.setQueryData(["action-availability", undefined, undefined, undefined], { actions });
      client.setQueryData(["action-availability", "default", undefined, undefined], { actions });
      client.setQueryData(["health"], { projects: [{ project: "default", environment_type: "CUSTOM", governance: "STRICT" }] });
      const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/default"]}><Routes><Route path="/:project" element={<ToastProvider>{page}</ToastProvider>} /></Routes></MemoryRouter></QueryClientProvider>);
      for (const label of labels) {
        const button = await screen.findByRole("button", { name: label });
        await waitFor(() => available
          ? expect(button).not.toHaveAttribute("aria-disabled", "true")
          : expect(button).toHaveAccessibleDescription("admin role is required for this action"));
        if (!available) expect(button).toHaveAttribute("aria-disabled", "true");
      }
      view.unmount();
      client.clear();
    }
  }
});

it("fails closed when an action has no server answer", async () => {
  vi.mocked(getJson).mockImplementation(async path => path.endsWith("/capabilities") ? { actions: [] } : { projects: [] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "reader", role: "admin", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
  client.setQueryData(["health"], { projects: [{ project: "default", environment_type: "CUSTOM", governance: "STRICT" }] });
  render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider><ActionButton code="default" label="Change" title="Change" effect="Change" endpoint="/missing" body={() => ({})} describe={() => "Done"} /></ToastProvider></MemoryRouter></QueryClientProvider>);
  const button = screen.getByRole("button", { name: "Change" });
  await waitFor(() => expect(button).toHaveAccessibleDescription("Availability is unavailable."));
  expect(button).toHaveAttribute("aria-disabled", "true");
  act(() => {
    client.setQueryData(["action-availability", "default", undefined, undefined], { actions: [{ endpoint: "/api/v1/missing", method: "POST", available: true, reason: "" }] });
    client.setQueryData(["health"], { projects: [] });
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Change" })).toHaveAccessibleDescription("Project default: environment is unavailable; refresh the project information before confirming."));
  client.clear();
});


it("keeps an account menu open when the table refreshes", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "reader", role: "admin", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
  const account = { name: "reader", kind: "USER", role: "viewer", active_flag: "Y", failed_signins: 0 };
  client.setQueryData(["health"], { projects: [] });
  client.setQueryData(["admin", "/api/v1/accounts", undefined], { accounts: [account] });
  client.setQueryData(["action-availability", undefined, undefined, undefined], { actions: [] });
  client.setQueryData(["action-availability", undefined, undefined, { account_name: "reader" }], { actions: [{ endpoint: "/api/v1/accounts/disable", method: "POST", available: false, reason: "admin role is required" }] });
  render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider><AccountsTab /></ToastProvider></MemoryRouter></QueryClientProvider>);
  fireEvent.keyDown(screen.getByRole("button", { name: "Actions for reader" }), { key: "Enter" });
  expect(await screen.findByRole("menuitem", { name: "Disable" })).toHaveAccessibleDescription("admin role is required");
  act(() => client.setQueryData(["admin", "/api/v1/accounts", undefined], { accounts: [{ ...account, failed_signins: 1 }] }));
  await screen.findByRole("cell", { name: "1" });
  expect(screen.getByRole("menuitem", { name: "Disable" })).toBeVisible();
  client.clear();
});


it("keeps an agent's command menu open when the agent list refreshes", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const agent = { agent_id: 7, pool: "default", host: "agent-host", version: "0.3.0", status: "ACTIVE", heartbeat_at: "2026-11-24T00:00:00Z", attempts: [], free_cpu: 4, free_memory_mb: 2048, pending_commands: [] };
  client.setQueryData(["agents"], { agents: [agent] });
  client.setQueryData(["action-availability", undefined, undefined, undefined], { actions: [] });
  client.setQueryData(["action-availability", undefined, undefined, { agent_id: 7 }], { actions: ["DRAIN", "RESUME", "STOP"].map(() => ({ endpoint: "/api/v1/agents/commands", method: "POST", available: false, reason: "operator role is required" })) });
  render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider><Agents /></ToastProvider></MemoryRouter></QueryClientProvider>);
  fireEvent.keyDown(screen.getByRole("button", { name: "Actions for agent 7" }), { key: "Enter" });
  expect(await screen.findByRole("menuitem", { name: "Drain" })).toHaveAccessibleDescription("operator role is required");
  act(() => client.setQueryData(["agents"], { agents: [{ ...agent, pending_commands: [{ command: "DRAIN" }] }] }));
  await screen.findByRole("cell", { name: "DRAIN" });
  expect(screen.getByRole("menuitem", { name: "Drain" })).toBeVisible();
  client.clear();
});

it("keeps data actions visible with the server's task-definition refusal", () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "reader", role: "admin", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
  const reason = "OPS/load: HANDLER=PYTHON; expected SQL SCD1/SCD2; select a merge task";
  client.setQueryData(["health"], { projects: [{ project: "default", environment_type: "CUSTOM", governance: "STRICT" }] });
  client.setQueryData(["pipeline", "default", "OPS"], { pipeline_code: "OPS", paused: null, task_pauses: [] });
  client.setQueryData(["task", "default", "OPS", "load"], { task_code: "load", handler: "PYTHON", parameters: {}, merge_key: [], merge_columns: [] });
  client.setQueryData(["offset", "default", "OPS", "load"], { kind: null });
  client.setQueryData(["task-runs", "default", "OPS", "load"], { entries: [] });
  client.setQueryData(["action-availability", "default", "OPS", { task_code: "load" }], { actions: ["/values/provenance", "/values", "/values/unlock"].map(endpoint => ({ endpoint: "/api/v1" + endpoint, method: "POST", available: false, reason })) });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/default/OPS/load"]}><Routes><Route path="/:project/:pipeline/:task" element={<ToastProvider><TaskDefinitionPanel code="default" pipeline="OPS" task="load" /></ToastProvider>} /></Routes></MemoryRouter></QueryClientProvider>);
  for (const name of ["Look up", "Edit a value", "Unlock values"]) {
    expect(screen.getByRole("button", { name })).toHaveAccessibleDescription(reason);
    expect(screen.getByRole("button", { name })).toHaveAttribute("aria-disabled", "true");
  }
  client.clear();
});

it("uses the exact log availability reason before offering a read", () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "reader", role: "admin", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
  const reason = "attempt_id=7: log pending upload; wait for the agent";
  client.setQueryData(["action-availability", "default", undefined, { attempt_id: 7 }], { actions: [{ endpoint: "/api/v1/attempts/{attempt_id}/log", method: "GET", available: false, reason }] });
  render(<QueryClientProvider client={client}><AttemptLog code="default" attempt={{ attempt_id: 7, status: "SUCCESS" }} /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Show log" })).toHaveAccessibleDescription(reason);
  expect(screen.getByRole("button", { name: "Show log" })).toHaveAttribute("aria-disabled", "true");
  client.clear();
});


it("keeps an item's mark dialog and chosen status across row updates", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "reader", role: "admin", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
  const record = { key: "file-a", status: "FAILED", row_count: 0, started: null, ended: null, error: null };
  const data = { task_run_id: 1, task_run_label: "task", records: [record], progress: { failed: 1, total: 1, done: 0, skipped: 0 }, availability: ["RERUN", "CANCEL", "MARK"].map(action => ({ action, item_key: "file-a", available: true, reason: "" })) };
  client.setQueryData(["health"], { projects: [{ project: "default", environment_type: "CUSTOM", governance: "STRICT" }] });
  client.setQueryData(["run-reference", "default", "1"], { pipeline_run_id: 1, run_label: "run" });
  client.setQueryData(["items", "default", "OPS", "1", "load"], data);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/default/OPS/1/load"]}><Routes><Route path="/:project/:pipeline/:runId/:task" element={<ToastProvider><Items /></ToastProvider>} /></Routes></MemoryRouter></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Mark as" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Mark as" }), { target: { value: "SKIPPED" } });
  expect(screen.getByRole("dialog")).toBeVisible();
  act(() => client.setQueryData(["items", "default", "OPS", "1", "load"], { ...data, records: [{ ...record, row_count: 1 }] }));
  await screen.findByRole("cell", { name: "1" });
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Mark as" })).toHaveValue("SKIPPED");
  client.clear();
});

it("uses a binding's tag rather than the page's project permission for revoke", () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["whoami", null], { name: "manager", role: "developer", settings: { timezone: "UTC", time_display: "UTC", page_size: 25 } });
  client.setQueryData(["health"], { projects: [{ project: "default", environment_type: "CUSTOM", governance: "STRICT" }] });
  client.setQueryData(["admin", "/api/v1/access/grants", { project: "default" }], { bindings: [{ scope: "PROJECT", project: "default", pipeline: null, tag: "team", group: null, account: "reader", audience: null, environment: null, role: "CAN_VIEW", action: null, active_flag: "Y" }] });
  client.setQueryData(["admin", "/api/v1/roles", undefined], { roles: [] });
  client.setQueryData(["action-availability", "default", undefined, undefined], { actions: ["/access/grants", "/access/revocations"].map(endpoint => ({ endpoint: "/api/v1" + endpoint, method: "POST", available: false, reason: "expected CAN_MANAGE on the project" })) });
  client.setQueryData(["action-availability", "default", undefined, { binding_tag: "team" }], { actions: [{ endpoint: "/api/v1/access/revocations", method: "POST", available: true, reason: "" }] });
  render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider><AccessTab project="default" projects={["default"]} /></ToastProvider></MemoryRouter></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Revoke" })).not.toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("button", { name: "Grant access" })).toHaveAccessibleDescription("expected CAN_MANAGE on the project");
  client.clear();
});


it("keeps run controls visible with the server's failed-read reason", async () => {
  vi.mocked(getJson).mockRejectedValue(new Error("operator role is required"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["health"], { projects: [{ project: "default", environment_type: "CUSTOM", governance: "STRICT" }] });
  render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider><ScopeControls code="default" pipeline="P" runId={1} /></ToastProvider></MemoryRouter></QueryClientProvider>);
  for (const name of ["Stop", "Abort", "Recover", "Restart", "Run paused"]) {
    await waitFor(() => expect(screen.getByRole("button", { name })).toHaveAccessibleDescription("operator role is required"));
    expect(screen.getByRole("button", { name })).toHaveAttribute("aria-disabled", "true");
  }
  act(() => client.setQueryData(["capabilities", "default", "P", 1, ""], { actions: ["STOP", "ABORT", "RECOVER", "RESTART", "RUN_PAUSED"].map(action => ({ action, available: true, reason: "", preserves_successful_work: true })) }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Stop" })).not.toHaveAttribute("aria-disabled", "true"));
  client.clear();
});


it("keeps an incomplete confirmation focusable and describes the missing input", () => {
  const confirm = vi.fn();
  render(<ConfirmDialog open title="Run" action="Confirm run" effect="Runs P." projectCode="default" env={{ type: "PROD", name: null }} error={null} busy={false} onConfirm={confirm} onClose={() => undefined} />);
  const button = screen.getByRole("button", { name: "Confirm run" });
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(button).toHaveAccessibleDescription("Enter a reason for this action.");
  button.focus();
  expect(button).toHaveFocus();
  fireEvent.click(button);
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Approved load" } });
  expect(button).toHaveAccessibleDescription("Type default to confirm the production action.");
  fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "default" } });
  expect(button).not.toHaveAttribute("aria-disabled", "true");
});
