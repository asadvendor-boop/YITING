#!/usr/bin/env bash
# Prepare a YITING checkout on Alibaba Cloud ECS.
#
# Usage:
#   bash deploy/alibaba-ecs/bootstrap.sh
#   bash deploy/alibaba-ecs/bootstrap.sh --install-packages
#
# The script is intentionally conservative:
#   - It does not overwrite .env.
#   - It does not start paid model workflows.
#   - It does not replace Caddy credentials.

set -euo pipefail

INSTALL_PACKAGES=0
if [[ "${1:-}" == "--install-packages" ]]; then
  INSTALL_PACKAGES=1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "YITING Alibaba ECS bootstrap"
echo "Root: $ROOT"

if [[ "$INSTALL_PACKAGES" == "1" ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=""
  else
    SUDO="sudo"
  fi
  echo "Installing OS packages..."
  $SUDO apt-get update
  $SUDO apt-get install -y curl git build-essential caddy nodejs npm
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "uv installed. If your shell cannot find it, reload your profile."
  fi
fi

if [[ ! -f .env ]]; then
  cp deploy/alibaba-ecs/yiting.env.example .env
  chmod 600 .env
  echo "Created .env from deploy/alibaba-ecs/yiting.env.example"
else
  echo ".env already exists; leaving it untouched"
fi

echo "Installing Python dependencies..."
uv sync --locked

echo "Installing dashboard dependencies..."
(cd dashboard && npm ci)

echo "Compiling dashboard..."
(cd dashboard && NEXT_PUBLIC_YITING_MODE="${NEXT_PUBLIC_YITING_MODE:-live}" npm run build)

echo "Validating Python sources..."
PYTHONPYCACHEPREFIX=/tmp/yiting-pycache .venv/bin/python -m compileall -q shared agents gateway scripts

echo ""
echo "Next manual steps:"
echo "1. Fill .env with DASHSCOPE_API_KEY, Gateway secrets, agent IDs, and approval secrets. Use QWEN_API_KEY only as a compatibility alias."
echo "2. Copy deploy/alibaba-ecs/systemd/*.service to /etc/systemd/system/."
echo "3. Copy deploy/Caddyfile to /etc/caddy/Caddyfile and set Caddy env values."
echo "4. Run: source .env && bash scripts/preflight.sh"
echo "5. Start services with systemctl, then run:"
echo "   python scripts/qwen_smoke.py"
echo "   python scripts/verify_deployment.py --public-url \"\$PUBLIC_BASE_URL\" --incident-id \"\$HERO_INCIDENT_ID\""
echo "6. After recording and switching to judge mode, run:"
echo "   make submission-proof PUBLIC_BASE_URL=\"\$PUBLIC_BASE_URL\" HERO_INCIDENT_ID=\"\$HERO_INCIDENT_ID\" MEASURED_SINGLE_AGENT_SECS=\"\$MEASURED_SINGLE_AGENT_SECS\" BASELINE_INCIDENT_FAMILY=\"\$BASELINE_INCIDENT_FAMILY\""
