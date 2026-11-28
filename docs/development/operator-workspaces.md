# Operator workspaces

An operator who starts on Home with a failed run should be able to inspect its first error,
then select the next failed task in the same grid. Opening evidence should preserve both the
grid's columns and the operator's place in it.

## Navigation and scope

| Sidebar, in order | Landing view | Local navigation |
| --- | --- | --- |
| Home | Current project dashboard | Overview, Capacity, Catalog health, Pipeline health, Data, Quality, Failures |
| Pipelines | Monitor | Monitor, Pipeline list, Run history |
| Catalog | Catalog explorer | Object tree and object tabs |
| Maintenance | System health | System health, Agents, Project maintenance |
| Console | Current project's command console | Transcript, command reference, recent requests |
| Admin | Accounts | Identity and access, Platform, Governance |

The header holds project switching, All projects, Search and the account menu. Show the
current project and environment. Mark platform-wide views explicitly. Scope a Home link to
its project. The Monitor scope can include all accessible projects and shows the environment
on each row. Selecting a row never changes a command's target implicitly. Keep the same
grants, unavailable-action reasons and scoped confirmations through every entry point.

## Layout and selection

```text
Sidebar     Main: grid, list, graph or Gantt across the available width
            -----------------------------------------------------------
            Selected object                    | Detail selected below
            task, run or agent                 | attempt, error or reason
```

Both lower panes open on selection or on a direct link. The lower-right pane takes width
only from the lower section and closes when its selection clears. Switching tasks clears
the previous attempt. Opening a full run promotes it to the main area. The horizontal divider
supports pointer and keyboard resizing. Collapse the lower section to return its height to
the grid. Let logs, SQL and long errors expand and restore the prior view, scroll and focus.
Project, environment, identity and live status fit in the header. Omit a permanent right rail.

At 390 px use one level at a time with a named Back action. Restore filters, selected row,
scroll and keyboard focus. Opening a shared attempt link goes straight to that attempt.
Retain full space for diagrams and logs. Use labeled cards where short tabular fields stack.
Keep named controls, visible focus, status symbols and words, and equivalent touch and
keyboard access to details. Dashboards, forms and the terminal each use the width they need.

## Page inventory

### Home

All seven views keep the project and time window. Link counts to corresponding rows with
the same scope and time semantics. Keep historical attempts reachable even outside the live
Monitor window.

| View | Content and drill-down |
| --- | --- |
| Overview | Project summary, trends and recent failures. Open the exact failed run. The incident strip links to the matching Monitor filter. |
| Capacity | Pool CPU and memory charts. Open Agents scoped to the selected pool. |
| Catalog health | Coverage, schema and lineage checks. Open Catalog gaps. |
| Pipeline health | Per-pipeline performance for the window. Open the pipeline workspace. |
| Data | Rows, freshness and task/table breakdowns. Open the named object. |
| Quality | Recorded rule results and counts. Follow the definition or the run evidence. |
| Failures | Failed or lost attempts during the selected window. Open the exact attempt. |

### Pipelines

| View | Main area and selection |
| --- | --- |
| Monitor | Live failing, running, late and waiting work. A row opens its reason and available actions below. Open the run when one exists. A missed start opens pipeline and schedule evidence. |
| Pipeline list | Search, tags, Scheduled and Paused filters, CSV and existing bulk actions. Select a row for facts below or open its grid workspace. |
| Scheduled filter | Order upcoming pipelines by next run. Group configured schedules without a next run and show the reason. |
| Paused filter | Include pipeline pauses and standing task pauses. Identify which matched and show the affected tasks, actor, time, reason and permitted resume controls below. |
| Run history | One execution per row with pipeline, project scope, status and tag filters. List and Calendar show actual runs including manual runs. Select a summary below or open the run. |
| Pipeline workspace | Identity, schedule, next run and controls above the full-width Grid, Graph or selected run's Gantt. Select a run column or a specific task cell. |
| Pipeline Overview, Runs, Audit log, Access | Show pipeline facts, scoped history, recorded changes/requests and scoped grants respectively. Long audit and grant tables can use the full work area. |
| Run selected in pipeline grid | Show Task instances and Details below. A selected instance opens its evidence at lower right. Open run offers a full workspace. |
| Run workspace | Identity, status, times and controls above Graph, List, Gantt, Events or Statistics. Keep one task per Statistics row. Reuse the task selection below each view. |
| Task definition | Without a run, show definition, lookups, offsets, standing pauses and recent history. Open the existing Catalog task mapping. |
| Task in a run | Logs, SQL / script, Details and Attempts share the lower pane. Keep task identity and attempt number visible. Expand logs and SQL on demand. |
| Attempt | Show outcome, times, metrics, first and last errors, reject counts and log anchors. At sufficient width use fixed metric columns with This try, Median and Samples as rows. On narrow surfaces label values. Keep one row per reject reason. |
| Task items | Give the list the main area. Show progress, keys, status, row counts, times and existing retry/mark controls. Open long errors below and return to the exact task/run. |
| Uploads | Enter from Pipeline list or an eligible pipeline. Show target, file action and upload history. Select an upload for outcome and resulting run. |

