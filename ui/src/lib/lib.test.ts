import { describe, expect, it } from "vitest";
import { environmentLabel, isProduction } from "@/lib/environment";
import { formatAgo, formatDuration, formatTime } from "@/lib/format";
import { layout } from "@/components/run-graph";

describe("environment", () => {
  it("makes production unmistakable and keeps names for the rest", () => {
    expect(environmentLabel({ type: "PROD", name: "eu" })).toBe("PRODUCTION");
    expect(environmentLabel({ type: "UAT", name: "eu" })).toBe("UAT · eu");
    expect(environmentLabel({ type: "CUSTOM", name: null })).toBe("CUSTOM");
    expect(isProduction({ type: "PROD", name: null })).toBe(true);
    expect(isProduction({ type: "UAT", name: null })).toBe(false);
  });
});

describe("format", () => {
  it("shows the zone with every time", () => {
    expect(formatTime("2026-11-05T12:00:00+00:00", "Europe/London")).toMatch(/GMT$/);
    expect(formatTime("2026-11-05T12:00:00+00:00", "America/New_York")).toMatch(/GMT-5$/);
    expect(formatTime(null, "UTC")).toBe("—");
  });
  it("formats durations and ages", () => {
    expect(formatDuration("2026-11-05T12:00:00Z", "2026-11-05T12:00:12Z")).toBe("12s");
    expect(formatDuration("2026-11-05T12:00:00Z", "2026-11-05T12:03:07Z")).toBe("3m 07s");
    expect(formatDuration("2026-11-05T12:00:00Z", "2026-11-05T14:05:00Z")).toBe("2h 05m");
    expect(formatAgo("2026-11-05T12:00:00Z", Date.parse("2026-11-05T12:10:00Z"))).toBe("10m ago");
  });
});

describe("graph layout", () => {
  const graph = {
    waves: [["extract"], ["load", "audit"], ["alert"]],
    conditional: ["alert"],
    depends_on: {
      extract: [],
      load: [["extract", "SUCCESS"]],
      audit: [["extract", "SUCCESS"]],
      alert: [["load", "FAILURE"]],
    },
  } as unknown as Parameters<typeof layout>[0];
  it("puts each wave in a column and draws one edge per dependency row", () => {
    const { nodes, edges } = layout(graph, { extract: "SUCCESS", load: "FAILED" }, "load");
    const x = Object.fromEntries(nodes.map((n) => [n.id, n.position.x]));
    expect(x.extract).toBeLessThan(x.load as number);
    expect(x.load).toBe(x.audit);
    expect(x.load).toBeLessThan(x.alert as number);
    expect(edges.map((e) => e.id).sort()).toEqual(["extract->audit", "extract->load", "load->alert"]);
    expect(edges.find((e) => e.id === "load->alert")?.label).toBe("failure");
    expect(edges.find((e) => e.id === "extract->load")?.label).toBeUndefined();
  });
  it("shows a task the run has not reached as queued, and marks the selection", () => {
    const { nodes } = layout(graph, {}, "audit");
    expect(nodes.find((n) => n.id === "alert")?.data.status).toBe("QUEUED");
    expect(nodes.filter((n) => n.data.selected).map((n) => n.id)).toEqual(["audit"]);
  });
  it("wraps a wide wave into columns of at most four", () => {
    const wide = { waves: [["a", "b", "c", "d", "e", "f"], ["g"]], conditional: [], depends_on: {} } as unknown as Parameters<typeof layout>[0];
    const { nodes } = layout(wide, {}, null);
    const at = (id: string) => nodes.find((n) => n.id === id)!.position;
    expect(at("a").x).toBe(at("d").x);
    expect(at("e").x).toBeGreaterThan(at("a").x);
    expect(at("g").x).toBeGreaterThan(at("e").x);
  });
});
