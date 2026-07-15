# Deployment Proof

YITING's judged deployment is the Alibaba ECS hosted app at:

```text
https://yiting.47.84.232.193.sslip.io/
```

This file is the stable rubric anchor for deployment proof. The detailed proof
documents are [`ALIBABA_CLOUD_PROOF.md`](ALIBABA_CLOUD_PROOF.md) and
[`ALIBABA_DEPLOYMENT_PROOF.md`](ALIBABA_DEPLOYMENT_PROOF.md).

## Code Evidence

- [`shared/config.py`](../shared/config.py) and
  [`shared/qwen_reasoning.py`](../shared/qwen_reasoning.py) show Qwen Cloud
  configuration and advisory model calls.
- [`deploy/shared-host/compose.prod.yml`](../deploy/shared-host/compose.prod.yml)
  is the judged ECS Compose profile.
- [`scripts/qwen_smoke.py`](../scripts/qwen_smoke.py) verifies live Qwen
  capability without writing secrets.
- [`scripts/verify_deployment.py`](../scripts/verify_deployment.py) generates
  the hosted deployment verification artifact after the final hero incident is
  selected.

## Proof Artifacts

- Qwen smoke proof: [`artifacts/qwen-smoke.json`](../artifacts/qwen-smoke.json)
- ECS deployment verification:
  [`artifacts/deployment-verification.json`](../artifacts/deployment-verification.json)
- Track 3 paired benchmark:
  [`artifacts/track3-paired-benchmark.json`](../artifacts/track3-paired-benchmark.json)

## External Publication Items

The final public repository URL, demo video, deployment-proof video, and hero
incident links are inserted only after Asad completes the human approval-password
hero run and publishes the videos. Until then, the strict audit must remain red
for those external items.
