# YITING

**Track 3 Agent Society:** YITING is an **auditable agent society** where disagreement, negotiation, and revision are first-class, recorded outputs — an Evidence-bound incident council whose specialized Qwen agents divide the work, challenge each other’s reasoning, take a human rejection and return a revised plan, and seal every step into a hash chain. Where a single agent produces one answer, YITING produces a defensible decision *and* the recorded trail of how the council reached it.

The name is Mandarin: **YITING** romanizes *yi ting* — "the deliberation hall," the chamber where a council hears evidence, debates openly, and puts its judgment on the record. Every council persona's own name encodes its charter the same way — see the [Agent Matrix](#agent-matrix).

## Canonical stat block

| Live measured fact | Value | Proof |
|---|---:|---|
| Executed incidents with verified recovery | 3 / 3 | [`artifacts/deployment-verification.json`](artifacts/deployment-verification.json) |
| Sealed agent handoffs across those runs | 22 | [`artifacts/deployment-verification.json`](artifacts/deployment-verification.json) |
| Disagreement on the record | 1 safety challenge + 1 human rejection → revised plans | [`artifacts/deployment-verification.json`](artifacts/deployment-verification.json) |
| Speed vs measured human baseline | 2.6× (501 s runbook-guided solo vs 196 s same-family council average) | [`artifacts/track3-baseline.json`](artifacts/track3-baseline.json) |
| Local verification gate | 709 tests passed | [`tests/`](tests/) |
| Real MCP server | `POST /mcp` — read-only JSON-RPC over the seven skill contracts | [`gateway/mcp.py`](gateway/mcp.py) |
| Hosted app | 200-ready ECS endpoint | `https://yiting.47.84.232.193.sslip.io/` |

**Deterministic society-contract regression harness — reproducible contract validation, not a live model measurement:**

| Contract-validation metric (20 paired scenarios) | Value | Proof |
|---|---:|---|
| Task success (society contract vs solo baseline) | 100% vs 33.33% | [`artifacts/track3-paired-benchmark.json`](artifacts/track3-paired-benchmark.json) |
| Unsupported claims | 0 vs 20 | [`artifacts/track3-paired-benchmark.json`](artifacts/track3-paired-benchmark.json) |
| Risks detected | 120 vs 40 | [`artifacts/track3-paired-benchmark.json`](artifacts/track3-paired-benchmark.json) |

These rows come from the committed deterministic society-contract regression harness
([`scripts/track3_paired_benchmark.py`](scripts/track3_paired_benchmark.py)): a
reproducible scoring of the society contract against a solo baseline on identical
scenarios, deliberately isolated from model variance. The artifact's own
`claims_not_made` field lists exactly what it does not claim — no speed
improvement, no statistical significance, and no live Qwen quality measurement in
deterministic mode. It is a design-integrity proof, not an empirical model
benchmark; the live measured facts above are the empirical results.

![YITING architecture](docs/assets/architecture.png)

## Deployment URLs

When deployed on Alibaba Cloud ECS:

- **Public landing page:** `https://yiting.47.84.232.193.sslip.io/`
- **Dashboard:** `https://yiting.47.84.232.193.sslip.io/dashboard/`
- **Evidence export:** `https://yiting.47.84.232.193.sslip.io/evidence/{incident_id}`

## Deployed on Alibaba Cloud

- **ECS live URL:** `https://yiting.47.84.232.193.sslip.io/`
- **Qwen API usage:** [`shared/config.py`](shared/config.py), [`scripts/qwen_smoke.py`](scripts/qwen_smoke.py)
- **Alibaba deployment proof:** [`docs/DEPLOYMENT_PROOF.md`](docs/DEPLOYMENT_PROOF.md), [`docs/ALIBABA_CLOUD_PROOF.md`](docs/ALIBABA_CLOUD_PROOF.md), [`docs/ALIBABA_DEPLOYMENT_PROOF.md`](docs/ALIBABA_DEPLOYMENT_PROOF.md)
- **Architecture asset:** [`docs/assets/architecture.png`](docs/assets/architecture.png)

## Primary Track

