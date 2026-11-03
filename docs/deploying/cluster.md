# Deploy controller, UI and agents

Use one active controller, two or more UI copies behind a TLS proxy and as many agents as
your workload needs. Use the same package version for every role.

| Image | Roles |
| --- | --- |
| `ghcr.io/etl-craft/etl-craft:<version>` | `controller --no-ui`, `agent`, `run` |
| `ghcr.io/etl-craft/etl-craft:<version>-ui` | `ui`, all-in-one `controller`, or any base role |

The base image includes every supported warehouse driver, S3 access and Excel upload support
so agents can take work from any project in their pool. The UI image adds the HTTP and browser
dependencies. Both run as UID/GID 10001 with `etl-craft` as the entrypoint. Mount writable
volumes at `/project`, `/state` and `/tmp`. The project volume holds project state, logs and
pending or processed uploads. Keep container root filesystems read-only.

Pull the exact version. The release workflow publishes those tags after the release gate and
deployment smoke checks pass. For a local build, use the wheel produced by this repository:

```sh
uv build --wheel
docker build --target base -t etl-craft:local .
docker build --target ui -t etl-craft:local-ui .
```

Keep one wheel in `dist/` for the build. The context excludes project credentials and other
workspace files. The image does not need build-time secrets.

## Single-host Compose

Use the [Compose template](compose/compose.yml), [host configuration](compose/engine.yml),
[agent bootstrap](compose/agent.yml) and [nginx configuration](compose/nginx.conf) in one
directory. The template runs PostgreSQL, a headless controller, two UI copies, one outbound
agent and an HTTPS proxy. It is separate from the repository's development services.

1. Set `ETL_CRAFT_VERSION` to the published version and `ENGINE_PASSWORD` to a secret. Provide
   `tls/server.pem`, `tls/server.key` and `tls/ca.pem` for `etl-craft.test`, or update the
   proxy name and the agent API URL together. The template binds the TLS port to loopback.
2. Start PostgreSQL. Initialize the database using a one-shot UI image container and the
   `setup --admin-name NAME --password-stdin` command. Supply the first password via stdin.
   For example, run `docker compose run --rm -T ui setup --admin-name NAME --password-stdin`.
3. Open a one-shot shell with `docker compose run --rm --entrypoint /bin/sh ui` and sign
   in there with `etl-craft login`. In that shell, issue an admin service token with
   `etl-craft token create --name host --role admin` and a pool-bound token with
   `etl-craft token create --name agent-one --role agent --pool default`.
   Set `CONTROLLER_TOKEN` and `AGENT_TOKEN` from your secret manager, then run
   `docker compose up -d --wait`. Follow [project bundles](project-bundles.md) to publish and
   refresh your project's execution files before submitting work.
4. Point clients and agents at the proxy's HTTPS URL. Check the controller and UI
   `/health` endpoints directly on the internal network. Scrape `/metrics` there too.
   The proxy leaves `/metrics` private.

The example uses DuckDB for a one-agent smoke project. Give production agents their appropriate
warehouse configuration and isolated credentials. Use a shared warehouse for jobs that must
see each other's output across agents.

## Kubernetes

Use the [controller and UI manifests](kubernetes/roles.yml) and the [agent
manifest](kubernetes/agent.yml). Replace the version tags and provide:

- An external PostgreSQL Engine DB with synchronous replication or managed zero-data-loss
  failover. Put the controller near the primary. It needs a direct or session-pooled connection
  for leadership and notifications. The UI's ordinary queries can use transaction pooling,
  with a separate session connection for claims. See [Engine DB setup](engine-db.md).
- A ConfigMap named `etl-craft-config` containing `engine.yml`, `agent.yml` and an HTTPS
  `api-url` for the ingress. Adapt the Compose configurations to the external database and
  warehouse. Leave the Engine section out of the agent bootstrap.
- A Secret named `etl-craft-engine` with `ENGINE_PASSWORD` and the host service
  `ETL_CRAFT_TOKEN` for the controller and UI. Give the agent its own Secret
  `etl-craft-agent-token` containing only `ETL_CRAFT_TOKEN`. The agent opens no port.
- A shared read/write claim named `etl-craft-project` for the controller and UI project files,
  logs and uploads. Use an RWX volume if the pods can run on different nodes. Configure a
  durable [artifact store](project-bundles.md) and [log store](operations.md) reachable from
  every role that reads or writes them. An agent retrieves pinned files through the API and
  uses its own writable bootstrap and temporary volumes.
- TLS ingress in front of the UI Service with no session affinity. Keep
  `Docs_site.Trusted_proxies` scoped to the actual ingress source network, and configure
  claim and stream timeouts as in [the proxy guide](load-balancer.md).

Apply the role and agent YAML with `kubectl apply -f roles.yml -f agent.yml` after creating
the referenced resources.

Keep each agent Deployment at one replica. Registration rejects a second live process using
the same token because that token owns its attempts. To add an agent, copy the Deployment,
give it a distinct name and selector, and reference a Secret containing a newly issued token.
Using an environment Secret reference avoids mounting token files where task children could
read them. Each copy uses `etl-craft agent health` to check a local renewal timestamp less
than 30 seconds old. This command opens no listener and needs no credentials.

The controller and UI probe `/health` on port 8730. The Prometheus scrape annotations are
examples for a collector that honors them. Restrict `/metrics` to the internal network, including
at ingress. S7.I reads `controller_tick_duration_seconds` from the headless controller's
`/metrics` endpoint.

## Sizing and systemd

Start with at least 1.5 times an agent's memory for the controller. Its supervision tick runs in
one thread. Favor a fast core, memory for active graphs and low latency to PostgreSQL. Scale the
UI copies for request demand and add independent agents for task capacity. See [sizing](sizing.md)
for connection ceilings and task slot budgets.

For hosts without containers, install the same version in `/opt/etl-craft` on all hosts and
adapt the [controller](systemd/etl-craft-controller.service), [UI](systemd/etl-craft-ui.service)
and [agent](systemd/etl-craft-agent.service) units. Create an unprivileged `etl-craft` account,
mount the project and stores with access for that account, and give each agent its own
bootstrap directory and token. Keep the systemd environment files root-readable only. Put
Engine DB credentials only in the controller and UI environment files. The agent environment
needs `ETL_CRAFT_API`, its own `ETL_CRAFT_TOKEN` and any separately authorized warehouse settings.
