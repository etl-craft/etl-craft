import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { downloadCsv, toCsv } from "@/lib/csv";

/** Export the rows a table shows; the file is built in the browser and goes nowhere else. */
export function CsvButton({ name, header, rows, size }: { name: string; header: string[]; rows: unknown[][]; size?: "sm" | "md" }) {
  return (
    <Button size={size} onClick={() => downloadCsv(name, toCsv(header, rows))} disabled={rows.length === 0}>
      <Download className="size-4" aria-hidden /> Export CSV
    </Button>
  );
}
