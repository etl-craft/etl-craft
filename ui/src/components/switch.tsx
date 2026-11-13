import { cn } from "@/lib/utils";

export function Switch({checked,onChange,label}:{checked:boolean;onChange:()=>void;label:string}) {
  return <button type="button" role="switch" aria-checked={checked} onClick={onChange} className="inline-flex cursor-pointer items-center gap-2 rounded-sm text-xs focus-visible:outline-2 focus-visible:outline-ring"><span aria-hidden className={cn("inline-flex h-5 w-9 items-center rounded-full p-0.5 transition-colors motion-reduce:transition-none",checked?"bg-accent":"bg-border-strong")}><span className={cn("size-4 rounded-full bg-surface shadow-sm transition-transform motion-reduce:transition-none",checked&&"translate-x-4")}/></span>{label}</button>;
}
