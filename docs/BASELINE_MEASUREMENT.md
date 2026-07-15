# Track 3 Baseline Measurement Worksheet

Use this worksheet before running `make submission-proof`. The goal is to make
the measurable efficiency claim defensible: YITING must be compared against a
same-family single-agent or one-person baseline, with the same terminal
criterion and a saved artifact.

## What The Baseline Proves

Track 3 asks for a measurable efficiency gain over a single-agent baseline.
YITING proves quality against a real single-agent baseline in the live paired
benchmark (`artifacts/track3-live-paired/`); the SPEED proof below is a
separate measured manual (human) baseline run:

```text
speedup_factor = baseline.measured_seconds / yiting.avg_total_resolution_seconds
```

The final packet is accepted only when `speedup_factor > 1` and the hosted run
also shows role handoffs, disagreement or revision, human intervention, and
recovery verification.

## Pick The Incident Family

Use the same family as the hero incident. Copy the exact value from the hero
evidence or run summary.

Good examples:

- `suspicious deploy`
- `latency spike`
- `certificate expiry`

Do not use placeholders like `<same-family-as-hero-incident>`.

## Keep The Terminal Criterion Fair

Use the same stopping point for both systems:

- High-risk remediation: final state `EXECUTED`, `ActionReceipt` present, and
  recovery verified.
- Low-risk remediation: final state `EXECUTED`, `PolicyAuthorization` present,
  and recovery verified.
- False-alarm comparison: final state `CLOSED_FALSE_ALARM`, if and only if the
  hero incident is also a false-alarm proof.

For the main Track 3 hero run, prefer an `EXECUTED` incident with either
`Verdict(CHALLENGE)` or `StructuredApproval(REJECTED)` in the chain.

## How To Measure

1. Save the alert payload or evidence summary for the hero incident family.
2. Start a stopwatch when the alert becomes visible to the baseline operator or
   single-agent prompt.
3. Let one person or one single-agent session investigate, choose the action,
   and decide whether the remediation is safe.
4. Stop the timer only when the baseline reaches the same terminal criterion as
   the YITING comparison.
5. Record the measured seconds without rounding down.
6. Save notes, screenshots, or a short log with the timestamp and action chosen.

Do not include YITING's agent chain, approval page, or Operator execution in
the baseline timing. The baseline is the comparison, not a second YITING run.

## Measurement Record

Fill this in before generating `artifacts/track3-baseline.json`.

```text
Incident family:
Hero incident ID:
Baseline label:
Baseline measured seconds:
Who/what ran the baseline:
Start timestamp:
End timestamp:
Terminal criterion reached:
Action selected:
Recovery verification evidence:
Notes file or screenshot:
```

## Generate The Artifact

```bash
python scripts/track3_baseline.py \
  --gateway-url "https://yiting.47.84.232.193.sslip.io" \
  --baseline-secs <measured-single-agent-seconds> \
  --baseline-label "Measured single-agent rehearsal" \
  --incident-family "<same-family-as-hero-incident>" \
  --output-json artifacts/track3-baseline.json
```

The script refuses placeholder families, non-positive timings, missing Track 3
counters, missing same-family runs when tagged runs exist, and comparisons that
do not prove `speedup_factor > 1`.

## Reproducible Paired Benchmark

The hosted stopwatch baseline above proves the live efficiency claim. YITING
also includes a fixed paired benchmark for the architecture claim:

```bash
python scripts/track3_paired_benchmark.py
```

This writes:

- `artifacts/track3-paired-benchmark.json`
- `artifacts/track3-paired-benchmark-raw.json`
- `artifacts/track3-paired-benchmark.csv`

The dataset is `evals/track3_paired_scenarios.json`. It contains 20 fixed
scenarios. The benchmark uses the same scenario inputs, same rubric, same model
identity, and the same token budget ceiling for `single_agent` and
`full_yiting_society`. It reports mean, median, failure count, total tokens,
latency, unsupported claims, risks detected, and quality per token.

The paired benchmark does not claim speed improvement. It is allowed to show
the society is slower while still proving higher task success, lower
unsupported-claim rate, more risks detected, and better final rubric score.

## Acceptance Checklist

- [ ] `baseline.measured_seconds` is a real stopwatch value.
- [ ] `artifacts/track3-paired-benchmark.json` was generated from the fixed
      paired dataset without manually removing failed cases.
- [ ] The paired benchmark says `comparison.speed_improvement_claimed` is
      `false` unless live data separately justifies speedup.
- [ ] `baseline.incident_family` matches the hero incident family.
- [ ] `yiting.matched_incident_ids` includes the hero incident when same-family
      run rows are available.
- [ ] `track3_requirements_checked.disagreement_or_revision` is `true`.
- [ ] `track3_requirements_checked.human_intervention` is `true`.
- [ ] `track3_requirements_checked.recovery_verification` is `true`.
- [ ] `speedup_factor > 1`.
- [ ] `scripts/verify_deployment.py --require-speedup` passes.
