import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { SearchBox } from "@/components/search-box";
import { ApiError, getJson } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({ ...await original<typeof import("@/lib/api")>(), getJson: vi.fn() }));
const scroll = vi.fn();

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: scroll });
  scroll.mockClear();
  render(<QueryClientProvider client={client}><MemoryRouter><SearchBox code="demo" /></MemoryRouter></QueryClientProvider>);
  return screen.getByRole("combobox");
}

afterEach(() => { vi.restoreAllMocks(); vi.mocked(getJson).mockReset(); });

it("exposes and scrolls the keyboard-selected search option while focus stays in the input", () => {
  const input = show();
  input.focus();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  const option = screen.getByRole("option", { name: "Home" });
  expect(option).toHaveAttribute("aria-selected", "true");
  expect(option.id).not.toBe("");
  expect(input).toHaveAttribute("aria-activedescendant", option.id);
  expect(input).toHaveFocus();
  expect(scroll).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
  expect(option).toHaveAttribute("tabindex", "-1");
  fireEvent.keyDown(input, { key: "Escape" });
  expect(input).not.toHaveAttribute("aria-activedescendant");
  fireEvent.keyDown(input, { key: "ArrowUp" });
  expect(input).toHaveAttribute("aria-expanded", "true");
});

it("announces a failed search and retries without removing local navigation", async () => {
  vi.mocked(getJson).mockRejectedValueOnce(new ApiError("The server did not answer.", 503)).mockResolvedValue({ hits: [], truncated: false });
  const input = show();
  fireEvent.change(input, { target: { value: "Pipelines" } });
  expect(await screen.findByRole("alert")).toHaveTextContent('Search for “Pipelines” failed: The server did not answer. Retry the search.');
  expect(screen.getByRole("option", { name: "Pipelines" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry search" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(getJson).toHaveBeenCalledTimes(2);
  expect(input).toHaveFocus();
});

it("never offers matches for earlier text, and a still pointer under the list selects nothing", async () => {
  vi.mocked(getJson).mockResolvedValue({ hits: [{ kind: "PIPELINE", label: "OPS", pipeline_code: "OPS" }], truncated: false });
  const input = show();
  fireEvent.change(input, { target: { value: "OPS" } });
  const stale = await screen.findByRole("option", { name: /OPS/ });
  fireEvent.mouseEnter(stale);
  expect(stale).toHaveAttribute("aria-selected", "false");
  fireEvent.change(input, { target: { value: "SALES" } });
  expect(screen.queryByRole("option", { name: /OPS/ })).toBeNull();
  expect(screen.getByText("Searching…")).toBeVisible();
});

it("closes search on Escape from retry and when keyboard focus leaves the popup", async () => {
  vi.mocked(getJson).mockRejectedValue(new ApiError("The server did not answer.", 503));
  const input = show();
  fireEvent.change(input, { target: { value: "missing" } });
  const retry = await screen.findByRole("button", { name: "Retry search" });
  retry.focus();
  fireEvent.keyDown(retry, { key: "Escape" });
  expect(input).toHaveAttribute("aria-expanded", "false");
  expect(input).toHaveFocus();
  fireEvent.focus(input);
  expect(input).toHaveAttribute("aria-expanded", "true");
  fireEvent.blur(input, { relatedTarget: document.body });
  expect(input).toHaveAttribute("aria-expanded", "false");
});
