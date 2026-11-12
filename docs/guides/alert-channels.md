# Webhook and Slack alerts

Alert channels send run failures, SLA breaches, LOST attempts and prolonged gate waits to an
HTTPS receiver. The controller observes recorded events and admits a separate ordinary run
selecting only the configured alert task. Event admission never performs HTTP.

The source run, its admission, tasks and dependency decisions are unchanged. The event satisfies
the selected alert task's source dependencies, so a stuck upstream cannot delay its notification.
A paused source pipeline **does not suppress alerts**. Holds or cancellation applied to the alert
run itself still control that run. Alert runs never generate further channel alerts.

## Configure a channel

Only deployment administrators manage routing, defaults and secret references. Open
**Administration → Alert channels**, select the project, and use **Set channel** or **Disable**.
Developers select an approved channel name through `ALERT_CHANNEL`; channels are not config
files and `config apply`/`config export` cannot change or export them.

The same operations serve the CLI and API:

```bash
etl-craft alert-channel set --project sales --name ops --kind WEBHOOK \
  --url-secret OPS_WEBHOOK_URL --signing-secret OPS_WEBHOOK_KEY \
  --default-alert-on 'FAILURE|SLA_BREACH|LOST|GATE_WAIT_OVER_5' --reason "Approve operations receiver"
etl-craft alert-channel list --project sales
etl-craft alert-channel disable --project sales --name ops --reason "Retire receiver"
```

`set` creates or replaces the full definition and enables it. The default event selection is
`FAILURE`; omitting or leaving the form's Default events field blank uses that default. WEBHOOK uses the JSON body;
SLACK uses the Slack body. API routes are `GET/POST /api/v1/alert-channels` and
`POST /api/v1/alert-channels/disable`, all admin-only. Reads show reference names, never values.

Channel names are unique within a project. `URL_SECRET` and `SIGNING_SECRET` are **variable
names**, resolved through the existing secrets provider when the alert task executes. They are
never literal values. The signing key must contain at least 32 UTF-8 bytes. The URL must use
HTTPS with a valid certificate, without URL user information. Redirects are not followed.
`ACTIVE_FLAG=N` stops new admissions and delivery starts. A task checks its channel when it
starts delivery; cancel an in-progress alert run to stop its remaining retries.

Configure an ordinary `EMAIL_ALERT` task in each pipeline to receive these events. Email
behavior stays unchanged when `ALERT_CHANNEL` is absent. With a channel, the same alert task
uses the server-owned delivery operation instead of SMTP:

| Task parameter | Meaning |
|---|---|
| `ALERT_CHANNEL` | Project channel name, such as `ops` |
| `ALERT_ON` | Pipe-separated selectors; absent means the channel's `DEFAULT_ALERT_ON` |

No `SECRETS` task declaration is used: the administrator-owned channel authorizes its references.
The local launcher resolves those names directly into its private credential pipe; agents never
receive channel values. Python scripts still require their own `SECRETS` declarations.
Supported selectors are
`FAILURE`, `SLA_BREACH`, `LOST` and `GATE_WAIT_OVER_<positive integer minutes>`. An explicitly empty
selector list disables that task's subscriptions. Unknown or duplicate selectors refuse.
The event selector watches the pipeline’s recorded events; dependency rows retain ordinary
source-run ordering but do not filter which source events are observed. In a normal source run the
channel task records that event admission owns delivery; it does not post a second notification.
The isolated alert run selects only that task and records its own attempts, logs and outcome.
It appears in ordinary run history and uses the normal pool/task capacity controls.

Run a controller to observe and supervise channel deliveries. Events are detected on controller
cycles, not by delivery hooks. Failure and SLA identities use the exact source run, LOST uses the
exact attempt, and gate thresholds use the recorded wait episode and threshold. Each configured
task/channel/event is admitted once, including after controller restart. A newly enabled
subscription catches up matching retained events, in bounded batches of one hundred total admissions per controller cycle. A gate selector applies
to a currently recorded, active wait. Observation does not reconstruct a wait's missing end time.

## Delivery and recovery

A delivery has four logical attempts. It starts immediately, then waits 5, 30 and 120 seconds
between retryable failures. Each HTTP attempt has a ten-second timeout. Transport failures,
HTTP 408/429 and 5xx responses retry; other non-2xx responses fail immediately. Normal task
ownership and cancellation still apply. Configure an adequate task timeout for the full schedule.

`AUD_ALERT_DELIVERIES` appends admission, send intent and outcome facts: event and run identities,
channel, logical attempt number, status, HTTP code or a controlled error class, actor and UTC time.
It contains neither endpoint values nor keys, response bodies or raw network exceptions.
The pipeline Overview and Administration → Projects show the newest hundred visible records.
The API's pipeline and project documents expose the same sanitized history. The existing CLI
`pipeline --json` and `project list --json` documents include it too.

Delivery is **at least once**. A crash after the receiver accepts a POST but before the outcome
is recorded can repeat that logical attempt. The repeated request keeps its stable `event_id`;
a generic receiver must deduplicate it. Slack can show duplicates. A recorded success is not sent
again on replay. A final failure remains failed; repair the receiver before submitting new work.
Attempt history follows the project's existing run-history retention policy. Admission receipts
remain while their source history exists, so retention cannot admit the same event again. Normal retention keeps the source history while its alert run is pending. A delivery refuses
if its exact source history has been removed outside that normal lifecycle.

## JSON and signature

A generic body has `schema: "etl-craft/alert/1"`, `event_id`, `trigger`, `run`, `task`, `status`,
`error` and `links`. Run navigation uses the integer identity; its stored label is also present.
Links are relative application addresses, so no public-address setting is added. Source status
and error are read from the recorded source history at delivery time; an operator may have
recovered the run since the event was admitted.

Headers:

```text
Content-Type: application/json
X-ETL-Craft-Timestamp: <Unix seconds>
X-ETL-Craft-Signature: v1=<lowercase hexadecimal HMAC>
```

Compute HMAC-SHA256 with the signing key over ASCII timestamp, a literal period (`.`), and the
**exact transmitted UTF-8 body bytes**, in that order. Verify using a constant-time comparison.
Reject timestamps outside a five-minute window and deduplicate accepted `event_id` values.
A signed timestamp by itself does not prevent replay within that window. Event IDs are scoped
to the sending Engine DB. A receiver aggregating instances must namespace deduplication by
sender, using distinct receiver routes/signing keys.

Slack receives a plain `text` body with mention expansion and link/media unfurling disabled.
It does not receive the generic JSON shape. The signing headers are included, but Slack's
incoming-webhook service does not validate our HMAC; its secret URL is the credential.

## Trust boundary

Administrative channel ownership prevents developer configuration from changing routing or
exposing reference names through channel management. It does not isolate credentials from
executable project code: Python tasks run with the host’s access, and projects on one instance
trust one another’s executable code, as the [security guide](../deploying/security.md) explains.
Local alert processes receive only the admitted channel’s credentials through the existing
private pipe; agents receive no channel credential values and request server-side delivery.
