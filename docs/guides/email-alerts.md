# Email alerts

A pipeline reports how a run went with one email, sent by a task with
`HANDLER = 'EMAIL_ALERT'` at the end of the pipeline. With `Orchestration.Enforce_sla: true`, the
engine also emails when a run misses its pipeline's SLA.

For HTTPS webhooks and Slack, select an administrator-approved `ALERT_CHANNEL` and optionally
choose event selectors through `ALERT_ON`; see [alert channels](alert-channels.md). These tasks
use server-owned delivery instead of SMTP and do not declare `SECRETS`.

## How email is sent

The `Email` block of the active `Orchestration` profile says how, in one of two ways:

| `Transport` | Sends through | Settings |
|---|---|---|
| `smtp` (the default) | an SMTP relay | `Host`, `Port`, `From_address`, `From_name`, `Tls_mode`, optional `Ca_file`, and `Auth_mode`: `NONE`, `PASSWORD` (`User`, `Secret`) or `OAUTH` (SMTP XOAUTH2: `User`, `Client_id`, `Secret`, `Token_url`) |
| `sendmail` | the host's own `sendmail` program, the one `mailx` and `mail` use | `From_address`, `From_name`, and `Sendmail_path` when it is not `/usr/sbin/sendmail` |

`From_address` is the sender's address and `From_name`, optional, the name shown with it, as in
`ETL Craft <etl@example.com>`. With `sendmail` the engine hands each message to the program, with the recipients taken from its
headers and `From_address` as the sender, and the host's mail system delivers it. Host, port and
login settings are refused there, since they would be ignored. Before a run starts, the engine
checks the relay answers using its TLS mode, or the program exists and can run. A failed email
preflight is logged and data tasks may still run; the alert task records any delivery failure.

`Tls_mode` is `STARTTLS` (the default), `SSL` for implicit TLS (usually port 465), or `NONE`
for an unauthenticated internal relay. Both TLS modes verify the relay's certificate and hostname.
`Ca_file` names a CA certificate file; a relative path starts at the project directory. Omit it
to use system trust. `doctor` shows the mode and trust source and checks the TLS connection without
logging in. Password and OAuth authentication require `STARTTLS` or `SSL`; `NONE` is refused with
either login mode.

With `sendmail`, TLS and login settings are refused because the host's mail system owns delivery.

## The alert task

An alert task depends on the tasks it reports on, usually through `ALWAYS` dependencies, so it runs
once they have finished. It works out the run's outcome from every other task's status:

| Outcome | When |
|---|---|
| `FAILED` | any task failed |
| `COMPLETED_WITH_ERRORS` | none failed, but a task was skipped, needed a retry, succeeded with an error message or has not finished, or the run is already past its SLA with `Enforce_sla` on |
| `SUCCESS` | every task succeeded cleanly |

Other alert tasks are left out, so two alerts (one to operations on `FAILED`, one to stakeholders
on `SUCCESS`) agree.

| Parameter | Value |
|---|---|
| `EMAIL_TO` | the recipients, separated by `\|`; required |
| `EMAIL_SUBJECT` | the subject; required |
| `EMAIL_BODY` | an opening paragraph; required unless `EMAIL_PIPELINES` is set |
| `EMAIL_SUBJECT_<OUTCOME>`, `EMAIL_BODY_<OUTCOME>` | the subject or body for one outcome, such as `EMAIL_SUBJECT_FAILED` |
| `EMAIL_ON_STATUS` | the outcomes to send on, separated by `\|`; every outcome when unset |
| `EMAIL_PIPELINES` | `ALL`, or pipeline codes separated by `\|`: adds a table of each one's latest run, with a section per pipeline listing its tasks |

On an outcome not in `EMAIL_ON_STATUS`, the task succeeds without sending, and its task log says
why.

Subjects and bodies may use these tokens:

| Token | Becomes |
|---|---|
| `$$status` | the outcome |
| `$$pipeline_id` | the pipeline definition's `pipeline_id` |
| `$$pipeline_run_id` | the run's `pipeline_run_id` |
| `$$task_run_id` | the alert task execution's `task_run_id` |
| `$$pipeline_code`, `$$task_code` | the pipeline's and the alert task's codes |
| `$$error_message` | the error messages of the tasks this one watches through `FAILURE` dependencies |

Any other `$$` token fails the task, naming it.
After substitution, the subject collapses whitespace to one space, removes other control
characters, and is limited to 200 characters, ending in `…` when shortened. The body keeps the
full error message, including line breaks.

## SLA emails

With `Enforce_sla: true`, a run of a pipeline with `SLA_IN_HOURS` that is still going when its SLA
passes gets one SLA email, at that moment; a run that ends late is emailed as it ends. The email
goes to the pipeline's `EMAIL_RECIPIENTS` in `PIPELINE_PARAMETERS`, else the email recipients in
`Orchestration.Email_recipients`. When neither is set, the engine logs that the SLA email could not
be sent and why; the run itself is not affected. With `Enforce_sla` off, runs are still marked `MET`
or `BREACHED`, and nothing is sent.

