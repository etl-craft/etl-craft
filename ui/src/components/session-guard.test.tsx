import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { SessionGuard } from "@/components/session-guard";
import { SESSION_ENDED } from "@/lib/api";

function guard(minutesLeft: number | null, timeDisplay = "relative") {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const ends = minutesLeft === null ? null : new Date(Date.now() + minutesLeft * 60_000).toISOString();
  client.setQueryData(["whoami", null], { name: "owner", role: "admin", session_expires_at: ends, settings: { time_display: timeDisplay, timezone: "Asia/Kolkata" } });
  return {
    client,
    ...render(
    <QueryClientProvider client={client}>
      <SessionGuard />
    </QueryClientProvider>,
    ),
  };
}

describe("the session guard", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not confirm cached expiry when the identity refresh fails", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockRejectedValue(new TypeError("Network unavailable"));
    vi.stubGlobal("fetch", fetch);
    const { client } = guard(-1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(client.getQueryState(["whoami", null])?.status).toBe("error");
    expect(document.querySelector("dialog[open]")).toBeNull();
    // A later clock tick must not turn the cached expiry into a confirmed end either.
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(document.querySelector("dialog[open]")).toBeNull();
  });

  beforeAll(() => {
    HTMLDialogElement.prototype.showModal = function showModal() {
      this.setAttribute("open", "");
    };
  });

  it("retries after a failed refresh and clears the warning on success", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Network unavailable"))
      .mockResolvedValue(new Response(JSON.stringify({
        name: "owner", role: "admin",
        session_expires_at: new Date(Date.now() + 45 * 60_000).toISOString(),
        settings: { time_display: "relative", timezone: "UTC" },
      })));
    vi.stubGlobal("fetch", fetch);
    guard(8);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText(/Your session ends/)).toBeTruthy();
    expect(document.querySelector("dialog[open]")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.queryByText(/Your session ends/)).toBeNull();
    expect(document.querySelector("dialog[open]")).toBeNull();
  });

  it("shows the ended state when a retry receives a server 401", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Network unavailable"))
      .mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetch);
    guard(8);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(document.querySelector("dialog[open]")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("dialog")).toHaveTextContent("Your session has ended");
  });

  it("is silent while the session has time left", () => {
    guard(45);
    expect(screen.queryByText(/Your session ends/)).toBeNull();
  });

  it.each(["relative", "absolute"])("warns using the account’s %s time display", (display) => {
    guard(8, display);
    const warning = screen.getByText(/Your session ends/);
    const time = warning.querySelector("time")!;
    expect(time).not.toBeNull();
    expect(display === "relative" ? time.textContent : time.title).toMatch(/^in \d+ min$/);
    expect(display === "absolute" ? time.textContent : time.title).toMatch(/GMT\+5:30/);
    expect(screen.getByRole("button", { name: "Stay signed in" })).toBeTruthy();
  });

  it("says the session has ended when a request is refused, without leaving the page", () => {
    guard(45);
    act(() => {
      window.dispatchEvent(new Event(SESSION_ENDED));
    });
    expect(screen.getByText("Your session has ended")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in again" })).toBeTruthy();
  });
});
