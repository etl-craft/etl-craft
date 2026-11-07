import { describe, expect, it } from "vitest";
import { impact, isOpenGap, type CatalogDoc, type CatalogGap } from "@/lib/catalog";
import { describeCron, relative } from "@/lib/format";

describe("a schedule in words", () => {
  it("describes the common shapes and leaves the rest to the expression", () => {
    expect(describeCron("*/15 * * * *")).toBe("Every 15 minutes");
    expect(describeCron("*/15 0-1,3-23 * * *")).toBe("Every 15 minutes, except hour 02");
    expect(describeCron("0 */6 * * *")).toBe("Every 6 hours");
    expect(describeCron("0 2 * * *")).toBe("Daily at 02:00");
    expect(describeCron("0 * * * *")).toBe("Every hour");
    expect(describeCron("0 9 * * 1")).toBeNull(); // a weekday needs the expression itself
    expect(describeCron(null)).toBeNull();
  });
});

describe("a time from now", () => {
  it("says how far, in the nearest unit, in either direction", () => {
    const now = Date.parse("2026-11-07T12:00:00Z");
    expect(relative("2026-11-07T14:14:00Z", now)).toBe("in 2 h");
    expect(relative("2026-11-07T11:57:00Z", now)).toBe("3 min ago");
    expect(relative("2026-11-04T12:00:00Z", now)).toBe("3 d ago");
    expect(relative(null, now)).toBe("—");
  });
});

describe("the catalog's gaps and impact", () => {
  it("does not call a match, an unchecked or an undeclared comparison an open gap", () => {
    const gap = (state: string) => ({ state }) as CatalogGap;
    expect(["Matched", "Unchecked", "Not declared", "Expected before first deployment"].some((s) => isOpenGap(gap(s)))).toBe(false);
    expect(["Type mismatch", "Deployed only", "Lineage gap"].every((s) => isOpenGap(gap(s)))).toBe(true);
  });

  it("lists what is upstream and downstream with the steps and the task that makes the first one", () => {
    const doc = { table_edges: [{ source: "a", target: "b", task: "P.t1" }, { source: "b", target: "c", task: "P.t2" }, { source: "c", target: "d", task: "P.t3" }] } as unknown as CatalogDoc;
    const rows = impact(doc, "b", 4);
    expect(rows).toEqual([
      { table: "a", direction: "Upstream", steps: 1, task: "P.t1" },
      { table: "c", direction: "Downstream", steps: 1, task: "P.t2" },
      { table: "d", direction: "Downstream", steps: 2, task: "P.t3" },
    ]);
    expect(impact(doc, "b", 1, "down").map((r) => r.table)).toEqual(["c"]);
  });
});
