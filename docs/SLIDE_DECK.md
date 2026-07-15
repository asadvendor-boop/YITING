# YITING Slide Deck Source

Use this as the source for the final 8-slide PDF or presentation deck. Keep it
short enough that a judge can skim it in two minutes, but concrete enough that
every claim points to a public proof artifact.

## Slide 1: Title

**YITING: Evidence-Bound Qwen Agent Society**

Subtitle: Governed incident response where specialized agents disagree, revise,
and execute only authorized remediation.

Visual:

- product logo or dashboard hero screenshot
- one-line Track 3 label: "Agent Society, not a single bot"
- small proof footer: "Qwen Cloud smoke + Alibaba ECS verifier + Track 3 scorecard"

Speaker note:

> YITING is submitted to Track 3 because the main proof is collaboration:
> specialized Qwen agents divide work, challenge weak reasoning, negotiate with
> a human, and resolve execution conflicts before action.

Stage One proof to mention:

- `artifacts/qwen-smoke.json` proves live Qwen Cloud API access.
- `artifacts/deployment-verification.json` proves the hosted Alibaba ECS
  deployment and public read-only judge mode.
- `docs/TRACK3_SCORECARD.md` maps the demo to the Track 3 requirements.

## Slide 2: The Problem

**Emergency changes are either too slow or too risky.**

Bullets:

- Manual response has slow handoffs and weak audit trails.
- Fully autonomous response can execute stale or unsafe actions.
- Regulated teams need speed, evidence, and human governance in the same flow.

Proof to show:

- dashboard incident state list
- final hero incident evidence URL

## Slide 3: The Agent Society

**Seven roles, one deterministic control plane.**

Bullets:

- Recorder seals evidence.
- Triage routes the alert.
- Diagnosis gathers evidence and proposes root cause.
- Safety Reviewer can challenge weak conclusions.
- Commander plans the remediation.
- Human Gate approves, rejects, or marks false alarm.
- Operator executes only the approved envelope and verifies recovery.

Proof to show:

- `/agent-skills`
- `collaboration.role_sequence`
- Agents page skill contracts

## Slide 4: Disagreement Is Real

**The system does not rubber-stamp itself.**

Bullets:

- `Verdict(CHALLENGE)` forces Diagnosis to revise.
- `StructuredApproval(REJECTED)` forces Commander to revise the plan.
- Revised plans bind a new nonce so stale approvals cannot execute.

Proof to show:

- hero chain containing `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)`
- revised `ResponsePlan`
- changed nonce or revision number

## Slide 5: Execution Conflict Control

**Reasoning agents propose. The Gateway authorizes. Operator executes exactly.**

Bullets:

- Every accepted card is canonical JSON with a SHA-256 hash.
- The Operator must match the approved action envelope exactly.
- Recovery must be verified before the final `ActionReceipt` is accepted.
- Duplicate and stale actions fail closed.

Proof to show:

- `/evidence/{incident_id}` with `chain_valid: true`
- `collaboration.execution_conflict_control.exact_match`
- final `ActionReceipt`

## Slide 6: Graduated Autonomy

**High risk gets a human gate. Low risk can use policy authorization.**

Bullets:

- High-risk incidents produce `StructuredApproval`.
- Low-risk safe remediation produces `PolicyAuthorization`.
- False alarms become sealed human decisions, not hidden edits.

Proof to show:

- one high-risk hero incident
- one low-risk contrast incident
- dashboard state and evidence chain for both paths

## Slide 7: Measured Impact

**Track 3 requires measurable efficiency gain, so the final packet measures it.**

Bullets:

- `/stats/runsummary` reports handoffs, disagreements, human decisions, and
  recovery verification.
- `scripts/track3_baseline.py` records a same-family single-agent/manual
  baseline.
- `scripts/verify_deployment.py --require-speedup` fails if `speedup_factor`
  is not greater than 1.

Proof to show:

- `/stats/runsummary`
- `artifacts/track3-baseline.json`
- `artifacts/final-proof-index.md`

Guardrail:

- Do not claim `speedup_factor > 1` until the same-family baseline artifact is
  generated from a measured single-agent/manual rehearsal.

## Slide 8: Why It Wins Track 3

**YITING is a governable agent society, not a dashboard demo.**

Score mapping:

- Innovation: Qwen-backed roles plus inspectable MCP-style skill contracts.
- Technical depth: evidence chain, nonce binding, exact-envelope execution,
  recovery verification.
- Impact: safer emergency change control for real operational teams.
- Presentation: public replay, evidence export, demo video, and final proof
  index.

Final line:

> The winning claim is simple: multiple agents can move faster than one agent,
> but only if the system makes disagreement, authority, and evidence explicit.
