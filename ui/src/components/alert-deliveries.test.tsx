import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AlertDeliveries } from "@/components/alert-deliveries";
import type { AlertDelivery } from "@/lib/types";

const step = (delivery_id: number, status: string, event_id = "event-1"): AlertDelivery => ({
  delivery_id, event_id, status, channel: "support_team", pipeline_code: "P", source_run_id: 3,
  source_run_label: "P-3", alert_run_id: 4, alert_run_label: "P-4", trigger: "FAILURE",
  attempt_number: 1, status_code: null, error_class: null, created_at: "2026-11-25T10:00:00+00:00",
});

function shown(rows: AlertDelivery[]) {
  const client = new QueryClient();
  client.setQueryData(["whoami", null], { name: "owner", role: "admin", settings: { timezone: "UTC", time_display: "UTC" } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AlertDeliveries code="demo" rows={rows} /></MemoryRouter></QueryClientProvider>);
}

describe("alert deliveries", () => {
  it("shows one row per delivery with its latest state, and its steps under its details", () => {
    // The server records admitted, started and sent as separate rows of one delivery event.
    shown([step(1, "ADMITTED"), step(2, "STARTED"), step(3, "SENT"), step(4, "ADMITTED", "event-2")]);
    const table = screen.getByRole("table", { name: "Alert deliveries" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("Sent")).toBeTruthy();
    const steps = within(rows[0]!).getAllByRole("listitem").map(item => item.textContent ?? "");
    expect(steps.map(text => text.split(" · ")[1]?.split(" ")[0])).toEqual(["Sent", "Started", "Admitted"]);
  });
});
