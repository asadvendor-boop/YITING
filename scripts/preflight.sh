#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# YITING — Deployment Preflight
# ═══════════════════════════════════════════════════════════════
# Run BEFORE starting services.  Validates:
#   1. All required environment variables are set
#   2. Caddy config passes validation
#   3. APPROVAL_PROXY_SECRET matches between Caddy and Gateway
#
# Usage:
#   source .env && bash scripts/preflight.sh
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

echo "═══════════════════════════════════════════════════"
echo "  YITING Deployment Preflight"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Required environment variables ────────────────────────
echo "▸ Checking required environment variables..."

required_vars=(
  # Qwen Cloud / Alibaba Cloud Model Studio endpoint
  QWEN_BASE_URL
  # Agent identities
  RECORDER_AGENT_ID
  TRIAGE_AGENT_ID
  DIAGNOSIS_AGENT_ID
  SAFETY_REVIEWER_AGENT_ID
  COMMANDER_AGENT_ID
  OPERATOR_AGENT_ID
  # Role-bound submission keys
  RECORDER_SUBMISSION_KEY
  TRIAGE_SUBMISSION_KEY
  DIAGNOSIS_SUBMISSION_KEY
  SAFETY_REVIEWER_SUBMISSION_KEY
  COMMANDER_SUBMISSION_KEY
  OPERATOR_SUBMISSION_KEY
  # Gateway
  GATEWAY_SECRET
  GATEWAY_DB_PATH
  # Approval UI (three-layer auth)
  APPROVAL_PROXY_SECRET
  APPROVAL_UI_USER
  APPROVAL_UI_BCRYPT_HASH
  APPROVAL_UI_APPROVER_ID
  APPROVAL_UI_CSRF_SECRET
  # Human approver allowlist
  HUMAN_APPROVER_IDS
)

if [[ -z "${DASHSCOPE_API_KEY:-}" && -z "${QWEN_API_KEY:-}" ]]; then
  echo -e "  ${RED}✗ Missing: DASHSCOPE_API_KEY (QWEN_API_KEY compatibility alias is accepted only for compatibility)${NC}"
  ERRORS=$((ERRORS + 1))
else
  if [[ -n "${DASHSCOPE_API_KEY:-}" ]]; then
    echo -e "  ${GREEN}✓${NC} DASHSCOPE_API_KEY"
  else
    echo -e "  ${YELLOW}!${NC} QWEN_API_KEY compatibility alias"
  fi
fi

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo -e "  ${RED}✗ Missing: $var${NC}"
    ERRORS=$((ERRORS + 1))
  else
    echo -e "  ${GREEN}✓${NC} $var"
  fi
done

if [[ -n "${OPENAI_API_KEY:-}" || -n "${OPENAI_API_BASE:-}" || -n "${OPENAI_BASE_URL:-}" ]]; then
  echo -e "  ${RED}✗ Remove explicit OPENAI_* source credentials from deployment env${NC}"
  echo "    YITING derives client compatibility variables from Qwen/DashScope values at runtime."
  ERRORS=$((ERRORS + 1))
fi

echo ""

# ── 2. Caddy config validation ──────────────────────────────
echo "▸ Validating Caddy configuration..."

CADDYFILE="${CADDYFILE_PATH:-/etc/caddy/Caddyfile}"
if [[ -f "$CADDYFILE" ]]; then
  if caddy validate --config "$CADDYFILE" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Caddy config valid"
  else
    echo -e "  ${RED}✗ Caddy config validation failed${NC}"
    echo "    Run: caddy validate --config $CADDYFILE"
    ERRORS=$((ERRORS + 1))
  fi

  # Check for literal placeholder credentials.
  if grep -q "JUDGE_USER HASHED_PASSWORD" "$CADDYFILE" 2>/dev/null; then
    echo -e "  ${RED}✗ Caddyfile still has literal placeholder credentials${NC}"
    echo "    Use the env-backed Caddyfile and set YITING_JUDGE_USER/YITING_JUDGE_HASH"
    ERRORS=$((ERRORS + 1))
  else
    echo -e "  ${GREEN}✓${NC} No literal placeholder credentials"
  fi
