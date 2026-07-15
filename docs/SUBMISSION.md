# YITING Submission Guide

This guide maps YITING to the Global AI Hackathon with Qwen Cloud requirements.
Use it as the final checklist before publishing the hackathon submission.

## Track

**Primary track:** Track 3 — Agent Society

Select Track 3 in the hackathon form. Track 4 is useful context for the
recovery outcome, but it is not the primary submission category.

YITING is a council of specialized agents. Each agent has a narrow authority
boundary, a named persona, a shared incident room, and a deterministic Gateway
that decides whether state can advance.

**Secondary fit:** Track 4 — Autopilot Agent

The same council can take a sandbox incident from detection to remediation once
the required authorization boundary is satisfied.

## Repository Requirement

The hackathon submission requires a public open-source repository.

Final checks:

```bash
git remote -v
python scripts/submission_audit.py --strict
```

The repository must include:

- `LICENSE`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/TRACK3_AGENT_SOCIETY.md`
- `docs/JUDGING_RUBRIC.md`
- `docs/INSTALL_AND_RUN.md`
- `docs/PUBLIC_REPOSITORY.md`
- `docs/BLOG_POST.md`
- `deploy/alibaba-ecs/README.md`
- `scripts/qwen_smoke.py`
- `scripts/verify_deployment.py`

## Alibaba Cloud Deployment Proof

The submission needs proof that the backend runs on Alibaba Cloud.

Recommended proof package:

1. A short screen recording of the ECS instance or terminal.
2. `curl https://yiting.47.84.232.193.sslip.io/health`
3. `curl https://yiting.47.84.232.193.sslip.io/stats`
4. `python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json`
5. `python scripts/verify_deployment.py --public-url "https://yiting.47.84.232.193.sslip.io" --incident-id "<hero-incident-id>" --output-json artifacts/deployment-verification.json`
6. A browser visit to `https://yiting.47.84.232.193.sslip.io/dashboard/`

Recommended code links for the proof:

- `docs/ALIBABA_CLOUD_PROOF.md` — one-page proof index for judges.
- `shared/config.py` — Qwen Cloud endpoint and DashScope credential routing.
- `shared/qwen_reasoning.py` — Qwen reasoning helper.
- `deploy/alibaba-ecs/README.md` — Alibaba ECS deployment guide.
- `scripts/qwen_smoke.py` — live Qwen credential smoke check.
- `scripts/verify_deployment.py` — hosted deployment verifier.
- `docs/THIRD_PARTY_COMPLIANCE.md` — authorization and licensing notes for
  APIs, SDKs, synthetic data, assets, and demo media.

## Architecture Diagram

Use `docs/ARCHITECTURE.md` as the architecture artifact. It shows:

- Alibaba Cloud ECS hosting boundary.
- Caddy public entrypoint.
- Gateway, SQLite evidence ledger, victim app, and local incident rooms.
- Qwen-backed agent society.
- Human approval boundary.

Use `docs/TRACK3_AGENT_SOCIETY.md` as the Track 3 proof artifact. It explains:

- role decomposition,
- agent-to-agent challenge loops,
- human rejection and revision loops,
- exact execution conflict controls,
- paired benchmark metrics for single-agent-vs-society quality gains, plus
  `/stats/runsummary` metrics for handoffs, challenges, human interventions,
  recovery verification, and optional measured-baseline speed.

Use `docs/JUDGING_RUBRIC.md` as the scorecard artifact. It maps YITING to:

- Stage One pass/fail viability,
- Innovation & AI Creativity,
- Technical Depth & Engineering,
- Problem Value & Impact, and
- Presentation & Documentation.

Use `docs/BLOG_POST.md` as the blog/social submission draft.

Use `docs/SUBMISSION_FORM.md` as the copy-paste form packet for title,
tagline, short description, long description, built-with list, public links,
and final proof command.

Use `docs/PUBLIC_REPOSITORY.md` before publishing the public repo. It lists the
GitHub visibility, MIT license detection, About-panel description, topics,
push commands, and checks for accidental secrets or runtime artifacts.

Use `docs/JUDGE_PACKET.md` as the one-page reviewer index. It gives the exact
screens, endpoints, and commands to verify the Track 3 proof quickly.

Use `docs/INSTALL_AND_RUN.md` as the installability artifact for judges. It
shows the exact source-package commands, local verification gates, and which
steps require live Qwen credentials or the hosted Alibaba Cloud ECS deployment.

Use `docs/FINAL_SUBMISSION_CHECKLIST.md` as the day-of-submission runbook. It
orders the final actions: record the live frontend flow first, switch the
hosted dashboard to public read-only judge mode, finalize public links, run
local readiness, run hosted proof, and only then submit.

## Three-Minute Demo Video

Use `docs/DEMO_SCRIPT.md`. The public video must be under three minutes;
judges are not required to watch beyond the three-minute mark.

The demo should show:

- the dashboard,
- one high-risk path requiring human approval,
- one low-risk path using policy authorization,
- the challenge loop if time permits,
- `/evidence/{incident_id}` returning `chain_valid: true`,
- `/evidence/{incident_id}.collaboration` showing role sequence, handoffs,
  challenges, human decisions, and exact execution match,
- the Alibaba Cloud deployment proof separately or as a short appendix clip.

## Text Description

Suggested submission description:

