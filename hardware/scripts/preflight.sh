#!/usr/bin/env bash
# ─────────────────────────────────────────────
# SoulForge 硬件接入预检脚本
# 在接入 ESP32 / 树莓派之前，验证后端服务全部就绪
# Usage: ./hardware/scripts/preflight.sh
# ─────────────────────────────────────────────
set +e  # Don't exit on failures — we track them manually

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AI_CORE="http://127.0.0.1:8100"
GATEWAY="http://127.0.0.1:8080"
SERVICE_TOKEN="${SERVICE_TOKEN:-test-service-token-for-dev}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

pass() { echo -e "  ${GREEN}[PASS]${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; ((WARN++)); }
header() { echo -e "\n${CYAN}── $1 ──${NC}"; }

# Bypass system proxy
export no_proxy="localhost,127.0.0.1"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy 2>/dev/null || true

header "1. Docker 服务"

for svc in soulforge-postgres soulforge-redis; do
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${svc}$"; then
    pass "$svc running"
  else
    fail "$svc not running"
  fi
done

header "2. AI Core 健康检查"

HEALTH=$(curl -sf --noproxy localhost "$AI_CORE/health" 2>/dev/null || echo '{}')
if echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok'" 2>/dev/null; then
  pass "AI Core healthy"
  DB=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('database','?'))" 2>/dev/null)
  REDIS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('redis','?'))" 2>/dev/null)
  [ "$DB" = "ok" ] && pass "  Database: ok" || fail "  Database: $DB"
  [ "$REDIS" = "ok" ] && pass "  Redis: ok" || fail "  Redis: $REDIS"
else
  fail "AI Core unreachable at $AI_CORE"
fi

header "3. Gateway 健康检查"

GW_HEALTH=$(curl -sf --noproxy localhost "$GATEWAY/health" 2>/dev/null || echo '{}')
if echo "$GW_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok'" 2>/dev/null; then
  pass "Gateway healthy"
  PROTOS=$(echo "$GW_HEALTH" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('protocols',[])))" 2>/dev/null)
  for p in xiaozhi web_audio generic_ws; do
    echo "$PROTOS" | grep -q "$p" && pass "  Protocol: $p" || warn "  Protocol $p missing"
  done
else
  fail "Gateway unreachable at $GATEWAY"
fi

header "4. LLM 对话测试"

# Find a character ID
CHAR_ID=$(docker exec soulforge-postgres psql -U soulforge -d soulforge -t -c "SELECT id FROM characters LIMIT 1" 2>/dev/null | tr -d ' \n')
BRAND_ID=$(docker exec soulforge-postgres psql -U soulforge -d soulforge -t -c "SELECT brand_id FROM characters LIMIT 1" 2>/dev/null | tr -d ' \n')

if [ -z "$CHAR_ID" ]; then
  fail "No characters found in database — create one first"
else
  pass "Test character: $CHAR_ID"

  START=$(python3 -c "import time; print(time.time())")
  LLM_RESP=$(curl -sf --noproxy localhost -X POST "$AI_CORE/chat/preview" \
    -H "Content-Type: application/json" \
    -H "X-Service-Token: $SERVICE_TOKEN" \
    -H "X-Brand-Id: $BRAND_ID" \
    -d "{\"character_id\":\"$CHAR_ID\",\"text\":\"你好\",\"with_audio\":false}" 2>/dev/null || echo '{}')
  END=$(python3 -c "import time; print(time.time())")
  LATENCY=$(python3 -c "print(int(($END - $START) * 1000))")

  TEXT=$(echo "$LLM_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('text','')[:50])" 2>/dev/null)
  if [ -n "$TEXT" ] && [ "$TEXT" != "" ]; then
    pass "LLM replied: \"$TEXT\" (${LATENCY}ms)"
  else
    fail "LLM no response"
  fi
fi

header "5. TTS 语音合成测试"

TTS_RESP=$(curl -sf --noproxy localhost -X POST "$AI_CORE/tts/preview" \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: $SERVICE_TOKEN" \
  -H "X-Brand-Id: $BRAND_ID" \
  -d '{"text":"你好呀","voice":"longxiaochun"}' 2>/dev/null || echo '{}')

HAS_AUDIO=$(echo "$TTS_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('audio_base64') else 'no')" 2>/dev/null)
if [ "$HAS_AUDIO" = "yes" ]; then
  AUDIO_LEN=$(echo "$TTS_RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('audio_base64','')))" 2>/dev/null)
  pass "TTS OK (audio: ${AUDIO_LEN} chars base64)"
else
  warn "TTS no audio returned (DashScope API key may be missing)"
fi

header "6. 触摸 API 测试"

if [ -n "$CHAR_ID" ]; then
  TOUCH_RESP=$(curl -sf --noproxy localhost -X POST "$AI_CORE/pipeline/touch" \
    -H "Content-Type: application/json" \
    -H "X-Service-Token: $SERVICE_TOKEN" \
    -H "X-Brand-Id: $BRAND_ID" \
    -d "{\"character_id\":\"$CHAR_ID\",\"device_id\":\"test\",\"session_id\":\"preflight-test\",\"gesture\":\"pat\",\"zone\":\"head\",\"pressure\":0.6}" 2>/dev/null || echo '{}')

  GESTURE=$(echo "$TOUCH_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gesture',''))" 2>/dev/null)
  if [ "$GESTURE" = "pat" ]; then
    pass "Touch API: pat→head processed"
  else
    fail "Touch API: unexpected response"
  fi
fi

header "7. WebSocket 端口"

if nc -z 127.0.0.1 8080 2>/dev/null; then
  pass "Gateway WebSocket port 8080 open"
else
  fail "Port 8080 closed — Gateway not listening"
fi

# Summary
echo ""
echo -e "${CYAN}════════════════════════════════════════${NC}"
echo -e "  ${GREEN}PASS: $PASS${NC}  ${RED}FAIL: $FAIL${NC}  ${YELLOW}WARN: $WARN${NC}"
echo -e "${CYAN}════════════════════════════════════════${NC}"

if [ "$FAIL" -eq 0 ]; then
  echo -e "\n  ${GREEN}All critical checks passed. Ready for hardware!${NC}\n"
else
  echo -e "\n  ${RED}$FAIL check(s) failed. Fix before connecting hardware.${NC}\n"
  exit 1
fi