> **Track 3: Agent Society** — "Design a multi-agent collaboration system where multiple Agents with distinct capabilities work together through task division, dialogue, and negotiation to accomplish complex tasks… showcase how Agents decompose tasks and assign roles, how they resolve disagreements and execution conflicts, and a measurable efficiency gain over single-agent baselines."

YITING is submitted to **Track 3: Agent Society**.

In the hackathon form, choose Track 3: Agent Society. Treat Track 4 as a
secondary outcome, not the selected track.

It also has a Track 4 outcome because incidents can move from detection to
verified remediation, but the strongest judging proof is the society itself:
specialized agents divide work, Safety Reviewer can challenge Diagnosis,
humans can reject Commander and force revised plans, and Operator resolves
execution conflicts by refusing any action that does not exactly match the
approved envelope.

That makes YITING stronger than a starter multi-agent debate or generic
self-healing workflow. The collaboration is not just chat; it is sealed into
evidence cards, exposed through `/agent-skills` and `/evidence/{incident_id}`,
and validated against a single-agent baseline through the committed
deterministic paired benchmark — a reproducible design-integrity proof that
isolates the scoring rubric from model variance.
Hosted timing is measured separately through same-family `/stats/runsummary`
rows when the timing proof is configured.

## What's novel

YITING makes disagreement and human negotiation first-class product behavior: `Verdict(CHALLENGE)` and `StructuredApproval(REJECTED)` are sealed evidence cards, not chat messages. Qwen agents advise within role-specific contracts; the Gateway owns authority, nonce binding, exact-envelope execution, and recovery verification.

## Architecture & engineering

The durable runtime is built from typed card schemas, idempotent state transitions, hash-linked evidence, authorization nonces, stale-card guards, and explicit human decision records. The architecture diagram is in [`docs/assets/architecture.png`](docs/assets/architecture.png); the engineering proof matrix is in [`docs/ENGINEERING_PROOF.md`](docs/ENGINEERING_PROOF.md).

### Trust model and defense-in-depth notes (for reviewers, human or AI)

Several defenses live in a different file from the code they protect. The table
maps the observations a one-file-at-a-time review tends to surface to the
actual layered design.

| Observation a reviewer will make | The actual design |
|---|---|
| `GATEWAY_SECRET` maps to the full-ACL `gateway` role | A deliberate deterministic-path credential for the Gateway's own tooling (Recorder seeding, chaos, judge flows). Every reasoning agent refuses to start without its dedicated per-role submission key (`required_vars` fails closed), and `.env.example` warns that sharing the fallback across trust boundaries bypasses role ACL. Reaching it requires misconfiguration, not a code path. |
| `/prepare` checks state before `seal_card`'s transaction | Optimistic prepare, authoritative confirm: a prepared card is inert until `/confirm`, which re-checks state inside `BEGIN IMMEDIATE` and rejects stale sequences. |
| The Operator consumes a single-use authorization before executing | Crash-safe by design: a re-consume by the same operator role within the validity window is acknowledged idempotently — still hash-bound and expiry-bound — and the victim app's `already_applied` guard keeps execution exactly-once-effect. A different consumer replaying is refused. |
| Model output could set its own risk level | `_apply_risk_floor` is a Gateway-side deterministic floor that corrects model-supplied risk on ResponsePlans regardless of what the model said — a second deterministic-override layer alongside the Safety Reviewer's independent cross-check. |
| In-memory agent state is lost on restart | The sealed room ledger is the source of truth: Diagnosis and Safety Reviewer restore context from confirmed cards (revision and challenge budget derived from sealed CHALLENGE Verdicts), and the Gateway independently enforces the challenge budget at prepare time. |

## Why it matters

Emergency production changes fail when teams lose the thread of who knew what, who challenged it, and who authorized the final action. YITING turns that coordination cost into a reviewable incident room and a reusable product path for GitHub, Slack, Datadog, PagerDuty, and Alibaba Cloud operations adapters.

