# Access

Use bindings to give people and service accounts the actions they need. For sign-in from
your own installation, start with the [remote CLI guide](remote-cli.md); for credentials and
the shared-instance trust boundary, see [Security](../deploying/security.md).

## Access: roles and bindings

Access combines an account’s deployment role with **bindings**. A binding gives **who** a **role or
one command**, **where**:

| Part | Choices |
| --- | --- |
| Who | `--account A`, `--group G`, or `--audience viewer\|operator\|developer` (every account whose deployment role is at least that) |
| What | `--role R` (a built-in `CAN_VIEW`, `CAN_UPLOAD`, `CAN_RUN`, `CAN_MANAGE`, or a custom role) or `--action "run"` (one action) |
| Where | `--deployment` (every project), `--environment PROD` (every project of that environment type), or `--project P`, optionally narrowed with `--pipeline X` or `--tag T` |

An account may run a command when its deployment role and built-in grants allow it, or when any
binding of the account, one of its groups or its audience includes the command on the
deployment, the project's environment type, the project, or every pipeline the request names
(directly or through one of its tags). One account can therefore hold a large role on one
project, a small one on another, read-only access to every PROD project, and one extra command
on a single pipeline.

```bash
etl-craft role create data-analyst --description "Runs and inspects reporting loads" --action run --action mark
etl-craft role add-action data-analyst --action control
etl-craft role describe CAN_RUN
etl-craft access grant --account ana --role data-analyst --project sales --reason "Sales analyst"
etl-craft access grant --account ana --role CAN_VIEW --environment PROD --reason "Read production"
etl-craft access grant --account ana --action run --project hr --pipeline PAYROLL --reason "Payroll reruns"
etl-craft access grant --group platform --role pool-keeper --deployment --reason "Pool owners"
etl-craft access revoke --account ana --action run --project hr --pipeline PAYROLL --reason "Done"
etl-craft access list --project sales
etl-craft access explain --account ana --action run --project hr --pipeline PAYROLL
```

**Built-in roles.** `CAN_VIEW` reads, `CAN_UPLOAD` adds stewarded uploads, `CAN_RUN` adds
execution and operator controls, and `CAN_MANAGE` adds access delegation and project
definitions. They cannot be changed or disabled; `role describe` lists what each allows. A
principal holds one built-in level at each exact place, so granting another replaces it.

**Custom roles** are named sets of commands. Commands that act on the whole deployment
(`pool`, `alert-channel`, `announce`, `agent control`) can only be bound with `--deployment`.
Identity, access and project administration (`account`, `token`, `group`, `role`,
`access grant`/`revoke`, `project add/set/disable`) stay with deployment administrators and
cannot be put in a role; neither can sign-in, agent or controller-host commands. A custom role
or single command implies read access where it is bound (except deployment-wide), so the
account can see what it may act on. Custom bindings sit beside built-in ones; each is granted
and revoked on its own. Disabling a role, or revoking a binding, takes effect on the next
request.

**Who manages access.** Deployment administrators manage roles and every binding, and are the
only ones who bind on `--deployment` or `--environment`. A holder of `CAN_MANAGE` on a project,
pipeline or tag can grant and revoke bindings there; granting on a tag requires `CAN_MANAGE` on
that tag. `access explain` shows whether an account may run a command, the
binding or role that allows it, or the refusal and the roles that would allow it.

The HTTP actions are `POST /api/v1/access/grants`, `POST /api/v1/access/revocations`,
`GET /api/v1/access/grants`, `GET /api/v1/access/explain` and the `/api/v1/roles` routes. In the
web interface, **Administration → Roles** manages roles and deployment and environment bindings;
the **Access** tab of a project or pipeline manages the bindings there. Binding changes require
a reason. Every role and binding change keeps actor-attributed history; revoked bindings are
retained with `ACTIVE_FLAG=N`.

Groups are managed with `etl-craft group add --name sales`, `group disable`, `group add-member
--name sales --account alice`, `group remove-member` and `group list`, under `/api/v1/groups`.
Group identities and memberships are retired with `ACTIVE_FLAG=N`, never deleted.

