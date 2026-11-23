import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AttemptLog } from "@/components/attempt-details";

const LOG = Array.from({ length: 500 }, (_, i) => `line ${i + 1} ${"x".repeat(200)}`).join("\n");

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getText: () => Promise.resolve(LOG),
  getJson: () => Promise.resolve({ actions: [{ endpoint: "/api/v1/attempts/{attempt_id}/log", method: "GET", available: true, reason: "" }] }),
}));

afterEach(() => vi.restoreAllMocks());

const REFUSED = "attempt 7: log not stored yet; retry after the upload finishes";

function show(available = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["action-availability", "p", undefined, { attempt_id: 7 }], { actions: [{ endpoint: "/api/v1/attempts/{attempt_id}/log", method: "GET", available, reason: available ? "" : REFUSED }] });
  render(
    <QueryClientProvider client={client}>
      <AttemptLog code="p" attempt={{ attempt_id: 7, status: "SUCCESS" }} open />
    </QueryClientProvider>,
  );
}

describe("AttemptLog", () => {
  it("wraps long lines by default and lets the reader turn wrapping off", async () => {
    show();
    const log = await screen.findByLabelText("Attempt log");
    expect(log.className).toContain("whitespace-pre-wrap");
    fireEvent.click(screen.getByLabelText("Wrap lines"));
    expect(log.className).not.toContain("whitespace-pre-wrap");
  });

  it("downloads the whole log, not only the lines shown", async () => {
    let blob: Blob | undefined;
    URL.createObjectURL = vi.fn((b: Blob | MediaSource) => {
      blob = b as Blob;
      return "blob:log";
    });
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    show();
    fireEvent.click(await screen.findByRole("button", { name: /Download log/ }));
    await waitFor(() => expect(blob).toBeDefined());
    expect(await blob!.text()).toBe(LOG);
    expect(screen.getByText(/Showing the last 400 of 500 lines/)).toBeInTheDocument();
  });

  it("keeps an unavailable log's reason in a hover annotation, not on the page", async () => {
    show(false);
    const button = await screen.findByRole("button", { name: "Show log" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    const note = document.getElementById(button.getAttribute("aria-describedby")!)!;
    expect(note).toHaveTextContent(REFUSED);
    expect(note).not.toBeVisible();
    expect(screen.queryByLabelText("Attempt log")).toBeNull();
    fireEvent.focus(button);
    expect(note).toBeVisible();
  });

  it("searches every line of the log", async () => {
    show();
    await screen.findByLabelText("Attempt log");
    fireEvent.change(screen.getByLabelText("Find in log"), { target: { value: "line 12 " } });
    await waitFor(() => expect(screen.getByText(/of 500 lines/)).toBeTruthy());
  });
});
