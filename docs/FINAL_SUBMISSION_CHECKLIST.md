# Final Submission Checklist

Use this checklist for the final recording and submission handoff. It is
intentionally strict: do not submit until every command here either passes or
produces the expected final artifact.

Final implementation approval depends on every local, hosted proof, link,
video, package, and submission-portal acceptance gate passing. A deployment that starts once is not submission-complete.

## 0. Final-Hour Order

Follow this sequence so the video captures the real frontend flow before the
hosted app is locked into public read-only judge mode:

1. Push and configure the public repository URL.
2. Deploy private recording mode with live controls enabled
   (`YITING_LIVE_CHAOS=1`, `NEXT_PUBLIC_YITING_MODE=live`).
3. Record the browser dashboard flow, trigger the live incident from the
   frontend, capture the approval page, and choose the hero incident.
   Use only project UI/proof artifacts and your own narration; do not add
   copyrighted music, unrelated third-party logos, stock footage, or external
   media.
4. Switch the hosted dashboard to public read-only judge mode before public
   sharing.
5. Run `make submission-finalize ...` with the final domain, repository, demo
   video, separate deployment-proof video, and hero incident values.
6. Commit finalized public artifacts, run `make submission-ready`, and push the
   final commit.
7. Run `make submission-proof ...` against the hosted read-only deployment.
8. Commit the generated proof artifacts, run `make submission-package`, and
   push the final proof commit.
9. Run the strict audit and resolve every remaining issue before submission.

## 1. Freeze The Hero Evidence

Record these values from the best hosted run:

- hero incident id
- final state is `EXECUTED`
- `chain_valid: true` from `/evidence/{incident_id}`
- total cards
- card sequence includes `ActionReceipt`
- `collaboration.role_sequence` includes Recorder, Triage, Diagnosis, Safety
  Reviewer, Commander, and Operator
- the hero evidence itself includes either `Verdict(CHALLENGE)` or
  `StructuredApproval(REJECTED)` so the selected incident proves Track 3
  disagreement, not only the aggregate run summary
- `collaboration.execution_conflict_control.exact_match: true`
- the overall run set has at least one disagreement event (Safety Reviewer
  challenge or human rejection/revision) and one human intervention in
  `/stats/runsummary`
- paired benchmark quality gains from `artifacts/track3-paired-benchmark.json`
- optional `speedup_factor` from `/stats/runsummary` only when the same-family
  hosted timing proof is configured
- measured single-agent/manual baseline seconds
- hero `incident_family` from `/evidence/{incident_id}` matching
  `artifacts/track3-baseline.json.baseline.incident_family`

Keep the exported hero incident JSON with the final proof packet.

## 2. Finalize Public Links

Patch README, the landing page, the judge packet, the submission form, and the
install guide with the final public values:

Use a public YouTube, Vimeo, or Facebook Video demo URL for `VIDEO_URL`; the
placeholder below is only an example format. Use a separate public YouTube,
Vimeo, or Facebook Video Alibaba deployment-proof URL for
`DEPLOYMENT_PROOF_VIDEO_URL`.

```bash
make submission-finalize \
  DOMAIN="https://yiting.47.84.232.193.sslip.io" \
  REPO_URL="https://github.com/<owner>/<repo>" \
  VIDEO_URL="https://youtu.be/<video-id>" \
  DEPLOYMENT_PROOF_VIDEO_URL="https://youtu.be/<deployment-proof-video-id>" \
  HERO_INCIDENT_ID="<hero-incident-id>"
```

Review the diff before committing:

```bash
python scripts/submission_links.py \
  --repository-url "https://github.com/<owner>/yiting" \
  --live-application-url "https://yiting.47.84.232.193.sslip.io" \
  --demo-video-url "https://youtu.be/<video-id>" \
  --deployment-proof-video-url "https://youtu.be/<deployment-proof-video-id>" \
  --check-reachable

git diff -- README.md landing/index.html docs/JUDGE_PACKET.md docs/SUBMISSION_FORM.md docs/INSTALL_AND_RUN.md
git add README.md landing/index.html docs/JUDGE_PACKET.md docs/SUBMISSION_FORM.md docs/INSTALL_AND_RUN.md artifacts/live/backup-restore.json artifacts/live/ecs-ops-acceptance.json artifacts/live/app-restart-resilience.json artifacts/live/uptime-monitoring.json artifacts/live/submission-links.json
git commit -m "docs: finalize public submission links"
```

## 3. Run Local Readiness

```bash
make submission-ready
make docker-build-images
make docker-smoke-images
```

Expected result:

- tests pass
- dashboard production build passes
- Python, victim, and dashboard container image smoke checks pass
- local certification shows policy and human paths reach `EXECUTED`
- source package is current
- final source package was built from a clean committed worktree
- non-strict audit has no local failures

`make submission-package` and `scripts/package_submission.py` refuse a dirty
working tree by default. Use `--allow-dirty` only for local rehearsal archives;
never use it for the public submission ZIP.

## 4. Run Hosted Proof

After the video is recorded, switch the public dashboard to judge mode before
running the final hosted proof:

```bash
cd /opt/apps/yiting/current
sudo sed -i.bak '/^YITING_LIVE_CHAOS=/d' /opt/apps/yiting/secrets/yiting.env
export YITING_ENV_FILE=/opt/apps/yiting/secrets/yiting.env
export YITING_PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io"
export NEXT_PUBLIC_YITING_MODE=judge
export YITING_PYTHON_IMAGE="registry.invalid/yiting/python@sha256:<digest>"
export YITING_DASHBOARD_IMAGE="registry.invalid/yiting/dashboard@sha256:<digest>"
docker compose -p yiting -f deploy/shared-host/compose.prod.yml up -d dashboard
```

