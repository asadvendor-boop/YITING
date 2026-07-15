# Public Judge Mode And Cost Control

This document explains how the public submission stays frictionless for judges
without exposing paid or state-changing actions to random visitors.

## Public Surfaces

These routes are intended to be public in judge mode:

- `/` landing page
- `/dashboard/` read-only dashboard and verified replay
- `/dashboard/runs` replay and Track 3 scorecard view
- `/agent-skills` inspectable MCP-style custom skill registry
- `/mcp` real read-only MCP server (JSON-RPC 2.0) over the same skill contracts — no tool can mutate state or start paid model calls
- `/evidence/{incident_id}` public evidence export
- `/stats` and `/stats/runsummary` read-only metrics
- `/health` deployment health check

Public visitors can inspect the project, replay verified incidents, export the
hash chain, and evaluate the Track 3 proof without credentials.

## Blocked Or Protected Surfaces

These actions must not be available to unauthenticated public visitors:

- live chaos triggers
- reset/mutation actions
- approval decisions
- any route that can start paid model calls
- any route that can seal a new card or mutate incident state

The dashboard API route `/dashboard/api/chaos/activate` checks
`YITING_LIVE_CHAOS`. When that environment variable is not exactly `1`, the
route returns HTTP `403` before contacting the Gateway. That is the public
judge-mode setting.

The approval UI remains protected separately through the deployment edge and
Gateway proxy-secret checks. Public judge mode should show verified approvals
from replay/evidence, not allow visitors to approve new actions.

## Recording Mode Versus Judge Mode

Use recording mode only while capturing the live demo:

```bash
YITING_LIVE_CHAOS=1
NEXT_PUBLIC_YITING_MODE=live
```

After recording, switch to public judge mode:

```bash
cd /opt/apps/yiting/current
sudo sed -i.bak '/^YITING_LIVE_CHAOS=/d' /opt/apps/yiting/secrets/yiting.env
export YITING_ENV_FILE=/opt/apps/yiting/secrets/yiting.env
export YITING_PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io"
export NEXT_PUBLIC_YITING_MODE=judge
# If rebuilding from a private registry, set exact immutable digest refs before compose.
export YITING_PYTHON_IMAGE="registry.invalid/yiting/python@sha256:<digest>"
export YITING_DASHBOARD_IMAGE="registry.invalid/yiting/dashboard@sha256:<digest>"
docker compose -p yiting -f deploy/shared-host/compose.prod.yml up -d dashboard
```

Judge mode keeps the replay, evidence, and metrics public while blocking the
paid/mutating path.

## Required Verification

The final proof command includes:

```bash
scripts/verify_deployment.py --require-public-read-only
```

That verifier must prove:

- the public dashboard loads without credentials,
- public evidence and metrics endpoints are reachable,
- `/dashboard/api/chaos/activate` returns the app-level disabled `403`,
- the hero evidence chain is still valid,
- the same final proof also passes Qwen smoke, paired quality benchmark,
  optional baseline speed, and exact-envelope execution checks.

## What To Say If Asked

> The live video shows the full system with controlled triggers. The submitted
> public site is read-only so judges can inspect evidence without letting the
> internet start paid model runs. The final proof verifies this with a real
> HTTP `403` check on the chaos endpoint.
