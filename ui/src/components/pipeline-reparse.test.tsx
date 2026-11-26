import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PipelineReparse } from "@/components/pipeline-reparse";
import { getJson } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  getJson: vi.fn(),
}));

vi.mock("@/components/toast", () => ({ useToast: () => vi.fn() }));

it.each([
  [undefined, "Re-parse all", "Governance is STRICT; standalone re-parse requires RELAXED."],
  ["daily", "Re-parse pipeline", "Governance is STRICT; standalone re-parse requires RELAXED."],
  [undefined, "Re-parse all", "Ask a project manager for permission to re-parse."],
  ["daily", "Re-parse pipeline", "Ask a project manager for permission to re-parse."],
])("shows the unavailable re-parse for %s with its reason", async (pipeline, label, reason) => {
  vi.mocked(getJson).mockImplementation(async (path) => (
    path.endsWith("/project-health")
      ? { projects: [{ project: "sales", environment_type: "DEV" }] }
      : { actions: [{ action: "pipelines re-parse", available: false, reason }] }
  ) as never);
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  query.setQueryData(["health"], { projects: [{ project: "sales", environment_type: "DEV" }] });
  render(
    <QueryClientProvider client={query}>
      <PipelineReparse code="sales" pipeline={pipeline} onDone={vi.fn()} />
    </QueryClientProvider>,
  );
  const button = screen.getByRole("button", { name: label });
  await waitFor(() => expect(button).toHaveAccessibleDescription(reason));
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByText(reason)).not.toBeVisible();
  fireEvent.pointerEnter(button);
  expect(screen.getByRole("tooltip")).toHaveTextContent(reason);
  fireEvent.pointerLeave(button);
  expect(screen.getByText(reason)).not.toBeVisible();
  fireEvent.focus(button);
  expect(screen.getByRole("tooltip")).toHaveTextContent(reason);
  fireEvent.keyDown(button, { key: "Escape" });
  expect(screen.getByText(reason)).not.toBeVisible();
  fireEvent.click(button);
  expect(screen.getByRole("tooltip")).toHaveTextContent(reason);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(getJson).toHaveBeenCalledWith(
    "/api/v1/projects/sales/capabilities", { definition: true, pipeline_code: pipeline },
  ));
});