Use the measured single-agent/manual baseline from the same incident family.
The proof helper uses same-family tagged `/stats/runsummary.runs` when present
and fails closed if `BASELINE_INCIDENT_FAMILY` does not match any measured run:

Do not invent the baseline. Time a one-person or single-agent rehearsal for
the same incident family as the hero run, record the seconds, and use that
number as `MEASURED_SINGLE_AGENT_SECS`. Use `docs/BASELINE_MEASUREMENT.md` as
the worksheet so the terminal criterion, incident family, measured seconds, and
saved notes are recorded before the proof artifact is generated. The final proof
is intentionally scoped to the same incident family so any hosted speed claim
is apples-to-apples. The reproducible paired benchmark is the separate
single-agent-vs-society quality proof and must not be described as a speed
proof.

```bash
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```

Expected generated or confirmed files after local readiness and hosted proof:

- `artifacts/qwen-smoke.json`
- `artifacts/track3-baseline.json`
- `artifacts/deployment-verification.json`
- `artifacts/hero-evidence.json`
- `artifacts/final-proof-index.md`
- `artifacts/live/backup-restore.json`
- `artifacts/live/ecs-ops-acceptance.json`
- `artifacts/live/app-restart-resilience.json`
- `artifacts/live/uptime-monitoring.json`
- `artifacts/live/submission-links.json`
- `dist/yiting-submission-source.zip` from `make submission-ready` or
  `make submission-package`

The hosted proof must include nonzero disagreement events (Safety Reviewer
challenge or human rejection/revision), nonzero human interventions, recovery
verification, and a hero evidence chain whose collaboration block proves role
sequence, handoffs, authorization path, exact execution match, and a sealed
`Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)`. The paired benchmark
must show the single-agent-vs-society quality gains. A hosted speed claim is
valid only when the same-family timing artifact proves `speedup_factor > 1`.
The hero evidence artifact must match `HERO_INCIDENT_ID`, be in final state
`EXECUTED`, and include an `ActionReceipt`.
The `make submission-proof` target passes `--require-public-read-only` to the
deployment verifier. It verifies that the dashboard loads publicly without
credentials and that paid/mutating chaos actions return the app-level disabled
`403` after judge mode is enabled.
It then writes `artifacts/hero-evidence.json` and
`artifacts/final-proof-index.md`, a single readable proof index tying together
the live Qwen smoke, baseline, deployment, read-only, and evidence-chain checks.
Because those proof artifacts are part of the final public packet, commit them
before the strict audit:

```bash
git add artifacts/qwen-smoke.json \
  artifacts/track3-baseline.json \
  artifacts/deployment-verification.json \
  artifacts/hero-evidence.json \
  artifacts/final-proof-index.md \
  artifacts/live/backup-restore.json \
  artifacts/live/ecs-ops-acceptance.json \
  artifacts/live/app-restart-resilience.json \
  artifacts/live/uptime-monitoring.json \
  artifacts/live/submission-links.json
git commit -m "docs: add final proof artifacts"
make submission-package
```

If `make submission-package` reports a dirty working tree, commit the final
source and proof artifacts first, then rebuild the archive from the clean
commit. Do not submit an archive built with `--allow-dirty`.

Open `artifacts/track3-baseline.json` and confirm it names the compared
incident family and states the formula:
`baseline.measured_seconds / yiting.avg_total_resolution_seconds`.
Use a concrete family label such as `suspicious deploy`, `certificate expiry`,
or `latency spike`; the proof target now fails before writing an artifact if
the family is left as placeholder text.

## 5. Run Strict Audit

```bash
python scripts/submission_audit.py --strict
python scripts/submission_status.py --require-final
```

Expected result:

- strict audit passes
- `final_submission: READY`
- no placeholder deployment domain
- public repository remote is configured
- landing page demo video is finalized
- Qwen Cloud smoke artifact is finalized
- source package matches the current commit
- `git status --short` is empty

## 6. Submission Fields

Use these repository artifacts while filling the hackathon form:

- One-line pitch: `docs/JUDGE_PACKET.md`
- Copy-paste form fields: `docs/SUBMISSION_FORM.md`
- Technical description: `docs/SUBMISSION.md`
- Architecture explanation: `docs/ARCHITECTURE.md`
- Track 3 proof: `docs/TRACK3_AGENT_SOCIETY.md`
- Rubric mapping: `docs/JUDGING_RUBRIC.md`
- Blog/social draft: `docs/BLOG_POST.md`
- Source package: `dist/yiting-submission-source.zip`
- Public repo publication guide: `docs/PUBLIC_REPOSITORY.md`

## 7. Final Guardrail

If any of these are still true, do not submit yet:

- README contains `<your-yiting-domain>`.
- Landing page still says the demo video is available during live presentation.
- `git remote get-url origin` fails.
- `artifacts/deployment-verification.json` is missing.
- `artifacts/qwen-smoke.json` is missing.
- `artifacts/track3-baseline.json` is missing.
- `artifacts/hero-evidence.json` is missing.
- `artifacts/final-proof-index.md` is missing.
- `artifacts/live/backup-restore.json` is missing.
- `artifacts/live/ecs-ops-acceptance.json` is missing.
- `python scripts/submission_audit.py --strict` fails.
- Public `/dashboard/api/chaos/activate` does not return `403` in judge mode.
- Demo video includes copyrighted music, unrelated third-party trademarks,
  stock footage, or external media without permission.
