# Hackathon Submission Form Fields

Use this as copy-paste source for the public hackathon form after the final
domain, repository URL, and video URL are available.

## Live measured results upfront

| Fact | Value | Proof |
|---|---:|---|
| Executed incidents with verified recovery | 3 / 3 | [`../artifacts/deployment-verification.json`](../artifacts/deployment-verification.json) |
| Sealed agent handoffs across those runs | 22 | [`../artifacts/deployment-verification.json`](../artifacts/deployment-verification.json) |
| Disagreement on the record | 1 safety challenge + 1 human rejection → revised plans | [`../artifacts/deployment-verification.json`](../artifacts/deployment-verification.json) |
| Speed vs measured human baseline | 2.6× (501 s solo runbook run vs 196 s same-family council average) | [`../artifacts/track3-baseline.json`](../artifacts/track3-baseline.json) |
| Verification gate | 709 tests passed | [`../tests/`](../tests/) |
| Hosted app | 200-ready ECS endpoint | `https://yiting.47.84.232.193.sslip.io/` |

Deterministic society-contract regression harness (reproducible contract validation, not a live model measurement): task success 100% vs 33.33%, unsupported claims 0 vs 20, risks detected 120 vs 40 across 20 paired scenarios — [`artifacts/track3-paired-benchmark.json`](../artifacts/track3-paired-benchmark.json).

## Project Name

YITING

Mandarin *yi ting* — "the deliberation hall": the chamber where a council hears evidence, debates openly, and puts its judgment on the record.

## Tagline

Evidence-bound Qwen agent society for governed incident response.

## Primary Track

Track 3: Agent Society

> Official brief: "Design a multi-agent collaboration system where multiple Agents with distinct capabilities work together through task division, dialogue, and negotiation… showcase how Agents decompose tasks and assign roles, how they resolve disagreements and execution conflicts, and a measurable efficiency gain over single-agent baselines." YITING answers each clause with sealed, judge-verifiable evidence.

Select Track 3 in the form. Do not choose Track 4 as the primary category; the
Track 4/autopilot behavior is the outcome produced by the Track 3 society.

## Track Choice Note

YITING has a secondary Track 4 fit because it completes an incident workflow,
but Track 3 is the stronger primary track. The main innovation is the agent
society itself: specialized roles decompose work, challenge weak reasoning,
negotiate revisions with a human, and resolve execution conflicts through an
exact approved-action boundary.

## One-Liner

YITING coordinates specialized Qwen agents that triage, diagnose, challenge,
plan, request human authority, and execute only verified remediation while every
decision is sealed into a browser-verifiable evidence chain.

## Inspiration

Production incident response is a coordination problem, not a single prompt:
teams need fast diagnosis, dissent, human judgment, and exact execution history
when a risky remediation is under pressure. YITING turns that collaboration
into an agent society whose disagreements, revisions, approvals, and execution
boundaries are visible to judges and auditors.

## Short Description

Production incident response is a coordination problem, not a single prompt.
YITING treats emergency change control as an agent society: Lin Xun triages,
Chen Ming investigates, Zhou Shen challenges weak evidence, Han Ce plans, Lu
Xing executes only authorized actions, and Wen Lu records the chain.

The system proves Track 3 behavior with role decomposition, sealed disagreement
loops, human rejection and revision, exact-envelope execution, and paired
quality gains against a single-agent baseline. Any speed claim is separate and
requires a measured same-family hosted baseline.

## What it does

YITING converts an incident signal into an auditable sequence of role-specific
agent work: triage, diagnosis, safety challenge, plan drafting, human decision,
exact-envelope execution, and recovery verification.

## Long Description

YITING is an evidence-bound incident council for emergency change control. A
synthetic or webhook-shaped signal enters the Gateway and becomes an AlertCard.
From there, distinct Qwen-backed agents collaborate through a shared incident
room:

1. Triage classifies and routes the alert.
2. Diagnosis gathers evidence and proposes a root cause.
3. Safety Reviewer independently reviews the evidence and can issue a sealed
   `Verdict(CHALLENGE)`.
4. Commander creates a nonce-bound remediation plan.
5. A human can approve, reject with instructions, or declare false alarm.
6. Operator executes only the exact approved envelope and verifies recovery.
7. Recorder seals every accepted decision into a SHA-256 linked evidence chain.

The important design choice is separation of reasoning from authority. Agents
can investigate, debate, revise, and propose. The Gateway owns state
transitions, nonce binding, policy authorization, evidence sealing, and recovery
verification. That gives the system fast incident response without invisible
automation.

