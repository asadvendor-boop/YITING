# YITING Demo Script

Target length: under 3 minutes. Judges are not required to watch beyond the
three-minute mark, so treat 2:55 as the hard edit target.

Goal: show a Qwen-backed agent society handling an incident with evidence,
disagreement, human governance, and verified execution.

## Recording Modes

Use **Live Mode** for the strongest opening shot: trigger one suspicious deploy
from the dashboard and let the agents move it through the room. If the live run
does not naturally produce a challenge or human rejection during the recording
window, switch to **Verified Replay Mode** for that proof beat.

Both are valid as long as the replay is tied to a real hosted incident whose
`/evidence/{incident_id}` export shows `chain_valid: true` and includes a
sealed `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)`, final state
`EXECUTED`, and an `ActionReceipt`. Do not show a mocked transcript,
fabricated speedup, or a dashboard-only animation as proof.

Recommended sequence:

1. Live Mode for the opening: trigger or show the active incident room.
2. Verified Replay Mode for the fastest proof of `Verdict(CHALLENGE)` or
   `StructuredApproval(REJECTED)`.
3. Evidence page for the final chain and exact execution match.
4. Live paired benchmark for single-agent-vs-society quality
   (`artifacts/track3-live-paired/`: society 0.844 vs 0.763, 10 wins / 4 ties /
   6 losses; post-fix validation `artifacts/track3-live-paired-postfix/`:
   0.968 vs 0.843, 5 wins / 2 ties / 0 losses) plus the deterministic
   contract harness, with `/stats/runsummary` for same-family measured
   human-baseline speed only if configured.

## Final Under-Three-Minute Edit Recipe

Use one hero incident for depth and one low-risk contrast for breadth. Do not
try to show every scenario in full.

| Time | Shot | Judge proof |
|---|---|---|
| 0:00-0:15 | Landing page and dashboard headline | Real-world emergency change-control problem. |
| 0:15-0:35 | `/agent-skills`, Agents page, and agent network | Distinct Qwen-backed roles, MCP-style registry, task division. |
| 0:35-1:10 | Hero incident in the dashboard and incident room | Live or replayed role handoff sequence. |
| 1:10-1:40 | `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)` | Disagreement, negotiation, and revision. |
| 1:40-2:05 | Approval page with exact action envelope | Human governance and stale-action prevention. |
| 2:05-2:20 | Low-risk `PolicyAuthorization` contrast | Graduated autonomy: safe work does not need the human gate. |
| 2:20-2:40 | Evidence page with `ActionReceipt` | Exact-envelope execution and recovery verification. |
| 2:40-2:55 | Paired benchmark, `/stats/runsummary`, and final proof commands | Quality gain proof, optional `speedup_factor > 1`, Qwen smoke, read-only judge mode. |
| 2:55-3:00 | Closing caption only | "An agent society with deterministic safety rails." |

Recording rules:

- Use the hero incident for depth and one low-risk contrast for breadth.
- Record only the project UI, proof artifacts, and your own narration. Do not
  add copyrighted music, unrelated third-party logos, stock footage, or external
  media unless you have permission.
- If the live run stalls, switch to Verified Replay Mode and keep the real
  evidence URL visible on screen.
- Do not spend video time on all six chaos scenarios; put the six-scenario
  acceptance matrix in the README, judge packet, or slides.
- Do not spend more than three seconds on terminal output unless it is a final
  proof command.
- Keep the public read-only judge-mode proof in the final 15 seconds so the
  cost-control concern is answered before the video ends.

## 0:00-0:15 — Problem

Narration:

> Production incidents force teams to choose between speed and control. Fully
> manual response is slow. Fully autonomous response is risky. YITING sits in
> the middle: Qwen-backed agents can investigate and plan, but the Gateway keeps
> evidence, authorization, and execution under deterministic control.

Show:

- public landing page,
- dashboard open on Operations Overview,
- agent status online.

## 0:15-0:35 — Agent Society

Narration:

> The system runs on Alibaba Cloud ECS. The public entrypoint is Caddy. The
> Gateway owns the incident room, the evidence ledger, nonce binding, and state
> transitions. Five Qwen-backed reasoning agents coordinate through the room:
> Triage, Diagnosis, Safety Reviewer, Commander, and Operator. This is the Track
> 3 claim: distinct agents decompose the task, hand work to the next specialist,
> and leave a verifiable trace of each role assignment.

Show:

- dashboard agent network,
- **Custom agent skills** panel on the Agents page,
- `docs/ARCHITECTURE.md` diagram or dashboard topology,
- Qwen model labels in the agent cards.

Call out:

- `/agent-skills` is a public MCP-style registry and review manifest for the
  seven custom skill contracts: stable tool name, input schema, output schema,
  Qwen prompt boundary, deterministic guardrail, evidence artifact, Qwen Cloud use, Track 3 proof category, and judge demo cue for each role.
- Say clearly: this is an inspectable custom-skill contract manifest, not a
  network MCP server.
- the evidence export later shows `collaboration.role_sequence`, the concrete
  proof of task decomposition.

## 0:35-1:10 — High-Risk Incident And Disagreement

Narration:

> I trigger a high-risk suspicious deploy. The Recorder seals the AlertCard.
> Triage routes it. Diagnosis gathers evidence. Safety Reviewer can challenge
> weak conclusions. Commander creates a plan, but because the action is high
> risk, nothing executes until the human gate is satisfied.

Show:

- ChaosPanel trigger for suspicious deploy,
- incident room messages/cards appearing,
- state moving toward `PLANNED`,
- a `Verdict(CHALLENGE)` card if the live run produces one, or the Evidence
  page from a certified challenge run,
