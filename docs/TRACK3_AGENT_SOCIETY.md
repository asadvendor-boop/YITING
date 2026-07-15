# Track 3 Proof — Agent Society

YITING is submitted primarily to **Track 3: Agent Society**.

The project is an incident-response council: specialized Qwen-backed agents
divide emergency-change work across narrow authority boundaries, resolve
disagreements through sealed review loops, and coordinate through a
Gateway-owned incident room.

## Why Track 3

Track 3 asks for a multi-agent collaboration system with:

1. distinct capabilities,
2. task division and role assignment,
3. disagreement or conflict resolution, and
4. measurable efficiency compared with a single-agent baseline.

YITING maps directly to those requirements.

| Track 3 requirement | YITING evidence |
|---|---|
| Distinct capabilities | Recorder, Triage, Diagnosis, Safety Reviewer, Commander, Operator, and optional Scribe each have a separate role, card type, and `/agent-skills` contract. |
| Task division | Every incident advances through role-owned cards: `AlertCard`, `TriageDecision`, `Assessment`, `Verdict`, `ResponsePlan`, authorization card, and `ActionReceipt`. |
| Dialogue and negotiation | Agents exchange room messages and sealed cards through the Gateway-owned incident room. |
| Disagreement handling | Safety Reviewer can issue `Verdict(CHALLENGE)`, forcing Diagnosis to revise its `Assessment`. Humans can issue `StructuredApproval(REJECTED)`, forcing Commander to create a revised plan. |
| Execution conflict control | Operator can execute only the envelope that exactly matches an authorized plan. Stale, modified, or unapproved actions fail closed. |
| Measurable efficiency | The paired benchmark reports quality, reliability, and quality-per-token gains over a single-agent baseline; `/stats/runsummary` separately reports per-run timing, handoffs, challenges, human interventions, and optional measured-baseline speed. |

## Track Choice

YITING also has a valid Track 4 angle because the system can carry an incident
from detection to verified remediation. Track 3 is still the stronger primary
submission because the winning behavior is not just autonomous execution. The
core proof is a coordinated society: roles divide work, Safety Reviewer can
challenge Diagnosis, humans can reject Commander and force a revised plan, and
Operator resolves execution conflicts by refusing any action that does not
match the approved envelope.

That distinction matters for judging. A single-agent autopilot could produce a
plan. YITING proves an auditable collaboration process around the plan.

## Why This Is More Than A Starter Idea

The hackathon inspiration examples are useful starting points. YITING is framed
as a fuller Track 3 entry because it combines several proof layers in one live
system:

| Starter angle | YITING extension |
|---|---|
| Multi-agent debate | Disagreements are not just text. `Verdict(CHALLENGE)` and `StructuredApproval(REJECTED)` become sealed state transitions that force revised work. |
| Cooperative swarm | Roles are authority-bounded. Each agent owns a specific card type, handoff, and failure mode instead of sharing one broad task. |
| Autonomous workflow | Execution is governed. Low-risk work can be policy-authorized, while high-risk work requires a human gate and exact-envelope execution. |
| Demo-only simulation | The browser exposes evidence chains, collaboration metrics, and deployment verification commands that judges can inspect directly. |

## Society Members

| Agent | Public name | Authority boundary |
|---|---|---|
| Recorder | Wen Lu | Creates the initial alert card and keeps deterministic records. |
| Triage | Lin Xun | Classifies and routes alerts. |
| Diagnosis | Chen Ming | Investigates root cause from evidence sources. |
| Safety Reviewer | Zhou Shen | Reviews diagnoses and can challenge weak evidence. |
| Commander | Han Ce | Converts a confirmed diagnosis into a remediation plan. |
| Operator | Lu Xing | Executes only authorized envelopes and verifies recovery. |
| Scribe | Song Shu | Optional postmortem enrichment. |

## Custom Skill Contracts

YITING exposes the society's skill map through:

```text
GET /agent-skills
```

Each entry names the role, Qwen model layer, prompt contract, deterministic
guardrail, input contract, output contract, evidence artifact, exact Qwen Cloud
use, Track 3 proof category, and judge demo cue. This makes the agent society
auditable from the browser instead of hiding the collaboration logic in prose.

The endpoint is intentionally shaped as an MCP-style manifest: every role has a
stable `tool_name`, JSON-like input and output schemas, a guardrail, and a
linked evidence artifact. Judges can inspect it without credentials or paid
model calls, then verify the corresponding card in `/evidence/{incident_id}`.

## Per-Incident Collaboration Proof

Every public evidence export includes a derived `collaboration` block:

```text
GET /evidence/{incident_id}
```

It contains the role sequence, handoffs, sealed challenges, human decisions,
authorization path, and exact planned-vs-executed action comparison. This is
the fastest way to prove the Track 3 requirements for a specific run:

| Track 3 proof | Evidence field |
|---|---|
| Task division and role assignment | `collaboration.role_sequence` and `collaboration.handoffs` |
| Dialogue and negotiation | Incident-room messages plus published card sequence |
| Disagreement resolution | `collaboration.challenges` |
| Human conflict resolution | `collaboration.human_decisions` |
| Execution conflict control | `collaboration.execution_conflict_control.exact_match` |

