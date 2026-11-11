import { describe, expect, it } from "vitest";
import { toCsv } from "@/lib/csv";

describe("toCsv", () => {
  it("quotes commas, quotes and line breaks, and leaves plain fields alone", () => {
    const text = toCsv(["a", "b"], [["x,y", 'say "hi"'], ["line\nbreak", null], [3, undefined]]);
    expect(text).toBe('a,b\r\n"x,y","say ""hi"""\r\n"line\nbreak",\r\n3,\r\n');
  });
});
