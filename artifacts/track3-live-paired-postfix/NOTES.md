# Post-fix live validation — society vs single agent (Track 3 follow-up)

Follow-up to the frozen pre-fix run in `artifacts/track3-live-paired/`
(society 0.8438 vs solo 0.7625: 10 wins / 4 ties / 6 losses). That run surfaced a real
routing defect; this artifact documents the fix and the live validation of
the FIXED, DEPLOYED build. Run date: 2026-07-17 (UTC), same frozen dataset,
rubric, and ground truth.

## Result (7 pairs, 5 of 6 fault families, live Qwen, deployed stack,
spec-corrected chain scoring)

| Metric | Single agent | Society |
|---|---|---|
| Mean final score | 0.843 | **0.968** |
| Pairs won / tied / lost (society view) | — | **5 / 2 / 0** |
| Success count | 2 | **7** |
| Unsupported claims (no-negation keyword detector; indicative) | 4 | **0** |
| Evidence chain live-verified | n/a | **7/7 `chain_valid: true`** |
| Mean tokens per incident | 2,441 | 6,227 (~2.6×, published) |

The two ties are the latency pairs (both arms chose scale_up with full
recall; the society's margin elsewhere comes from decoy discipline and
policy-consistent actions). Chain scoring follows the dataset spec (solo =
1.0; the initial 0.55 mis-implementation is corrected here and in the
dataset's post_run_corrections). The declared-but-unenforced equal token cap
correction also applies: this is not an equal-budget comparison (~2.6×
society cost, published). Pre/post unsupported-claim counts are NOT directly
comparable across detector versions; within this artifact a single detector
(v3) scored both arms. At least one solo decoy hit is exculpatory phrasing
(the L3-011 response notes the deploy PREDATES the errors), so solo's 4 may
overcount — the detector has no negation handling.

Society raw provenance: the sealed card chains of all validation incidents
are preserved in the VM's dated DB snapshots
(/opt/backups/yiting-eval/yiting-data-mid-eval-*.tgz); rows do not embed
incident IDs (runner limitation, noted for v2 of the harness).

Cert was excluded from validation because P3 cert incidents auto-execute via
the low-risk PolicyAuthorization path (adding executed incidents to public
stats); cert scored 3/3 at 1.0 for the society in the frozen pre-fix run.

## What was fixed (product, not ruler)

1. **Diagnosis evidence branching** (`agents/diagnosis/__init__.py`): the
   deterministic baseline branched on substrings of its own composed text;
   the literal field name `latency_p99=` appears in every metric-anomaly
   string, so the "latency" branch injected a circuit-breaker recommendation
   for latency, db, and memory families alike — anchoring the Qwen refinement
   AND keyword-routing the commander to RB-004. Replaced with structured
   signal checks (saturation/rate-limit/pool thresholds → scale; heap/GC →
   restart; deploy correlation → rollback). The assessment now also
   enumerates the verified signals by name (proper incident documentation).
2. **Runbook selection** (`agents/commander/__init__.py`, `select_runbook`):
   bare "deployment"/"dependency"/"upstream" mentions no longer route
   remediation runbooks; capacity scaling outranks circuit breaking when both
   are described; a leaking process (heap/OOM evidence + restart intent)
   restarts rather than scales — scaling multiplies leaking replicas.
3. **Diagnosis prompt**: names the primary failing signal, forbids dependency
   attribution unless the evidence shows a failing dependency, prefers the
   alert's remediation hint when consistent with evidence.

Regression pins: `tests/test_runbook_routing_fix.py` (13 tests, exact losing
phrasings); full suite 705 green. Deployed as
`yiting-python:routingfix3-20260717` — the build serving the public stack.
(Count note, 2026-07-18: 705 was the suite size at that deployment; four
live-eval spec-guard tests added afterward — `tests/test_live_eval_spec.py` —
bring the current verification gate to 709.)

## Detector lineage (all disclosed, applied identically to both arms)

* **v1** (frozen run): society text = incident + room messages + evidence
  exports. Kept as published.
* **v2**: strips the literal `"rollback_action": "..."` envelope schema field
  before decoy scanning — its KEY name matched the "rollback" decoy keyword
  structurally in every sealed plan (proven false positive; the only decoy
  match in INC-CHAOS-E7CED6's cards was this field).
* **v3** (this artifact): both arms scored on their ASSERTIONS only — the
  society on prose the agents authored in sealed non-Alert cards, the solo
  agent on its JSON answer. Raw victim evidence is input, not assertion:
  scoring it as society text both credited un-asserted findings and charged
  un-made claims (e.g. the db family's "deploy" decoy matched embedded deploy
  evidence).

## Run-integrity disclosures

* Environment stalls (society state stuck at DETECTED with ≈0 tokens at the
  480s deadline) occurred when accumulated PLANNED eval incidents from
  earlier validation cycles congested agent room-polling. Stalled rows were
  mechanically invalidated (rule: no plan state AND ≈0 society tokens) and
  rerun on a restored-clean stack; `rows.jsonl` keeps one row per scenario
  from the final uniform build. Intermediate runs (detector v1/v2 surfaces,
  earlier builds) are preserved in the session's run logs and host backups.
* Sentry action choice showed genuine run-to-run variance across the night's
  runs (restart-then-scale vs scale phrasing); the final row reflects the
  deployed build's live behavior, not a selected best-of.
* Solo raw responses: `solo_raw.jsonl`. Society raw output is the sealed card
  chain of each `INC-CHAOS-*` validation incident.
