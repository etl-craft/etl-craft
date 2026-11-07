import { X } from "lucide-react";
import { SelectField } from "@/components/common";

/**
 * The pipeline tags: a pipeline, or the runs of one, must carry every tag selected. A dropdown adds a tag, so a
 * thousand tags cost one control; the selected ones stay in view as chips that remove themselves.
 */
export function TagFilter({ known, selected, onToggle }: { known: string[]; selected: string[]; onToggle: (tag: string) => void }) {
  const addable = known.filter((tag) => !selected.includes(tag));
  return (
    <div className="flex flex-wrap items-end gap-2" role="group" aria-label="Filter by tag">
      {known.length === 0 ? (
        <span className="text-xs text-muted">No pipeline has tags; declare them in PIPELINE_PARAMETERS.TAGS.</span>
      ) : (
        <SelectField compact label="Tag" value="" onChange={(tag) => tag && onToggle(tag)}>
          <option value="">{selected.length ? "Add a tag" : "Any tag"} ({addable.length})</option>
          {addable.map((tag) => (
            <option key={tag} value={tag}>
              {tag}
            </option>
          ))}
        </SelectField>
      )}
      {selected.map((tag) => (
        <button
          key={tag}
          type="button"
          aria-label={`Remove tag ${tag}`}
          onClick={() => onToggle(tag)}
          className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-full border border-accent bg-accent px-2.5 text-xs text-accent-fg max-sm:h-10"
        >
          {tag}
          <X aria-hidden className="size-3" />
        </button>
      ))}
    </div>
  );
}
