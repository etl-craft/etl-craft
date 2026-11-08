import { describe, expect, it } from "vitest";
import { autoStarts, describeAutoStarts } from "@/lib/auto-starts";

describe("autoStarts", () => {
  it("is unrestricted when both allow everything", () => {
    expect(autoStarts("SCHEDULE|ALWAYS", "SCHEDULE|ALWAYS")).toMatchObject({ schedule: true, off: false, limited: false });
  });
  it("is off when either side says NONE", () => {
    expect(autoStarts("NONE", "SCHEDULE|ALWAYS")?.off).toBe(true);
    expect(autoStarts("SCHEDULE|ALWAYS", "NONE")?.off).toBe(true);
  });
  it("keeps only what both sides allow", () => {
    expect(autoStarts("SCHEDULE|SUCCESS|FAILURE", "SCHEDULE|FAILURE")).toMatchObject({ schedule: true, endings: ["FAILURE"], limited: true });
    expect(autoStarts("SUCCESS", "SCHEDULE|ALWAYS")).toMatchObject({ schedule: false, endings: ["SUCCESS"], off: false });
  });
});

describe("describeAutoStarts", () => {
  it("says the default and NONE in words and names the rest", () => {
    expect(describeAutoStarts("SCHEDULE|ALWAYS")).toBe("everything");
    expect(describeAutoStarts("NONE")).toBe("nothing");
    expect(describeAutoStarts("SCHEDULE|FAILURE")).toBe("schedules, after failure");
  });
});
