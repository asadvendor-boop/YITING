# YITING Standalone Compose Profile

Use this profile when a judge or maintainer wants to deploy only YITING from
this repository. It runs Caddy, dashboard, gateway, victim app, and workers in a
single Compose project.

## Configure

```bash
cp deploy/standalone/yiting.env.example deploy/standalone/yiting.env
$EDITOR deploy/standalone/yiting.env
```

Fill in a live DashScope/Qwen key and generated gateway, agent, approval, and
judge credentials. Keep the completed file out of Git.

## Deploy

```bash
docker build -t yiting-python:local .
docker build -f dashboard/Dockerfile \
  --build-arg NEXT_PUBLIC_GATEWAY_URL=https://yiting.your-domain.invalid \
  --build-arg NEXT_PUBLIC_YITING_MODE=judge \
  -t yiting-dashboard:local .
export YITING_ENV_FILE=$PWD/deploy/standalone/yiting.env
export YITING_DOMAIN=yiting.your-domain.invalid
export YITING_PUBLIC_BASE_URL=https://yiting.your-domain.invalid
export ACME_EMAIL=ops@your-domain.invalid
export YITING_PYTHON_IMAGE=yiting-python:local
export YITING_DASHBOARD_IMAGE=yiting-dashboard:local
docker compose -p yiting -f deploy/standalone/compose.yml up -d
```

Caddy is the only service with host ports. Gateway, dashboard, victim app, and
workers stay on Compose networks.

## Verify

```bash
docker compose -p yiting -f deploy/standalone/compose.yml ps
curl -fsS https://$YITING_DOMAIN/health
curl -fsS https://$YITING_DOMAIN/ready
curl -I https://$YITING_DOMAIN/dashboard/
export YITING_OPERATOR_TOKEN="<private-judge-token>"
python scripts/smoke.py \
  --base-url "https://$YITING_DOMAIN" \
  --require-https \
  --require-live-qwen \
  --live-qwen-token "$YITING_OPERATOR_TOKEN"
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
```

For the final shared ECS VM submission, use `deploy/shared-host/compose.prod.yml`
instead so the platform reverse proxy can route YITING, and replace the local
image tags with immutable image digests.
