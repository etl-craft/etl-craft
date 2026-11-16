# Browser UI

Run `etl-craft ui` with the `ui` extra, or use the controller's HTTP server. Put an HTTPS
reverse proxy in front of it, preserving the public Host header (for example nginx
`proxy_set_header Host $http_host`): browser cookies are always Secure, including local sign-in.
Open `/ui`; sign-in is at `/ui/signin`. The minimum width is 320 CSS pixels; 1024 pixels or
wider gives the desktop layout.
The layout remains usable at 200% zoom.

## Sign-in and sessions

With `Auth.Browser_state_secret` configured, **Sign in with SSO** redirects to the identity
provider and returns to the page you asked for; no code needs copying. The callback briefly
shows “Signing in…” and displays a refusal with a way to start again when proof fails.
See [browser SSO setup](../deploying/security.md#browser-single-sign-on) for the public callback
address and signing-secret requirements. Without that optional setting, the button keeps the
device-flow fallback and explains which setting enables browser redirects.

Local accounts and configured SSO use the existing login actions. Wrong account names and
passwords give the same message. Recovery means contacting the administrator shown on the
sign-in page; there are no emailed resets. SSO accounts use their identity provider.

A session ends after `Auth.Session_idle_minutes` (default 60) without use, and always
`Auth.Session_hours` (default 12) after sign-in; the command line follows the same rule.
Credentials stay in HTTP-only, Secure, SameSite=Lax host-only cookies, never browser storage.
The page warns ten minutes before the end ("Stay signed in" renews it), and when the server
ends the session it says so in a dialog and offers sign-in, which returns to the same
same-site page; external return addresses are refused. The page's own refreshes are marked
as background (`X-ETL-Background: 1`) and do not extend a session. Signing out revokes the
session in every tab. A failed identity refresh keeps the current session state and retries;
cached expiry alone does not confirm a sign-out. Every browser change needs its CSRF challenge. Browser pages refuse
framing by other sites and ship a content security policy.

After `Auth.Lockout_after` consecutive wrong passwords (default 5; 0 disables lockout), a
local user locks until an admin runs `etl-craft account unlock --name ACCOUNT`. A locked
message appears only after the correct password. Successful sign-in resets the count.
SSO and service identities do not accumulate password lockouts. The last usable admin
cannot be locked, disabled or demoted. Admin password resets create temporary passwords;
the user must change one before opening other pages. Password changes revoke all sessions.

## Profile, settings and themes

The profile menu shows the account, deployment role, current project permission and groups,
last sign-in in settings, help, About and sign-out. Local users have Change password; SSO users do not.

Personal settings belong to the account: theme (`system`, `light`, `dark`), IANA timezone,
default project, page size (1–100) and relative or absolute times. The top-bar theme switch
saves to the same account setting. Home summaries, dashboard window boundaries, time-labelled
run grids and session warnings use the same time preference: relative times show the exact time
and timezone on hover; exact times show the relative time on hover. Calendar dates and chart
day labels stay dates. Both themes use the catalog's shared assets and the product mark. Every list shows values
unwrapped (hover shows the full value); **Wrap text** wraps them, and the choice is kept.

Use Tab and Shift+Tab to move, the skip link to reach content, `/` or Ctrl+K for search, and
Escape to close a dialog or menu. Opening a different page focuses its content pane; changing
workspace tabs or run/task selections leaves focus on the control you used. Action feedback stays
until you dismiss it, so background updates cannot remove an answer before you finish reading it.
Every project page names its environment and
governance; production has a stronger bordered badge as well as the word PRODUCTION.

The page is a standard application frame. A header bar holds the logo, the project switcher (the
project and its environment as one control, production in red), search, the theme and the
account; the navigation sits beside the content with a divider, the selected item marked by a bar;
and a footer bar shows the etl-craft and Engine DB schema versions with the live-update status.
Every button, input and dropdown has one height (larger on a phone), so rows of controls line up.

```sh
etl-craft account settings --theme dark --timezone Asia/Kolkata --page-size 40
etl-craft account change-password
etl-craft account unlock --name alice
```

## Home, About and catalog

Navigation groups **Home, Pipelines and Catalog** under Overview; **Runs, Scheduled runs,
Held and paused, Uploads, Console and Maintenance** under Operations; and **Projects, System
health, Agents and Administration** under Platform. Maintenance and Administration appear
only for administrators. The old project Insights address redirects to Home and retains filters.
Home contains Overview, Capacity, Catalog, Pipelines, Data, Quality and Failures tabs.

Pipelines is the operational list: description, schedule, dependency conditions, last run,
recent success and tag filters live together. Pipeline list/detail JSON includes `depends_on`
as pairs of upstream pipeline names and recorded dependency types. Export CSV includes
the dependency conditions and last-run IDs as well.

A pipeline and its runs share one workspace. The grid shows tasks as rows and runs as columns,
newest on the right, with duration bars above the same columns when enough runs exist. Grid/Graph
switches views. The right pane contains Overview, the selected run, Runs, Audit log and Access. Selecting a run or task persists `?run=ID&task=CODE`; old run addresses
redirect here while retaining task selections and view filters. Desktop panes scroll independently
within the window; below 1024 pixels they stack. A selected run's panel comes first on a narrow
screen. Overview links to the catalog for pipeline and task descriptions, keeping one documentation
source.

On phones, Home's time presets, custom date range and pipeline filter use the same control
height and wrap within the page. The custom range still opens the two UTC-day fields.

Home shows only authorized projects and pipeline work. Running runs and queued tasks are
current; failed runs and SLA misses use a rolling **last 24 h**, including the start and
excluding the end. The JSON supplies both UTC window boundaries. Counts have no links until
the filtered list pages exist. All counts come from the shared `PROJECT_HEALTH` read:

```sh
etl-craft project-health --json
etl-craft --project SALES project-health --json
etl-craft about --json
etl-craft --project SALES about
etl-craft --project SALES catalog page --path index.html --output catalog-page.html
```

About gives package, applied Engine DB schema, server and live controller versions, the
license and version-specific docs. It omits hosts, paths and connection details.

Catalog pages stream the project's existing `generate-docs` output through the same session;
a read never builds a catalog. Only whole-project viewers may open this static catalog:
it lists every pipeline, so pipeline-limited users must request whole-project access or use
authorized pipeline views. A filtered catalog is later work. The generated site's graphs,
search, tables, gaps and theme control remain one implementation, including offline mode.
`publish-docs` remains unchanged as the interim one-project server.

The corresponding API reads are `GET /api/v1/project-health`, `GET /api/v1/about`, and
`GET /api/v1/projects/{project}/catalog/page?path=index.html`. Catalog paths must be literal
relative generated HTML, CSS, JavaScript or SVG files, without traversal, encodings or symlinks.
CLI and API stream the same bytes.

## Previewing a table's rows

A table's page in the catalog has a **Data** tab for developers and administrators: the first 100
rows, read from the warehouse when the tab opens, with long values cut at 200 characters.

```sh
etl-craft --project SALES catalog preview --table ods.orders --limit 20
```

`GET /api/v1/projects/{project}/table-preview?table=ods.orders&limit=100` returns the same rows
(`etl-craft/table-preview/1`: columns, rows as text, `more`). Only a table the project's catalog lists
is read, only by whole-project accounts with the developer role or above, and every request is
recorded in the audit log like an administrator's access reads, because it reads business rows. A
viewer sees no Data tab. It is a preview, not a query tool: it takes no SQL.

## Pipelines, runs and controls

**Pipelines** in the sidebar lists the project's pipelines you may view: tags, schedule, the
next scheduled run (as the controller computes it, business calendars included; a schedule that
cannot run, such as one naming an inactive calendar, shows why), the five newest runs as status
marks, the latest run's SLA result, whether automatic runs are paused, and paused tasks. Select
pipelines with their check boxes to pause or resume them together; each succeeds or fails on its
own and the result lists each one. **Export CSV** saves the listed rows. The tag list on the left filters by tag;
the filter is the same `tag` parameter as `etl-craft pipelines --tag` and
`GET /api/v1/projects/{project}/pipelines?tag=…`, so the page, the CLI and the API return the
same pipelines, with the same `next_run`, `schedule_problem` and `recent_runs` fields in JSON.

A pipeline's **Runs** tab keeps its run identifiers, outcomes, durations and filters; the
workspace grid compares the same runs by task. Select a task name in the grid to inspect its
handler and declared upstream tasks, including before the pipeline has run. The dialog links
to the task's history, definition and complete parameters. Pipeline settings, including restart
behaviour and task count, stay in the header facts; its description lives in the catalog.
Overview keeps window summaries and links to run history instead of repeating recent-run lists.
The former Tasks and Details tab addresses open Overview and preserve a selected run and task.

**Scheduled runs** also contains **Run history by day**, the historical calendar formerly on a
pipeline's Calendar tab. It includes manual runs, has a pipeline filter and can load earlier
runs; its note states how many records are loaded. It is separate from the next scheduled-start
list and is not a forecast. Old Calendar addresses open this view with the pipeline selected.

**Run now** admits one manual run of
the whole pipeline for the controller, optionally for a run date, or as a one-time **Full refresh** (optionally of one task and the tasks that read it); when a refresh would empty append targets the dialog names them and asks for a switch to accept before it runs. The pipeline header keeps the schedule, refresh type, SLA, tags and automatic-run state;
upstream pipeline relationships remain in the catalog. **Pause** and **Resume** act on automatic runs of this pipeline only. The same confirmation
appears in its header and its Pipelines row, with the wait, run-now and catch-up choices for
scheduled pipelines. Held and paused keeps the pause actor, time, reason and pipeline link;
follow that link to resume. Task Resume/Release and selected-pipeline bulk controls remain
available for their separate scopes.

The pipeline grid has one adjustable divider beside the details panel. Task names automatically
expand to the longest complete name as the grid widens, taking space from older runs first.
When the latest run would otherwise be hidden, names narrow instead. Once names fit, extra
space shows more runs. The task-name boundary is not adjustable. Drag the grid divider or
focus it and use Left/Right; Home or double-click restores the default pane width.

Automatic graph fits and **Fit view** share a readable minimum zoom (0.7 in filled panes).
Large graphs remain reachable by dragging to pan; manual zoom controls still work. Wide panes
use a horizontal layout unless another direction is selected.

The graph reads task statuses for the selected run and refreshes them every five seconds while
the run is in progress, even when the run-details tab is closed. Recorded skipped tasks say
Skipped with the shared slate colour; running tasks stay blue and successful tasks green.

A run's page draws its tasks as a graph coloured by status, with the same tasks in a table;
the **Timeline** view puts each attempt on one time axis, its wait to start apart from its run.
Select a task in the graph or the table to open its panel (status, rows, rejects, attempts and
what it waits for); the page address keeps the selection, so a link or Back returns to it.
Actions act on the selection only: the whole run, or the selected task in it. Each action comes
from the `capabilities` read: an unavailable one is disabled and says why. Choosing one opens a
confirmation with the exact scope, its data effect and whether successful work is kept; the
request goes to `POST /api/v1/projects/{project}/controls`. The scoped CLI commands
`hold`, `release`, `stop`, `abort`, `run --recover` and `run --restart` submit the
corresponding requests. The page shows the recorded status. A request is not completion: the page shows the run's state
when it changes.

A selected task's panel also has **Task actions**, each with the same confirmation: **Rerun
task** and **Rerun from here** (with the tasks that depend on it) in this run, **Run task only**
(a standalone execution outside any pipeline run), **Mark as** SUCCESS, FAILED or SKIPPED,
**Pause task** in every run (optionally giving downstream tasks a standing outcome and an end
time) and **Resume task**, and, for a fan-out task, **Items**: each item's status, rows and error,
with Rerun, Cancel and Mark as per item and **Rerun failed items**. A run that is still going has
**Reconcile**, which records attempts whose owner stopped renewing their lease as LOST so their
tasks can be retried. The pipeline header has **Refresh**, which validates and pins the current
definition. Each posts the same `/api/v1` request as the CLI (`run`, `mark`, `pause`, `items`,
`reconcile`, `pipelines refresh`).

The list, pipeline and run pages refresh themselves every 10 to 30 seconds while you use them,
as you, and stop refreshing in a background tab.

Each attempt in a task's panel opens the attempt's page: status, owner, host and process, exit
code, times, rows, the error with its failure class, and the log. The log shows its last
256 KiB (the download has all of it) and, while the attempt is queued or running, follows new
lines every 2 seconds; clear **Follow the end** to stop scrolling. **Download log** saves the
same bytes as `etl-craft logs --attempt-id ID` and
`GET /api/v1/projects/{project}/attempts/{attempt_id}/log`.

A run's **Run log** view is the pipeline run log: one line per recorded event of the run, in
time order, each with its time in UTC, a stable code (`RUN_STARTED`, `TASK_QUEUED`,
`TASK_RETRY_DUE`, `TASK_ADMITTED`, `TASK_STARTED`, `TASK_ENDED`, `TASK_LOST`, `TASK_SETTLED`,
`WAIT_OPENED`, `GATE_DECIDED`, `CONTROL_REQUESTED`, `CONTROL_ACKNOWLEDGED`, `CONTROL_COMPLETED`,
`INTERVENTION`, `SLA_BREACHED`, `SLA_MET`, `RUN_ENDED`, and the cancel codes), the run, the
task, the actor who caused it where one did, and the event's values. It is rendered from the
audit tables, not written separately, so it matches `status`, `explain` and the audit, wherever
the tasks ran. **Download run log** saves the same text as
`etl-craft logs --pipeline-code CODE --run-id ID` and `GET /api/v1/projects/{project}/run-log`.
**Download run zip** saves the whole run in one file: `run.log`, `status.json`,
`history.json` (with the run's interventions), and per task `explain.json` and each attempt's
log (`TASK/attempt-N.log`). `manifest.json` lists every file with its size; an attempt log that
cannot be read here (removed by retention, not uploaded yet, or moved) is listed with that
reason instead of being left out. `etl-craft logs --pipeline-code CODE --run-id ID --zip PATH`
writes the same zip, and `GET /api/v1/projects/{project}/run-zip` serves it.

## Pipeline Insights

**Home** shows operational panels in its tabs for the pipelines you can view, over a
window of UTC days (the last 7 by default, at most 92), optionally for selected pipelines:

- totals: runs, success rate (of finished runs), average duration, SLA breaches, retries, the
  average wait to start and the average execution time, and rows written;
- daily runs: one-to-four-day windows show dated counts and average durations as numbers;
  longer windows use a chart with a slot for every UTC day, including quiet days, and capped bars;
  days without a finished run say “No finished runs” instead of drawing a duration point;
- per pipeline: runs, success rate, average and longest duration, SLA breaches, attempts,
  retries, lost attempts, rows written and rows per second of measured execution;
- rows by task: source, target, inserted, updated, deleted and rejected counts of successful
  task runs as each handler reported them (stages are never added together);
- failures by task and failure class; data quality rules with their failed runs, passed and not
  passed table checks, flagged rows and newest observed values; schema and lineage checks by
  attribute and state; and the latest runs, each linking to its run.

A count a task did not report is shown as **Not measured**, never 0, and rates are computed
from summed counts. `etl-craft insights [--from DAY] [--to DAY] [--pipeline-code CODE]
[--tag TAG] --format json` and `GET /api/v1/projects/{project}/insights` return the same
document, and the generated catalog has an **Insights** tab with the last 7 days at generation.

The schema and lineage panel says when the warehouse was last compared with the declared tables
and on what schedule. **Check now** runs the comparison and rebuilds the catalog (it needs the
developer role, and is disabled when the project turns on-demand checks off). Until a check
has run, the states come from the declared metadata only and most read Unchecked.

## Command console

**Console** in the sidebar is the etl-craft CLI in the browser. Type a command line as you
would in a terminal (`pipelines`, `status --pipeline-code ORDERS`, `pause --pipeline-code
ORDERS --reason maintenance`, `--format json` for JSON): it runs in the selected project as
you, through the same actions and checks as the CLI and the API, and prints the CLI's own text,
errors and exit code. Tab completes commands and flags, ↑ and ↓ recall earlier lines, and
`help` or `COMMAND --help` prints the usage.

The console lists the commands your account role or pipeline grants can run; each command is
still checked when it runs. It never runs host commands (`controller`, `migrate`, `ui`), never
edits config files (`config`, `rename`), never signs in, never reads or writes a file on the
server (options such as `--zip` or `--output`), and never prompts for a password: use the CLI
for those. **Your recent requests** lists your audited requests (`audit --mine`); reads are not
recorded. The console is available in servers started with `etl-craft ui` or
`etl-craft controller`.

## Search

The search box in the top bar (press `/` or Ctrl+K) finds pipelines and tasks by any part of
their code or name, a run by its exact run id or run key, and tables when you can view the
whole project. Results open the object's page; a table opens its catalog page. The search page
also lists the pipelines and runs you opened recently in this browser; they are kept in the
browser only. `etl-craft search TEXT` and `GET /api/v1/projects/{project}/search?q=TEXT` return
the same hits. In top-bar suggestions, Up/Down selects a result and scrolls it into view; Enter
opens it, and Escape closes the suggestions. A failed search names the query and the cause,
with **Retry search** reachable by Tab; page shortcuts remain available during an index outage.
The interface names task handlers in words (for example, Email alert); API and
CLI results retain the handler codes.

## Administration

Administrators see **Administration** in the sidebar. Its tabs list accounts, groups, API
tokens, pipeline access (per project), projects, pools and announcements, and each form or row
action posts the same request as the matching CLI command (`account`, `group`, `token`,
`access`, `project`, `pool`, `announce`), so the same checks and audit records apply. The
Accounts tab shows whether an account is locked, its failed sign-ins and last sign-in, and
offers **Unlock**; you cannot disable your own account from the page. A created token's value
appears once, with **Copy token**: store it then, because it is never shown again.

Announcements post a banner on every page for everyone signed in, from their start until their
end or until an administrator ends them; critical announcements are read out by screen
readers. From the CLI:

```bash
etl-craft announce add --message "Upgrade tonight at 22:00 UTC" --level WARNING \
  --ends-at 2026-11-01T23:00:00+00:00 --reason "planned upgrade"
etl-craft announce list --all
etl-craft announce end --announcement-id 3 --reason "upgrade finished"
```

## Tasks and uploads

Select a task name in the pipeline grid, then follow **Task history, definition and parameters**
(or find the task with search) to open its page: its last
runs with the rows read, inserted, updated, deleted and rejected, how long each took and rows
per second, and the success count. An ingestion Python task shows its stored **Offset** and a
watermarked SQL task its **Watermark**; operators can reset it, and the next run starts from
the new value (the same request as `etl-craft mark --offset` or `--watermark`). `etl-craft offset
--pipeline-code P --task-code T` prints the stored value.

**Uploads** lists the pipelines that take files from you (`STEWARDABLE_FLAG=Y` and a
`CAN_UPLOAD` grant). Choose one, pick a file and select **Upload**; the receipt says which run
validates and loads it, or which run it waits behind. The table below lists the pipeline's
recent files with their state, run and the validation reason for a refused file. See
[Stewardship uploads](stewardship.md).

## Task definitions and data

A task's page also shows its **Definition**: the handler and every parameter, as new runs use
them (`etl-craft task` prints the same). On an SCD1 or SCD2 merge task, the **Data** panel looks
up one business key in the target and shows who last wrote each value and which values are
locked against the next merge. Administrators can **Save values** (edited values stay locked)
and **Unlock** values so the next merge applies source values again. Every lookup, edit and
unlock is recorded.

## Catalog and refresh actions

The **Catalog** page offers **Validate metadata** to everyone, **Rebuild catalog** and
**Refresh lineage** to developers, and **Record catalog versions** to administrators; before the
first build it says the catalog is not generated yet. The **Pipelines** list has **Refresh all**
for developers, which validates every pipeline's current definition and pins passing versions.

## Held and paused work

**Held and paused** lists what is waiting on a person: runs or tasks on hold (operators can
**Release** them), paused pipelines (resume them from the pipeline's page, where you choose to
run now, catch up or wait), and paused tasks with what downstream tasks see meanwhile (operators
can **Resume task**). `etl-craft holds` lists the holds.

On a pipeline's **Runs** and **Matrix** tabs, filter runs by **Pool**, **Agent id** or
**Failure class** to find, for example, the runs that failed permanently or ran on one agent;
the filters stay on the older-runs links. `etl-craft history --pipeline-code P --all
--failure-class PERMANENT` returns the same runs.

## Operations

**System health** in the sidebar shows whether a controller is running (no heartbeat in the
last minute means schedules, retries and queued tasks are not starting), warns when
controllers run another version than the server, gives the Engine DB schema version, and, when
`Deployment.Profile` is `CONTROLLER_AGENTS`, the active agents and each pool's free capacity.
It also lists each project's running, queued, failed and SLA-missed work for the last 24
hours. Warehouse connections are checked by each task and by `etl-craft doctor` on the host.
The schema version shows its number; hover over it for the complete migration filename.

**Agents** lists registered agents with their pool, version, heartbeat, running attempts and
free capacity. Operators can **Drain** an agent (it finishes its tasks and claims no more),
**Resume** it, or **Stop** it, the same requests as `etl-craft agent drain|resume|stop`.

**Scheduled runs** lists a project's scheduled pipelines by their next run, and separately the
scheduled pipelines that will not run, with the reason: paused (by whom and why) or a schedule
with no next run.

**Maintenance** (admins) previews each task before it runs: **Preview purge** lists the history
rows that would be removed, **Preview SQL** shows the rehash or audit-column upgrade
statements, and the second button runs the task after you confirm. **Clone now** copies the
Engine DB tables into the warehouse when cloning is enabled.

## Upgrade

Run `etl-craft migrate` before starting the new server. Normal login and UI startup refuse
pending Engine migrations, naming the Engine DB key and applied/required migration. If no
admin session is available, the local `migrate` command prompts for the admin account and
password. Its upgrade-only proof reads the original account fields, issues no session and
never applies lockout counters; wrong passwords and non-admins are refused and audited. Engine migration
`0075_browser_accounts.sql` follows business calendars (0074) in both dialects. It adds
`FAILED_SIGNINS` (0), `LOCKED_DATE` (NULL), `MUST_CHANGE_PASSWORD` (N) and validated
`UI_SETTINGS` ({}) to existing `CFG_ACCOUNTS` rows. Existing passwords and accounts remain;
a later admin password reset sets the temporary-password requirement. The migration also
adds partial indexes for recent health counts and successful sign-in/catalog audit reads.

Migration `0078_announcements.sql` adds the `AUD_ANNOUNCEMENTS` audit table; existing data is
unchanged.

## Audit presentation

The run grid orders runs from oldest to newest, with the newest on the right and initially visible. Its single outer divider remains
adjustable; names size automatically to the longest name and narrow only to preserve the newest
run. Recorded skipped tasks name their failed upstream in the task list, and active-run graphs
refresh recorded task statuses and shared colours while the run is still in progress.
Sparse rankings and duration series show numbers rather than tiny charts. Catalog gaps name the
next corrective step. Nested pages use breadcrumbs and shared controls; empty lists explain what
fills them. Graph code loads on opening the graph; catalog code loads on entering the catalog.
Home’s daily chart and sparkline renderers load when used, with their space reserved while
loading. Numeric summaries and the run/catalog duration strips keep their existing rendering.

Run now still opens a confirmation naming the project and environment. Its reason follows the project’s governance: STRICT requires one in every environment;
RELAXED permits an empty reason. Production projects remain STRICT and still require the exact
project code to be typed. Other run actions follow the same governance policy. Account Kind and Role are populated required fields, and SSO
email-binding guidance is help text beside the email field.

The console's recent requests show completed command outcomes. These do not substitute for run
status: admission of a run can succeed while the run later fails. API documentation remains at
`/api/v1/docs` and `/api/v1/openapi.json`.

Run addresses accept the complete stored label as well as an integer. The browser sends the
full value to the shared operations resolver; a wrong-case or mismatched label displays the
server's refusal and expected label, without opening controls for the numeric suffix.

## Reading lists and failure details

Empty lists and charts name what is missing and give the next step for that page: for example,
set a pipeline schedule, choose an upload, or start an agent. Dense lists show a status dot and
word; failures and warnings retain their pills, as do statuses on detail pages.

An attempt leads with its recorded error message. Open **Process details** for the unchanged
failure classification, source and code, along with process and retry evidence. The Home
Failures table also keeps its classification under **Process details**.

On screens narrower than 480 px, Runs uses labelled cards that retain every table field.
Run numbers appear above single-line labels; hover or keyboard focus reveals the full label.
Pipeline, Status and Tags filters stack. Home tabs scroll within the 16 px side gutters;
keyboard focus brings each tab into view without scrolling the page horizontally. Left/Right
moves between tabs; Home/End selects the first/last tab. Edge chevrons indicate more tabs.
The recent-run strip and duration bars open a run chooser with full identifiers and statuses;
choose a run with touch or the keyboard to inspect it in the current tab.

Column-mapping nodes initially show five rows. Scroll their column lists or resize the boxes
to inspect more; wires follow visible rows, with off-screen columns attached at the list boundary.

Drag a mapping node by its header to move it independently; drag the canvas background to pan.
Diagram canvases have application-drawn horizontal and vertical scrollbars inside their frames. Their
thumbs follow panning, zoom and Fit view; scroll the tracks or focus them and use the arrow keys.
The toolbar’s Move view left/right/up/down buttons remain available for mouse, touch or
Enter/Space activation. Both methods retain the zoom and node positions.

Collapsed tasks show a type icon with their name underneath; table headers keep their
compact framed identity. Expanded objects become framed windows with a distinct title bar.
Expanded windows keep persistent application-drawn vertical and horizontal scrollbars; long column names and
details scroll inside the window without clipping. Runtime task
icons keep their identity while status badges report the changing run state. Workspace panes
keep visible neutral scroll tracks when their content overflows.
The tracks and thumbs retain their appearance even when browser or OS settings hide native
scrollbars. Tab focuses a scrollbar; arrows move in small steps, Page Up/Down moves a page,
and Home/End reaches either end. Drag a thumb or click its track with a mouse or touch.
Column content retains native wheel, touch and focus scrolling.

Connection anchors stay invisible. Three dots in the lower-right scrollbar corner resize the
window. Narrow mouse resize bands follow the frame edges, leaving the surrounding canvas free.
Focus a mapping width/height grip and use the arrow keys to resize it. Column lists keep a
scrollbar gutter; collapsing a resized box hides its rows, and expanding restores its size.
Click a wire, or focus it and press Enter/Space, to highlight its recorded path and endpoints.
Column connections highlight the corresponding rows; object-only connections highlight their
frames without implying column lineage. Activate it again or press Escape to clear the selection.
Selecting a connection keeps the address and viewport unchanged.

Table columns and split panes also support keyboard resizing. The view key opens on request, remembers your choice and keeps its close
button visible while you scroll its entries. Desktop mapping and catalog graph panes fill the
available frame height. Fit view zooms out to show the complete diagram; workspace task graphs
keep a 70% readability floor, with scrollbars reaching the remaining objects in large graphs.
Reset zoom returns to 100% for reading.

Mapping rows with filters, expressions or rules have a neutral icon/label and a logic preview;
these indicators do not use the selected lineage’s accent ring. Resolved object/column names
identify each row, while the source-alias key explains abbreviations in the unchanged SQL preview.

Diagram categories use separate colour families: cyan inputs, violet relational stages, magenta
filters and rules, teal calculations, and brown writes and targets. Run-state colours keep their
own meanings. Keys show the same dependency patterns, selection outlines, condition chips and
row markers as the view. The selection entry appears only while a lineage path is selected.
Expand a derived-query alias to inspect its recorded SQL. After upgrading, rebuild an older
catalog to include its subquery and CTE source bindings.

The table’s **Lineage diagram** opens table boxes into columns. Select a column to follow
its recorded upstream and downstream paths; collapsed boxes keep the object relationship.
A labelled dashed connection means the table relationship is known but a column path is not
recorded. The same scroll, resize and independent header-drag controls apply to these boxes.
**Column sources** lists each column’s upstream source and writing task. When more than one
task writes a target, choose a Writing task to filter that list. Unavailable lineage names
the task and the recorded reason, rather than suggesting that an existing definition is absent.


The Catalog header's **Collapse catalog sidebar** / **Expand catalog sidebar** controls every
catalog page, independently of the application navigation. It replaces the diagram-only Full
width control; small screens start collapsed. Mapping remains a diagram on phones too. Its
**Column sources** tab keeps the table, stage conditions, rule expressions, provenance and
declared table-level sources. Column rows can be filtered without hiding whole-task logic.
Table Overview keeps Written by, Read by and Schema once; its column list stays there.
The catalog pipeline's **Open pipeline runs** link opens the project's live Runs page filtered
to that pipeline, and its old Runs tab address redirects there. Task Runs stays because it adds
task-run identifiers and inserted/updated/deleted counts. The catalog filter remains scoped to
the built objects and columns, while top-bar search uses the live operational index.