Project access is default deny. Deployment admins hold every action everywhere. Every other
access comes from bindings: a built-in `CAN_*` role, a custom role or one named action, granted
to an account, a group or an audience on the deployment, an environment type, a project, or one
of its pipelines or tags. Each role is a stored set of actions; `etl-craft role describe CAN_RUN`
lists the built-in ones, which cannot be changed. One evaluator decides every request from them.

Grants only add. A pipeline's actions are those of every binding that reaches it, project-wide
or on the pipeline or one of its tags, so granting one person access to a pipeline never hides it
from anyone else. Any binding in a project makes the project visible, limited to what the binding
reaches: a pipeline or tag grant alone shows that pipeline and nothing else. Missing and
inaccessible projects answer identically, as do missing and inaccessible pipelines (exit 24,
HTTP 404). Lists and searches omit hidden objects. An action a visible pipeline's bindings do not
include is a permission refusal (exit 26 / HTTP 403). Disabled groups' grants stop applying, and
revocation takes effect on the next request, without a cache.

Tags remain the only pipeline grouping. `config plan` and `deploy` report the tag grants a tag edit makes
start or stop matching a pipeline, in text and JSON. This is a report only; it does not enumerate
accounts or change grant rows.

Every authenticated account has a deployment role; service tokens and SSO sessions use that
account role. Projects created with `project add` have no grants: an admin must grant access
explicitly.

`config plan`, `deploy`, project migrations and `generate-docs` require
a project binding that includes the action (`CAN_MANAGE` or a custom role). A full config
export requires `CAN_VIEW` on every pipeline, so it cannot
disclose a pipeline the account cannot see. Engine migrations and changed connection approvals still require
deployment admin. Declaring a cross-project dependency also requires `CAN_VIEW` on the upstream project.
Without upstream access, a recorded dependency reveals only its project/pipeline code and
decision, never upstream runs, logs or data. Incoming dependents are shown only when both sides
are visible.

With SSO, set optional `Auth.Oidc_groups_claim: groups` beside `Auth.Oidc_issuer` and
`Auth.Oidc_client_id`. The configured claim must be a list of group names. Only names matching
active groups at sign-in are retained; unmatched names appear in the session's login audit.
The session stores **group IDs**, so a rename keeps the identity and reusing a name cannot
transfer an old session's access to another group. Explicit Engine DB memberships are checked
on every request as well.

## Environments and governance

Only deployment admins change `ENVIRONMENT_TYPE`, `ENVIRONMENT_NAME` or `GOVERNANCE` with
`project add` or `project set`, always with `--reason`. Project `CAN_MANAGE` does not grant
these deployment-admin actions. These fields are not YAML settings or config CSV columns.
Projects upgrade as `CUSTOM` and `STRICT`; `PROD` cannot use `RELAXED`.

`RELAXED` accepts empty intervention reasons. It never relaxes roles, project grants, auditing,
constraints, leases, fencing, target locks, recorded consumption, human data protection, secrets
or retention. Administrative project, pool and access reasons remain mandatory.

For direct SQL edits and the PostgreSQL and SQLite trust boundaries, see
[database access hardening](../deploying/security.md#direct-sql-and-database-access).

## Browser account policy

See the [browser UI guide](browser-ui.md) for secure cookies, CSRF, fixed session
expiry, forced password replacement and account settings. `Auth` settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `Lockout_after` | `5` | Consecutive failed local password sign-ins; `0` disables lockout. |
| `Admin_contact` | `your administrator` | Contact text shown on sign-in and recovery. |
| `Signin_notice` | absent | Optional sign-in notice, rendered as text. |

`Auth.Session_hours` also bounds the browser cookie's fixed lifetime. SSO and service tokens
are never locked by password failures. `etl-craft account unlock --name ACCOUNT` requires an
admin. Password resets require the local user to choose a replacement at next sign-in;
`etl-craft account change-password` prompts for current and new passwords and revokes sessions.
