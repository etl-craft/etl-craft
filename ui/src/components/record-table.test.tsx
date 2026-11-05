import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecordTable } from "@/components/record-table";

describe("RecordTable", () => {
  it("makes one column per key found, hides the keys it is told to, and shows missing values as a dash", () => {
    render(
      <RecordTable
        label="Values"
        hide={["key_hash"]}
        records={[
          { column_name: "amount", writer: "etl", key_hash: "abc" },
          { column_name: "status", locked: true, key_hash: "abc" },
        ]}
      />,
    );
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["column name", "writer", "locked"]);
    expect(screen.queryByText("abc")).toBeNull();
    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.getByText("true")).toBeInTheDocument();
  });
});