## What makes the architecture different

The agent society is measured and enforced, not just named. Each role has a
public skill contract, every accepted decision becomes a hash-linked card, and
the Gateway refuses stale nonces, modified action envelopes, and unauthorized
execution. Qwen performs judgment; deterministic code owns authority.

## How we built it

YITING uses FastAPI, Next.js, SQLite, Qwen Cloud / Alibaba Cloud Model Studio,
and a shared-host Alibaba ECS deployment. The evidence system is built from
canonical JSON cards, SHA-256 links, nonce-bound approvals, and a deterministic
Gateway state machine.

## Challenges

The hard part was proving agent collaboration without overclaiming speed. The
paired benchmark shows quality, risk, unsupported-claim, and quality-per-token
gains, while hosted timing remains a separate same-family measurement.

## Measured results

Live, from sealed hosted runs: 3 executed incidents with verified recovery, 22
sealed agent handoffs, 1 safety challenge and 1 human rejection that each forced
a revised plan, and a 2.6× speedup against a measured human baseline (501 s
runbook-guided solo run vs 196 s same-family council average,
`artifacts/track3-baseline.json`).

Separately, the committed deterministic society-contract regression harness —
reproducible contract validation, not a live model measurement — reports 20
scenarios, 60 runs per variant, 100% task success for the society contract,
33.33% for the solo baseline, zero unsupported claims for the society, and 120
risks detected versus 40.

## What's next

Add Datadog, GitHub, Slack, and PagerDuty adapters behind the existing Gateway
contracts; publish a scored-run gallery; and expand organization policy packs
without weakening exact-envelope execution.

## What Makes It Track 3

- **Distinct capabilities:** `/agent-skills` exposes the inspectable MCP-style
  custom tool contract for each role. It is a review manifest, not a network MCP
  server.
- **Task decomposition:** `/evidence/{incident_id}.collaboration.role_sequence`
  shows work moving across Recorder, Triage, Diagnosis, Safety Reviewer,
  Commander, Human Gate, and Operator.
- **Dialogue and negotiation:** `Verdict(CHALLENGE)` forces Diagnosis to revise;
  `StructuredApproval(REJECTED)` forces Commander to create a revised plan.
- **Execution conflict resolution:**
  `collaboration.execution_conflict_control.exact_match` proves Operator
  executed only the approved envelope.
- **Measured efficiency:** `artifacts/track3-live-paired/` is a live paired
  benchmark on the deployed stack — 20 real incidents, each run through both a
  single Qwen agent (same model tier, complete task, identical evidence) and
  the deployed six-agent society. The society scores 0.844 vs 0.763
  (10 wins / 4 ties / 6 losses), reaches 100% finding and risk recall (solo:
  87.5%/92.5%), and seals a live-verified evidence chain on all 20 plans; the
  ~2.5× society token cost is published in the same artifact (not an
  equal-budget comparison; corrections logged). The surfaced routing defect
  was fixed, deployed, and validated live the same day
  (`artifacts/track3-live-paired-postfix/`: 0.968 vs 0.843, 5 wins / 2 ties /
  0 losses across five validated families). Separately,
  `artifacts/track3-paired-benchmark.json` is the deterministic
  society-contract regression harness (reproducible contract validation, not
  a live model measurement); it pins higher task success, lower
  unsupported-claim rate, more risks detected, better final score, and better
  quality per token for the society contract than a solo baseline.
  `/stats/runsummary` and `artifacts/track3-baseline.json` provide the live
  measured human-baseline speedup and support a
  speed claim only when a measured same-family hosted baseline proves
  `speedup_factor > 1`.

## What Is Novel

YITING is not a single incident-response chatbot and not a dashboard mockup. It
is a governed agent society where Qwen-backed roles reason inside deterministic
authority boundaries:

- `/agent-skills` makes the custom skill contracts inspectable as an MCP-style
  review manifest: tool name, input schema, output schema, Qwen prompt boundary,
  guardrail, evidence artifact, Qwen Cloud use, Track 3 proof category, and
  judge demo cue for each role. The manifest route is not a network MCP server;
  it is the public custom-skill contract layer judges can inspect. The same
  seven contracts are also served by a **real read-only MCP server** at `/mcp`
  (`gateway/mcp.py` — JSON-RPC 2.0 `initialize`, `tools/list`, `tools/call`).
- Disagreement is operational, not cosmetic. `Verdict(CHALLENGE)` and
  `StructuredApproval(REJECTED)` are sealed cards that force revised work.