## When sending fails

When the relay refuses only some recipients, the task succeeds and records `EMAIL_WARNING` in
`TASK_LOG` and a WARNING in the attempt log, naming each refused address and the relay's answer.
A total refusal or another delivery error fails the alert task.

Failed alert tasks stay `FAILED` in the audit tables and logs and are named at ERROR when the
pipeline ends. They do not change a data pipeline's outcome: successful data tasks still produce
a `SUCCESS` run, failed data tasks a `FAILED` run, and all-skipped data tasks a `SKIPPED` run.
A pipeline containing only alerts uses its alert tasks' outcomes. Task dependency edges still
judge an alert's actual task status, so put alerts at the end of the data pipeline.

The task fails with a message naming the relay and the step (`connect`, `start TLS`, `log in`,
`send`, or `build headers`) and the relay's own answer, or the `sendmail` program and its exit
status and output:

```
email to ops@example.com was not sent: the relay smtp.example.com:587 failed at log in: SMTPAuthenticationError: (535, b'5.7.8 Authentication failed')
```

## Environment and designed templates

Every alert and SLA subject begins `[PRODUCTION]` for PROD or `[<TYPE>]` otherwise. The
built-in HTML uses a 640px table layout, inline CSS, status symbols and colors, complete
wrapped errors, and a recipient-reason footer. Start by copying
`src/etl_craft/handlers/email_templates/default.html` (installed under
`etl_craft/handlers/email_templates/default.html`) into your project's `email_templates/`.
The companion `default.txt` supplies the multipart plain-text alternative.

Set `EMAIL_TEMPLATE`=`email_templates/team.html` on an EMAIL_ALERT task, optionally
`EMAIL_TEMPLATE_TEXT`=`email_templates/team.txt`. SLA uses `Orchestration.Email_template`.

| Parameter | Value |
|---|---|
| `EMAIL_TEMPLATE` | Confined HTML file under email_templates/ |
| `EMAIL_TEMPLATE_TEXT` | Optional confined .txt file under email_templates/ |
Both default to built-ins when unset. Files ship with the immutable project bundle.
EMAIL_SUBJECT*/EMAIL_BODY* retain their $$ tokens; their substituted strings become `subject`
and `body`. Jinja variables are separate from SQL and $$ substitution.

A copyable `email_templates/team.html`:

```html+jinja
<!doctype html><html lang="en"><body>
<h1>{{ environment.label }} · {{ project.code }} · {{ pipeline.code }}</h1>
<p>{{ subject }}</p><div style="white-space:pre-wrap">{% for line in body_lines %}{{ line }}<br>{% endfor %}</div>
<p>Run {{ run.id }}: {{ run.status }} — {{ run.start }}</p>
{% for error in errors %}<pre style="white-space:pre-wrap;word-break:break-word">{{ error }}</pre>{% endfor %}
<p>etl-craft {{ version }} — {{ recipient_reason }}</p>
</body></html>
```

### Template context

| Field | Value |
|---|---|
| `environment.type`, `.name`, `.label` | Existing project type, optional name, display label (PRODUCTION for PROD) |
| `project.code` | Project code |
| `pipeline.code` | Pipeline code |
| `run.id`, `.logical_date`, `.start`, `.end`, `.duration`, `.status` | Exact run; ISO dates, zoned UTC timestamps (end may be null), elapsed seconds and outcome |
| `run.symbol`, `.color` | Status symbol and color |
| `task` | Alert code, run_id, status and attempt; null for SLA |
| `errors` | Complete task error strings, not HTML |
| `watched_tasks` | Non-alert task rows in this run: code, status, error, attempts, symbol, color |
| `pipelines` | EMAIL_PIPELINES rows: code, run_id, status, start, end, tasks (same task-row shape) |
| `sla` | Null or hours, elapsed_hours, message |
| `subject`, `body` | Existing subject/body after $$ substitution |
| `body_lines` | Body split into lines for escaped text followed by literal HTML line breaks |
| `version` | Installed package version |
| `recipients`, `recipient_reason` | Addresses and why this recipient list was chosen |

The default has no View run button: no public UI base URL setting exists.
Docs_site.External_url serves the static catalog and is not a UI URL.

### Template security and failures

Templates use Jinja SandboxedEnvironment, StrictUndefined and automatic HTML escaping.
Only primitive data is exposed, without Python attributes/calls, globals, includes/imports,
network or file loaders. Keep autoescaping enabled; raw safe HTML is not supported. Absolute
paths, traversal and symlinks leaving email_templates/ are refused. `validate` checks referenced
files and reports file/line/remedy. A rendering error at send time fails before SMTP; it never
sends partially rendered content or silently falls back. Review team templates as project code.
