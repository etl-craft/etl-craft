import { HBars, KpiTile, Panel, type BarRow } from "@/components/charts";
import { isOpenGap, type CatalogDoc } from "@/lib/catalog";
import { catalogPath } from "@/lib/routes";

const percent = (part: number, whole: number): string => (whole === 0 ? "—" : `${Math.round((part / whole) * 100)}%`);

/** How complete and healthy the catalog is: what is documented, written, checked by rules, and still open as a gap. */
export function CatalogInsights({ code, doc }: { code: string; doc: CatalogDoc }) {
  const tables = doc.tables.filter((t) => !t.external);
  const tasks = doc.tasks;
  const documented = tasks.filter((t) => t.documentation).length;
  const written = tables.filter((t) => t.writers.length > 0).length;
  const read = tables.filter((t) => t.readers.length > 0).length;
  const ruled = tables.filter((t) => t.rules.length > 0).length;
  const open = doc.gaps.filter(isOpenGap);
  const byState = new Map<string, number>();
  for (const gap of open) byState.set(gap.state, (byState.get(gap.state) ?? 0) + 1);
  const gapRows: BarRow[] = [...byState].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, tone: "warn" as const }));
  const popular: BarRow[] = [...tables]
    .sort((a, b) => b.readers.length - a.readers.length)
    .filter((t) => t.readers.length > 0)
    .slice(0, 8)
    .map((t) => ({ label: t.name, value: t.readers.length, text: `${t.readers.length} task${t.readers.length === 1 ? "" : "s"}`, to: catalogPath(code, "tables", t.name) }));
  const schemas = new Map<string, number>();
  for (const t of tables) schemas.set(t.schema, (schemas.get(t.schema) ?? 0) + 1);
  const schemaRows: BarRow[] = [...schemas].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, tone: "accent" as const }));
  const orphans: BarRow[] = tables
    .filter((t) => t.writers.length === 0)
    .slice(0, 8)
    .map((t) => ({ label: t.name, value: 1, text: "no writer", tone: "warn" as const, to: catalogPath(code, "tables", t.name) }));
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto" data-scroll-area>
      <div className="grid grid-cols-2 md:grid-cols-5">
        <KpiTile label="Tasks documented" value={percent(documented, tasks.length)} hint={`${documented} of ${tasks.length}`} tone={documented === tasks.length ? "ok" : undefined} />
        <KpiTile label="Tables written by a task" value={percent(written, tables.length)} hint={`${written} of ${tables.length}`} />
        <KpiTile label="Tables read by a task" value={percent(read, tables.length)} hint={`${read} of ${tables.length}`} />
        <KpiTile label="Tables with a rule" value={percent(ruled, tables.length)} hint={`${ruled} of ${tables.length}`} />
        <KpiTile label="Open gaps" value={open.length} tone={open.length ? "warn" : "ok"} hint={doc.gaps.length ? `of ${doc.gaps.length} compared` : undefined} />
      </div>
      <div className="grid md:grid-cols-2">
        <Panel title="Open gaps by state"><HBars label="Open gaps by state" rows={gapRows} empty="No open gaps." /></Panel>
        <Panel title="Most read tables"><HBars label="Most read tables" rows={popular} empty="No table is read by a task yet." /></Panel>
        <Panel title="Tables by schema"><HBars label="Tables by schema" rows={schemaRows} empty="No tables yet." /></Panel>
        <Panel title="Tables no task writes"><HBars label="Tables no task writes" rows={orphans} empty="Every table has a writer." /></Panel>
      </div>
    </div>
  );
}