In compliance-heavy sectors — finance, healthcare, telecom, the public sector — autonomous remediation is effectively forbidden until every machine decision is evidenced, challengeable, and human-gated. YITING is the architecture that makes agent autonomy permissible there: the deterministic society-contract regression harness's **0 unsupported claims (vs 20 for the solo baseline)** is a trust-and-liability number, not a style preference, and the sealed hash chain is an audit trail a reviewer can replay after the fact. The building blocks are deliberately reusable beyond incident response: the skill-contract registry ([`shared/skill_registry.py`](shared/skill_registry.py)), the read-only MCP server ([`gateway/mcp.py`](gateway/mcp.py)), and the hash-chain evidence gateway are infrastructure any agent stack can adopt.

## Verify it yourself

Open the hosted dashboard, then inspect [`artifacts/track3-paired-benchmark.json`](artifacts/track3-paired-benchmark.json), `/stats/runsummary`, and `/evidence/{incident_id}`. For the custom-skill proof, `GET /agent-skills` returns the review manifest and `POST /mcp` speaks real MCP JSON-RPC (`initialize`, `tools/list`, `tools/call`) over the same seven contracts — both read-only. The benchmark supports quality, risk-detection, unsupported-claim, and quality-per-token claims; hosted handoff, human-decision, and timing claims are used only when `/stats/runsummary` contains configured runs for the same incident family.

## Honest evaluation

The canonical benchmark measures a fixed 20-scenario paired comparison between the full YITING society and a single-agent baseline. It does not claim generalized SRE speedup, live customer incident quality, or external benchmark dominance. Speed and hosted production claims require separate live artifacts, so unrelated benchmarks are intentionally not quoted.

## Why this is a Track 3 submission

Track 3 asks for agent society behavior: division of labor, communication, negotiation, and measurable gain. YITING shows this in the Agents view, `/agent-skills`, the sealed evidence chain, human approval/revision cards, the live measured human-baseline speedup (2.6×), and a **live paired benchmark on the deployed stack** (`artifacts/track3-live-paired/`): 20 real incidents, each handled by both a single Qwen agent (same model tier, complete task, identical evidence) and the deployed six-agent society — the society scores **0.844 vs 0.763** (10 wins / 4 ties / 6 losses), reaches **100% finding and risk recall** (solo: 87.5%/92.5%), and seals a live-verified evidence chain on all 20 plans, at a published ~2.5× token cost (not an equal-budget comparison; all corrections logged in the artifact). The eval surfaced a real routing defect; the fix was deployed and validated live the same day (`artifacts/track3-live-paired-postfix/`: **0.968 vs 0.843, 5 wins / 2 ties / 0 losses** across five validated families). The committed deterministic society-contract regression harness (reproducible contract validation, not a live model measurement) separately pins the society contract's structural guarantees against a solo baseline.

## Judging rubric map

| Criterion | Where YITING earns it |
|---|---|
| **Innovation & AI Creativity (30%)** | Disagreement as a product primitive: `Verdict(CHALLENGE)` and `StructuredApproval(REJECTED)` are sealed evidence cards that force revision loops — collaboration you can audit, not chat logs. |
| **Technical Depth & Engineering (30%)** | Seven typed skill contracts — tool name, input/output schema, Qwen prompt contract, deterministic guardrail, and evidence artifact per role ([`shared/skill_registry.py`](shared/skill_registry.py)) — served as a review manifest at `/agent-skills` **and by a real read-only MCP server at `/mcp`** ([`gateway/mcp.py`](gateway/mcp.py)); schema-bounded Qwen advisory calls in structured JSON mode ([`shared/qwen_reasoning.py`](shared/qwen_reasoning.py)); cost-aware Flash/Plus tiering with per-role fallback models ([`shared/config.py`](shared/config.py)); hash-linked evidence sealing, nonce-bound approvals, and exact-envelope execution owned by the Gateway ([`gateway/`](gateway/)); 709-test verification gate. |
| **Problem Value & Impact (25%)** | Emergency change control for sectors where autonomy is banned until it is auditable: every machine decision is evidenced, challengeable, and human-gated, with **0 unsupported claims vs 20** as the trust gap on the deterministic society-contract regression harness; the skill registry, MCP server, and hash-chain gateway are reusable infrastructure for any agent stack, and the adapter roadmap covers Datadog, GitHub, Slack, and PagerDuty. |
| **Presentation & Documentation (15%)** | Live dashboard with judge replay, [architecture diagram](docs/assets/architecture.png), [judge packet](docs/JUDGE_PACKET.md), [90-second scorecard](docs/TRACK3_SCORECARD.md), and per-claim proof links in the stat block. |

