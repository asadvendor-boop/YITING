#!/bin/sh
set -eu

load_secret_file() {
  var_name="$1"
  file_var_name="${var_name}_FILE"
  file_path="$(printenv "$file_var_name" 2>/dev/null || true)"
  current_value="$(printenv "$var_name" 2>/dev/null || true)"
  if [ -n "$file_path" ] && [ -z "$current_value" ]; then
    if [ ! -r "$file_path" ]; then
      echo "Cannot read secret file for $var_name: $file_path" >&2
      exit 78
    fi
    export "$var_name=$(cat "$file_path")"
  fi
}

for secret_name in \
  DASHSCOPE_API_KEY \
  QWEN_API_KEY \
  GATEWAY_SECRET \
  RECORDER_SUBMISSION_KEY \
  TRIAGE_SUBMISSION_KEY \
  DIAGNOSIS_SUBMISSION_KEY \
  SAFETY_REVIEWER_SUBMISSION_KEY \
  COMMANDER_SUBMISSION_KEY \
  OPERATOR_SUBMISSION_KEY \
  INCIDENT_ROOM_API_KEY \
  APPROVAL_PROXY_SECRET \
  APPROVAL_UI_BCRYPT_HASH \
  APPROVAL_UI_CSRF_SECRET
do
  load_secret_file "$secret_name"
done

service="${YITING_SERVICE:-${1:-gateway}}"

case "$service" in
  gateway)
    exec uv run --no-sync uvicorn gateway.app:app --host "${GATEWAY_HOST:-0.0.0.0}" --port "${GATEWAY_PORT:-8000}"
    ;;
  victim)
    exec uv run --no-sync uvicorn app:app --app-dir victim-app --host "${VICTIM_HOST:-0.0.0.0}" --port "${VICTIM_PORT:-9000}"
    ;;
  agent)
    if [ -z "${AGENT_ROLE:-}" ]; then
      echo "AGENT_ROLE is required for YITING_SERVICE=agent" >&2
      exit 64
    fi
    exec uv run --no-sync python -m "agents.${AGENT_ROLE}"
    ;;
  recorder-heartbeat)
    exec uv run --no-sync python -m agents.recorder.heartbeat
    ;;
  *)
    echo "Unknown YITING service: $service" >&2
    exit 64
    ;;
esac
