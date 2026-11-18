# Alerts

An alert is a task with `HANDLER = 'ALERT'` that names a project **channel** and the **events**
it reports. The controller watches the recorded run history; when a named event happens, it
admits a separate run of that one task, which delivers through the channel and records every
attempt. Email, HTTPS webhooks and Slack work the same way.

```text
source run ends FAILED  ──►  controller admits an alert run  ──►  ALERT task sends  ──►  AUD_ALERT_DELIVERIES
```

The source run is never changed or delayed by its alerts. Inside an ordinary run an alert task
does nothing and succeeds; it needs no dependencies, because the event starts it.

## Channels

Deployment administrators own routing. A channel belongs to one project and has one kind:

| Kind | Delivers to | Set with |
|---|---|---|
| `EMAIL` | recipients, through the `Email` relay in `craft-connector.yml` | `--recipients` |
| `WEBHOOK` | an HTTPS receiver, as signed JSON | `--url-secret`, `--signing-secret` |
| `SLACK` | a Slack incoming webhook | `--url-secret`, `--signing-secret` |

Open **Administration → Alert channels**, or use the CLI or API:

```bash
etl-craft alert-channel set --project sales --name ops --kind EMAIL \
  --recipients 'ops@example.com|oncall@example.com' --reason "Operations mailbox"
etl-craft alert-channel set --project sales --name hooks --kind WEBHOOK \
  --url-secret OPS_WEBHOOK_URL --signing-secret OPS_WEBHOOK_KEY \
  --default-alert-on 'FAILURE|SLA_BREACH|LOST|GATE_WAIT_OVER_5' --reason "Incident receiver"
etl-craft alert-channel list --project sales
etl-craft alert-channel disable --project sales --name hooks --reason "Retire receiver"
```

`set` creates or replaces the whole definition and enables it. An `EMAIL` channel takes only
recipients; `WEBHOOK` and `SLACK` take only the two secret variable names. Mixing them is
refused. `--default-alert-on` is the event list a task uses when it sets no `ALERT_ON`; it
defaults to `FAILURE`. API routes are `GET/POST /api/v1/alert-channels` and
`POST /api/v1/alert-channels/disable`, all admin-only. Channels are not config files:
`config apply` and `config export` neither change nor export them.

`URL_SECRET` and `SIGNING_SECRET` are **variable names**, resolved through the secrets provider
when the alert sends, never literal values. The signing key must contain at least 32 UTF-8
bytes. The URL must use HTTPS with a valid certificate and no user information; redirects are
not followed. Reads show the names, never the values. `ACTIVE_FLAG=N` stops new admissions and
delivery starts.

## The alert task

| Parameter | Value |
|---|---|
| `ALERT_CHANNEL` | the project channel's name; required |
| `ALERT_ON` | events separated by `\|`; the channel's default when absent, none when empty |
| `ALERT_SUBJECT` | the subject or headline; built in when absent |
| `ALERT_BODY` | the message; built in when absent |
| `EMAIL_TEMPLATE`, `EMAIL_TEMPLATE_TEXT` | `EMAIL` channels: HTML and plain-text templates under `email_templates/` |
| `EMAIL_PIPELINES` | `EMAIL` channels: `ALL`, or pipeline codes separated by `\|`, adds each one's latest run |

The events:

| Event | When |
|---|---|
| `FAILURE` | a run ends `FAILED` |
| `SUCCESS` | a run ends `SUCCESS` and every non-alert task succeeded cleanly: no error message, one attempt, and the run within its SLA |
| `COMPLETED_WITH_ERRORS` | a run ends `SUCCESS`, but a task was skipped, needed a retry or succeeded with an error message, or the run missed its SLA |
| `SLA_BREACH` | a run of a pipeline with `SLA_IN_HOURS` passes its SLA, at that moment if still running; only where `Orchestration.Enforce_sla` is `true`, so each environment decides whether a missed SLA alerts |
| `LOST` | an attempt is reconciled as `LOST` |
| `GATE_WAIT_OVER_<minutes>` | a run has waited at a gate for longer than that many minutes |

