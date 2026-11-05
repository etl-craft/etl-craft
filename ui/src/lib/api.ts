/** The SPA calls only /api/v1, as the signed-in browser session. */
export class ApiError extends Error {
  status: number;
  kind: string | null;
  constructor(message: string, status: number, kind: string | null = null) {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

export function csrfToken(): string {
  return document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ?? "";
}

function query(params?: Params): string {
  const pairs = Object.entries(params ?? {}).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return pairs.length ? "?" + new URLSearchParams(pairs.map(([k, v]) => [k, String(v)])).toString() : "";
}

export function signInAgain(): void {
  const back = window.location.pathname + window.location.search;
  window.location.assign("/signin?return_to=" + encodeURIComponent(back));
}

async function send(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError("The server did not answer; check that the etl-craft server is running and reload.", 0);
  }
  if (response.status === 401) {
    signInAgain();
    throw new ApiError("Your session has ended; sign in again.", 401);
  }
  if (!response.ok) {
    let detail: { message?: string; detail?: string; error?: string } = {};
    try {
      detail = await response.json();
    } catch {
      /* the body was not JSON; the status line below names the failure */
    }
    const message = detail.message ?? detail.detail ?? `Request failed with status ${response.status}.`;
    throw new ApiError(message, response.status, detail.error ?? null);
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

export async function signOut(): Promise<void> {
  await fetch("/api/v1/login/revoke", {
    method: "POST",
    credentials: "same-origin",
    redirect: "manual",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
    body: "{}",
  });
  window.location.assign("/signin");
}

export const project = (code: string): string => `/api/v1/projects/${encodeURIComponent(code)}`;