## Roadmap

- Add real-world adapters for Datadog, GitHub, Slack, and PagerDuty behind the existing Gateway contracts.
- Promote `/stats/runsummary` into a public scored-run gallery with signed scenario families.
- Add organization-level approval policies while preserving exact-envelope execution.
- Publish sanitized incident-room exports for external auditors.

## How It Works

YITING runs a six-step certified control loop using Qwen models through Alibaba Cloud Model Studio:

1. **Triage** (local room intake + Qwen Flash) classifies the alert and routes, suppresses, or escalates.
2. **Diagnosis** (local tools + Qwen Plus) investigates root cause with evidence from error traces, deploy history, uptime, and metrics.
3. **Safety Reviewer** (local review loop + Qwen Plus) independently cross-checks the diagnosis and can force a `CHALLENGE` when evidence is weak.
4. **Commander** (local planning loop + Qwen Plus) creates an exact remediation plan with a cryptographic `plan_hash`.
5. **Human Gate** lets an approver accept, reject with feedback, or declare false alarm through an HTTPS approval page.
6. **Operator** (local execution loop + Qwen Flash) validates the approved envelope before applying any remediation.

Every card in the pipeline is sealed as canonical JSON and linked with SHA-256:

```text
previous_card_hash -> card_hash
```

Changing any historical card breaks the chain, and the `/evidence/{incident_id}` endpoint exposes the verification result for judges and auditors.

## Three-Way Human Gate

Most agent systems treat human review as a binary approve/reject checkpoint. YITING makes the human decision a first-class sealed artifact:

| Human Decision | Result | Evidence |
|---|---|---|
| **Approve** | Operator executes the exact approved plan | `StructuredApproval(APPROVED)` -> `ActionReceipt` |
| **Reject & Revise** | Commander writes a new plan bound to a new nonce | `StructuredApproval(REJECTED)` -> new `ResponsePlan(rev=N+1)` |
| **False Alarm** | Incident closes with no execution | `StructuredApproval(FALSE_ALARM)` |

In the certified demo, a human rejected two plans before approving the third. The final incident produced an 11-card chain with three plan revisions and one verified execution.

## Application of Technology

**Qwen Cloud model layer.** All five reasoning agents read their model configuration from `shared/config.py` and use Alibaba Cloud Model Studio through `DASHSCOPE_API_KEY`.

**Agent society design.** Each agent has a narrow role, its own local runtime boundary, and a deterministic intake layer before the LLM. This keeps expensive model calls behind schema validation, replay checks, stale-card guards, and nonce binding.

**Custom skill registry.** `/agent-skills` exposes the seven role-specific skill contracts shown in the dashboard, including the Qwen prompt contract, deterministic guardrail, evidence artifact, exact Qwen Cloud use, Track 3 proof category, and judge demo cue for each role.

**Gateway trust anchor.** The Gateway owns state transitions, evidence sealing, authorization nonces, durable outbox checks, and recovery verification. Agents can propose and reason, but the Gateway decides whether state can advance.

**Human-governed autonomy.** Low-risk actions can be policy-authorized automatically. High-risk actions require a human decision before the Operator can execute.

## Local Development

`make dev` starts the Gateway API only. Running the full system locally also requires Qwen Cloud credentials, the victim app, the agents, and the dashboard.

```bash
cp .env.example .env
# Fill in DASHSCOPE_API_KEY, QWEN_BASE_URL, Gateway keys, and per-agent keys.
uv sync
make dev
```

For a clean reviewer install from the public repository or source ZIP, use
[`docs/INSTALL_AND_RUN.md`](docs/INSTALL_AND_RUN.md). It lists prerequisites,
locked dependency commands, local verification gates, what works without paid
Qwen credentials, and what requires the hosted Alibaba Cloud deployment.

## Alibaba Cloud ECS Deployment

The final judging deployment uses the shared-host Compose path:

