import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { SessionGuard } from "@/components/session-guard";
import { SESSION_ENDED } from "@/lib/api";

function guard(minutesLeft: number | null, timeDisplay = "relative") {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const ends = minutesLeft === null ? null : new Date(Date.now() + minutesLeft * 60_000).toISOString();
  client.setQueryData(["whoami", null], { name: "owner", role: "admin", session_expires_at: ends, settings: { time_display: timeDisplay, timezone: "Asia/Kolkata" } });
  return render(
    <QueryClientProvider client={client}>
      <SessionGuard />
    </QueryClientProvider>,
  );
}

describe("the session guard", () => {
  beforeAll(() => {
    HTMLDialogElement.prototype.showModal = function showModal() {
      this.setAttribute("open", "");
    };
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
