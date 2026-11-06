import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { Field, inputClass, Notice, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { failureText, useIdentity } from "@/hooks";
import { postJson } from "@/lib/api";
import { useDocumentTitle } from "@/title";

/** Changing the password ends every session, so the person signs in again with the new one. */
export function Password() {
  useDocumentTitle("Change password");
  const identity = useIdentity();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [again, setAgain] = React.useState("");
  const change = useMutation({
    mutationFn: () => postJson<{ message: string }>("/api/v1/account/password", { current_password: current, password: next }),
    onSuccess: () => window.location.assign("/ui/signin?changed=1"),
  });
  const mismatch = again !== "" && again !== next;
  if (identity.data && !identity.data.local_password) {
    return (
      <div className="grid gap-5">
        <PageHeader title="Change password" />
        <Notice info>Your account signs in through single sign-on, so its password is managed by your identity provider.</Notice>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Change password" />
      {identity.data?.must_change_password ? <Notice info>Your temporary password must be changed before continuing.</Notice> : null}
      <Card className="max-w-xl p-5">
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!mismatch) change.mutate();
          }}
        >
          <Field label="Current password">
            <input required type="password" autoComplete="current-password" className={inputClass} value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New password">
            <input required type="password" autoComplete="new-password" className={inputClass} value={next} onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="Confirm new password">
            <input required type="password" autoComplete="new-password" className={inputClass} value={again} onChange={(e) => setAgain(e.target.value)} />
          </Field>
          {mismatch ? <Notice>The two new passwords differ; type the same one twice.</Notice> : null}
          {change.isError ? <Notice>{failureText(change.error)}</Notice> : null}
          <div>
            <Button type="submit" variant="primary" disabled={change.isPending || mismatch}>
              {change.isPending ? "Changing…" : "Change password and sign in again"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
