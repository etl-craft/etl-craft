import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AttemptLog } from "@/components/attempt-details";

const LOG = Array.from({ length: 500 }, (_, i) => `line ${i + 1} ${"x".repeat(200)}`).join("\n");

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getText: () => Promise.resolve(LOG),
}));

afterEach(() => vi.restoreAllMocks());

function show() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
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

  it("searches every line of the log", async () => {
    show();
    await screen.findByLabelText("Attempt log");
    fireEvent.change(screen.getByLabelText("Find in log"), { target: { value: "line 12 " } });
    await waitFor(() => expect(screen.getByText(/of 500 lines/)).toBeTruthy());
  });
});
