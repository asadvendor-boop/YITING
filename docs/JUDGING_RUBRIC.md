# YITING Judging Rubric Map

This document maps YITING directly to the published judging criteria. It is
written for a reviewer who has only a few minutes and needs to understand why
the project belongs in the top tier.

## Stage One: Baseline Viability

| Requirement | YITING proof |
|---|---|
| Fits the hackathon theme | Primary track is **Track 3: Agent Society**. The system is a council of specialized agents that hand off work, challenge weak reasoning, and coordinate through a shared incident room. |
| Uses required Qwen Cloud APIs | All reasoning agents route model calls through `shared/qwen_reasoning.py`, `shared/config.py`, and `DASHSCOPE_API_KEY` / `QWEN_BASE_URL`. `scripts/qwen_smoke.py` provides live credential proof. |
| Runs on Alibaba Cloud | `deploy/alibaba-ecs/` provides ECS systemd units, Caddy routing, environment generation, and `scripts/verify_deployment.py --output-json` for hosted proof. |
| Public, verifiable demo path | Landing page, dashboard, `/agent-skills`, `/evidence/{incident_id}`, `/stats/runsummary`, and the sanitized source package are all prepared for public review. |

## Stage Two Scorecard

### Innovation & AI Creativity — 30%

| What judges look for | YITING evidence |
|---|---|
| Sophisticated Qwen Cloud use | Five reasoning roles use Qwen advisory calls with strict JSON contracts. Qwen suggests reasoning, but deterministic Gateway controls preserve safety. |
| Custom agent skills | `/agent-skills` exposes a deterministic MCP-style review manifest with seven project-specific tool contracts: tool name, input schema, output schema, Qwen prompt boundary, deterministic guardrail, evidence artifact, explicit Qwen Cloud use, Track 3 proof category, and judge demo cue for triage routing, evidence fusion, independent challenge review, runbook planning, exact-envelope execution, evidence sealing, and postmortem enrichment. The manifest route is not a network MCP server; it is the public custom-skill contract layer judges can inspect. The same seven contracts are also served by a real read-only network MCP server at `POST /mcp` (`gateway/mcp.py` — JSON-RPC 2.0 `initialize`, `tools/list`, `tools/call`). The dashboard renders the same registry under **Agents & Room → Custom agent skills**. |
| Novel multi-agent behavior | The Safety Reviewer can issue a sealed `Verdict(CHALLENGE)` that forces Diagnosis to revise. Humans can reject a plan and force Commander to produce a new revision. `/evidence/{incident_id}.collaboration` summarizes these proof points per run. |
| Creative governance model | Human review is not a simple approve button. It is a three-way sealed decision: approve, reject-and-revise, or false alarm. |
| Custom collaboration layer | YITING replaces generic chat dependency with a Gateway-owned incident room, room messages, participants, and card publication verification. |

**Best demo beat:** show a challenge or rejection loop in the evidence chain,
then point to `/stats/runsummary` for handoffs, challenges, human decisions, and
recovery verification.

### Technical Depth & Engineering — 30%

| What judges look for | YITING evidence |
|---|---|
| Modular architecture | Gateway, agents, victim app, dashboard, local room runtime, Qwen reasoning layer, and deployment scripts are separated by clear boundaries. |
| Non-trivial logic | `docs/ENGINEERING_PROOF.md` maps SHA-256 evidence sealing, nonce-bound approvals, exact action envelope validation, replay guards, bounded suppression, durable state transitions, publication verification, and recovery verification to code and tests. |
| Error handling | Publication verification, fail-closed authorization, stale-card guards, package hygiene, deployment proof JSON, and local certification for both policy and human paths. |
| Scalability path | Agents can scale by role; incident rooms isolate context per incident; public judge mode disables paid/mutating actions while preserving replay. |
| Advanced stack adoption | FastAPI, SQLite ledger, Next.js dashboard, Caddy edge routing, systemd units, Alibaba ECS, and Alibaba Cloud Model Studio/Qwen. |

**Best demo beat:** export `/evidence/{incident_id}` and show
`chain_valid: true`, then show an altered action being blocked by exact-envelope
validation.

