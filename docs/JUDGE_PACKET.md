# Judge Packet

This is the shortest path through YITING for a reviewer. It is designed to make
the Track 3 Agent Society proof visible without reading the whole repository.

## What To Open First

1. **Landing page** — project pitch, architecture summary, and demo video.
2. **Dashboard** — live incident states, agent status, run metrics, and replay.
3. **Agents page** — custom agent skill contracts from `/agent-skills`.
4. **Evidence page** — `/evidence/{incident_id}` with `chain_valid: true`.
5. **Runs page** — `/stats/runsummary` metrics for handoffs, challenges, human
   decisions, recovery verification, and measured same-family timing proof.
6. **Engineering proof matrix** — `docs/ENGINEERING_PROOF.md` maps the
   non-trivial mechanisms to code, tests, and public proof endpoints.
7. **Track 3 scorecard** — `docs/TRACK3_SCORECARD.md` gives the 90-second route
   through task division, negotiation, execution conflicts, and measured
   quality/timing proof.
8. **Third-party compliance notes** — `docs/THIRD_PARTY_COMPLIANCE.md` documents
   model/cloud authorization, dependency manifests, synthetic data, and
   demo-media hygiene.

## Track Choice In One Sentence

The submission form should be evaluated as Track 3: Agent Society.

YITING has a Track 4 outcome because incidents can reach verified remediation,
but it is submitted to **Track 3: Agent Society** because the judged behavior is
the collaboration itself: specialized Qwen agents divide work, dispute weak
reasoning, negotiate revisions with a human, and resolve execution conflicts
before any action touches production.

## Judge Objection Quick Answers

| Likely question | Short answer |
|---|---|
| Is this really Track 3, not Track 4? | Yes. Track 4 is the operational outcome. The submitted proof is Track 3: role handoffs, disagreement, human negotiation, exact-envelope execution conflict control, paired quality gains over one agent, and optional measured same-family timing proof. |
| Is `/agent-skills` a real MCP server? | The manifest route itself is an inspectable MCP-style registry and review manifest, not a network MCP server. The same seven contracts ARE served by a real read-only network MCP server at `POST /mcp` (`gateway/mcp.py` — JSON-RPC 2.0 `initialize`, `tools/list`, `tools/call`; no tool can mutate state or spend tokens). The packet states the split explicitly so the Qwen custom-skill proof is honest. |
| Is the demo mocked? | No. The final packet requires a hosted hero `/evidence/{incident_id}` export, `chain_valid: true`, real Qwen smoke proof, source package, deployment verification, and a public read-only replay. |
| Are third-party APIs, SDKs, and media authorized? | The final packet includes `docs/THIRD_PARTY_COMPLIANCE.md`: Qwen and Alibaba access use entrant-provided keys, dependencies are declared in manifests, incident data is synthetic, and the demo should use project UI without copyrighted music or unrelated external media. |
| Is speedup invented? | No. The deterministic paired benchmark does not claim speed improvement; it records that the society is slower but higher quality. A speed claim is only accepted when `scripts/track3_baseline.py` records a same-family measured baseline and deployment verification requires `speedup_factor > 1`. |
| Can public visitors burn credits? | No in judge mode. Public judge mode is read-only: evidence, dashboard replay, and docs are public while chaos, approvals, and mutation routes are disabled or rejected. |
| Can agents execute unsafe or stale actions? | The Operator uses exact-envelope execution. Nonce-bound authorization, Gateway state transitions, recovery verification, and duplicate-suppression guards prevent stale or unapproved actions from becoming valid evidence. |

## Hero Evidence Links

Fill these after the final hosted run with `make submission-finalize` using
`DOMAIN`, `REPO_URL`, `VIDEO_URL`, `DEPLOYMENT_PROOF_VIDEO_URL`, and
`HERO_INCIDENT_ID`.

| Item | Final value |
|---|---|
| Hero incident | Pending final hosted hero run and human approval-password step. |
| Evidence export | Pending final hosted hero run; `make submission-finalize` writes the public URL. |
| Run summary | Pending final hosted hero run; `make submission-finalize` writes the public URL. |
| Dashboard replay | Pending final hosted hero run; `make submission-finalize` writes the public URL. |

## Track 3 Proof Checklist

