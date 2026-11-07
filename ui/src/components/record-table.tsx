import { columnsOf, DataTable } from "@/components/data-table";

const text = (value: unknown): string => (value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value));

/** Records whose columns are not fixed in advance, such as value provenance: one column per key found. */
export function RecordTable({ records, label, hide = [] }: { records: Record<string, unknown>[]; label: string; hide?: string[] }) {
  const keys = [...new Set(records.flatMap((record) => Object.keys(record)))].filter((c) => !hide.includes(c));
  return (
    <DataTable
      label={label}
      data={records}
      columns={columnsOf<Record<string, unknown>>(keys.map((key) => ({ id: key, header: key.replaceAll("_", " "), value: (record) => text(record[key]), size: 180, cell: (record) => <span className="font-mono text-xs">{text(record[key])}</span> })))}
    />
  );
}