S7.BB.4 owns selected-stream log evidence, S7.BB.5 owns waiting and agent evidence, and
S7.BB.6 owns the bounded cross-project Monitor feed, Home counts and missed-start accounting.
Use the [monitoring design](monitoring-and-operability.md) for visibility, time windows,
pagination, performance and evidence. Before those reads ship, expose only recorded states
available through existing operations. Do not infer a missed start from an empty history.

### Catalog

Keep the existing collapsible tree and object area. The overview holds rebuild, validation,
lineage re-parse and version actions with results in place. Table inventory opens each table.
The gaps page retains object, attribute, observed state, reason and remedy.

| Object | Tabs |
| --- | --- |
| Pipeline | Overview, Graph |
| Task | Overview, Mapping, Column sources, Runs |
| Table | Overview, Data, Lineage diagram, Column sources, History, Quality |

Preserve data-access checks and links into the live workspace. The standalone published
Catalog retains Search, DAGs, Warehouse, Gaps, Insights and its generated pipeline, run,
task, table, business-rule and Python-script pages. S7.BF still owns scoped publication reads.

### Maintenance and Console

| Page | Components and layout |
| --- | --- |
| System health | Full-width controller, Engine DB, agent, pool and project health. Follow links to scoped Agents. Keep diagnostics accessible to their current readers. |
| Agents | Table above. Selected worker, pool, capacity, current attempts, pending commands and permitted controls below. Link an attempt to its run. |
| Project maintenance | Show project and environment. Purge history and Rehash a merge target each keep inputs, preview, effect and confirmation together. Clone Engine DB tables shows source, warehouse destination, effect and result. |
| Console | Command input and wide output transcript with recall and completion. Collapsible command reference preserves typed input. Recent requests below expand in place. |

### Admin

Group Accounts, Groups, Roles, Tokens and Access under Identity and access. Group Projects,
Pools, Alert channels and Announcements under Platform, and Erasure under Governance.
Use a labeled section picker on phones.

| Page | Components and layout |
| --- | --- |
| Accounts | Account table, state, creation and credential actions in focused forms. |
| Groups | Group table above, selected membership and controls below. |
| Roles | Roles above, selected commands and bindings below. Keep Explain access inputs and result together. |
| Tokens | Inventory, ownership, role, expiry and revoke controls. Issuance retains its credential display flow. |
| Access | Scope above grants. Carry project/pipeline identity into grant and revoke confirmations. |
| Alert channels | Project channel list, configuration and event settings for the chosen record. |
| Projects | Registration and administration. The header's All projects opens the everyday chooser. |
| Pools | Definitions, configured resources and controls. Link live activity to Maintenance → Agents. |
| Announcements | List, level, display period, state and compose/end forms. |
| Erasure | Project register, scoped request, confirmation and result. |

### Other entry points and bookmarks

| Page or address | Destination and behavior |
| --- | --- |
| App entry, All projects | Open the active project's Home or the chooser. Project cards show environment, governance and health. |
| Search | Header or keyboard shortcut. Grouped results and recent objects link to their owning workspace and selection. |
| Personal settings | Account menu. Identity, theme, table density/wrapping, timezone, time display, default project, page size and password link. |
| Change password, About | Focused credential form or version and live controller information, respectively. |
| Sign in, SSO callback | Standalone configured sign-in methods, then progress or refusal and a path back to sign-in. |
| Unknown address | Page-not-found message with Back and Home. |
| Existing links | Runs opens Run history. Scheduled opens Scheduled, and its pipeline-scoped historical calendar opens that pipeline's history calendar. Paused/Held opens Paused. Uploads, System health, Agents and Insights retain their equivalent destinations. Preserve project, pipeline, run, task, attempt, filters and applicable log anchors across direct entry, refresh and Back. |

Confirm the failed-run walkthrough with a seeded run containing two failed tasks. Open one
from Home, inspect its first error, switch to the other task, then return. Check grid width,
row position and readable log height at laptop size. Exercise direct attempt links and Back
at 390 px. Attach the actual changed screens at 1440 and 390 px in both themes to each UI
implementation PR for owner visual approval.
