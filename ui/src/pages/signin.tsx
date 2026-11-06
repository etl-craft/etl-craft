import { useMutation, useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
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
      } catch {
        return setStatus("SSO sign-in refused or expired. Start again.");
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
        Code: <strong className="font-mono">{grant.user_code}</strong>
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
  const returnTo = params.get("return_to") ?? "/app";
  const methods = useQuery({ queryKey: ["login-methods"], queryFn: () => getJson<SignInMethods>("/api/v1/login/methods") });
  const [name, setName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const login = useMutation({
    mutationFn: () => postJson<Redirect>("/api/v1/login/password", { name, password, _return_to: returnTo }),
    onSuccess: (answer) => window.location.assign(answer.redirect ?? "/app"),
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
            <Button disabled={sso.isPending} onClick={() => sso.mutate()}>
              Sign in with SSO
            </Button>
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
