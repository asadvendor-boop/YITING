#!/usr/bin/env bash
# Start all YITING services
# Usage: ./scripts/start_all.sh
set -euo pipefail

# Resolve repo root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Load deployment configuration before any Python module imports environment
# variables.  Existing shell variables still win when operators export them
# explicitly before launching the script.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Activate virtualenv if it exists
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
else
  echo "ERROR: .venv not found. Run 'uv sync --locked --all-groups' first."
  exit 1
fi

PYTHON="$REPO_ROOT/.venv/bin/python"
UVICORN="$REPO_ROOT/.venv/bin/uvicorn"

require_alive() {
  local name=$1
  local pid=$2
  local log_file=$3
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "  ❌ $name exited during startup"
    tail -n 30 "$log_file" 2>/dev/null || true
    exit 1
  fi
}

PIDS=()
cleanup() {
  echo "Shutting down services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait
  echo "All services stopped."
}
trap cleanup EXIT INT TERM

# 0. Victim App (must start first — agents call it for heal/metrics)
echo "Starting Victim App on port 9000..."
"$UVICORN" app:app --app-dir victim-app --host 127.0.0.1 --port 9000 > /tmp/victim_app.log 2>&1 &
victim_pid=$!
PIDS+=("$victim_pid")
sleep 2
require_alive "Victim App" "$victim_pid" /tmp/victim_app.log
if curl -sf http://127.0.0.1:9000/healthz > /dev/null; then
  echo "  ✅ Victim App ready"
else
  echo "  ❌ Victim App failed to start"
  exit 1
fi

# 1. Gateway
echo "Starting Gateway on port 8000..."
"$UVICORN" gateway.app:app --host 127.0.0.1 --port 8000 > /tmp/gateway.log 2>&1 &
gateway_pid=$!
PIDS+=("$gateway_pid")
sleep 3
require_alive "Gateway" "$gateway_pid" /tmp/gateway.log
if curl -sf http://127.0.0.1:8000/health > /dev/null; then
  echo "  ✅ Gateway ready"
else
  echo "  ❌ Gateway failed to start"
  exit 1
fi

# 2. Agents (staggered by 5s for room polling cooldown)
for agent in triage diagnosis safety_reviewer commander operator; do
  echo "Starting $agent..."
  "$PYTHON" -m "agents.$agent" > "/tmp/${agent}.log" 2>&1 &
  agent_pid=$!
  PIDS+=("$agent_pid")
  echo "  $agent PID=$agent_pid"
  sleep 5
  require_alive "$agent" "$agent_pid" "/tmp/${agent}.log"
done

# 3. Recorder heartbeat
echo "Starting Recorder heartbeat..."
"$PYTHON" -m agents.recorder.heartbeat > /tmp/recorder_heartbeat.log 2>&1 &
heartbeat_pid=$!
PIDS+=("$heartbeat_pid")
sleep 1
require_alive "Recorder heartbeat" "$heartbeat_pid" /tmp/recorder_heartbeat.log

# 4. Dashboard (Next.js) — build if needed
echo "Starting Dashboard on port 3000..."
if [ ! -d dashboard/.next ]; then
  echo "  Building dashboard (first run)..."
  (cd dashboard && npm run build)
fi
if [ ! -x dashboard/node_modules/.bin/next ]; then
  echo "  ❌ Dashboard dependencies missing. Run 'cd dashboard && npm ci'."
  exit 1
fi
(
  cd dashboard
  exec ./node_modules/.bin/next start -p 3000 > /tmp/dashboard.log 2>&1
) &
dashboard_pid=$!
PIDS+=("$dashboard_pid")
sleep 2
require_alive "Dashboard" "$dashboard_pid" /tmp/dashboard.log

# 5. Verify all services
sleep 5
echo ""
echo "=== SERVICE STATUS ==="
check_service() {
  local name=$1
  local url=$2
  if curl -sf "$url" > /dev/null 2>&1; then
    echo "  ✅ $name: RUNNING"
  else
    echo "  ❌ $name: DOWN"
  fi
}
check_service "Victim App" "http://127.0.0.1:9000/healthz"
check_service "Gateway" "http://127.0.0.1:8000/health"
check_service "Dashboard" "http://127.0.0.1:3000"

echo ""
echo "Agent PIDs: ${PIDS[*]}"
echo "Logs: /tmp/{victim_app,gateway,triage,diagnosis,safety_reviewer,commander,operator,recorder_heartbeat,dashboard}.log"
echo ""
echo "Press Ctrl+C to stop all services."
wait