- approval page with exact action envelope.

## 1:10-1:40 — Human Negotiation And Conflict Resolution

Narration:

> The human can approve, reject with instructions, or declare false alarm. The
> human decision is not a side note: it is sealed as its own card in the same
> evidence chain. A rejection is a negotiation event: Commander must revise the
> plan, bind a new nonce, and the Operator still cannot execute stale actions.

Show one of:

- reject once, show `StructuredApproval(REJECTED)`,
- show the revised `ResponsePlan(rev=2)`,
- approve the revised plan and let Operator execute.

Call out:

- new nonce on revised plan,
- action envelope must match exactly,
- Operator waits for authorization.
- final `ActionReceipt` matches the approved envelope, proving execution
  conflict resolution.

## 1:40-2:05 — Approval And Exact Execution

Narration:

> The approval page shows the exact action envelope. After approval, Operator
> executes only that envelope, verifies recovery, and submits an ActionReceipt.

Show:

- approval page with action id, target, and parameters,
- final state moving to `EXECUTED`,
- `ActionReceipt` matching the approved envelope.

## 2:05-2:20 — Low-Risk Contrast

Narration:

> For low-risk actions, YITING can use policy authorization. This proves the
> system is not just a manual approval form: it supports graduated autonomy.

Show:

- certificate-expiry or other low-risk scenario,
- `PolicyAuthorization` card,
- no human approval step,
- `ActionReceipt`.

## 2:20-2:40 — Evidence Verification

Narration:

> Every accepted card is canonical JSON. The Gateway stores the hash and links
> it to the previous card. The browser can verify the chain without trusting the
> agents.

Show:

- Evidence page,
- `chain_valid: true`,
- card sequence and hashes.
- Runs & Replay scorecard with handoffs, challenges, human decisions, and
  paired quality gain evidence.
- `/stats/runsummary` shows `speedup_factor > 1` only after the measured
  same-family manual (human) timing baseline is configured.

## 2:40-2:55 — Closing

Narration:

> YITING demonstrates an agent society where Qwen models collaborate, challenge,
> and plan, while deterministic controls keep execution auditable and safe. The
> important measurement is not just that it worked: the final proof command
> compares the hosted run against a measured human baseline, and the
> committed live paired benchmark scores the society against a real
> single-agent baseline — one Qwen model given the complete task — on the
> same incidents: ten wins, four ties, six losses pre-fix, and five wins,
> two ties, zero losses after the routing fix the benchmark itself uncovered.

Show:

- final dashboard state,
- Alibaba deployment proof clip or terminal command:

```bash
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
python scripts/verify_deployment.py \
  --public-url "https://yiting.47.84.232.193.sslip.io" \
  --incident-id "<hero-incident-id>" \
  --require-speedup \
  --output-json artifacts/deployment-verification.json
```

## Must-Capture Judge Shots

These five shots are the minimum viable video for Track 3:

1. `/agent-skills` or the Agents page showing distinct inspectable MCP-style role contracts.
2. Evidence page showing `collaboration.role_sequence`.
3. Hero evidence showing `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)`.
4. `ActionReceipt` showing exact approved-envelope execution.
5. Live paired benchmark artifacts showing single-agent-vs-society quality
   (0.844 vs 0.763 pre-fix; 0.968 vs 0.843 post-fix, corrections logged), with
   `/stats/runsummary` showing `speedup_factor > 1` only for the separate hosted
   timing proof (measured human baseline).

## Scoreboard Overlay

If you add captions or quick lower-third labels, use these exact proof labels:

| Video proof beat | Score criterion |
|---|---|
| Inspectable MCP-style custom skill contracts and Qwen model labels | Innovation & AI Creativity — 30% |
| Gateway-owned state, nonce gate, evidence hashes, exact envelope | Technical Depth & Engineering — 30% |
| High-risk human gate, low-risk policy authorization, false-alarm handling | Problem Value & Impact — 25% |
| Dashboard replay, evidence export, final proof commands | Presentation & Documentation — 15% |
| `Verdict(CHALLENGE)` / `StructuredApproval(REJECTED)` | Track 3 disagreement and negotiation |
| Live paired benchmark quality gains (10W/4T/6L pre-fix; 5W/2T/0L post-fix) plus optional `speedup_factor > 1` | Track 3 measurable efficiency gain |

## Recording Checklist

- `python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json` passes.
- `python scripts/verify_deployment.py --public-url "https://yiting.47.84.232.193.sslip.io" --incident-id "<hero-incident-id>" --output-json artifacts/deployment-verification.json` passes.
- Final Track 3 proof run uses `--require-speedup` after the same measured
  baseline is available in both places: `MANUAL_BASELINE_SECS` on the hosted
  Gateway for `/stats/runsummary`, and `MEASURED_SINGLE_AGENT_SECS` when you
  run `make submission-proof`.
- Video shows the five **Must-Capture Judge Shots** above.
- Video contains no copyrighted music, unrelated third-party trademarks, stock
  footage, or external media.
- Dashboard is in live mode for the recording.
- Agents page shows the **Custom agent skills** panel and `/agent-skills`
  responds with seven skills.
- After recording, compile the dashboard in judge mode, remove `YITING_LIVE_CHAOS`
  from the dashboard environment, and run the final proof with
  `--require-public-read-only` so public visitors cannot trigger paid actions.
- Run `make submission-finalize DOMAIN=... REPO_URL=... VIDEO_URL=... DEPLOYMENT_PROOF_VIDEO_URL=... HERO_INCIDENT_ID=...`
  to embed the final public video, deployment URL, and hero evidence links.
- Export one evidence chain URL for the submission text.
