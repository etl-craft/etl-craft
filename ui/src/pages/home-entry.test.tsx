import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { HomeEntry } from "@/pages/home";

const project = (code: string) => ({ project: code, project_name: code, environment_type: "CUSTOM", environment_name: null, governance: "STRICT", failed: 0, running: 0, sla_misses: 0, queued_tasks: 0 });

function open(codes: string[], defaultProject: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(["health"], { projects: codes.map(project), window_start: "2026-01-01T00:00:00Z" });
  client.setQueryData(["whoami", null], { name: "owner", role: "admin", settings: { default_project: defaultProject } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route index element={<HomeEntry />} />
          <Route path="projects/:project" element={<p>inside project page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Home", () => {
  beforeEach(() => window.localStorage.clear());

  it("opens the only project, so a single-project installation never sees a list", () => {
    open(["support_insights"], null);
    expect(screen.getByText("inside project page")).toBeTruthy();
  });

  it("opens the default project when there are several", () => {
    open(["a", "b"], "b");
    expect(screen.getByText("inside project page")).toBeTruthy();
  });

  it("opens the project last used when it is still active", () => {
    window.localStorage.setItem("etl-craft-project", "a");
    open(["a", "b"], null);
    expect(screen.getByText("inside project page")).toBeTruthy();
  });

  it("ignores a default or last project that is no longer active, and lists the choices", () => {
    window.localStorage.setItem("etl-craft-project", "gone");
    open(["a", "b"], "also-gone");
    expect(screen.queryByText("inside project page")).toBeNull();
    expect(screen.getByText(/none is chosen/)).toBeTruthy();
  });
});
