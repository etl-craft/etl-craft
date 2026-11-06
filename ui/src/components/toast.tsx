import { CircleCheck, X } from "lucide-react";
import * as React from "react";

interface Toast {
  id: number;
  text: string;
}
/** How long an answer stays before it closes itself; the close button dismisses it sooner. */
export const TOAST_MS = 8000;
const Context = React.createContext<(text: string) => void>(() => undefined);

/** The one place action results appear; it outlives the button or page that asked, so a refetch cannot hide an answer. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const next = React.useRef(0);
  const push = React.useCallback((text: string) => {
    const id = next.current++;
    setToasts((now) => [...now, { id, text }]);
    window.setTimeout(() => setToasts((now) => now.filter((t) => t.id !== id)), TOAST_MS);
  }, []);
  return (
    <Context.Provider value={push}>
      {children}
      <div role="status" aria-live="polite" className="fixed bottom-4 right-4 z-50 grid max-w-sm gap-2">
        {toasts.map((toast) => (
          <div key={toast.id} className="flex items-start gap-3 rounded-lg border border-border-strong bg-surface p-3 text-sm shadow-xl">
            <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-ok" />
            <p className="m-0 min-w-0 flex-1 break-words">{toast.text}</p>
            <button type="button" aria-label="Dismiss" className="cursor-pointer rounded p-0.5 text-muted hover:text-fg" onClick={() => setToasts((now) => now.filter((t) => t.id !== toast.id))}>
              <X aria-hidden className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </Context.Provider>
  );
}

export const useToast = () => React.useContext(Context);
