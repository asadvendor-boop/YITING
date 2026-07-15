# Alibaba Deployment Proof

YITING's submitted judging deployment uses Alibaba ECS as the backend host and
Qwen Cloud / DashScope for model calls.

## Code Links

- `infra/alibaba-ecs/` — reproducible ECS VM IaC/parity proof.
- `deploy/shared-host/compose.prod.yml` — YITING shared-host Compose profile.
- `deploy/standalone/compose.yml` — independent YITING-only Compose profile.
- `deploy/ecs/compose.prod.yml` — ECS entry point for the shared-host profile.
- `scripts/qwen_smoke.py` — live Qwen Cloud smoke check.
- `scripts/verify_deployment.py` — hosted ECS verification report.
- `scripts/uptime_monitoring.py` — public-safe external uptime monitor proof
  generator consumed by ECS operations acceptance.
- `shared/config.py` and `shared/qwen_reasoning.py` — Qwen/DashScope runtime
  configuration and calls.

## Console proof (human step before submission)

The hackathon requires deployment proof in two places: repository code links
(above) and an Alibaba Cloud console capture. Record or screenshot:

1. The ECS console instance overview (Workbench) showing the running instance
   that serves the live URL — instance state, region, and public IP visible.
2. Optionally, the Alibaba Cloud Model Studio console showing the Qwen model
   activation used by the live deployment.

Store the reviewed captures as `docs/assets/console/ecs-overview.png` (and
optionally `docs/assets/console/model-studio.png`), then link them from the
submission form. Do not show API keys, access-key secrets, tokens, billing
details, or reusable signed URLs; blur environment values if the console
displays them.

## Provisioning Truth

Manual ECS provisioning is allowed. If the VM is provisioned manually, the
Terraform files in `infra/alibaba-ecs/` are reproducible infrastructure proof
matching the actual deployed ECS VM's documented configuration, not proof that
Terraform was applied. The parity table in `infra/alibaba-ecs/README.md` must
be filled from the actual deployed VM before final proof is recorded.

## Final Proof Commands

```bash
export YITING_OPERATOR_TOKEN="<private-judge-token>"
python scripts/smoke.py \
  --base-url "https://yiting.47.84.232.193.sslip.io" \
  --require-https \
  --require-live-qwen \
  --live-qwen-token "$YITING_OPERATOR_TOKEN"
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
python scripts/verify_deployment.py \
  --public-url "https://yiting.47.84.232.193.sslip.io" \
  --incident-id "<hero-incident-id>" \
  --require-speedup \
  --require-public-read-only \
  --output-json artifacts/deployment-verification.json
python scripts/uptime_monitoring.py \
  --yiting-url "$YITING_LIVE_URL" \
  --yiting-monitor-url "$YITING_UPTIME_MONITOR_URL"
```

The proof video must show the backend running on Alibaba ECS without exposing
secrets, full account identifiers, Qwen keys, database files, or local SSH keys.
