# Live paired eval — single Qwen agent vs deployed society (Track 3)

Run date: 2026-07-17 (UTC). Live Qwen calls on the deployed Alibaba ECS stack;
nothing in this directory is simulated or deterministic.

## Result (20 paired incidents, frozen rubric, spec-corrected chain scoring)

| Metric | Single agent | Society |
|---|---|---|
| Mean final score | 0.7625 | **0.8438** |
| Pairs won / tied / lost (society view) | — | **10 / 4 / 6** |
| Success count (rubric threshold) | 5 | **8** |
| Mean finding recall | 0.875 | **1.0** |
| Mean risk recall | 0.925 | **1.0** |
| Unsupported claims (total) | 9 | 11 |
| Evidence chain live-verified | n/a (no sealed chain) | **20/20 `chain_valid: true`** |
| Mean tokens per incident | 2,141 | 5,366 (~2.5×) |

Both arms: same live incidents, same evidence bytes, same qwen3.7-plus
diagnosis tier, same frozen rubric and ground truth
(`evals/track3_live_paired_scenarios.json`). The solo agent receives the
complete task, not a weakened prompt. Society is scored at the PLANNED state —
the human approval gate is never bypassed.

## Honest readout — including where the society loses

* Spec-corrected per family (society wins/ties/losses): deploy 3/0/1,
  sentry 2/1/0, cert 3/0/0, db 2/1/0, memory 0/2/1, latency 0/0/4 — with
  perfect society finding/risk recall across all 20 (v1 scored surface).
* Every society loss but one shares a single signature: the runbook selector
  routed to `enable_circuit_breaker` where the ground-truth policy output is
  `scale_up`/`restart_service` (all 4 latency pairs + 1 memory pair; the
  remaining deploy loss is a 0.875-vs-0.9 recall margin).
* Root cause (verified in code, `agents/commander/__init__.py`,
  `select_runbook()`): the `dependency/upstream` keyword rule outranks the
  `scale/capacity/load` rule, and the diagnosis agent's prose for
  saturation-family faults tends to include dependency-chain narration. The
  society's 11 unsupported claims cluster in these same rows — one defect, two
  symptoms. This is a real product finding this eval surfaced. **The fix was
  implemented, deployed, and validated live the same day: see
  `artifacts/track3-live-paired-postfix/` (society 0.968 vs solo 0.843:
  5 wins / 2 ties / 0 losses across five validated families, 0 society
  unsupported claims, deployed build `yiting-python:routingfix3-20260717`).** This pre-fix artifact remains
  frozen as-is.

## Files

* `summary.json` — aggregate means and fairness controls.
* `rows.json` / `rows.jsonl` — canonical 20 pairs (one per scenario id).
* `rows_full_history.jsonl` — append-only history (22 rows) including the two
  superseded rows described below. Nothing was deleted.
* `rows_pilot_invalid.jsonl` — 3 rows from an aborted pilot batch whose
  society arm never ran (harness defect, zero society tokens). Archived, never
  counted.
* `solo_raw.jsonl` — raw solo model responses (scenario ids L3-011..L3-020;
  earlier batches predate the raw-dump hook — see limitations). Society raw
  output is the sealed card chain retained in the gateway DB snapshots.

## Post-run corrections (also logged in the dataset)

1. **Chain scoring implemented against spec, then corrected.** The runner
   scored the solo arm's evidence_chain at 0.55 (the deterministic harness's
   constant); this dataset's scoring_method declares solo = 1.0 so the
   dimension advantages neither arm. All rows here are rescored to the spec
   (+0.045 per solo final_score). Under the original mis-implementation the
   split read 15/5; the spec-correct split is 10 wins / 4 ties / 6 losses.
2. **The declared equal token cap was never enforced.** fairness_controls
   promised a 4,000-token aggregate cap per arm per incident; no cap was
   enforced on either arm. The declaration is replaced by the truthful
   control (usage measured and published per row: society ≈5.2–8.2k, solo
   ≈1.4–2.8k). This comparison is therefore NOT equal-budget; the society's
   ~2.5× token cost is part of the published result.
3. **Action-match is policy agreement, by declared design.** expected_action
   is the system's own select_runbook() output; the society's commander runs
   that same policy over its diagnosis, the solo agent must infer it. This
   measures agreement with the system's remediation policy (25% weight), not
   independently adjudicated correctness.
4. **Keyword detection has no negation handling.** Findings, risks, and decoy
   claims are substring matches; exculpatory phrasing (e.g. a solo response
   noting a deploy PREDATES the errors) can still trigger a decoy hit.
   Unsupported-claim counts are indicative, not adjudicated.

## Disclosed limitations and incidents

1. **Two superseded rows (L3-011, L3-012).** During batches 0–3 a runaway
   duplicate of the eval harness (operator error, two zombie processes from an
   earlier failed launch) flooded the stack with phantom incidents. Agent
   room-polling degraded until two society arms starved before planning
   (states DETECTED/TRIAGED at the 480s deadline, ≈0 tokens). Invalidation
   rule, applied mechanically: society state never reached a plan AND society
   tokens ≈ 0. Both scenarios were rerun on a restored-clean stack. The rerun
   LOWERED the society's L3-011 score (0.75 → 0.625) — reruns replaced invalid
   measurements, not unfavorable ones.
2. **Society token counts are unmeasured for L3-001..L3-006** (recorded as 0
   or a placeholder in those rows): those batches ran from a container whose
   usage-meter file was not the shared volume. Solo tokens for those rows are
   exact. The society mean-token figure in `summary.json` is computed over the
   rows with real accounting.
3. **Solo raw responses for L3-001..L3-010 were not captured** (the raw-dump
   hook landed mid-campaign). Scores, actions, and token deltas for those rows
   were recorded at run time in the rows files.
4. **Unsupported-claim surface asymmetry.** The society's scored text includes
   its full deliberation (room messages + all cards), while the solo text is
   one JSON response. A hypothesis mentioned-and-rejected in deliberation can
   match a decoy keyword. The count is reported as-is under the frozen rubric;
   per-card attribution is part of the follow-up analysis.
