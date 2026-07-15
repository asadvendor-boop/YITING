#!/bin/bash
# YITING Agent Restart Script
# Uses graceful shutdown (SIGTERM → agent.stop(timeout=40)) + 40s cooldown
# before starting new processes. Follows local incident-room runtime best practices.
#
# Usage:
#   ./scripts/restart_agents.sh           # Restart all agents
#   ./scripts/restart_agents.sh triage    # Restart specific agent

set -euo pipefail

TARGET_ROLES=("triage" "diagnosis" "safety_reviewer" "commander" "operator")
COOLDOWN=40
STAGGER=3
LOG_DIR="/tmp"

cd "$(dirname "$0")/.."
source .venv/bin/activate

# Export all vars from .env so agents can read them via os.getenv()
# Without this, RECORDER_AGENT_ID etc. are invisible to child processes.
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "Loaded .env ($(wc -l < .env | tr -d ' ') vars)"
else
    echo "⚠️  No .env file found — agents may fail startup validation"
fi

restart_agent() {
    local agent=$1
    local module="agents.${agent}"
    
    echo "[$agent] Checking for existing process..."
    pid=$(pgrep -f "python3 -m ${module}" 2>/dev/null || true)
    
    if [ -n "$pid" ]; then
        echo "[$agent] Sending SIGTERM to PID $pid (graceful shutdown via agent.stop(timeout=40))..."
        kill -TERM "$pid" 2>/dev/null || true
        
        # Wait for process to exit (agent.stop() drains messages + closes WebSocket)
        echo "[$agent] Waiting for graceful shutdown (up to 45s)..."
        for i in $(seq 1 45); do
            if ! kill -0 "$pid" 2>/dev/null; then
                echo "[$agent] Process exited cleanly after ${i}s"
                break
            fi
            sleep 1
        done
        
        # If still alive after 45s, force kill
        if kill -0 "$pid" 2>/dev/null; then
            echo "[$agent] ⚠️ Still alive after 45s — force killing (SIGKILL)"
            kill -9 "$pid" 2>/dev/null || true
            sleep 1
        fi
        
        # 40s cooldown after disconnect (runtime: 30s + jitter)
        echo "[$agent] Cooldown ${COOLDOWN}s (room poll settle window)..."
        sleep "$COOLDOWN"
    else
        echo "[$agent] No existing process found"
    fi
    
    # Start new agent
    echo "[$agent] Starting: python3 -m ${module}"
    nohup python3 -m "$module" > "${LOG_DIR}/${agent}.log" 2>&1 &
    local new_pid=$!
    echo "[$agent] ✅ Started PID $new_pid (log: ${LOG_DIR}/${agent}.log)"
}

# Determine which agents to restart
if [ $# -gt 0 ]; then
    TARGET_ROLES=("$@")
fi

echo "========================================"
echo "YITING Agent Restart"
echo "  Agents: ${TARGET_ROLES[*]}"
echo "  Cooldown: ${COOLDOWN}s"
echo "  Stagger: ${STAGGER}s between agents"
echo "========================================"
echo ""

for agent in "${TARGET_ROLES[@]}"; do
    restart_agent "$agent"
    
    # Stagger between agents (skip for last one)
    if [ "$agent" != "${TARGET_ROLES[-1]}" ]; then
        echo ""
        echo "--- Stagger delay: ${STAGGER}s ---"
        sleep "$STAGGER"
        echo ""
    fi
done

echo ""
echo "========================================"
echo "All agents restarted. Verifying..."
echo "========================================"
sleep 3

for agent in "${TARGET_ROLES[@]}"; do
    module="agents.${agent}"
    pid=$(pgrep -f "python3 -m ${module}" 2>/dev/null || echo "NOT FOUND")
    echo "  $agent: PID $pid"
done

echo ""
echo "✅ Done"
