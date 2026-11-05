import { Table, Td, Th } from "@/components/ui/table";

const text = (value: unknown): string => (value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value));

/** Records whose columns are not fixed in advance, such as value provenance: one column per key found. */
export function RecordTable({ records, label, hide = [] }: { records: Record<string, unknown>[]; label: string; hide?: string[] }) {
  const columns = [...new Set(records.flatMap((record) => Object.keys(record)))].filter((c) => !hide.includes(c));
  return (
    <Table aria-label={label}>
      <thead>
        <tr>
          {columns.map((column) => (
            <Th key={column}>{column.replaceAll("_", " ")}</Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {records.map((record, row) => (
          <tr key={row}>
            {columns.map((column) => (
              <Td key={column} className="max-w-72 break-words font-mono text-xs">
                {text(record[column])}
              </Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
