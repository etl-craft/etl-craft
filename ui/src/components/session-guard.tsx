import { focusManager, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useIdentity } from "@/hooks";
import { SESSION_ENDED, signInAddress } from "@/lib/api";

const WARN_MS = 10 * 60_000;
const QUIET_MS = 2 * 60_000;

/**
 * The server ends a session after idle time (and always at its absolute end). This warns ten
 * minutes before, renews it when the person keeps working, and says so when it has ended.
 * Polling stops while nobody is using the page, so a forgotten tab does not keep the session alive.
 */
export function SessionGuard() {
  const client = useQueryClient();
  const identity = useIdentity();
  const [now, setNow] = React.useState(() => Date.now());
  const [ended, setEnded] = React.useState(false);
  const lastInput = React.useRef(0);
  const quiet = React.useRef(false);
  const ends = identity.data?.session_expires_at ? Date.parse(identity.data.session_expires_at) : null;
  const left = ends === null ? null : ends - now;
  const over = ended || (left !== null && left <= 0);
  const warning = left !== null && left > 0 && left < WARN_MS;
  const renew = React.useCallback(() => void client.invalidateQueries({ queryKey: ["whoami"] }), [client]);

  React.useEffect(() => {
    const onEnded = () => setEnded(true);
    const onInput = () => {
      lastInput.current = Date.now();
      if (quiet.current) {
        quiet.current = false;
        focusManager.setFocused(undefined);
      }
    };
    lastInput.current = Date.now();
    const events = ["pointerdown", "keydown", "wheel", "touchstart"] as const;
    events.forEach((name) => window.addEventListener(name, onInput, { passive: true }));
    window.addEventListener(SESSION_ENDED, onEnded);
    const tick = window.setInterval(() => {
      setNow(Date.now());
      if (!quiet.current && Date.now() - lastInput.current > QUIET_MS) {
        quiet.current = true;
        focusManager.setFocused(false);
      }
    }, 15_000);
    return () => {
      events.forEach((name) => window.removeEventListener(name, onInput));
      window.removeEventListener(SESSION_ENDED, onEnded);
      window.clearInterval(tick);
    };
  }, []);

  return (
    <>
      {warning && !over ? (
        <Notice info className="mx-4 mt-3 flex flex-wrap items-center justify-between gap-3 sm:mx-6">
          <span>
            Your session ends at {new Date(ends ?? 0).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} unless you keep working.
          </span>
          <Button size="sm" onClick={renew}>
            Stay signed in
          </Button>
        </Notice>
      ) : null}
      <Dialog open={over} onClose={() => undefined} labelledBy="session-ended-title">
        <div className="grid gap-4 p-5">
          <h2 id="session-ended-title" className="m-0 text-base font-semibold">
            Your session has ended
          </h2>
          <p className="m-0 text-sm text-muted">
            For your security you were signed out. What is on this page is unchanged, so copy anything you need first. Signing in brings you back to this page.
          </p>
          <div className="flex justify-end">
            <Button variant="primary" onClick={() => window.location.assign(signInAddress())}>
              Sign in again
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