For different wording per event, use one alert task per event. Unknown or duplicate events are
refused. `validate` checks that the channel exists and is active, the events, the tokens, and
that email-only parameters name an `EMAIL` channel, whose project needs an `Email` relay.

A subscription covers events from the moment it took its current form: the task's creation, or
the latest change to its `ALERT_CHANNEL`, `ALERT_ON` or channel. Adding an alert, or re-enabling a
channel, does not replay the pipeline's history.

Subjects and bodies may use these tokens:

| Token | Becomes |
|---|---|
| `$$trigger` | the event, such as `FAILURE` or `GATE_WAIT_OVER_30` |
| `$$status` | the source run's status |
| `$$pipeline_id`, `$$pipeline_run_id` | the pipeline definition and the source run |
| `$$task_run_id` | this alert task's execution |
| `$$pipeline_code`, `$$task_code` | the pipeline's and the alert task's codes |
| `$$error_message` | the source run's error message, empty when it has none |

Any other `$$` token is refused. After substitution the subject collapses whitespace, removes
other control characters and is limited to 200 characters, ending in `…` when shortened. Without
`ALERT_BODY`, the built-in body adds the error message on its own line.

## Delivery and recovery

Run a controller to observe events and deliver. Each event is admitted once per task and channel,
including after a controller restart, in batches of at most one hundred admissions per cycle. The
alert run selects only the alert task, appears in ordinary run history and uses the normal
pool and task capacity controls. Alert runs never raise alerts of their own.

A delivery has four attempts: at once, then after 5, 30 and 120 seconds. An HTTP attempt has a
ten-second timeout; transport failures, HTTP 408, 429 and 5xx retry, and other non-2xx responses
fail at once. An email attempt that the relay refuses retries; a refusal of only some recipients
is logged with each refused address and counts as sent. Configure a task timeout that covers the
full schedule.

`AUD_ALERT_DELIVERIES` appends the admission, each attempt's start and its outcome: event and run
identities, channel, attempt number, status, HTTP code or a controlled error class, actor and UTC
time. It holds no endpoint values, keys, response bodies or raw network errors. The pipeline
Overview and **Administration → Projects** show the newest hundred visible records, and the API's
pipeline and project documents, `pipeline --json` and `project list --json` include them.

Delivery is **at least once**. A crash after the receiver accepts but before the outcome is
recorded can repeat that attempt with the same `event_id`; a receiver must deduplicate it. A
recorded success is not sent again on replay; a final failure stays failed, so repair the
receiver and wait for the next event. Attempt history follows the project's run-history
retention.

Pipeline `DRAIN` pauses let running alert attempts finish and stop new dispatch until resume. A
standing `FAILED` task outcome creates no attempt and therefore no failure alert. A paused source
pipeline does not suppress alerts.

## Email

The `Email` block of the active `Orchestration` profile says how email is sent:

| `Transport` | Sends through | Settings |
|---|---|---|
| `smtp` (the default) | an SMTP relay | `Host`, `Port`, `From_address`, `From_name`, `Tls_mode`, optional `Ca_file`, and `Auth_mode`: `NONE`, `PASSWORD` (`User`, `Secret`) or `OAUTH` (SMTP XOAUTH2: `User`, `Client_id`, `Secret`, `Token_url`) |
| `sendmail` | the host's own `sendmail` program | `From_address`, `From_name`, and `Sendmail_path` when it is not `/usr/sbin/sendmail` |

`From_address` is the sender's address and `From_name`, optional, the name shown with it. With
`sendmail`, host, port, TLS and login settings are refused, since the host's mail system owns
delivery. `Tls_mode` is `STARTTLS` (the default), `SSL` for implicit TLS (usually port 465), or
`NONE` for an unauthenticated internal relay; both TLS modes verify the certificate and hostname.
`Ca_file` names a CA certificate file relative to the project directory. Password and OAuth
logins require `STARTTLS` or `SSL`. `doctor` checks the relay without logging in.

