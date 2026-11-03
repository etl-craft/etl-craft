#!/usr/bin/env bash
# Run the published workloads with a disposable, external Compose PostgreSQL.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
scratch=$1
postgres=$2
ui=$3
cluster=etl-craft-deploy-test
network="k3d-$cluster"
export KUBECONFIG="$scratch/kubeconfig"
k3d cluster create "$cluster" --image rancher/k3s:v1.35.5-k3s1 --timeout 120s \
    --kubeconfig-update-default=false --kubeconfig-switch-context=false
k3d kubeconfig get "$cluster" > "$KUBECONFIG"
cleanup_cluster() {
    status=$?
    if [ "$status" -ne 0 ]; then
        kubectl get pods -o wide >&2 || true
        for app in etl-craft-controller etl-craft-ui agent agent-two smoke-proxy; do
            kubectl logs -l "app=$app" --tail=35 >&2 || true
        done
    fi
    docker network disconnect "$network" "$postgres" >/dev/null 2>&1 || true
    k3d cluster delete "$cluster"
}
trap cleanup_cluster EXIT
image="$ETL_CRAFT_PROJECT_IMAGE"
docker network connect "$network" "$postgres"
address=$(docker inspect -f '{{with index .NetworkSettings.Networks "'"$network"'"}}{{.IPAddress}}{{end}}' "$postgres")
node="k3d-$cluster-server-0"
platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
docker image save --platform "$platform" "$image" nginx:stable-alpine |
    docker exec -i "$node" ctr -n k8s.io images import -
apply_manifest() {
    local manifest
    manifest=$(cat)
    printf '%s\n' "$manifest" | kubectl apply --server-side --dry-run=server -f - >/dev/null
    printf '%s\n' "$manifest" | kubectl apply --server-side -f -
}
docker exec "$node" mkdir -p /etl-craft-smoke
docker exec "$ui" tar -C /project/artifacts -cf - . |
    docker exec -i "$node" tar -C /etl-craft-smoke -xf -
docker exec "$node" chown -R 10001:10001 /etl-craft-smoke
apply_manifest <<YAML
apiVersion: v1
kind: Service
metadata: {name: postgres}
spec: {clusterIP: None, ports: [{port: 5432}]}
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: postgres
  labels: {kubernetes.io/service-name: postgres}
addressType: IPv4
ports: [{port: 5432}]
endpoints: [{addresses: ["$address"]}]
---
apiVersion: v1
kind: PersistentVolume
metadata: {name: etl-craft-smoke}
spec:
  capacity: {storage: 1Gi}
  accessModes: [ReadWriteMany]
  storageClassName: ""
  hostPath: {path: /etl-craft-smoke}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: etl-craft-project}
spec:
  accessModes: [ReadWriteMany]
  resources: {requests: {storage: 1Gi}}
  storageClassName: ""
  volumeName: etl-craft-smoke
YAML
kubectl create configmap etl-craft-config --from-file="$scratch/engine.yml" \
    --from-file="$scratch/agent.yml" --from-literal=api-url=https://etl-craft-ui-tls --dry-run=client -o yaml | apply_manifest
kubectl create configmap smoke-ca --from-file=ca.pem="$scratch/tls/ca.pem" \
    --dry-run=client -o yaml | apply_manifest
create_secret() {
    # Keep literal credentials out of process arguments and command output.
    local name=$1
    python -c 'import json,os,sys; name=sys.argv[1]; args=[p.split("=",1) for p in sys.argv[2:]]; print(json.dumps({"apiVersion":"v1","kind":"Secret","metadata":{"name":name},"stringData":{k:os.environ[v] for k,v in args}}))' \
        "$@" | apply_manifest >/dev/null
}
create_secret etl-craft-engine ENGINE_PASSWORD=ENGINE_PASSWORD ETL_CRAFT_TOKEN=CONTROLLER_TOKEN
create_secret etl-craft-agent-token ETL_CRAFT_TOKEN=AGENT_TOKEN
create_secret etl-craft-agent-two-token ETL_CRAFT_TOKEN=SECOND_AGENT_TOKEN
kubectl create secret tls smoke-tls --cert="$scratch/tls/server.pem" --key="$scratch/tls/server.key" \
    --dry-run=client -o yaml | apply_manifest
apply_manifest <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata: {name: smoke-proxy}
data:
  default.conf: |
    server {
      listen 443 ssl;
      ssl_certificate /tls/tls.crt;
      ssl_certificate_key /tls/tls.key;
      location / {
        proxy_pass http://etl-craft-ui:8730;
        proxy_read_timeout 300s;
        proxy_buffering off;
      }
    }
