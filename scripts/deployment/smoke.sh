#!/usr/bin/env bash
# Execute the published Compose example with disposable credentials and volumes.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
: "${ETL_CRAFT_VERSION:?Set the exact built image version}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-etl-craft-deploy-test}"
export ETL_CRAFT_PROJECT_IMAGE="etl-craft-project:$ETL_CRAFT_VERSION"
export ENGINE_PASSWORD="$(openssl rand -hex 24)"
export SMOKE_ADMIN_PASSWORD="Aa!$(openssl rand -hex 24)"
unset CONTROLLER_TOKEN AGENT_TOKEN
scratch=$(mktemp -d)
cp "$root"/docs/deploying/compose/* "$scratch/"
compose() { docker compose -f "$scratch/compose.yml" "$@"; }
cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then compose logs --no-color --tail=80 >&2 || true; fi
    compose down -v --remove-orphans >&2
    unlink "$scratch/tls/server.key"
    unlink "$scratch/tls/server.pem"
    unlink "$scratch/tls/ca.pem"
    rmdir "$scratch/tls"
    rm -rf "$scratch/build"
    for file in "$scratch"/*; do unlink "$file"; done
    rmdir "$scratch"
}
trap cleanup EXIT
mkdir -m 700 "$scratch/tls"
openssl req -new -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=etl-craft.test \
    -addext 'subjectAltName=DNS:etl-craft.test,DNS:etl-craft-ui-tls' \
    -keyout "$scratch/tls/server.key" -out "$scratch/tls/server.pem" >/dev/null 2>&1
cp "$scratch/tls/server.pem" "$scratch/tls/ca.pem"
mkdir -p "$scratch/build/wheels"
cp -R "$root/scripts/deployment/project" "$scratch/build/project"
uv build --wheel --out-dir "$scratch/build/wheels" "$root"
docker build -f "$root/docs/deploying/Dockerfile" \
    --build-arg "BASE_IMAGE=ghcr.io/etl-craft/etl-craft:$ETL_CRAFT_VERSION-ui" \
    --build-arg "ETL_CRAFT_REQUIREMENT=etl-craft[duckdb]==$ETL_CRAFT_VERSION" \
    -t "$ETL_CRAFT_PROJECT_IMAGE" "$scratch/build"
rm -r "$scratch/build"
compose up -d --wait postgres
credentials=$(compose run --rm -T --no-deps -e SMOKE_ADMIN_PASSWORD --entrypoint python ui - \
    < "$root/scripts/deployment/bootstrap.py")
read -r CONTROLLER_TOKEN AGENT_TOKEN SMOKE_AGENT_ID <<< "$credentials"
export CONTROLLER_TOKEN AGENT_TOKEN SMOKE_AGENT_ID
compose up -d --wait --wait-timeout 120 controller ui proxy agent
for index in 1 2; do
    compose exec -T --index "$index" -e SMOKE_ADMIN_PASSWORD ui python - <<'PY'
import json
import os
from urllib.request import Request, urlopen

body = json.dumps({"name": "smoke-admin", "password": os.environ["SMOKE_ADMIN_PASSWORD"]}).encode()
request = Request("http://127.0.0.1:8730/api/v1/login/password", body,
                  {"Content-Type": "application/json"})
with urlopen(request, timeout=5) as response:
    assert response.status == 200 and json.load(response)["access_token"]
print("UI replica accepted sign-in")
PY
done
compose exec -T controller python - <<'PY'
from urllib.error import HTTPError
from urllib.request import urlopen

for path in ("/health", "/metrics"):
    with urlopen("http://127.0.0.1:8730" + path, timeout=5) as response:
        assert response.status == 200
try:
    urlopen("http://127.0.0.1:8730/api/v1/docs", timeout=5)
except HTTPError as error:
    assert error.code == 404
else:
    raise AssertionError("controller unexpectedly served API traffic")
print("Controller serves its headless probes")
PY
compose exec -T agent python - <<'PY'
import os
from pathlib import Path

assert os.getuid() != 0
assert "ENGINE_PASSWORD" not in os.environ and "CONTROLLER_TOKEN" not in os.environ
assert "Engine:" not in Path("craft-connector.yml").read_text()
PY
ETL_CRAFT_TOKEN="$CONTROLLER_TOKEN" compose run --rm -T --no-deps -e ETL_CRAFT_TOKEN agent \
    run --pipeline-code SMOKE --init-only --run-key deployment-smoke
compose exec -T controller python - deployment-smoke "$SMOKE_AGENT_ID" \
    < "$root/scripts/deployment/check-attempt.py"
if [ "${1:-}" = "--k3d" ]; then
    second=$(compose exec -T ui etl-craft token create --name smoke-agent-two \
        --role agent --pool default --format json)
    read -r SECOND_AGENT_TOKEN SECOND_AGENT_ID < <(
        python -c 'import json,sys; d=json.load(sys.stdin); print(d["token"],d["metadata"]["token_id"])'             <<< "$second"
    )
    export SECOND_AGENT_TOKEN SECOND_AGENT_ID
    compose stop agent controller
    bash "$root/scripts/deployment/k3d.sh" "$scratch" "$(compose ps -q postgres)" "$(compose ps -q ui | head -1)"
fi