else
  echo -e "  ${YELLOW}⚠ Caddyfile not found at $CADDYFILE (skipping)${NC}"
fi

echo ""

# ── 3. Caddy ↔ Gateway secret match ─────────────────────────
echo "▸ Checking Caddy ↔ Gateway secret consistency..."

read_caddy_env() {
  local key="$1"
  local file="$2"
  grep "Environment=${key}=" "$file" 2>/dev/null | tail -n 1 | sed "s/.*Environment=${key}=//" || true
}

CADDY_SECRET=""
CADDY_USER=""
CADDY_HASH=""
CADDY_ENV="${CADDY_ENV_PATH:-}"
if [[ -z "$CADDY_ENV" ]]; then
  if [[ -f "/etc/systemd/system/caddy.service.d/yiting.conf" ]]; then
    CADDY_ENV="/etc/systemd/system/caddy.service.d/yiting.conf"
  else
    CADDY_ENV="/etc/systemd/system/caddy.service.d/env.conf"
  fi
fi
if [[ -f "$CADDY_ENV" ]]; then
  CADDY_SECRET=$(read_caddy_env "APPROVAL_PROXY_SECRET" "$CADDY_ENV")
  CADDY_USER=$(read_caddy_env "YITING_JUDGE_USER" "$CADDY_ENV")
  CADDY_HASH=$(read_caddy_env "YITING_JUDGE_HASH" "$CADDY_ENV")
fi

GW_SECRET="${APPROVAL_PROXY_SECRET:-}"
GW_USER="${APPROVAL_UI_USER:-}"
GW_HASH="${APPROVAL_UI_BCRYPT_HASH:-}"

if [[ -n "$CADDY_SECRET" && -n "$GW_SECRET" ]]; then
  if [[ "$CADDY_SECRET" == "$GW_SECRET" ]]; then
    echo -e "  ${GREEN}✓${NC} APPROVAL_PROXY_SECRET matches between Caddy and Gateway"
  else
    echo -e "  ${RED}✗ APPROVAL_PROXY_SECRET MISMATCH between Caddy and Gateway${NC}"
    echo "    Caddy: ${CADDY_SECRET:0:8}..."
    echo "    Gateway: ${GW_SECRET:0:8}..."
    ERRORS=$((ERRORS + 1))
  fi
elif [[ -z "$CADDY_SECRET" ]]; then
  echo -e "  ${YELLOW}⚠ Cannot read Caddy env (skipping match check)${NC}"
else
  echo -e "  ${RED}✗ Gateway APPROVAL_PROXY_SECRET not set${NC}"
  ERRORS=$((ERRORS + 1))
fi

if [[ -f "$CADDY_ENV" ]]; then
  if [[ -z "$CADDY_USER" || -z "$CADDY_HASH" ]]; then
    echo -e "  ${RED}✗ Caddy judge basic-auth env is incomplete${NC}"
    echo "    Set YITING_JUDGE_USER and YITING_JUDGE_HASH in $CADDY_ENV"
    ERRORS=$((ERRORS + 1))
  elif [[ "$CADDY_USER" == "$GW_USER" && "$CADDY_HASH" == "$GW_HASH" ]]; then
    echo -e "  ${GREEN}✓${NC} Judge auth matches between Caddy and Gateway"
  else
    echo -e "  ${RED}✗ Judge auth mismatch between Caddy and Gateway${NC}"
    ERRORS=$((ERRORS + 1))
  fi
fi

echo ""

# ── 4. Port availability ────────────────────────────────────
echo "▸ Checking port availability..."

for port in 8000 3000 9000; do
  if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
    echo -e "  ${YELLOW}⚠ Port $port already in use${NC}"
  else
    echo -e "  ${GREEN}✓${NC} Port $port available"
  fi
done

echo ""

# ── Result ──────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════"
if [[ $ERRORS -eq 0 ]]; then
  echo -e "  ${GREEN}✅ PREFLIGHT PASSED — safe to deploy${NC}"
  echo "═══════════════════════════════════════════════════"
  exit 0
else
  echo -e "  ${RED}❌ PREFLIGHT FAILED — $ERRORS error(s) found${NC}"
  echo "═══════════════════════════════════════════════════"
  exit 1
fi