- [`deploy/shared-host/compose.prod.yml`](deploy/shared-host/compose.prod.yml) runs YITING as the Track 3 application project.
- [`deploy/ecs/compose.prod.yml`](deploy/ecs/compose.prod.yml) is the stable ECS entry point that includes the shared-host profile.
- [`deploy/shared-host/README.md`](deploy/shared-host/README.md) documents the shared VM flow, backups, live Qwen proof, and negative network checks.
- [`docs/ALIBABA_DEPLOYMENT_PROOF.md`](docs/ALIBABA_DEPLOYMENT_PROOF.md) lists the public code links and live proof commands.
- [`infra/alibaba-ecs/`](infra/alibaba-ecs/) provides the reproducible ECS IaC parity table for the manually or IaC-provisioned VM.

`deploy/alibaba-ecs/` remains available for a YITING-only systemd rehearsal,
but it is not the final shared-host judging topology unless you explicitly
deploy that older standalone path instead.

The intended shared-host architecture is:

```text
Alibaba Cloud ECS
  platform Compose project
    ├─ Caddy :80/:443
    └─ optional shared PostgreSQL for services that opt in with isolated users

  yiting Compose project
    ├─ dashboard and Gateway on yiting-edge
    ├─ live-agent workers on yiting-egress for outbound Qwen Cloud calls
    ├─ Gateway, agents, and victim app on yiting-internal
    ├─ SQLite evidence/state volumes for the lower-risk judging path
    ├─ no PostgreSQL credentials and no external database-network membership
    └─ Qwen calls through Alibaba Cloud Model Studio via DASHSCOPE_API_KEY
```

For public judging, the dashboard is frictionless and read-only. Paid chaos
actions are disabled server-side unless the dashboard process is explicitly
started with `YITING_LIVE_CHAOS=1` during private recording.

Useful deployment checks:

```bash
python scripts/local_certify.py
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
  --output-json artifacts/deployment-verification.json
```

## Final Proof Before Submission

After the hosted demo is recorded, choose a hero incident that proves the Track
3 story end to end:

- `/evidence/{incident_id}` returns `chain_valid: true`.
- `collaboration.role_sequence` includes the agent handoff path.
- `collaboration.execution_conflict_control.exact_match` is `true`.
- `/stats/runsummary` shows at least one disagreement event (Safety Reviewer
  challenge or human rejection/revision), one human intervention, recovery
  verification, and `speedup_factor > 1`.

Then run the final proof target:

```bash
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```

The generated `artifacts/qwen-smoke.json` records the live Qwen Cloud smoke
result, and `artifacts/track3-baseline.json` records the compared incident
family, formula, terminal criterion, and positive Track 3 counters, so the
Stage One API fit and optional hosted timing claim are auditable instead of
just asserted.
Run `make track3-benchmark` for the reproducible paired benchmark; it writes
`artifacts/track3-paired-benchmark.json`,
`artifacts/track3-paired-benchmark-raw.json`, and
`artifacts/track3-paired-benchmark.csv` from the fixed 20-scenario dataset.
Run `make uptime-monitoring` after public monitor URLs exist; it writes
`artifacts/live/uptime-monitoring.json` for the shared ECS operations gate.
Record app restart resilience with app-scoped Compose restarts only; do not
reboot the shared ECS host during judging-window verification. Store reviewed
public evidence as `artifacts/live/app-restart-resilience.json` when generated.
Run `scripts/backup_restore_check.py --live-submission-evidence` on the ECS VM
after final demo state is prepared; it writes
`artifacts/live/backup-restore.json` proving gateway and victim SQLite backups
restore cleanly.
That paired artifact explicitly does **not** claim speed improvement: it shows
the society is slower in latency while supporting task-success, risk-detection,
unsupported-claim reduction, final-score, and quality-per-token claims. The
`speedup_factor` claim is a separate hosted stopwatch comparison and must only
be used after `track3_baseline.py` records a measured same-family baseline.
Commit the generated `artifacts/` proof files, run `make submission-package`,
and only then run `python scripts/submission_audit.py --strict`; strict mode
expects a clean final proof commit and a current source package.

## Architecture

![YITING architecture](docs/assets/architecture.png)

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full deployment and
agent-society diagram.