A failed attempt is logged naming the relay, the step (`connect`, `start TLS`, `log in`, `send`
or `build headers`) and the relay's answer, or the `sendmail` program's exit status and output:

```
email to ops@example.com was not sent: the relay smtp.example.com:587 failed at log in: SMTPAuthenticationError: (535, b'5.7.8 Authentication failed')
```

Every subject begins `[PRODUCTION]` for PROD or `[<TYPE>]` otherwise. The built-in HTML uses a
640px table layout, inline CSS, status symbols and colors, complete wrapped errors and a footer
saying which channel chose the recipients. To design your own, copy
`etl_craft/handlers/email_templates/default.html` and `default.txt` from the installed package
into your project's `email_templates/`, and set `EMAIL_TEMPLATE`=`email_templates/team.html` and
optionally `EMAIL_TEMPLATE_TEXT`=`email_templates/team.txt`. Templates ship in the project bundle.

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
| `environment.type`, `.name`, `.label` | project environment type, optional name, display label (PRODUCTION for PROD) |
| `project.code`, `pipeline.code` | project and pipeline codes |
| `run.id`, `.logical_date`, `.start`, `.end`, `.duration`, `.status` | the source run; ISO dates, UTC timestamps (end may be null), elapsed seconds and status (`COMPLETED_WITH_ERRORS` for that event) |
| `run.symbol`, `.color` | status symbol and color |
| `task` | the alert task's code, run_id, status and attempt |
| `errors` | complete task error strings, not HTML |
| `watched_tasks` | the source run's non-alert task rows: code, status, error, attempts, symbol, color |
| `pipelines` | `EMAIL_PIPELINES` rows: code, run_id, status, start, end, tasks (same task-row shape) |
| `sla` | null, or hours, elapsed_hours and message when the run passed its SLA |
| `subject`, `body`, `body_lines` | the subject and body after `$$` substitution, and the body as lines |
| `version` | installed package version |
| `recipients`, `recipient_reason` | the addresses, and the channel that chose them |

Templates use Jinja's sandbox with strict undefined values and automatic HTML escaping; only
primitive data is exposed, with no attributes, calls, includes or loaders. Absolute paths,
traversal and symlinks leaving `email_templates/` are refused. `validate` renders referenced
templates and reports file, line and remedy. A rendering error fails the alert before any
attempt; nothing partial or substituted is ever sent.

## Webhook JSON and signature

A `WEBHOOK` body has `schema: "etl-craft/alert/1"`, `event_id`, `trigger`, `subject`, `body`,
`run`, `task`, `status`, `error` and `links`. Links are relative application addresses. Source
status and error are read from the recorded history at delivery time.

```text
Content-Type: application/json
X-ETL-Craft-Timestamp: <Unix seconds>
X-ETL-Craft-Signature: v1=<lowercase hexadecimal HMAC>
```

Compute HMAC-SHA256 with the signing key over the ASCII timestamp, a literal period (`.`) and the
**exact transmitted UTF-8 body bytes**, in that order, and compare in constant time. Reject
timestamps outside a five-minute window and deduplicate accepted `event_id` values; event IDs are
scoped to the sending Engine DB.

`SLACK` receives a plain `text` body, the subject and body, with mention expansion and
link/media unfurling disabled. The signing headers are included, but Slack does not check them;
its secret URL is the credential.

## Trust boundary

Administrative channel ownership keeps routing and secret reference names out of developer
configuration. It does not isolate credentials from executable project code: Python tasks run
with the host's access, as the [security guide](../deploying/security.md) explains. A local alert
process receives only its channel's credentials through the private pipe; agents receive none
and ask the server to deliver.
