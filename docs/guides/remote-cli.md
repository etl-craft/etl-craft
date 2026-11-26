# Operating a server from your own installation

Install etl-craft on your laptop or CI runner and operate an existing server by its URL.
You need an account on that server and access to the project, but no Engine DB or warehouse
credentials, drivers or network access to those databases. The server holds those credentials
and executes the work.

## Install and sign in

```bash
pip install etl-craft
etl-craft login --api https://etl.example.com
```

Use the server's base URL, without `/ui` or `/api/v1`. Enter your account name and password
at the prompts. If the server offers SSO, answer yes to **Sign in with SSO?**, open the
verification URL and enter the displayed device code in your browser. The CLI waits for the
server to verify the sign-in. Your administrator must have configured device flow with the
identity provider.

Sign-in stores credentials privately for that server URL. Access tokens last one hour;
the CLI renews them using a refresh token lasting `Auth.Refresh_days` (default 30 days).
A service token already set in `ETL_CRAFT_TOKEN` takes precedence over a stored user session;
unset it when signing in as yourself.

Name the server once for the shell session, and select the server's project code explicitly:

```bash
export ETL_CRAFT_API=https://etl.example.com
etl-craft whoami --project SALES
etl-craft pipelines --project SALES
```

`--api` overrides `ETL_CRAFT_API` for one command. `--project` selects the metadata namespace
on that server, not a local directory. If a local `craft-connector.yml` selects a different
project, use that project's own directory instead; conflicting selections are refused.
Read-only commands need no local connector file when you pass `--project`.

## Plan and deploy from a laptop

Start with your team's checked-out project directory, containing `craft-connector.yml` and
its `config/`, scripts and any `seeds/`. Connection secrets in the connector remain variable
names; you do not need their values locally. Ask the administrator for a developer account
with project management permission and a server project configured with `Artifacts.Store`.
Remote deploy requires that store; without it, deploy reads the server's host directory and
refuses API deployment. Changing the approved connection contract requires an admin.

```bash
etl-craft deploy --project SALES --project-dir ./sales-project --plan
etl-craft deploy --project SALES --project-dir ./sales-project
```

Review the plan before applying it. `--plan` checks the uploaded files, validates and rolls
back config changes, and lists seed tables; it publishes nothing and changes nothing.
Deploy uploads the project, publishes a bundle to the configured store, applies config files,
loads seeds and re-parses pipelines in that order. It stops at the first failure. A project
without `config/` skips that step. See [configuration files](configuration-files.md) for the
CSV format and merge rules.

Project migrations are different: `migrate` is host-only and must run on the controller's
host. Deploy does not send or apply `migrations/`. Have the deployment administrator apply
reviewed migrations there using the [migration guide](configuration-migrations.md).

## Deploy from CI

Have an administrator issue a SERVICE account token with the required developer permissions.
Store it in your CI secret store and inject it as `ETL_CRAFT_TOKEN`; never put its value in the
repository or a command argument. Service tokens do not refresh. Rotate them before expiry.
With the project checked out and the token injected, the job runs:

```bash
export ETL_CRAFT_API=https://etl.example.com
etl-craft deploy --project SALES --project-dir ./sales-project --plan --yes
etl-craft deploy --project SALES --project-dir ./sales-project --yes
etl-craft run --project SALES --pipeline-code SALES_DAILY --reason "CI deployment" --yes
```

Use a reviewed plan as your deployment gate. `--yes` supplies the production project
confirmation for unattended commands; it does not bypass authorization or validation.

## Run, watch and step in

An operator with the appropriate pipeline grant can submit a run. A whole-pipeline run over
the API submits work for the controller; a successful submission does not mean the load has
finished. Copy the returned run identity and use it for later commands. The numbers below
stand for identities returned by your server:

```bash
etl-craft run --project SALES --pipeline-code SALES_DAILY --reason "daily load"
etl-craft history --project SALES --pipeline-code SALES_DAILY --all
etl-craft status --project SALES --pipeline-code SALES_DAILY --run-id 42
etl-craft steps --project SALES --pipeline-code SALES_DAILY --run-id 42
etl-craft history --project SALES --pipeline-code SALES_DAILY --task-code load_orders --all
etl-craft logs --project SALES --attempt-id 4812
```

Watch progress by repeating `status` for that exact run, or open the server's browser UI.
`steps` shows task status and parameters; task history lists attempts. Use an attempt id
for its log. To step in, inspect the failure
and record a reason for the intervention:

```bash
etl-craft stop --project SALES --pipeline-code SALES_DAILY --run-id 42 --reason "bad source file"
etl-craft run --project SALES --pipeline-code SALES_DAILY --run-id 42 --recover --reason "source repaired" --request-key repair-42
```

Recovery prepares unfinished work and keeps successful/skipped tasks and checkpoints. Follow
its returned execution identity explicitly when resuming; see [stepping in](run-control.md)
for recovery, marks and reruns. These actions retain the server's role, grant and governance
checks and audit records.

## Connection failures and host work

Use HTTPS. Plain HTTP is accepted only for this machine (`localhost`, `127.0.0.1`, `::1`),
for example the [Quick Start's local server](../quick-start.md#operate-the-local-server).
Redirects are refused, so use the server's final address.

An unreachable server, or a response that is not etl-craft JSON, exits **27**. Check the URL,
network and server health before retrying. Connections and request sends keep a 60-second socket
timeout. Long operations such as deploy, full validation, erasure and warehouse maintenance wait
for the server without a client read deadline. Other actions exit **33** if the response stalls for
60 seconds after the request was sent. The server may still be completing it. Check its audit
record or the action's read command before retrying. For deploy, run `deploy --plan` to see which
config changes remain and check the audit for the deployment outcome. For a run, check `status`
using the exact run identity. Other refusals keep their own exit codes and explain the remedy.

Engine DB setup and migrations, local diagnostics and exports, and starting server processes
are host work. The [generated actions reference](../reference/actions.md) is the authority for
where each action runs and which role it needs; the CLI refuses host-only actions over
`--api` with the action's remedy. This includes project migrations even though deploy can
apply config remotely.

When finished with your user session:

```bash
etl-craft logout
```

Logout, account disabling or refresh-token revocation ends that session. See
[server security](../deploying/security.md#operating-a-server-from-your-own-installation)
for the token and transport policy.