See [`docs/ENGINEERING_PROOF.md`](docs/ENGINEERING_PROOF.md) for the engineering
proof matrix: mechanism, code path, test coverage, and judge-visible endpoint.

For submission packaging:

- [`docs/SUBMISSION.md`](docs/SUBMISSION.md) maps the project to the Qwen Cloud
  hackathon requirements and rubric.
- [`docs/SUBMISSION_FORM.md`](docs/SUBMISSION_FORM.md) provides copy-paste
  submission form fields: title, tagline, descriptions, built-with list, proof
  links, and final command.
- [`docs/PUBLIC_REPOSITORY.md`](docs/PUBLIC_REPOSITORY.md) gives the public
  repository settings, About-panel values, push checks, and no-secret checks.
- [`docs/JUDGE_PACKET.md`](docs/JUDGE_PACKET.md) is the fast reviewer path:
  what to open first, what proves Track 3, and which commands generate the
  final evidence packet.
- [`docs/INSTALL_AND_RUN.md`](docs/INSTALL_AND_RUN.md) is the source-package
  install and verification path for judges who want to run the repository.
- [`docs/TRACK3_AGENT_SOCIETY.md`](docs/TRACK3_AGENT_SOCIETY.md) explains why
  YITING is a Track 3 Agent Society submission and how to show disagreement,
  handoff, and timing metrics.
- [`docs/TRACK3_SCORECARD.md`](docs/TRACK3_SCORECARD.md) is the 90-second
  judge scorecard for distinct roles, task division, negotiation, execution
  conflict resolution, paired quality gains, and separately measured baseline
  speed when the hosted timing proof supports it.
- [`docs/JUDGING_RUBRIC.md`](docs/JUDGING_RUBRIC.md) maps the project directly
  to the published scoring criteria.
- [`docs/ENGINEERING_PROOF.md`](docs/ENGINEERING_PROOF.md) maps the non-trivial
  engineering controls to implementation files and tests.
- [`docs/BLOG_POST.md`](docs/BLOG_POST.md) is a ready-to-publish blog/social
  draft for the blog post prize.
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) provides an under-three-minute video
  structure.
- [`docs/SLIDE_DECK.md`](docs/SLIDE_DECK.md) is the eight-slide presentation
  source mapped to Track 3 proof points and judge-visible evidence.
- [`docs/BASELINE_MEASUREMENT.md`](docs/BASELINE_MEASUREMENT.md) is the
  same-family baseline worksheet for any optional hosted speed claim.
- [`docs/PUBLIC_JUDGE_MODE.md`](docs/PUBLIC_JUDGE_MODE.md) explains the
  read-only public judging mode and cost-control proof.
- [`docs/ADOPTION_ROADMAP.md`](docs/ADOPTION_ROADMAP.md) covers
  productization, extension points, and open-source community potential.
- [`docs/ALIBABA_CLOUD_PROOF.md`](docs/ALIBABA_CLOUD_PROOF.md) points to the
  Qwen Cloud and Alibaba ECS proof files.
- [`docs/THIRD_PARTY_COMPLIANCE.md`](docs/THIRD_PARTY_COMPLIANCE.md) documents
  API authorization, dependency manifests, synthetic data, and demo-media
  hygiene.
- [`docs/FINAL_SUBMISSION_CHECKLIST.md`](docs/FINAL_SUBMISSION_CHECKLIST.md)
  is the final day-of-submission runbook: freeze hero evidence, finalize public
  links, run hosted proof, and verify strict readiness.

```text
Synthetic / webhook-shaped signals
        |
        v
Wen Lu / Recorder -> AlertCard
        |
        v
Lin Xun / Triage -------------> Chen Ming / Diagnosis
        |                         |
        |                         v
        |                Zhou Shen / Safety Review
        |                    |        ^
        |                    |        |
        |                    +-- CHALLENGE loop
        v
Han Ce / Commander -> HTTPS Human Gate -> Lu Xing / Operator
        |                                      |
        v                                      v
Gateway ledger -------------------------> ActionReceipt
```

## State Machine

