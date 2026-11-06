import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { Field, inputClass } from "@/components/common";

export interface FieldSpec {
  name: string;
  label: string;
  kind?: "text" | "password" | "number" | "select" | "textarea" | "datetime-local";
  options?: string[];
  /** A select's empty choice, such as "Keep"; without it the first option is chosen. */
  blank?: string;
  required?: boolean;
  hint?: string;
  initial?: string;
}

const initialValues = (fields: FieldSpec[]): Record<string, string> =>
  Object.fromEntries(fields.map((f) => [f.name, f.initial ?? (f.kind === "select" && !f.blank ? (f.options?.[0] ?? "") : "")]));

/** A request that needs input: the fields and the usual confirmation share one dialog; empty fields are left out of the request. */
export function FormAction<TResult>({
  fields,
  extra,
  ...action
}: {
  fields: FieldSpec[];
  /** Values sent as they are with every request. */
  extra?: Record<string, unknown>;
} & Omit<React.ComponentProps<typeof ActionButton<TResult>>, "body" | "fields" | "canSubmit">) {
  const [values, setValues] = React.useState(() => initialValues(fields));
  const missing = fields.some((f) => f.required && !values[f.name]?.trim());
  const body = (reason: string) => {
    const sent: Record<string, unknown> = { ...extra };
    for (const f of fields) {
      const raw = values[f.name]?.trim();
      if (!raw) continue;
      sent[f.name] = f.kind === "number" ? Number(raw) : f.kind === "datetime-local" ? new Date(raw).toISOString() : raw;
    }
    return action.askReason === false ? sent : { ...sent, reason };
  };
  return (
    <ActionButton<TResult>
      {...action}
      body={body}
      canSubmit={!missing}
      onDone={(result) => {
        setValues(initialValues(fields));
        action.onDone?.(result);
      }}
      fields={
        <div className="grid gap-3">
          {fields.map((f) => (
            <Field key={f.name} label={f.label + (f.required ? "" : " (optional)")}>
              {f.kind === "select" ? (
                <select value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} className={inputClass}>
                  {f.blank ? <option value="">{f.blank}</option> : null}
                  {f.options?.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : f.kind === "textarea" ? (
                <textarea value={values[f.name]} rows={3} maxLength={500} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} className="rounded-md border border-border-strong bg-surface p-2 text-sm" />
              ) : (
                <input
                  type={f.kind ?? "text"}
                  value={values[f.name]}
                  placeholder={f.hint}
                  autoComplete={f.kind === "password" ? "new-password" : "off"}
                  onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                  className={inputClass}
                />
              )}
            </Field>
          ))}
        </div>
      }
    />
  );
}