## Disagreement Loops

### Agent-to-Agent Challenge

```text
Assessment(revision=1)
  -> Verdict(CHALLENGE)
  -> Assessment(revision=2)
  -> Verdict(CONFIRM)
```

This proves the reviewer does not simply rubber-stamp Diagnosis. A challenge is
sealed into the evidence chain and the revised assessment must be linked to the
same incident.

### Human-to-Agent Revision

```text
ResponsePlan(revision=1)
  -> StructuredApproval(REJECTED, reason=...)
  -> ResponsePlan(revision=2)
  -> StructuredApproval(APPROVED)
  -> ActionReceipt
```

This proves a human can redirect the agent society without granting permission
to execute the rejected plan. The revised plan receives a new nonce and a new
authorization binding.

## Measurable Efficiency

YITING does not invent an industry baseline. The hosted system exposes
transparent measurements through:

```text
GET /stats/runsummary
```

Important fields:

| Field | Meaning |
|---|---|
| `avg_agent_processing_secs` | Mean time from alert publication to response-plan publication. |
| `avg_total_resolution_secs` | Mean time from alert publication to terminal state. |
| `total_handoffs` | Adjacent role-to-role transitions across published cards. |
| `total_challenges_issued` | Number of sealed Safety Reviewer challenges. |
| `total_human_rejections` | Number of sealed human rejections that force Commander revision. |
| `disagreement_events` | Sum of Safety Reviewer challenges and human rejection/revision events. |
| `human_interventions` | Count of consumed human approvals. |
| `recovery_verified_count` | Count of incidents with verified execution receipt. |
| `speedup_factor` | Present only when `MANUAL_BASELINE_SECS` is set from a measured baseline. |

To show a fair baseline comparison:

1. Measure the same incident type using your chosen single-agent or manual
   incident-response workflow.
2. Generate a shareable proof artifact from the measured baseline and the live
   run summary. The artifact records the incident family, formula, terminal
   criterion, and nonzero Track 3 counters so the comparison is auditable. When
   `/stats/runsummary` includes family-tagged runs, the helper uses only runs
   whose `incident_family` matches `--incident-family` and records the matched
   incident IDs:

```bash
python scripts/track3_baseline.py \
  --gateway-url "https://yiting.47.84.232.193.sslip.io" \
  --baseline-secs <measured-single-agent-seconds> \
  --baseline-label "Measured single-agent rehearsal" \
  --incident-family "<same-family-as-hero-incident>" \
  --output-json artifacts/track3-baseline.json
```

3. Set `MANUAL_BASELINE_SECS` on the ECS host to the same measured duration.
4. Restart the Gateway.
5. Open `/stats/runsummary` and quote the resulting `speedup_factor`.
6. Run the deployment verifier with `--require-speedup` so the final proof
   fails closed if the single-agent comparison is missing:

```bash
python scripts/verify_deployment.py \
  --public-url "https://yiting.47.84.232.193.sslip.io" \
  --incident-id "<hero-incident-id>" \
  --require-speedup \
  --output-json artifacts/deployment-verification.json
```

If no measured baseline is configured, the API intentionally returns
`speedup_factor: null`.

## Paired Single-Agent Benchmark

The same-family hosted baseline is intentionally live and stopwatch-based. For
repeatable local review, YITING also ships a paired benchmark:

```bash
python scripts/track3_paired_benchmark.py
```

It compares `single_agent` against `full_yiting_society` on the fixed dataset
`evals/track3_paired_scenarios.json`. The artifact
`artifacts/track3-paired-benchmark.json` records:

- fixed 20-scenario dataset version
- same model identity for both variants
- same declared rubric
- three paired runs per scenario
- raw JSON and CSV row artifacts
- mean, median, failure count, total tokens, latency, unsupported claims,
  risks detected, and quality per token

This benchmark supports quality and reliability claims, not speed claims. The
generated summary explicitly sets `comparison.speed_improvement_claimed` to
`false` and lists speed improvement under `claims_not_made`.

## Judge Demo Beats

For the under-three-minute video, capture the same five proof beats listed in
`docs/DEMO_SCRIPT.md`. Together they cover the exact Track 3 scoring language:

1. **Distinct roles:** `/agent-skills` or the Agents page showing role-specific
   skill contracts.
2. **Task decomposition:** `/evidence/{incident_id}.collaboration.role_sequence`
   showing the handoff sequence.
3. **Disagreement:** a `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)`
   card showing that the society can challenge and revise.
4. **Execution conflict control:** `ActionReceipt` showing the exact approved
   envelope was executed and recovery was verified.
5. **Measured efficiency:** the paired benchmark showing higher success,
   fewer unsupported claims, more risks detected, better final score, and
   better quality per token; `/stats/runsummary` or the Runs page shows
   `speedup_factor > 1` only after the separate same-family hosted timing
   baseline is configured.

Then mention the Track 3 proof in one sentence:

> "This is an Agent Society: each role owns a different authority boundary,
> challenges are sealed into the audit chain, and the system reports timing,
> handoff, challenge, human-intervention, and manual-baseline timing metrics
> through `/stats/runsummary`."
