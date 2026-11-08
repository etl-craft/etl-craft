import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

const KEYS: [string, string][] = [
  ["?", "opens this list"],
  ["/ or Ctrl+K", "moves to search"],
  ["Escape", "closes dialogs and menus"],
  ["Tab and Shift+Tab", "move between controls; Enter or Space activates one"],
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} labelledBy="shortcuts-title">
      <div className="grid gap-4 p-5">
        <h2 id="shortcuts-title" className="m-0 text-base font-semibold">
          Keyboard shortcuts
        </h2>
        <ul className="m-0 grid list-none gap-2 p-0 text-sm">
          {KEYS.map(([key, what]) => (
            <li key={key} className="flex items-baseline gap-3">
              <kbd className="whitespace-nowrap rounded-sm border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-xs">{key}</kbd>
              <span>{what}</span>
            </li>
          ))}
        </ul>
        <div className="flex justify-end">
          <Button onClick={onClose}>Close shortcuts</Button>
        </div>
      </div>
    </Dialog>
  );
}
