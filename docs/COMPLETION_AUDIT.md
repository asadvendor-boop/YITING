# YITING Completion Audit

This audit maps the active hackathon requirements to current evidence in the
repository. It is intentionally strict: local checks can prove source readiness,
but they cannot prove public deployment, public repository configuration, or a
final video until those artifacts exist.

## Source Requirements

| Requirement | Current evidence | Status |
|---|---|---|
| Present the app with a council-hall identity | Public docs, landing page, dashboard metadata, and app title use **YITING** with English-only copy. | Locally satisfied |
| Remove external room dependency | Source hygiene tests reject removed room-provider references; `shared/incident_room.py`, `shared/local_room_runtime.py`, and `gateway/routes/rooms.py` implement Gateway-owned incident rooms. | Locally satisfied |
| Build our own Incident Room | `tests/test_incident_rooms.py` exercises room creation, participants, messages, dashboard redaction, and production-mode confirmation against the local room ledger. | Locally satisfied |
| Remove non-Qwen model providers | `tests/test_submission_hygiene.py` scans tracked text sources for removed provider names. | Locally satisfied |
| Route model layer through Qwen / Alibaba Cloud | `shared/config.py`, `shared/qwen_reasoning.py`, `.env.example`, and `deploy/alibaba-ecs/yiting.env.example` route model credentials through primary `DASHSCOPE_API_KEY`, optional `QWEN_API_KEY` compatibility alias support, and `QWEN_BASE_URL`. | Locally satisfied |
| Do not rely on generic model source credentials | `tests/test_qwen_reasoning.py` verifies generic `OPENAI_*` env does not enable Qwen calls or override Qwen base URL. | Locally satisfied |
| Give agents human-readable Pinyin names | `shared/personas.py`, README, architecture docs, landing page, and dashboard profile map use Lin Xun, Chen Ming, Zhou Shen, Han Ce, Lu Xing, Wen Lu, and Song Shu. | Locally satisfied |
| Keep public copy product-first | `tests/test_submission_hygiene.py` scans public docs and landing page for prohibited history/rework phrases. | Locally satisfied |

## Hackathon Submission Requirements

| Requirement | Current evidence | Status |
|---|---|---|
| Identify track | README, `docs/SUBMISSION.md`, `docs/ARCHITECTURE.md`, and `docs/TRACK3_AGENT_SOCIETY.md` identify **Track 3: Agent Society** as primary and Track 4 as secondary. | Locally satisfied |
| Public open-source repo with license | `LICENSE`, README, source package workflow, and `docs/PUBLIC_REPOSITORY.md` exist. `scripts/submission_audit.py --strict` still requires a configured public `origin` remote. | External pending |
| Use Qwen models available on Qwen Cloud | Source configuration and `scripts/qwen_smoke.py` are present. A live paid Qwen call requires real DashScope/Qwen credentials. | External pending for live proof |
| Third-party authorization and media hygiene | `docs/THIRD_PARTY_COMPLIANCE.md` documents Qwen/Alibaba authorization, dependency manifests, synthetic data, bundled assets, and final demo-media restrictions. | Locally satisfied |
| Alibaba Cloud backend deployment proof | `deploy/alibaba-ecs/`, `deploy/Caddyfile`, `scripts/verify_deployment.py`, and `docs/ALIBABA_CLOUD_PROOF.md` are present. Actual ECS URL and proof recording are not local artifacts yet. | External pending |
| Architecture diagram | `docs/ARCHITECTURE.md` contains Mermaid system and evidence-chain diagrams. | Locally satisfied |
| Public demo video | `docs/DEMO_SCRIPT.md` exists and `scripts/finalize_submission.py` can inject the final video into the landing page. Landing page intentionally still has a video placeholder until the public video exists. | External pending |
| Text description | README and `docs/SUBMISSION.md` include the project description and rubric mapping. | Locally satisfied |
| Submission form packet | `docs/SUBMISSION_FORM.md` provides copy-paste title, tagline, descriptions, built-with list, Track 3 proof, final proof command, and public link placeholders for the hackathon form. | Locally satisfied |
| Final submission checklist | `docs/FINAL_SUBMISSION_CHECKLIST.md` gives the ordered day-of-submission runbook for freezing hero evidence, finalizing links, generating proof artifacts, and running strict audit. | Locally satisfied |
| Functional source package | `scripts/package_submission.py` creates a sanitized archive excluding env files, DBs, node_modules, build outputs, and unused portrait drafts. | Locally satisfied |

## Verification Commands

Run these before publishing or deploying:

```bash
make submission-ready
```

`make submission-ready` is local-only and intentionally no-network. It runs the
full test suite, dashboard production build, local room certification, sanitized
source packaging, the non-strict submission audit, and
`scripts/submission_status.py --require-final`. The final status output checks that the source
archive matches the current git commit, then lists any external artifacts still
missing. It does not prove the public repository, deployed Alibaba ECS URL, live
Qwen credentials, or final video.

Run these after Alibaba ECS deployment:

```bash
make submission-proof \
  PUBLIC_BASE_URL="https://yiting.47.84.232.193.sslip.io" \
  HERO_INCIDENT_ID="<hero-incident-id>" \
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```

`make submission-proof` performs the hosted Qwen smoke check, writes
`artifacts/qwen-smoke.json`, writes `artifacts/track3-paired-benchmark.json`,
writes `artifacts/track3-baseline.json`, verifies
the public deployment with `--require-speedup` and
`--require-public-read-only`, writes `artifacts/deployment-verification.json`,
writes `artifacts/hero-evidence.json` plus `artifacts/final-proof-index.md`,
and then runs the non-strict submission audit. Commit those proof artifacts,
run `make submission-package`, and then run the strict submission audit.

## Known External Blockers

These are not provable from the local workspace:

1. Public GitHub remote URL.
2. Public Alibaba ECS domain replacing README placeholders.
3. Public YouTube, Vimeo, or Facebook Video demo video replacing the landing-page
   placeholder.
4. Live Qwen smoke check with real Qwen Cloud credentials.
5. Hosted deployment verification against Alibaba ECS, including the paired
   quality benchmark, optional measured single-agent timing proof, and public
   read-only chaos/mutation rejection proof.
6. Final proof index generated from the hosted artifacts and hero evidence.

Do not mark the project submission-complete until those six items are real,
the generated proof artifacts are committed, `make submission-package` has
regenerated the source archive from that final commit, and
`python3 scripts/submission_audit.py --strict` passes.
