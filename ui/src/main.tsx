import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { ToastProvider } from "@/components/toast";
import { About } from "@/pages/about";
import { Admin } from "@/pages/admin";
import { Agents } from "@/pages/agents";
import { Loading } from "@/components/common";
const Catalog = lazy(() => import("@/pages/catalog").then((module) => ({ default: module.Catalog })));
import { Console } from "@/pages/console";
import { Maintenance } from "@/pages/maintenance";
import { Password } from "@/pages/password";
import { Search } from "@/pages/search";
import { Settings } from "@/pages/settings";
import { SignIn, SsoCallback } from "@/pages/signin";
import { System } from "@/pages/system";
import { Paused, HeldRedirect } from "@/pages/paused";
import { ProjectDashboard, InsightsRedirect } from "@/pages/project-dashboard";
import { Items } from "@/pages/items";
import { HomeEntry, ProjectList } from "@/pages/home";
import { PipelineDetail } from "@/pages/pipeline-detail";
import { AttemptRedirect, RunRedirect, TaskRedirect } from "@/pages/run-redirect";
import { Pipelines } from "@/pages/pipelines";
import { Scheduled } from "@/pages/scheduled";
import { Uploads } from "@/pages/uploads";
import { Runs } from "@/pages/runs";
import { applyDensity, applyTheme, initialTheme, storedDensity } from "@/lib/theme";
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./index.css";

applyTheme(initialTheme());
applyDensity(storedDensity());
const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <ToastProvider>
      <Suspense fallback={<Loading what="page" />}>
      <BrowserRouter basename="/ui">
        <Routes>
          <Route path="signin" element={<SignIn />} />
          <Route path="signin/callback" element={<SsoCallback />} />
          <Route element={<AppShell />}>
            <Route index element={<HomeEntry />} />
            <Route path="projects" element={<ProjectList />} />
            <Route path="projects/:project" element={<ProjectDashboard />} />
            <Route path="system" element={<System />} />
            <Route path="agents" element={<Agents />} />
            <Route path="admin" element={<Admin />} />
            <Route path="about" element={<About />} />
            <Route path="settings" element={<Settings />} />
            <Route path="password" element={<Password />} />
            <Route path="projects/:project/search" element={<Search />} />
            <Route path="projects/:project/maintenance" element={<Maintenance />} />
            <Route path="projects/:project/pipelines" element={<Pipelines />} />
            <Route path="projects/:project/pipelines/:pipeline" element={<PipelineDetail />} />
            <Route path="projects/:project/pipelines/:pipeline/tasks/:task" element={<TaskRedirect />} />
            <Route path="projects/:project/uploads" element={<Uploads />} />
            <Route path="projects/:project/insights" element={<InsightsRedirect />} />
            <Route path="projects/:project/console" element={<Console />} />
            <Route path="projects/:project/catalog/*" element={<Catalog />} />
            <Route path="projects/:project/scheduled" element={<Scheduled />} />
            <Route path="projects/:project/paused" element={<Paused />} />
            <Route path="projects/:project/held" element={<HeldRedirect />} />
            <Route path="projects/:project/runs" element={<Runs />} />
            <Route path="projects/:project/runs/:pipeline/:runId/tasks/:task/attempts/:attemptId" element={<AttemptRedirect />} />
            <Route path="projects/:project/runs/:pipeline/:runId/tasks/:task/items" element={<Items />} />
            <Route path="projects/:project/runs/:pipeline/:runId" element={<RunRedirect />} />
            <Route path="*" element={<p className="text-muted">That page does not exist. Use the navigation to go Home.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
      </Suspense>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
