# Adoption And Open-Source Roadmap

YITING is a hackathon project, but the architecture is intentionally shaped so
teams can extend it into a real governed incident-response control plane. This
roadmap explains the extension points, deployment path, and community-facing
work that make the idea scalable beyond the demo.

## Product Thesis

Most teams do not need a fully autonomous incident bot. They need a governed
agent society that can move quickly while preserving authority boundaries,
evidence, and recovery proof.

YITING's product direction is:

```text
evidence connectors -> role-specific Qwen agents -> deterministic Gateway
-> human or policy authorization -> exact-envelope execution -> audit proof
```

## Extension Points

| Area | How to extend | Safety boundary |
|---|---|---|
| Evidence sources | Add connectors that create `AlertCard` evidence from monitoring, deploy, ticket, or security systems. | Connectors can submit evidence, but cannot advance incident state directly. |
| Agent roles | Add a new skill contract in `shared/skill_registry.py` and a role-specific card type. | A role owns a narrow card contract and still publishes through the Gateway. |
| Runbooks | Add deterministic runbook definitions and severity policy rules. | Operator still executes only the authorized envelope. |
| Policy rules | Add organization-specific low-risk authorization policy. | High-risk and destructive actions still require human approval. |
| Evidence viewers | Build additional dashboards or export formats on top of `/evidence/{incident_id}`. | Viewers are read-only and cannot mutate the ledger. |
| Baseline metrics | Add more runsummary dimensions for team-specific comparison. | `scripts/track3_baseline.py` must still compare same-family runs. |

## Open-Source Starter Tasks

Good first issues:

1. Add a new read-only evidence connector.
2. Add a new runbook with tests for risk classification and exact-envelope
   execution.
3. Add a dashboard panel that visualizes `collaboration.role_sequence`.
4. Add a new `/evidence` export format for auditors.
5. Add a deployment health check to `scripts/verify_deployment.py`.

Core maintainer tasks:

1. Define a stable plugin contract for evidence connectors.
2. Add policy-pack loading for organization-specific risk rules.
3. Add external identity integration for approver mapping.
4. Add signed release artifacts for source packages and final proof bundles.
5. Add long-running deployment telemetry for agent health and model cost.

## Deployment Maturity Path

| Phase | Goal | Proof |
|---|---|---|
| Hackathon | Public read-only replay, evidence export, source package, demo video. | `scripts/submission_status.py` and `artifacts/final-proof-index.md`. |
| Team pilot | One service family, one evidence connector, one human approval group. | Weekly runs with `chain_valid: true` and recovery verification. |
| Department rollout | Multiple connectors, policy packs, and runbook owners. | Same-family baseline reports and bounded false-alarm rules. |
| Regulated deployment | Identity-bound approvals, signed evidence exports, retention policies. | External audit can recompute hashes from exported `card_json`. |

## Community Boundaries

YITING should stay honest about what is safe to change:

- Agent prompts can evolve, but card schemas and Gateway state rules need tests.
- New connectors must be evidence-only until reviewed.
- New runbooks need severity policy, exact-envelope tests, and recovery checks.
- Public demo mode must stay read-only unless an operator intentionally enables
  recording mode.
- Baseline claims must be measured with `docs/BASELINE_MEASUREMENT.md`, not
  estimated after the fact.

## Why This Matters For Judges

The roadmap supports the Problem Value & Impact criterion:

- **Real-world relevance:** emergency change control is a real operational pain
  point for teams with uptime, safety, or compliance pressure.
- **Scalability potential:** teams can add connectors, runbooks, policies, and
  role contracts without weakening the Gateway authority boundary.
- **Community potential:** contributors can work on evidence connectors,
  dashboard views, policy packs, and deployment verification without needing
  access to private credentials or paid model runs.

