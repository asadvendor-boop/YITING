# Alibaba Cloud ECS Standalone Guide

This folder contains a YITING-only Alibaba Cloud ECS deployment layout and proof
material. It keeps the public entrypoint in Caddy and binds all Python and
Next.js services to `127.0.0.1`.

For the final shared ECS VM judging deployment, use
`deploy/shared-host/compose.prod.yml` or the ECS entry point
`deploy/ecs/compose.prod.yml` from this repository, alongside the platform
Compose project. The shared-host path uses `/opt/apps/yiting/`,
Docker networks, bounded Docker logs, private state volumes, and the external
Caddy/PostgreSQL platform project. This standalone systemd path is retained as
an independent YITING-only deployment option and as Alibaba Cloud proof code;
do not describe it as the final two-application shared-host deployment unless
that is the path actually deployed.

## 1. Provision ECS

- Ubuntu 24.04 LTS or Ubuntu 22.04 LTS
- Security group inbound: `80/tcp`, `443/tcp`, and SSH from your IP
- Recommended YITING-only size: 2 vCPU / 4 GB RAM or larger
- Recommended shared YITING judging VM: 4 vCPU / 8 GB RAM or larger
- Attach your domain or use an Alibaba Cloud DNS record pointed at the ECS IP

## 2. Install Runtime Packages

Fast path from a checked-out repo:

```bash
bash deploy/alibaba-ecs/bootstrap.sh --install-packages
```

Manual package setup:

```bash
sudo apt-get update
sudo apt-get install -y curl git build-essential caddy
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Log out and back in if `uv` is not on `PATH`.

## 3. Place the Application

```bash
sudo mkdir -p /opt/yiting
sudo chown "$USER":"$USER" /opt/yiting
git clone <your-public-repo-url> /opt/yiting
cd /opt/yiting
```

Recommended: generate `.env` and a matching Caddy drop-in with strong random
secrets and the approval-page basic-auth hash:

```bash
make deployment-env \
  PUBLIC_BASE_URL="https://$YITING_DOMAIN" \
  JUDGE_USER="$JUDGE_USER" \
  JUDGE_PASSWORD="$JUDGE_PASSWORD" \
  APPROVER_ID="$APPROVER_ID" \
  DASHSCOPE_API_KEY="$DASHSCOPE_API_KEY"

sudo mkdir -p /etc/systemd/system/caddy.service.d
sudo cp deploy/alibaba-ecs/caddy.generated.env /etc/systemd/system/caddy.service.d/yiting.conf
```

Alternatively, fill `.env` manually with your DashScope/Qwen key, Gateway
secrets, all agent IDs, role-bound submission keys, and approval UI settings.
Do not add explicit `OPENAI_*` source credentials; YITING derives client-library
compatibility variables from Qwen/DashScope settings at runtime.

```bash
cp deploy/alibaba-ecs/yiting.env.example .env
chmod 600 .env
```

## 4. Install Dependencies and Build Dashboard

```bash
cd /opt/yiting
bash deploy/alibaba-ecs/bootstrap.sh
```

Or manually:

```bash
cd /opt/yiting
uv sync --locked
cd dashboard
npm ci
NEXT_PUBLIC_YITING_MODE=live npm run build
```

## 5. Install systemd Units

```bash
sudo cp deploy/alibaba-ecs/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yiting-victim yiting-gateway yiting-dashboard
sudo systemctl enable --now yiting-agent@triage
sudo systemctl enable --now yiting-agent@diagnosis
sudo systemctl enable --now yiting-agent@safety_reviewer
sudo systemctl enable --now yiting-agent@commander
sudo systemctl enable --now yiting-agent@operator
sudo systemctl enable --now yiting-recorder-heartbeat
```

## 6. Install Caddy Config

```bash
sudo mkdir -p /etc/systemd/system/caddy.service.d
sudo cp deploy/alibaba-ecs/caddy.generated.env /etc/systemd/system/caddy.service.d/yiting.conf
sudoedit /etc/systemd/system/caddy.service.d/yiting.conf
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl reload caddy
```

If you generated deployment env files, the Caddy drop-in already contains
`YITING_JUDGE_USER`, `YITING_JUDGE_HASH`, and `APPROVAL_PROXY_SECRET` for the
state-changing `/approve/*` route. The dashboard itself is public in judge mode;
paid chaos actions are blocked by omitting `YITING_LIVE_CHAOS`. For a manual
deployment, create the same approval values yourself with:

```bash
caddy hash-password --plaintext 'replace-me'
```

## 7. Acceptance Checks

```bash
python scripts/qwen_smoke.py
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:9000/healthz
curl -I https://$YITING_DOMAIN/
curl -I https://$YITING_DOMAIN/dashboard/
curl -fsS https://$YITING_DOMAIN/stats
export YITING_OPERATOR_TOKEN="<private-judge-token>"
python scripts/smoke.py \
  --base-url "https://$YITING_DOMAIN" \
  --require-https \
  --require-live-qwen \
  --live-qwen-token "$YITING_OPERATOR_TOKEN"
python scripts/track3_baseline.py \
  --gateway-url "https://$YITING_DOMAIN" \
  --baseline-secs "$MEASURED_SINGLE_AGENT_SECS" \
  --baseline-label "Measured single-agent rehearsal" \
  --incident-family "$BASELINE_INCIDENT_FAMILY" \
  --output-json artifacts/track3-baseline.json
python scripts/verify_deployment.py \
  --public-url "https://$YITING_DOMAIN" \
  --incident-id "$HERO_INCIDENT_ID" \
  --require-speedup \
  --require-public-read-only \
  --output-json artifacts/deployment-verification.json
```

Keep `artifacts/deployment-verification.json` with the final submission
materials. It is safe to share because it records check results and target URLs,
not approval credentials. See `docs/ALIBABA_CLOUD_PROOF.md` for the field map.

Before recording, fire one low-risk scenario and one high-risk scenario from the
dashboard and confirm:

- the incident room receives all sealed cards,
- high-risk path creates a human approval page,
- low-risk path uses policy authorization,
- `/evidence/{incident_id}` returns `chain_valid: true`.
- `/stats/runsummary` exposes Track 3 handoff, challenge, human-intervention,
  recovery-verification, and measured speedup metrics. Set
  `MANUAL_BASELINE_SECS` from a measured single-agent/manual run before using
  `--require-speedup`. Set `BASELINE_INCIDENT_FAMILY` to the same family as the
  hero incident, and keep `artifacts/track3-baseline.json` as the shareable
  measurement artifact.

## 8. Public Judge Mode

After recording the live demo, compile the dashboard with paid/mutating actions
disabled. This has two parts: set the public UI to judge mode and remove the
server-side live-chaos flag so direct POSTs to the dashboard API return `403`.

```bash
cd /opt/yiting/dashboard
sudo sed -i.bak '/^YITING_LIVE_CHAOS=/d' /etc/yiting/yiting.env
NEXT_PUBLIC_YITING_MODE=judge npm run build
sudo systemctl restart yiting-dashboard
python scripts/verify_deployment.py \
  --public-url "https://$YITING_DOMAIN" \
  --incident-id "$HERO_INCIDENT_ID" \
  --require-speedup \
  --require-public-read-only
```

The read-only dashboard still shows evidence, incidents, agent status, and
verified replay without letting public visitors trigger paid model calls.