### Problem Value & Impact — 25%

| What judges look for | YITING evidence |
|---|---|
| Real-world relevance | Emergency production changes are high-risk: teams need speed, auditability, and human governance. |
| Authentic business pain | The system addresses alert fatigue, weak incident handoffs, unsafe automation, and poor audit trails. |
| Product potential | The Gateway-owned ledger can become an open-source control plane for regulated incident response. |
| Scalable adoption | Teams can add evidence connectors, new runbooks, more Qwen-backed roles, and organization-specific policy. |
| Trust story | Agents reason, but they do not silently execute. The Gateway owns authority, state, nonces, and evidence. |

**Best demo beat:** contrast low-risk policy authorization with high-risk human
approval. That is the product: autonomy with governance.

### Presentation & Documentation — 15%

| What judges look for | YITING evidence |
|---|---|
| Clear technical demo | `docs/DEMO_SCRIPT.md` gives an under-three-minute story: signal, agent society, challenge/human gate, execution, evidence proof. |
| Architecture docs | `docs/ARCHITECTURE.md` includes Alibaba ECS and evidence-chain diagrams; `docs/ENGINEERING_PROOF.md` maps non-trivial algorithms to code, tests, and judge-visible endpoints. |
| Track clarity | `docs/TRACK3_AGENT_SOCIETY.md` explains why this is Track 3 and how to demonstrate agent collaboration. |
| Fast reviewer path | `docs/JUDGE_PACKET.md` lists the exact pages, endpoints, and proof commands judges should inspect first. |
| Deployment proof | `docs/ALIBABA_CLOUD_PROOF.md` and `artifacts/deployment-verification.json` show hosted proof without exposing secrets. |
| Form-ready copy | `docs/SUBMISSION_FORM.md` provides copy-paste title, tagline, descriptions, links, and proof command fields. |
| Submission checklist | `docs/FINAL_SUBMISSION_CHECKLIST.md`, `make submission-ready`, `scripts/submission_status.py --require-final`, and `scripts/submission_audit.py --strict` keep the final packet honest. |

**Best demo beat:** keep the video focused on the visible agent society and the
evidence chain. Avoid spending time on setup commands except as a short proof
appendix.

## One-Sentence Judge Pitch

YITING is a Qwen-powered incident council where specialized agents collaborate,
challenge each other, require human approval for risky changes, and seal every
decision into a tamper-evident evidence chain on Alibaba Cloud.

## 100-Point Optimization Checklist

- [ ] Live Qwen smoke check passes on Alibaba ECS and writes `artifacts/qwen-smoke.json`.
- [ ] `docs/JUDGE_PACKET.md` has the final incident ID and evidence links.
- [ ] Hosted dashboard and landing page pass `scripts/verify_deployment.py`.
- [ ] `docs/ENGINEERING_PROOF.md` maps each technical invariant to code and tests.
- [ ] One low-risk incident reaches policy-authorized `EXECUTED`.
- [ ] One high-risk incident requires human approval before `EXECUTED`.
- [ ] At least one challenge or rejection loop appears in the demo or replay.
- [ ] `/agent-skills` shows the custom agent skill registry in the live demo.
- [ ] `/evidence/{incident_id}` shows `chain_valid: true` and a populated `collaboration` block.
- [ ] `/stats/runsummary` shows handoffs, human decisions, recovery metrics, and family-tagged runs.
- [ ] `scripts/track3_baseline.py` writes the measured same-family single-agent comparison artifact.
- [ ] `scripts/verify_deployment.py --require-speedup` passes after a measured same-family manual (human) baseline is configured.
- [ ] `artifacts/final-proof-index.md` ties the Qwen smoke, matched same-family baseline runs, deployment, public read-only, hero evidence, and source package proofs together.
- [ ] Public source archive is current and sanitized.
- [ ] `docs/SUBMISSION_FORM.md` has the final form copy ready.
- [ ] `docs/FINAL_SUBMISSION_CHECKLIST.md` has no unchecked local work.
- [ ] Demo video is embedded on the landing page.
- [ ] `python scripts/submission_audit.py --strict` passes.
