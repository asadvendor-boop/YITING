# YITING Shared-Host Compose Profile

This profile runs YITING as an independently deployable app behind the shared
platform reverse proxy on Alibaba ECS. It is intentionally scoped to the YITING
Compose project, networks, state volumes, and credentials.

## Networks

Ensure these external networks exist before starting YITING. On the shared
judging VM, the platform network bootstrap creates them. For a manual
YITING-only shared-host rehearsal, create them directly:

```bash
docker network create yiting-edge
docker network create yiting-egress
docker network create --internal yiting-internal
```

Only Caddy and YITING public services join `yiting-edge`. Live-agent workers
join `yiting-egress` only for outbound Qwen Cloud calls. Gateway, dashboard,
victim app, and workers use `yiting-internal` for private traffic. No YITING
service joins any neighboring app network.

The approved judging profile keeps YITING on private SQLite volumes. No YITING service joins `yiting-db` and no YITING container receives PostgreSQL
credentials such as `DATABASE_URL`, `POSTGRES_PASSWORD`, or
`YITING_POSTGRES_PASSWORD_FILE`. If a later deployment migrates YITING to
PostgreSQL, that deployment must add separate `yiting_app` credentials and
fresh database-isolation evidence before it can replace this profile.

## Secrets And State

Create a root-owned env file and point Compose at it:

```bash
sudo install -d -o root -g root -m 0750 /opt/apps/yiting/secrets
sudo cp deploy/alibaba-ecs/yiting.env.example /opt/apps/yiting/secrets/yiting.env
sudo chmod 0640 /opt/apps/yiting/secrets/yiting.env
```

Fill the file with the real DashScope/Qwen key and generated gateway, agent,
approval, and judge values. Do not commit the completed file.

YITING keeps SQLite state in the `yiting-data` volume, victim idempotency state
in `yiting-victim-data`, and the shared daily Qwen circuit-breaker meter in
`yiting-qwen-usage` at `/qwen-usage/yiting-qwen-usage.json`. Back up and
restore these volumes separately from any neighboring app before recording the
demo.

Set `YITING_DAILY_TOKEN_LIMIT` to the cap you are willing to spend per UTC day.
If a new live Qwen call would exceed that cap, the agent fails before making the
provider request instead of silently falling back to another model or mock mode.
Set `YITING_RATE_LIMIT_PER_MINUTE` and `YITING_RATE_LIMIT_WINDOW_SECONDS` to
positive values for judge traffic. The gateway rate limiter keys by
authenticated agent/operator identity where available and otherwise by source
IP.

## Backup And Restore Test

Run a restore test after the final demo data is prepared and before recording
the public videos. The helper uses SQLite's online backup API, restores the
copy, and runs `PRAGMA integrity_check` without printing secrets.

```bash
docker compose -p yiting -f deploy/shared-host/compose.prod.yml exec gateway \
  python scripts/backup_restore_check.py \
    --sqlite-db /data/yiting.db \
    --victim-db /data/heal_idempotency.db \
    --backup-dir /tmp/yiting-backup \
    --live-submission-evidence \
    --output-json /tmp/yiting-backup/backup-restore.json

sudo install -d -o root -g root -m 0750 /opt/apps/backups/yiting
docker cp yiting-gateway-1:/tmp/yiting-backup/. /opt/apps/backups/yiting/
mkdir -p artifacts/live
sudo install -m 0640 /opt/apps/backups/yiting/backup-restore.json artifacts/live/backup-restore.json
sudo chown "$(id -u):$(id -g)" artifacts/live/backup-restore.json
sudo find /opt/apps/backups/yiting -type f -exec chmod 0640 {} \;
```

Keep this backup separate from other app backups. Same-VM backups protect
against logical/container failures; copy them off-host if you need survival of
complete ECS host loss.

## Deploy

Build and push the final images before judging, then deploy only immutable
digest references:

