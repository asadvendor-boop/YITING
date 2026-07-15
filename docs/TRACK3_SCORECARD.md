# Track 3 Judge Scorecard

This is the one-page scoring route for YITING as a **Track 3: Agent Society**
entry. It mirrors the hackathon wording so judges can verify the required
behaviors without reverse-engineering the repository.

## The Claim

YITING is a Qwen-backed incident council. Specialized agents divide emergency
change work, exchange evidence through a shared incident room, challenge weak
reasoning, negotiate revisions with a human approver, and allow execution only
when the final action exactly matches the authorized plan.

## Five Proofs Judges Should Inspect

| Track 3 requirement | YITING proof | What to look for |
|---|---|---|
| Agents with distinct capabilities | `/agent-skills`, Agents page, `shared/skill_registry.py` | Recorder, Triage, Diagnosis, Safety Reviewer, Commander, Operator, and Scribe expose separate skill contracts, prompts, schemas, guardrails, evidence artifacts, Qwen Cloud use, Track 3 proof category, and judge demo cue. |
| Task division and role assignment | `/evidence/{incident_id}.collaboration.role_sequence` | The role sequence should show the incident moving through role-owned cards instead of one generic agent doing everything. |
| Dialogue and negotiation | Incident room plus sealed cards | `Verdict(CHALLENGE)` shows Safety Reviewer disputing Diagnosis; `StructuredApproval(REJECTED)` shows the human sending Commander back to revise. |
| Execution conflict resolution | `/evidence/{incident_id}.collaboration.execution_conflict_control.exact_match` | Operator can execute only the exact approved envelope; stale, modified, or unapproved actions fail closed. |
| Measurable efficiency gain | `artifacts/track3-paired-benchmark.json`, `/stats/runsummary`, `artifacts/track3-baseline.json`, `scripts/verify_deployment.py --require-speedup` | The paired benchmark must show higher success, lower unsupported-claim rate, more risks detected, better final score, and better quality per token against a single-agent baseline. A speed claim is accepted only when the hosted proof shows `speedup_factor > 1` against a measured same-family manual (human) baseline; tagged runsummary rows are matched by `incident_family` before the artifact is accepted. |
| Reproducible society benchmark | `artifacts/track3-paired-benchmark.json`, raw JSON/CSV, `evals/track3_paired_scenarios.json` | The fixed paired benchmark compares `single_agent` and `full_yiting_society` on the same 20 scenarios, same rubric, same model identity, and token-normalized metrics without claiming speed improvement. |

## 90-Second Verification Route

1. Open the landing page and confirm the primary track is **Track 3: Agent
   Society**.
2. Open `/agent-skills` or the Agents page and inspect the role-specific skill
   contracts.
3. Open the hero `/evidence/{incident_id}` export and verify:
   - `chain_valid: true`
   - `collaboration.role_sequence` contains the handoff path
   - at least one `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)` exists
   - `collaboration.execution_conflict_control.exact_match: true`
4. Open `artifacts/track3-paired-benchmark.json` and verify the paired quality
   gains. Then open `/stats/runsummary` and verify handoffs, human decisions,
   recovery verification, and `speedup_factor > 1` only when a same-family
   hosted timing artifact is being used.
5. Check `artifacts/qwen-smoke.json`, `artifacts/track3-baseline.json`,
   `artifacts/track3-paired-benchmark.json`, and
   `artifacts/deployment-verification.json` in the final proof packet.

## Rubric Mapping

| Criterion | Judge-facing proof |
|---|---|
| Innovation & AI Creativity — 30% | Qwen-backed role society, MCP-style skill contracts, challenge loops, three-way human decisions, exact execution boundary. |
| Technical Depth & Engineering — 30% | Gateway-owned state machine, SHA-256 evidence chain, nonce-bound approvals, outbox/recovery verification, sanitized public package. |
| Problem Value & Impact — 25% | Emergency change control: fast remediation without invisible automation, false-alarm closure, and audit-ready proof for regulated teams. |
| Presentation & Documentation — 15% | Landing page, dashboard replay, judge packet, demo script, architecture doc, engineering proof matrix, and this scorecard. |

## Why Track 3 Beats Track 4 For This Submission

Track 4 explains the outcome: incidents can reach verified remediation. Track 3
explains the differentiator: YITING proves the collaboration process around the
outcome. The submission is strongest when judges see agents decomposing work,
disagreeing, revising, and resolving execution conflicts before anything
touches production.
