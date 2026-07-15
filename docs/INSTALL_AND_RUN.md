# Install And Run Guide

This guide is for judges or reviewers starting from the public repository or
the sanitized source package. It separates local verification from the hosted
Alibaba Cloud ECS deployment so the project can be checked without relying on
files left on the author's machine.

## Prerequisites

- Python 3.12 or 3.13
- `uv`
- Node.js 20 LTS or newer
- `npm`

Live model calls also require a Qwen Cloud / DashScope key. Local tests and the
local certification script run in test mode and do not require a paid model key.

## Install From Source

```bash
git clone <public-repository-url>
cd yiting
uv sync --locked
cd dashboard
npm ci
npm run build
cd ..
```

If you are reviewing the source ZIP instead of the repository, extract it first
and run the same commands from the extracted directory.

## Local Verification

Run the local readiness gates:

```bash
make test
make dashboard-build
make local-certify
make submission-package
python scripts/submission_audit.py
python scripts/submission_status.py
```

The expected result before final public links are filled in is:

- tests pass,
- dashboard production build succeeds,
- local certification succeeds,
- source package is generated at `dist/yiting-submission-source.zip`,
- submission status reports local checks as passing,
- final submission still shows pending external artifacts such as the public
  repository URL, hosted domain, public video URL, and hero incident evidence.

## Run The Local Gateway

For development, start only the Gateway API:

```bash
cp .env.example .env
# Fill in Gateway keys. Add DASHSCOPE_API_KEY only for live Qwen calls.
make dev
```

The local Gateway listens on `127.0.0.1:8000`.

Running the full live system locally requires additional processes: the victim
app, all agent workers, dashboard server, local environment secrets, and live
Qwen credentials. The intended full deployment path is Alibaba Cloud ECS.

## Hosted Deployment

Use the ECS guide for the complete hosted setup:

```bash
bash deploy/alibaba-ecs/bootstrap.sh
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
python scripts/verify_deployment.py \
  --public-url "https://yiting.47.84.232.193.sslip.io" \
  --incident-id "<hero-incident-id>" \
  --output-json artifacts/deployment-verification.json
```

For final submission proof, use:

```bash
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```

`make submission-proof` performs the live Qwen smoke check, same-family Track 3
baseline proof, hosted deployment verification, final proof index generation,
and a non-strict submission audit. Commit the generated `artifacts/` proof
files, run `make submission-package`, and then run
`python scripts/submission_audit.py --strict` for the final clean-packet check.

## Public Judge Mode

After recording the live demo, host the dashboard in read-only judge mode.
Read-only mode should expose the landing page, dashboard, evidence export, run
summary, and replay views while rejecting state-changing chaos actions.

See:

- `docs/PUBLIC_JUDGE_MODE.md`
- `docs/FINAL_SUBMISSION_CHECKLIST.md`
- `deploy/alibaba-ecs/README.md`