- Execution conflict resolution is deterministic. Operator can execute only the
  exact approved envelope; stale, modified, or unauthorized actions fail closed.
- The efficiency claim is split honestly. `scripts/track3_paired_benchmark.py`
  records paired quality, reliability, and quality-per-token gains and
  explicitly does not claim speed improvement. `scripts/track3_baseline.py`
  separately records the same-family hosted timing baseline, and
  `scripts/verify_deployment.py --require-speedup` fails if that hosted timing
  proof does not show `speedup_factor > 1`. When `/stats/runsummary` exposes
  same-family tagged runs, the helper matches `BASELINE_INCIDENT_FAMILY`
  against each run's `incident_family` before accepting the comparison.

In one sentence: YITING uses Qwen for judgment, a Gateway for authority, and a
hash chain for proof.

## Built With

- Qwen Cloud / Alibaba Cloud Model Studio
- Alibaba Cloud ECS
- Python, FastAPI, SQLite
- Next.js dashboard
- Caddy HTTPS entrypoint
- SHA-256 evidence chain
- Deterministic Gateway state machine

## Project status

YITING is a new project: all application code, agents, the MCP server, evaluation harness, documentation, and assets in this repository were designed and built during the Global AI Hackathon Series with Qwen Cloud submission window. It is not a fork of, or derived from, any pre-existing product or repository.

## Demo Script Summary

1. Open the landing page and dashboard.
2. Show `/agent-skills` or the Agents page for role contracts.
3. Trigger or replay the hero incident.
4. Show a challenge or human rejection loop.
5. Show approval and exact execution.
6. Open `/evidence/{incident_id}` and verify `chain_valid: true`.
7. Open the paired benchmark artifact for quality gain, then open
   `/stats/runsummary` only for the separate hosted timing proof if
   `speedup_factor > 1` is present.

## Public Links To Fill In

- Landing page: `https://yiting.47.84.232.193.sslip.io/`
- Dashboard: `https://yiting.47.84.232.193.sslip.io/dashboard/`
- Evidence export: `https://yiting.47.84.232.193.sslip.io/evidence/<hero-incident-id>`
- Public repository: `https://github.com/asadvendor-boop/YITING`
- Demo video: `https://youtu.be/<video-id>`
- Alibaba deployment-proof video: `https://youtu.be/<deployment-proof-video-id>`

Use a public YouTube, Vimeo, or Facebook Video URL for the demo video. The YouTube-shaped
placeholder above is not a platform restriction.
Use a separate public YouTube, Vimeo, or Facebook Video URL for the Alibaba
deployment-proof video.

## Alibaba Cloud Deployment Proof Code Links

If the form has a single proof field, use the first link. It points to the code
that routes agent reasoning through Qwen Cloud / Alibaba Cloud Model Studio.

- Primary code proof: `https://github.com/asadvendor-boop/YITING/blob/main/shared/config.py`
- Qwen smoke proof: `https://github.com/asadvendor-boop/YITING/blob/main/scripts/qwen_smoke.py`
- Hosted ECS verifier: `https://github.com/asadvendor-boop/YITING/blob/main/scripts/verify_deployment.py`
- ECS deployment guide: `https://github.com/asadvendor-boop/YITING/blob/main/deploy/alibaba-ecs/README.md`

## Final Proof Command

```bash
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```

The proof must pass with a valid hero evidence chain, nonzero disagreement
events (challenge or rejection/revision), nonzero human intervention count,
exact execution match, and paired benchmark quality gains. A speed claim is
accepted only when the same-family baseline artifact proves
`speedup_factor > 1` for the hosted timing run.

Keep the generated proof artifacts with the final packet:

- `artifacts/track3-baseline.json`
- `artifacts/track3-paired-benchmark.json`
- `artifacts/qwen-smoke.json`
- `artifacts/deployment-verification.json`
- `artifacts/hero-evidence.json`
- `artifacts/final-proof-index.md`
- `artifacts/live/backup-restore.json`
- `artifacts/live/ecs-ops-acceptance.json`
- `artifacts/live/app-restart-resilience.json`
- `artifacts/live/uptime-monitoring.json`
- `artifacts/live/submission-links.json`
- `dist/yiting-submission-source.zip`

## Blog Post Prize

Use `docs/BLOG_POST.md` as the long-form blog/social post. It explains the
agent-society design, governance loops, evidence chain, Qwen Cloud fit, and
paired quality gains plus separate measured baseline proof.
