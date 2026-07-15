# Alibaba Cloud Proof

YITING uses Alibaba Cloud in two places:

1. **Qwen Cloud / Alibaba Cloud Model Studio** for agent reasoning.
2. **Alibaba Cloud ECS** for the hosted backend and dashboard deployment.

This page is intended as the code-link artifact for the hackathon deployment
proof requirement.

## Qwen Cloud API Usage

Authoritative source files:

- [`shared/config.py`](../shared/config.py)
- [`shared/qwen_reasoning.py`](../shared/qwen_reasoning.py)
- [`scripts/qwen_smoke.py`](../scripts/qwen_smoke.py)

Important implementation details:

- `DASHSCOPE_API_KEY` is the primary model credential source.
- `QWEN_API_KEY` remains accepted only as a backward-compatible alias.
- `QWEN_BASE_URL` selects the Alibaba Cloud Model Studio compatible endpoint;
  `DASHSCOPE_BASE_URL` remains accepted only as a compatibility alias.
- Generic client-library environment variables are not treated as source
  credentials. They can be populated from Qwen values at runtime, but they do
  not override Qwen/DashScope configuration.
- `scripts/qwen_smoke.py` performs a live Qwen call and should be run on the ECS
  host after secrets are configured.

Smoke command:

```bash
export YITING_OPERATOR_TOKEN="<private-judge-token>"
python scripts/smoke.py \
  --base-url "$PUBLIC_BASE_URL" \
  --require-https \
  --require-live-qwen \
  --live-qwen-token "$YITING_OPERATOR_TOKEN"
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
```

The command writes `artifacts/qwen-smoke.json`, a sanitized proof artifact with
the Qwen provider, HTTPS base URL, configured model, and pass/fail result. It
does not write secrets.

## Alibaba Cloud ECS Hosting

Authoritative deployment files:

- [`infra/alibaba-ecs/README.md`](../infra/alibaba-ecs/README.md)
- [`infra/alibaba-ecs/main.tf`](../infra/alibaba-ecs/main.tf)
- [`deploy/shared-host/compose.prod.yml`](../deploy/shared-host/compose.prod.yml)
- [`deploy/ecs/compose.prod.yml`](../deploy/ecs/compose.prod.yml)
- [`deploy/alibaba-ecs/README.md`](../deploy/alibaba-ecs/README.md)
- [`deploy/alibaba-ecs/bootstrap.sh`](../deploy/alibaba-ecs/bootstrap.sh)
- [`deploy/alibaba-ecs/systemd/yiting-gateway.service`](../deploy/alibaba-ecs/systemd/yiting-gateway.service)
- [`deploy/alibaba-ecs/systemd/yiting-agent@.service`](../deploy/alibaba-ecs/systemd/yiting-agent@.service)
- [`deploy/alibaba-ecs/systemd/yiting-dashboard.service`](../deploy/alibaba-ecs/systemd/yiting-dashboard.service)
- [`deploy/Caddyfile`](../deploy/Caddyfile)
- [`scripts/verify_deployment.py`](../scripts/verify_deployment.py)

Manual ECS provisioning is allowed. If the VM is provisioned manually, the
Terraform files under `infra/alibaba-ecs/` are reproducible parity proof for the
declared ECS shape; they must not be described as applied unless they were
actually applied. Fill the IaC parity table in
[`infra/alibaba-ecs/README.md`](../infra/alibaba-ecs/README.md) from the live
ECS console before recording the deployment-proof video.

Acceptance command:

```bash
python scripts/verify_deployment.py \
  --public-url "https://yiting.47.84.232.193.sslip.io" \
  --incident-id "<hero-incident-id>" \
  --require-speedup \
  --require-public-read-only \
  --output-json artifacts/deployment-verification.json
```

The JSON report is sanitized: it records target URLs and pass/fail check
results. Public dashboard access is verified without credentials; state-changing
approval remains protected separately by the `/approve/*` route.

Deployment proof report fields:

| Field | Meaning |
|---|---|
| `proof_type` | Always `alibaba-ecs-deployment-verification`. |
| `schema_version` | Report schema version for repeatable review. |
| `primary_track` | Declares `Track 3: Agent Society`. |
| `rubric_proof[]` | Maps hosted proof checks to the judging criteria. |
| `submission_artifacts` | Points to the judge packet, form copy, final checklist, blog draft, source package, baseline proof, and final proof index files. |
| `final_proof_command` | Shows the one-command hosted proof target. |
| `targets.public_url` | Public Alibaba ECS/Caddy base URL that was checked. |
| `targets.incident_id` | Optional incident chain verified through `/evidence/{id}`. |
| `targets.require_speedup` | Whether the verifier required a measured `speedup_factor > 1`. |
| `targets.require_public_read_only` | Whether the verifier required public chaos/mutation actions to return `403` in judge mode. |
| `passed` | True only when every deployment check passed. |
| `checks[]` | Individual health, dashboard, stats, agent, run summary, and evidence-chain checks. |

## Local Certification Before Cloud Deployment

Before using paid model calls, the local room and evidence ledger can be checked
without any network access:

```bash
python scripts/local_certify.py
```

That command verifies both:

- low-risk policy authorization, and
- high-risk nonce-bound human approval.

Both paths must end in `EXECUTED` with `chain_valid: true`.