> YITING is an evidence-bound incident council for emergency change control.
> Qwen-backed agents triage alerts, diagnose root cause, challenge weak
> conclusions, plan remediation, and enforce a human gate for high-risk actions.
> Every accepted decision is sealed into a SHA-256 linked evidence chain that
> judges can verify in the browser. The Gateway owns state transitions, nonce
> binding, policy authorization, and recovery verification, so agents can reason
> without being able to silently execute unauthorized changes.

## Rubric Mapping

| Criterion | What to Show |
|---|---|
| Technical Depth & Engineering | Gateway-owned incident rooms, Qwen Cloud model layer, sealed evidence chain, nonce-bound approval, deterministic execution boundary |
| Innovation & AI Creativity | Agent society with named roles, challenge loop, three-way human decisions, bounded false-alarm suppression |
| Problem Value & Impact | Emergency change control for production incidents, human-governed autonomy, audit-ready evidence |
| Presentation & Documentation | Dashboard, architecture diagram, deployment proof, short demo with evidence verification |

Track 3-specific proof points:

- **Task division:** show the card sequence moving across Recorder, Triage,
  Diagnosis, Safety Reviewer, Commander, Human Gate, and Operator, then point
  to `/evidence/{incident_id}.collaboration.role_sequence`.
- **Disagreement resolution:** show `Verdict(CHALLENGE)` or
  `StructuredApproval(REJECTED)` in the evidence chain.
- **Measurable collaboration:** show `artifacts/track3-paired-benchmark.json`
  for the fixed single-agent versus full-society quality benchmark. Show
  `/stats/runsummary` for handoffs, challenges, human interventions, recovery
  verification, and optional measured manual (human) baseline speed only when the
  hosted timing proof supports it.

Before running the final deployment verifier with `--require-speedup`, create a
measured baseline artifact:

```bash
python scripts/track3_baseline.py \
  --gateway-url "https://yiting.47.84.232.193.sslip.io" \
  --baseline-secs <measured-single-agent-seconds> \
  --baseline-label "Measured single-agent rehearsal" \
  --incident-family "<same-family-as-hero-incident>" \
  --output-json artifacts/track3-baseline.json
```

Then set `MANUAL_BASELINE_SECS` to the same measured value on the host, restart
the Gateway, and keep `artifacts/track3-baseline.json` with the final evidence
packet. The artifact records the incident family, formula, terminal criterion,
and positive Track 3 counters so the comparison is judge-auditable.

For the reproducible architecture benchmark:

```bash
python scripts/track3_paired_benchmark.py
```

This writes raw JSON, raw CSV, and a summary artifact from the fixed
`evals/track3_paired_scenarios.json` dataset. It compares the same scenarios,
same rubric, same model identity, and token-normalized metrics for
`single_agent` and `full_yiting_society`. It does not claim speed improvement.

## Final Pre-Submission Commands

After you have the public GitHub URL, Alibaba ECS domain, public demo video,
and separate public Alibaba deployment-proof video, patch the public-facing
placeholders:

`VIDEO_URL` can be any public YouTube, Vimeo, or Facebook Video URL. The example below
uses YouTube only as a placeholder.
`DEPLOYMENT_PROOF_VIDEO_URL` must be a separate public YouTube, Vimeo, or
Facebook Video URL.

```bash
make submission-finalize \
  DOMAIN="https://yiting.47.84.232.193.sslip.io" \
  REPO_URL="https://github.com/asadvendor-boop/YITING" \
  VIDEO_URL="https://youtu.be/<video-id>" \
  DEPLOYMENT_PROOF_VIDEO_URL="https://youtu.be/<deployment-proof-video-id>" \
  HERO_INCIDENT_ID="<hero-incident-id>"
```

Then run:

```bash
python scripts/submission_links.py \
  --repository-url "https://github.com/asadvendor-boop/YITING" \
  --live-application-url "https://yiting.47.84.232.193.sslip.io" \
  --demo-video-url "https://youtu.be/<video-id>" \
  --deployment-proof-video-url "https://youtu.be/<deployment-proof-video-id>" \
  --check-reachable
python scripts/uptime_monitoring.py \
  --yiting-url "$YITING_LIVE_URL" \
  --yiting-monitor-url "$YITING_UPTIME_MONITOR_URL"

git diff -- README.md landing/index.html docs/JUDGE_PACKET.md docs/SUBMISSION_FORM.md docs/INSTALL_AND_RUN.md
git add README.md landing/index.html docs/JUDGE_PACKET.md docs/SUBMISSION_FORM.md docs/INSTALL_AND_RUN.md artifacts/live/backup-restore.json artifacts/live/ecs-ops-acceptance.json artifacts/live/app-restart-resilience.json artifacts/live/uptime-monitoring.json artifacts/live/submission-links.json
git commit -m "docs: finalize public submission links"
make submission-ready
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
git add artifacts/qwen-smoke.json \
  artifacts/track3-baseline.json \
  artifacts/deployment-verification.json \
  artifacts/hero-evidence.json \
  artifacts/final-proof-index.md \
  artifacts/live/backup-restore.json \
  artifacts/live/ecs-ops-acceptance.json \
  artifacts/live/app-restart-resilience.json \
  artifacts/live/uptime-monitoring.json \
  artifacts/live/submission-links.json
git commit -m "docs: add final proof artifacts"
make submission-package
python scripts/submission_audit.py --strict
```

The hosted proof target saves `artifacts/hero-evidence.json` and writes
`artifacts/final-proof-index.md`, the one-page proof attachment that ties the
Qwen smoke, baseline, deployment, public read-only, and hero evidence checks
together. Commit those generated proof artifacts before the strict audit so the
source package can match a clean final proof commit.
