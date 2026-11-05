import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { Attempt } from "@/pages/attempt";
import { Held } from "@/pages/held";
import { Items } from "@/pages/items";
import { Home } from "@/pages/home";
import { PipelineDetail } from "@/pages/pipeline-detail";
import { Pipelines } from "@/pages/pipelines";
import { Scheduled } from "@/pages/scheduled";
import { Task } from "@/pages/task";
import { Runs } from "@/pages/runs";
import { applyTheme, initialTheme } from "@/lib/theme";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";

applyTheme(initialTheme());
const RunDetail = lazy(() => import("@/pages/run-detail").then((m) => ({ default: m.RunDetail })));
const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter basename="/app">
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Home />} />
            <Route path="projects/:project/pipelines" element={<Pipelines />} />
            <Route path="projects/:project/pipelines/:pipeline" element={<PipelineDetail />} />
            <Route path="projects/:project/pipelines/:pipeline/tasks/:task" element={<Task />} />
            <Route path="projects/:project/scheduled" element={<Scheduled />} />
            <Route path="projects/:project/held" element={<Held />} />
            <Route path="projects/:project/runs" element={<Runs />} />
            <Route path="projects/:project/runs/:pipeline/:runId/tasks/:task/attempts/:attemptId" element={<Attempt />} />
            <Route path="projects/:project/runs/:pipeline/:runId/tasks/:task/items" element={<Items />} />
            <Route path="projects/:project/runs/:pipeline/:runId" element={<Suspense fallback={<p className="text-muted">Loading run…</p>}><RunDetail /></Suspense>} />
            <Route path="*" element={<p className="text-muted">That page does not exist. Use the navigation to go Home.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