| Track 3 requirement | Where to verify |
|---|---|
| Distinct agent capabilities | `/agent-skills` and the Agents page show each role's inspectable MCP-style tool contract, Qwen prompt contract, input/output schema, guardrail, evidence artifact, Qwen Cloud use, Track 3 proof category, and judge demo cue. The manifest is a review document, not a network MCP server — the real read-only MCP server serving the same contracts is `POST /mcp`. |
| Task decomposition and role assignment | `/evidence/{incident_id}.collaboration.role_sequence` shows the published role sequence across the incident. |
| Dialogue and negotiation | Evidence chains can include `Verdict(CHALLENGE)` and `StructuredApproval(REJECTED)` cards. |
| Disagreement resolution | A challenge forces Diagnosis to revise; a human rejection forces Commander to revise and bind a new nonce. |
| Execution conflict resolution | `/evidence/{incident_id}.collaboration.execution_conflict_control.exact_match` proves the Operator executed only the approved envelope. |
| Measured efficiency gain | `artifacts/track3-live-paired/` is a live paired benchmark on the deployed stack: 20 real incidents, each run through both a single Qwen agent (same tier, complete task, identical evidence) and the deployed society — society 0.844 vs 0.763 (10 wins / 4 ties / 6 losses), 100% finding/risk recall (solo 87.5%/92.5%), all 20 plans chain-verified, ~2.5× token cost published (not equal-budget; corrections logged in the artifact). The surfaced routing defect was fixed and validated live the same day (`artifacts/track3-live-paired-postfix/`: 0.968 vs 0.843, 5 wins / 2 ties / 0 losses, five families). `artifacts/track3-paired-benchmark.json` is the deterministic society-contract regression harness (reproducible contract validation, not a live model measurement): the society contract records higher success, score, risk detection, unsupported-claim reduction, and quality per token than a solo baseline. The live efficiency evidence is `scripts/track3_baseline.py`'s measured same-family timing artifact (a measured human-baseline run), and `scripts/verify_deployment.py --require-speedup` fails if the hosted run lacks `speedup_factor > 1`. |

## Scoring Map

| Criterion | Best evidence |
|---|---|
| Innovation & AI Creativity | Qwen-backed role society, custom skill registry, challenge loop, three-way human decisions. |
| Technical Depth & Engineering | Gateway-owned state machine, SHA-256 evidence chain, nonce-bound approvals, exact-envelope execution, recovery verification. |
| Problem Value & Impact | Emergency production changes need reliable remediation with human governance, audit-ready proof, and measured timing only when the hosted baseline supports it. |
| Presentation & Documentation | Landing page, dashboard, evidence export, architecture doc, demo script, and this packet. |

## Five-Minute Scoring Route

If time is short, score the project in this order:

| Score area | Open this | What it proves |
|---|---|---|
| Stage One viability | Landing page, `/agent-skills`, and `docs/ALIBABA_CLOUD_PROOF.md` | The project fits Track 3, uses Qwen Cloud APIs, and has an Alibaba Cloud deployment path. |
| Innovation & AI Creativity — 30% | Agents page plus a hero `/evidence/{incident_id}` export | Inspectable MCP-style custom skill contracts, role-specific Qwen prompts, sealed `Verdict(CHALLENGE)`, and three-way human decisions. |
| Technical Depth & Engineering — 30% | `/evidence/{incident_id}`, `docs/ARCHITECTURE.md`, and `docs/ENGINEERING_PROOF.md` | Hash-chain verification, nonce-bound authorization, exact-envelope execution conflict control, durable duplicate suppression, and recovery verification. |
| Problem Value & Impact — 25% | Runs page, `/stats/runsummary`, and `artifacts/track3-paired-benchmark.json` | Real emergency-change-control pain, false-alarm handling, human governance, paired quality gains over a single agent, and measured hosted timing only when the same-family baseline supports it. |
| Presentation & Documentation — 15% | Demo video, dashboard replay, `docs/DEMO_SCRIPT.md`, and `docs/SUBMISSION_FORM.md` | The key logic is visible in the browser and the public submission copy is ready. |
| Blog Post Prize | `docs/BLOG_POST.md` | Long-form explanation of the agent-society design, Qwen Cloud fit, governance model, and impact narrative. |
| Track 3 quick score | `docs/TRACK3_SCORECARD.md` | One-page mapping from the published Track 3 wording to exact YITING proof endpoints and artifacts. |

## Final Proof Commands

Run these after deployment, baseline measurement, and video recording:

```bash
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```

The selected hero incident must itself be the `EXECUTED` incident named in the
final proof command, must include an `ActionReceipt`, and must contain either a
sealed `Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)`. Aggregate
run-summary disagreement is still reported, but the hero evidence link should
be enough for a judge to see Track 3 negotiation without opening a second
incident.

Keep these generated files with the final evidence packet:

- `artifacts/qwen-smoke.json`
- `artifacts/track3-baseline.json`
- `artifacts/track3-paired-benchmark.json`
- `artifacts/deployment-verification.json`
- `artifacts/hero-evidence.json`, the exported hero incident JSON from `/evidence/{incident_id}`
- `artifacts/final-proof-index.md`
- the final source package from `dist/yiting-submission-source.zip`

The paired benchmark is a reproducible design-validation harness that isolates
the scoring rubric from model variance — included as a design-integrity proof,
not as an empirical live-model benchmark. The artifact is self-checking for
quality claims: its `claims_not_made` field records that it does not claim
speed improvement, statistical significance, or live Qwen quality measurement
in deterministic mode. The baseline artifact is self-checking
for hosted timing claims: it records the incident family, matched same-family
run IDs, speedup formula, terminal criterion, and positive Track 3 counters for
handoffs, challenge/revision, human intervention, and recovery verification.
The final proof index is the one-page attachment that ties those artifacts to
the hero evidence chain and public read-only proof.

For form copy, use `docs/SUBMISSION_FORM.md`.

Before submitting, run the ordered checklist in
`docs/FINAL_SUBMISSION_CHECKLIST.md`.

## One-Line Pitch

YITING is a Qwen-powered incident council: specialized agents decompose an
incident, challenge weak reasoning, negotiate with a human gate, and execute
only the exact approved remediation while sealing every decision into a
tamper-evident chain.
