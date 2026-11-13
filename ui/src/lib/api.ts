/** The SPA calls only /api/v1, as the signed-in browser session. */
export class ApiError extends Error {
  status: number;
  kind: string | null;
  /** The targets a refusal asks to be confirmed (HTTP 428), as the server lists them. */
  targets: string[];
  constructor(message: string, status: number, kind: string | null = null, targets: string[] = []) {
    super(message);
    this.status = status;
    this.kind = kind;
    this.targets = targets;
  }
}

type Params = Record<string, string | number | boolean | string[] | null | undefined>;

export function csrfToken(): string {
  return document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ?? "";
}

function query(params?: Params): string {
  const pairs = Object.entries(params ?? {}).flatMap(([k, v]): [string, string][] =>
    v === undefined || v === null || v === "" ? [] : Array.isArray(v) ? v.map((item): [string, string] => [k, item]) : [[k, String(v)]],
  );
  return pairs.length ? "?" + new URLSearchParams(pairs).toString() : "";
}

const onSignInPage = (): boolean => window.location.pathname.endsWith("/signin");

export const SESSION_ENDED = "etl-craft:session-ended";

/** The sign-in address that returns to the page being viewed. */
export const signInAddress = (): string => "/ui/signin?return_to=" + encodeURIComponent(window.location.pathname + window.location.search);

/** The session has ended: the shell says so and offers sign-in, so nothing on the page is thrown away. */
export function signInAgain(): void {
  if (onSignInPage()) return;
  window.dispatchEvent(new Event(SESSION_ENDED));
}

let lastInput = Date.now();
const QUARTER_MINUTE = 15_000;

/** Real use of the page (a click or key), as opposed to the page refreshing itself. */
export const noteInput = (): void => {
  lastInput = Date.now();
};

async function send(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  // The server ends a session after idle time; a refresh nobody asked for must not extend it.
  const background: Record<string, string> = Date.now() - lastInput > QUARTER_MINUTE ? { "X-ETL-Background": "1" } : {};
  try {
    response = await fetch(path, { credentials: "same-origin", ...init, headers: { ...(init.headers as Record<string, string> | undefined), ...background } });
  } catch {
    throw new ApiError("The server did not answer; check that the etl-craft server is running and reload.", 0);
  }
  if (response.status === 401 && !onSignInPage()) {
    signInAgain();
    throw new ApiError("Your session has ended; sign in again.", 401);
  }
  if (!response.ok) {
    let detail: { message?: string; detail?: string; error?: string; targets?: unknown } = {};
    try {
      detail = await response.json();
    } catch {
      /* the body was not JSON; the status line below names the failure */
    }
    const message = detail.message ?? detail.detail ?? `Request failed with status ${response.status}.`;
    const targets = Array.isArray(detail.targets) ? detail.targets.filter((t): t is string => typeof t === "string") : [];
    throw new ApiError(message, response.status, detail.error ?? null, targets);
  }
  return response;
}

export async function getJson<T>(path: string, params?: Params): Promise<T> {
  const response = await send(path + query(params), { headers: { Accept: "application/json" } });
  return (await response.json()) as T;
}

export async function getText(path: string, params?: Params): Promise<string> {
  const response = await send(path + query(params), {});
  return response.text();
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await send(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken() },
    body: JSON.stringify(body),
  });
  return (await response.json()) as T;
}

/** A multipart upload as the session; the browser sets the boundary, so no content type is given. */
export async function postForm<T>(path: string, body: FormData, params?: Params): Promise<T> {
  const response = await send(path + query(params), { method: "POST", headers: { Accept: "application/json", "X-CSRF-Token": csrfToken() }, body });
  return (await response.json()) as T;
}

export async function signOut(): Promise<void> {
  const answer = await postJson<{ redirect: string | null; message: string }>("/api/v1/login/revoke", {});
  window.location.assign(answer.redirect ?? "/ui/signin?signed_out=local");
}

export const project = (code: string): string => `/api/v1/projects/${encodeURIComponent(code)}`;
