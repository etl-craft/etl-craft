import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Copy, ExternalLink } from "lucide-react";
import * as React from "react";
import { useSearchParams } from "react-router-dom";
import { Field, inputClass, Loading, Notice, PageHeader } from "@/components/common";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { failureText } from "@/hooks";
import { getJson, postJson } from "@/lib/api";
import type { Redirect, SignInMethods, SsoStart } from "@/lib/types";
import { useDocumentTitle } from "@/title";

/** Waits for the person to approve at the identity provider, then follows the redirect the server gives. */
function SsoWait({ grant, returnTo }: { grant: SsoStart; returnTo: string }) {
  const [status, setStatus] = React.useState("Waiting for approval…");
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    const end = Date.now() + grant.expires_in * 1000;
    const poll = async (interval: number): Promise<void> => {
      await new Promise((resolve) => setTimeout(resolve, interval * 1000));
      if (!live) return;
      if (Date.now() + interval * 1000 >= end) return setStatus("SSO approval expired. Start again.");
      try {
        const answer = await postJson<Redirect>("/api/v1/login/sso/poll", { device_code: grant.device_code, nonce: grant.nonce, _return_to: returnTo });
        if (answer.redirect) return window.location.assign(answer.redirect);
        return poll(Math.max(1, interval + (answer.interval ?? 0)));
      } catch (error) {
        return setStatus(`SSO sign-in refused: ${failureText(error)} Start again.`);
      }
    };
    void poll(Math.max(1, grant.interval));
    return () => {
      live = false;
    };
  }, [grant, returnTo]);
  return (
    <div className="grid gap-2 rounded-md border border-border p-4 text-sm">
      <h2 className="m-0 text-base font-semibold">Approve SSO sign-in</h2>
      <p className="m-0">
        Code: <strong className="font-mono">{grant.user_code}</strong>{" "}
        <button
          type="button"
          aria-label="Copy the code"
          title="Copy the code"
          onClick={() => {
            void navigator.clipboard?.writeText(grant.user_code).then(() => setCopied(true));
          }}
          className="ml-1 inline-grid size-6 cursor-pointer place-items-center rounded-sm align-middle text-muted hover:bg-surface-2 hover:text-fg"
        >
          {copied ? <Check className="size-3.5 text-ok" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        </button>
      </p>
      <a className="inline-flex items-center gap-1 text-accent hover:underline" href={grant.verification_uri} target="_blank" rel="noopener noreferrer">
        Open your identity provider <ExternalLink className="size-3.5" aria-hidden />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
      <p role="status" className="m-0 text-muted">
        {status}
      </p>
    </div>
  );
}

export function SignIn() {
  useDocumentTitle("Sign in");
  const [params] = useSearchParams();
  const returnTo = params.get("return_to") ?? "/ui";
  const methods = useQuery({ queryKey: ["login-methods"], queryFn: () => getJson<SignInMethods>("/api/v1/login/methods") });
  const [name, setName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const login = useMutation({
    mutationFn: () => postJson<Redirect>("/api/v1/login/password", { name, password, _return_to: returnTo }),
    onSuccess: (answer) => window.location.assign(answer.redirect ?? "/ui"),
  });
  const browser = useMutation({
    mutationFn: () => postJson<{ authorization_url: string }>("/api/v1/login/browser/start", { return_to: returnTo }),
    onSuccess: answer => window.location.assign(answer.authorization_url),
  });
  const sso = useMutation({ mutationFn: () => postJson<SsoStart>("/api/v1/login/sso", { _return_to: returnTo }) });
  const data = methods.data;
  return (
    <main className="grid min-h-dvh place-items-center bg-bg p-4">
      <Card className="grid w-full max-w-sm gap-5 p-6">
        <Logo className="size-12" />
        <PageHeader title="Sign in to etl-craft" />
        {params.get("changed") ? <Notice info>Your password was changed. Sign in with the new one.</Notice> : null}
        {data?.notice ? <Notice info>{data.notice}</Notice> : null}
        {methods.isPending ? <Loading what="sign-in options" /> : null}
        {methods.isError ? <Notice>{failureText(methods.error)}</Notice> : null}
        {data?.local ? (
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              login.mutate();
            }}
          >
            <Field label="Account name">
              <input required maxLength={255} autoComplete="username" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Password">
              <input required type="password" autoComplete="current-password" className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            {login.isError ? <Notice>{failureText(login.error)}</Notice> : null}
            <Button type="submit" variant="primary" disabled={login.isPending}>
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        ) : null}
        {data?.sso ? (
          <div className="grid gap-3">
            <Button disabled={sso.isPending || browser.isPending} onClick={() => data.browser_sso ? browser.mutate() : sso.mutate()}>
              Sign in with SSO
            </Button>
            {!data.browser_sso ? <Notice info>Browser sign-in needs Auth.Browser_state_secret; see the security guide.</Notice> : null}
            {browser.isError ? <Notice>{failureText(browser.error)}</Notice> : null}
            {sso.isError ? <Notice>{failureText(sso.error)}</Notice> : null}
            {sso.data ? <SsoWait grant={sso.data} returnTo={returnTo} /> : null}
          </div>
        ) : null}
        {data ? (
          <p className="m-0 text-sm text-muted">
            Password recovery does not send email. Contact {data.contact ?? "your administrator"}.
          </p>
        ) : null}
      </Card>
    </main>
  );
}

export function SsoCallback() {
  useDocumentTitle("Signing in");
  const [params] = useSearchParams();
  const code = params.get("code") ?? "";
  const state = params.get("state") ?? "";
  const refusal = params.get("error");
  const started = React.useRef(false);
  const login = useMutation({
    mutationFn: () => postJson<Redirect>("/api/v1/login/browser/callback", { code, state }),
    onSuccess: answer => window.location.assign(answer.redirect ?? "/ui"),
  });
  const { mutate } = login;
  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    if (!refusal) mutate();
  }, [mutate, refusal]);
  return <main className="grid min-h-dvh place-items-center bg-bg p-4"><Card className="grid w-full max-w-sm gap-4 p-6">
    <PageHeader title="Signing in…" />
    {refusal || login.isError ? <Notice>{refusal ? "The identity provider refused sign-in. Start again." : failureText(login.error)}</Notice> : <p role="status">Signing in…</p>}
    {refusal || login.isError ? <a href="/ui/signin" className="text-accent hover:underline">Start sign-in again</a> : null}
  </Card></main>;
}
