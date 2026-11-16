import type { CatalogTask } from "@/lib/catalog";
import { sourceAliases } from "@/lib/mapping-logic";

/** Explain the recorded bindings beside both diagrams and their source tables. */
export function SourceAliases({task,label="SQL source aliases"}:{task:CatalogTask;label?:string}) {
  const aliases=sourceAliases(task).filter(({alias,object,query})=>query||alias.toLowerCase()!==object.toLowerCase());
  return aliases.length?<div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted" aria-label={label}>
    <span className="font-medium">{label}:</span>
    {aliases.map(({alias,object,query})=>query?<details key={`${alias}:${object}:${query}`} className="min-w-0 max-w-full">
      <summary className="cursor-pointer"><code>{alias} = derived query</code></summary>
      <pre tabIndex={0} aria-label={`Derived query ${alias}`} className="my-2 max-h-48 overflow-auto whitespace-pre-wrap break-all border border-border bg-surface-2 p-3 font-mono text-xs text-fg">{query}</pre>
    </details>:<span key={`${alias}:${object}`} className="break-all"><code>{alias} = {object}</code></span>)}
  </div>:null;
}