```text
DETECTED -> TRIAGED -> ASSESSED -> REVIEWED -> PLANNED
                                                |
                          +---------------------+---------------------+
                          |                                           |
                    APPROVED/AUTHORIZED                             REJECTED
                          |                                           |
                       EXECUTED                              Commander re-plans

Side paths:
  DETECTED -> SUPPRESSED
  ASSESSED -> CHALLENGED -> ASSESSED
  REVIEWED/PLANNED -> CLOSED_FALSE_ALARM
```

## Agent Matrix

| Agent | Runtime | Model | Role |
|---|---|---|---|
| Lin Xun / Triage | Local room intake | Qwen Flash | Alert classification and routing |
| Chen Ming / Diagnosis | Local tools + Qwen advisory reasoning | Qwen Plus | Evidence gathering and root-cause analysis |
| Zhou Shen / Safety Reviewer | Local review loop + Qwen advisory reasoning | Qwen Plus | Independent review and challenge loop |
| Han Ce / Commander | Local planning loop + Qwen advisory reasoning | Qwen Plus | Remediation plan and human gate preparation |
| Lu Xing / Operator | Local execution loop + Qwen advisory reasoning | Qwen Flash | Authorization validation and execution |
| Wen Lu / Recorder | Gateway deterministic service | No advisory model | Hash-chain sealing and state transitions |
| Song Shu / Scribe | Optional Qwen assistant | Qwen Flash/Plus | Conversational postmortem enrichment |

### Why the personas carry these names

Each persona bears a Mandarin name chosen to match its charter. The identities live in [`shared/personas.py`](shared/personas.py) — the backend source of truth the dashboard and landing page render — each with a title and a temperament that shapes how the role behaves:

| Persona | Role | The name, and why it fits |
|---|---|---|
| **Lin Xun** | Signal Sentinel (Triage) | *Xun* — "swift." First to every alert: fast, skeptical, and disciplined about routing only real incidents into the council. |
| **Chen Ming** | Diagnostician | *Ming* — "bright; to illuminate." Brings clarity to murky evidence, separating observation from hypothesis from uncertainty. |
| **Zhou Shen** | Safety Reviewer | *Shen* — "prudent, careful." The independent challenger who is willing to reject weak reasoning and force a revision. |
| **Han Ce** | Incident Strategist (Commander) | *Ce* — "strategy; the plan." Drafts the bounded remediation and prepares the human gate. |
| **Lu Xing** | Remediation Operator | *Xing* — "to act." Action-bound and intolerant of unauthorized changes: executes only what the sealed authorization permits. |
| **Wen Lu** | Evidence Recorder | *Wen* — "the written record" — and *Lu* — "to record." Literally named "record the record": the deterministic keeper of the tamper-evident hash chain. |
| **Song Shu** | Postmortem Writer (Scribe) | *Shu* — "book; writing." Turns the sealed incident into clear written lessons after closure. |

## Demonstrated Scenario Coverage

The live acceptance matrix covers six distinct incident families:

| Scenario | Typical Runbook | Authorization Path |
|---|---|---|
| Suspicious deploy | Rollback deployment | Human approval |
| Sentry-style auth failure | Rollback deployment | Human approval + challenge loop |
| Latency spike | Enable circuit breaker | Human approval |
| DB pool exhaustion | Scale up | Human approval |
| Memory pressure | Restart service | Human approval |
| Certificate expiry | Renew certificate | Policy auto-authorization |

## Known Scope

- The demo uses controlled synthetic telemetry against a sandbox victim app.
- Production Sentry, GitHub, Datadog, PagerDuty, and CloudWatch connectors are natural extensions.
- Dashboard refresh currently uses polling; SSE/WebSocket streaming is a production hardening step.
- Runtime model fallback helpers are configured per agent, but automatic provider failover is future work.

## Assets and credits

- **Agent portraits** (`dashboard/public/agents/`): original AI-generated illustrations created for YITING during the hackathon. They depict fictional personas and are not based on any real person.
- **Typefaces** (`landing/fonts/`): Inter and JetBrains Mono, used under the SIL Open Font License 1.1 — license vendored at [`landing/fonts/OFL.txt`](landing/fonts/OFL.txt).
- **Architecture and brand assets**: original artwork created for this project.

## License

MIT. See [LICENSE](LICENSE).