```bash
make docker-build-images
make docker-smoke-images
docker build -t "$YITING_PYTHON_REPOSITORY:$(git rev-parse --short HEAD)" .
docker build -f dashboard/Dockerfile \
  --build-arg NEXT_PUBLIC_GATEWAY_URL="https://yiting.your-domain.invalid" \
  --build-arg NEXT_PUBLIC_YITING_MODE=judge \
  -t "$YITING_DASHBOARD_REPOSITORY:$(git rev-parse --short HEAD)" .
docker push "$YITING_PYTHON_REPOSITORY:$(git rev-parse --short HEAD)"
docker push "$YITING_DASHBOARD_REPOSITORY:$(git rev-parse --short HEAD)"
docker buildx imagetools inspect "$YITING_PYTHON_REPOSITORY:$(git rev-parse --short HEAD)"
docker buildx imagetools inspect "$YITING_DASHBOARD_REPOSITORY:$(git rev-parse --short HEAD)"

export YITING_ENV_FILE=/opt/apps/yiting/secrets/yiting.env
export YITING_PUBLIC_BASE_URL=https://yiting.your-domain.invalid
export NEXT_PUBLIC_YITING_MODE=judge
export YITING_PYTHON_IMAGE=registry.invalid/yiting/python@sha256:...
export YITING_DASHBOARD_IMAGE=registry.invalid/yiting/dashboard@sha256:...
docker compose -p yiting -f deploy/shared-host/compose.prod.yml up -d
```

The app Compose profile publishes no host ports. Caddy in the platform project
must reverse proxy the final YITING hostname to `yiting-dashboard:3000` and API
paths to `yiting-gateway:8000` through the `yiting-edge` network.

## Acceptance Checks

Run these checks after the shared ECS deployment is up and the final image
digest environment variables are exported:

```bash
docker compose -p yiting -f deploy/shared-host/compose.prod.yml ps
docker network inspect yiting-edge
docker network inspect yiting-egress
docker network inspect yiting-internal
docker compose -p yiting -f deploy/shared-host/compose.prod.yml exec gateway python -c "import urllib.request; print(urllib.request.urlopen('http://victim:9000/healthz').status)"
docker compose -p yiting -f deploy/shared-host/compose.prod.yml exec commander sh -c 'test -w /qwen-usage && test -f /qwen-usage/yiting-qwen-usage.json || true'
```

Negative checks for the shared VM:

```bash
docker compose -p yiting -f deploy/shared-host/compose.prod.yml exec gateway sh -c 'test ! -e /var/run/docker.sock'
docker compose -p yiting -f deploy/shared-host/compose.prod.yml exec gateway sh -c 'python - <<PY
import socket
for host in ("neighbor-victim", "neighbor-worker", "neighbor-postgres"):
    try:
        socket.getaddrinfo(host, 80)
    except OSError:
        continue
    raise SystemExit(f"unexpectedly resolved {host}")
PY'
```

The automated ECS ops acceptance artifact must also prove the same boundary:
no YITING container may mount a neighboring app control socket, receive a
neighboring app control group, mount `/var/run/docker.sock`, join neighboring
app networks, or resolve neighboring private services. It also verifies that no
YITING container joins an external database network, no YITING container receives PostgreSQL credentials, only the gateway and dashboard join
`yiting-edge`, only live-agent workers join `yiting-egress`,
all YITING containers join `yiting-internal`, Caddy is the only approved
non-YITING member of `yiting-edge`, and that `yiting-internal` has only YITING members.

Run the live proof only after the final domain is routed:

```bash
export YITING_OPERATOR_TOKEN="<private-judge-token>"
python scripts/smoke.py \
  --base-url "$YITING_PUBLIC_BASE_URL" \
  --require-https \
  --require-live-qwen \
  --live-qwen-token "$YITING_OPERATOR_TOKEN"
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
python scripts/verify_deployment.py --public-url "$YITING_PUBLIC_BASE_URL" --incident-id "$HERO_INCIDENT_ID" --require-speedup --require-public-read-only
sudo -E python scripts/ecs_ops_acceptance.py \
  --billing-valid-until "$ECS_BILLING_VALID_UNTIL" \
  --judging-end-date "$QWEN_JUDGING_END_DATE" \
  --uptime-monitor-file artifacts/live/uptime-monitoring.json \
  --output-json artifacts/live/ecs-ops-acceptance.json
```
