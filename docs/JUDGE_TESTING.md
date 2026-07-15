# Judge Testing

This guide is the shortest repeatable path for a fresh tester to verify YITING
without developer help. Final credentials must be supplied through Devpost's
private submission fields, not committed to this repository.

## Public URL

Use the final Track 3 URL supplied in the Devpost submission.

## Expected Flow

1. Open the dashboard.
2. Confirm the visible agent room shows distinct YITING roles.
3. Open the verified replay or start the approved demo flow if private judge
   credentials are supplied.
4. Inspect the incident room transcript for task division, disagreement or
   challenge, revision, human decision, and final action receipt.
5. Open the evidence export for the hero incident and confirm the chain is
   valid.
6. Open the benchmark artifacts:
   - `artifacts/track3-paired-benchmark.json`
   - `artifacts/track3-paired-benchmark-raw.json`
   - `artifacts/track3-paired-benchmark.csv`

## Required Acceptance Checks

Final implementation approval depends on all listed acceptance gates passing,
not just the application starting once.

```bash
export YITING_OPERATOR_TOKEN="<private-judge-token>"
python scripts/smoke.py \
  --base-url "https://yiting.47.84.232.193.sslip.io" \
  --require-https \
  --require-live-qwen \
  --live-qwen-token "$YITING_OPERATOR_TOKEN"
python scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
python scripts/track3_paired_benchmark.py
python scripts/verify_deployment.py \
  --public-url "https://yiting.47.84.232.193.sslip.io" \
  --incident-id "<hero-incident-id>" \
  --require-speedup \
  --require-public-read-only
# If rerunning immutable-image checks, set exact private registry digest refs here.
# The public submission proof is the committed deployment and ECS operations artifacts.
python scripts/uptime_monitoring.py \
  --yiting-url "$YITING_LIVE_URL" \
  --yiting-monitor-url "$YITING_UPTIME_MONITOR_URL"
```

```bash
# App restart resilience is checked with app-scoped Compose service restarts only.
# Do not reboot the shared ECS host during judging-window verification.
docker compose -p yiting -f deploy/shared-host/compose.prod.yml restart gateway
docker compose -p yiting -f deploy/shared-host/compose.prod.yml ps
docker compose -p yiting -f deploy/shared-host/compose.prod.yml exec gateway \
  python scripts/backup_restore_check.py \
    --sqlite-db /data/yiting.db \
    --victim-db /data/heal_idempotency.db \
    --backup-dir /tmp/yiting-backup \
    --live-submission-evidence \
    --output-json /tmp/yiting-backup/backup-restore.json
sudo install -d -o root -g root -m 0750 /opt/apps/backups/yiting
docker cp yiting-gateway-1:/tmp/yiting-backup/. /opt/apps/backups/yiting/
mkdir -p artifacts/live
sudo install -m 0640 /opt/apps/backups/yiting/backup-restore.json artifacts/live/backup-restore.json
sudo chown "$(id -u):$(id -g)" artifacts/live/backup-restore.json
```

The deployed agent containers share `/qwen-usage/yiting-qwen-usage.json` as the
daily Qwen usage circuit breaker. If the configured cap is reached, the workflow
must return a clear limit failure rather than using mock or non-Qwen output.
The ECS operations artifact verifies disk, container memory, OOM, swap,
public-listener, billing-period, external uptime-monitoring, immutable-image,
app restart resilience, and YITING network-isolation gates for the shared
Alibaba VM.

Private recording or repeat-test reset uses the operator token supplied outside
Git:

```bash
python scripts/reset_demo.py \
  --gateway-url "https://yiting.47.84.232.193.sslip.io" \
  --via-dashboard \
  --yes
```

The public judge mode must not expose paid or state-mutating demo controls. Any
private credentials used for recording or judge replay must remain outside Git.
