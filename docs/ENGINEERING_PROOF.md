# Engineering Proof Matrix

This document is the fast path for judging **Technical Depth & Engineering**
and the algorithm/engineering portion of **Innovation & AI Creativity**.

YITING is not just a set of prompts. The Qwen-backed agents reason inside a
deterministic control plane with explicit invariants, measurable outputs, and
tests that exercise the failure modes.

## Core Mechanisms

| Mechanism | Why it matters | Code | Verification |
|---|---|---|---|
| Canonical evidence sealing | Every accepted decision becomes canonical JSON with `sha256(card_json)` and a previous-card link. | `shared/integrity.py` | `tests/test_state_paths.py`, `tests/test_submission_client.py`, `/evidence/{incident_id}` |
| Gateway-owned state machine | Agents can propose, but only the Gateway advances incident state. | `gateway/routes/submission.py`, `gateway/routes/authorization.py`, `gateway/routes/nonce.py` | `tests/test_state_paths.py`, `tests/test_authorization.py`, `tests/test_nonce_consumption.py` |
| Nonce-bound human authority | Human decisions bind incident, plan hash, action hash, revision, expiry, and approver. | `shared/approval.py`, `gateway/routes/approve_ui.py`, `gateway/routes/nonce.py` | `tests/test_approve_ui.py`, `tests/test_nonce_hash_contracts.py`, `tests/test_c11_behavioral.py` |
| Exact-envelope execution | Operator cannot execute a changed action, target, count, or parameter set. | `agents/operator/__init__.py`, `victim-app/app.py` | `tests/test_operator_preprocessor.py`, `tests/test_council_fixes.py`, `/evidence/{incident_id}.collaboration.execution_conflict_control` |
| Durable duplicate suppression | Remediation requests use canonical execution keys so retries do not mutate state twice. | `victim-app/app.py` | `tests/test_replay_guard.py`, `tests/test_council_fixes.py` |
| Replay and stale-message control | Agents skip stale room cards and chatter after reconnects, reducing wasted model calls while failing open to Gateway checks. | `shared/replay_guard.py` | `tests/test_replay_guard.py`, `tests/test_post_handoff_silence.py` |
| Challenge and revision loops | Disagreements are sealed transitions, not comments. They force new assessments or plans. | `agents/diagnosis/__init__.py`, `agents/safety_reviewer/__init__.py`, `agents/commander/__init__.py` | `tests/test_diagnosis.py`, `tests/test_three_way_decision.py`, `/evidence/{incident_id}` |
| Bounded suppression learning | False alarms can create bounded rules, but P1/security signals bypass suppression. | `gateway/app.py`, `agents/triage/__init__.py` | `tests/test_heartbeat_suppression.py`, `/suppression-rules` |
| Publication verification and outbox checks | The system refuses silent success when required room publication proof is missing. | `gateway/routes/submission.py`, `gateway/routes/nonce.py` | `tests/test_council_r5.py`, `tests/test_council_r6.py`, `scripts/verify_deployment.py` |
| Clean submission packaging | The source package records the Git commit and clean-tree status before final submission. | `scripts/package_submission.py`, `scripts/submission_status.py`, `scripts/submission_audit.py` | `tests/test_package_submission.py`, `tests/test_submission_status.py`, `tests/test_submission_audit.py` |

## Performance And Cost Controls

YITING optimizes the expensive part of the system: model reasoning calls.

| Control | Effect | Proof |
|---|---|---|
| Deterministic preprocessor gates | Rejects wrong sender, wrong state, stale card, replay, or malformed approval before Qwen is called. | `tests/test_triage.py`, `tests/test_operator_preprocessor.py`, `tests/test_replay_guard.py` |
| Same-room handoff state | Agents process only the card type they own and silently consume unsupported cards. | `tests/test_post_handoff_silence.py`, `tests/test_agent_skills.py` |
| Bounded replay checks | Restarted agents avoid reprocessing old incident history while Gateway remains the final authority. | `shared/replay_guard.py`, `tests/test_replay_guard.py` |
| Public judge mode | The dashboard can expose evidence and replay without exposing paid or mutating actions. | `docs/FINAL_SUBMISSION_CHECKLIST.md`, `scripts/submission_audit.py` |
| Measured baseline proof | `track3-baseline.json` records the same incident family, formula, terminal criterion, Track 3 counters, and matched run IDs when `/stats/runsummary` exposes family-tagged runs. | `scripts/track3_baseline.py`, `tests/test_track3_baseline.py` |
| Paired reproducible benchmark | `track3-paired-benchmark.json` compares `single_agent` and `full_yiting_society` on the same 20 fixed scenarios, same rubric, same model identity, and token-normalized metrics without claiming speed improvement. | `scripts/track3_paired_benchmark.py`, `evals/track3_paired_scenarios.json`, `tests/test_track3_paired_benchmark.py` |

## Failure-Mode Posture

| Failure | System behavior |
|---|---|
| Wrong or replayed nonce | Reject before state advance. |
| Plan superseded after human review | Reject because plan/action hashes no longer match. |
| Agent attempts stale or modified action | Reject before side effects. |
| Recovery check fails | No successful `ActionReceipt` is certified. |
| Evidence card is edited after sealing | `/evidence/{incident_id}` reports an invalid chain. |
| Source package built while dirty | `submission_status.py` reports `source_package: NOT CURRENT`. |

## What Judges Should Open

1. `/agent-skills` for the MCP-style skill contracts.
2. `/evidence/{incident_id}` for the hash chain, collaboration block, and exact
   execution conflict proof.
3. `/stats/runsummary` for handoffs, challenges, human interventions, recovery
   verification, and measured speedup.
4. `artifacts/deployment-verification.json` for hosted checks.
5. `artifacts/track3-baseline.json` for the same-family baseline comparison.
6. `artifacts/track3-paired-benchmark.json` plus raw JSON/CSV for the
   reproducible single-agent versus society benchmark.