---
apiVersion: v1
kind: Service
metadata: {name: etl-craft-ui-tls}
spec:
  selector: {app: smoke-proxy}
  ports: [{port: 443}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: smoke-proxy}
spec:
  replicas: 1
  selector: {matchLabels: {app: smoke-proxy}}
  template:
    metadata: {labels: {app: smoke-proxy}}
    spec:
      containers:
      - name: proxy
        image: nginx:stable-alpine
        imagePullPolicy: Never
        volumeMounts:
        - {name: config, mountPath: /etc/nginx/conf.d, readOnly: true}
        - {name: tls, mountPath: /tls, readOnly: true}
      volumes:
      - name: config
        configMap: {name: smoke-proxy}
      - name: tls
        secret: {secretName: smoke-tls}
YAML
# Test-only CA. The published example uses the deployment ingress CA.
apply_agent() {
    kubectl patch --local -f - --type=strategic -o yaml -p '{
      "spec":{"template":{"spec":{
        "containers":[{"name":"agent","env":[{"name":"SSL_CERT_FILE","value":"/ca/ca.pem"}],
          "volumeMounts":[{"name":"ca","mountPath":"/ca","readOnly":true}]}],
        "volumes":[{"name":"ca","configMap":{"name":"smoke-ca"}}]
      }}}}' | apply_manifest
}
sed "s|etl-craft-project:1.0.0rc1|$image|g" "$root/docs/deploying/kubernetes/roles.yml" |
    apply_manifest
sed "s|etl-craft-project:1.0.0rc1|$image|g" "$root/docs/deploying/kubernetes/agent.yml" |
    apply_agent
# Kubernetes must refuse to start an agent whose Secret lacks the token key.
kubectl create secret generic smoke-missing-token --from-literal=unrelated=unused \
    --dry-run=client -o yaml | apply_manifest
sed -e "s|etl-craft-project:1.0.0rc1|$image|g" \
    -e 's/^  name: agent$/  name: agent-missing-token/' \
    -e 's/app: agent$/app: agent-missing-token/' \
    -e 's/etl-craft-agent-token/smoke-missing-token/' \
    "$root/docs/deploying/kubernetes/agent.yml" | apply_agent
kubectl wait --for='jsonpath={.status.containerStatuses[0].state.waiting.reason}=CreateContainerConfigError' \
    pod -l app=agent-missing-token --timeout=60s
kubectl get pod -l app=agent-missing-token \
    -o 'jsonpath={.items[0].status.containerStatuses[0].state.waiting.message}' |
    grep -F ETL_CRAFT_TOKEN
kubectl delete deployment agent-missing-token
for workload in deployment/etl-craft-controller deployment/etl-craft-ui \
    deployment/smoke-proxy deployment/agent; do
    kubectl rollout status "$workload" --timeout=180s
done

submit() {
    kubectl exec deploy/etl-craft-ui -- etl-craft run --pipeline-code SMOKE \
        --init-only --run-key "$1"
    kubectl exec -i deploy/etl-craft-controller -- python - "$1" "$2" \
        < "$root/scripts/deployment/check-attempt.py"
}
submit kubernetes-agent-zero "$SMOKE_AGENT_ID"
# Drain the first registration so the second agent must claim the next run.
kubectl exec -i deploy/etl-craft-ui -- python - "$SMOKE_AGENT_ID" <<'PY'
import sys
from etl_craft.config import load_config
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, AgentCommand, ApiRole
from etl_craft.dialects.engine import build_engine
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.agent_models import AgentControl

config = load_config("craft-connector.yml")
engine = build_engine(config)
ctx = OperationContext(engine, config, Actor("smoke-host", ActorKind.SERVICE), role=ApiRole.ADMIN)
invoke(ctx, ActionName.AGENT_CONTROL, AgentControl(agent_id=int(sys.argv[1]), command=AgentCommand.DRAIN))
engine.dispose()
PY
sed -e "s|etl-craft-project:1.0.0rc1|$image|g" \
    -e 's/^  name: agent$/  name: agent-two/' \
    -e 's/app: agent$/app: agent-two/' \
    -e 's/etl-craft-agent-token/etl-craft-agent-two-token/' \
    "$root/docs/deploying/kubernetes/agent.yml" | apply_agent
kubectl rollout status deployment/agent-two --timeout=180s
submit kubernetes-agent-one "$SECOND_AGENT_ID"
