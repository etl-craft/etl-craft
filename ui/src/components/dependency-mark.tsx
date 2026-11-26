import {Database,X} from "lucide-react";
import type {DefinitionEdge} from "@/lib/catalog";
import {definitionLabel} from "@/lib/catalog-flow";
export function DependencyBadge({ edge }: { edge: Pick<DefinitionEdge, "dependency_type" | "consume_repairs"> }) {
  const label = definitionLabel({kind:"task",source:"",target:"",...edge});
  return label ? <span className="inline-flex items-center gap-1 rounded-sm bg-surface px-1 text-xs">{edge.dependency_type === "HAS_DATA" ? <Database aria-hidden className="size-3" /> : edge.dependency_type === "FAILURE" ? <X aria-hidden className="size-3" /> : null}{label}</span> : null;
}


export function OptionalTask() {
  return <span className="text-xs text-muted" title="Failure of this task does not fail the pipeline run">Optional<span className="sr-only">. Failure of this task does not fail the pipeline run.</span></span>;
}
