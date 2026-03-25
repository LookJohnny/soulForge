#!/usr/bin/env bash
# ─────────────────────────────────────────────────
# SoulForge Development Launcher
# Usage: ./scripts/dev.sh
# ─────────────────────────────────────────────────
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Ensure local services bypass system proxy (Clash/V2Ray etc.)
export no_proxy="localhost,127.0.0.1"
export NO_PROXY="localhost,127.0.0.1"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[SoulForge]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

cleanup() {
  log "Shutting down..."
  [ -n "$AI_CORE_PID" ] && kill "$AI_CORE_PID" 2>/dev/null
  [ -n "$GATEWAY_PID" ] && kill "$GATEWAY_PID" 2>/dev/null
  [ -n "$NEXT_PID" ] && kill "$NEXT_PID" 2>/dev/null
  wait 2>/dev/null
  ok "All services stopped."
}
trap cleanup EXIT INT TERM

# ─── 1. Docker services ──────────────────────────
log "Checking Docker services..."
if ! docker info &>/dev/null; then
  err "Docker is not running. Please start Docker Desktop."
  exit 1
fi

REQUIRED_CONTAINERS=("soulforge-postgres" "soulforge-redis")
MISSING=()
for c in "${REQUIRED_CONTAINERS[@]}"; do
  if ! docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
    MISSING+=("$c")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  warn "Starting Docker services (${MISSING[*]})..."
  docker compose up -d postgres redis minio
  log "Waiting for services to be healthy..."
  sleep 3
fi
ok "Docker services running"

# ─── 2. Database migration ───────────────────────
log "Checking database migrations..."
cd packages/database
if pnpm prisma migrate status 2>&1 | grep -q "following migration"; then
  warn "Pending migrations found, applying..."
  pnpm prisma migrate deploy
fi
ok "Database schema up to date"

# ─── 3. Prisma client generation ─────────────────
log "Generating Prisma client..."
pnpm prisma generate
ok "Prisma client generated"
cd "$ROOT_DIR"

# ─── 4. AI Core (Python) ─────────────────────────
log "Starting AI Core (port 8100)..."
if lsof -i :8100 -t &>/dev/null; then
  warn "Port 8100 in use, killing old process..."
  lsof -i :8100 -t 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 2
fi

"$ROOT_DIR/.venv/bin/uvicorn" ai_core.main:app \
  --host 0.0.0.0 --port 8100 --reload \
  --app-dir "$ROOT_DIR/packages/ai-core/src" \
  > "$ROOT_DIR/logs/ai-core.log" 2>&1 &
AI_CORE_PID=$!

# Wait for AI Core to be ready (use nc instead of curl to avoid proxy issues)
for i in {1..15}; do
  if nc -z 127.0.0.1 8100 2>/dev/null; then
    ok "AI Core ready (PID $AI_CORE_PID)"
    break
  fi
  [ "$i" -eq 15 ] && { err "AI Core failed to start. Check logs/ai-core.log"; exit 1; }
  sleep 1
done

# ─── 5. Gateway (Python) ─────────────────────────
log "Starting Gateway (port 8080)..."
if lsof -i :8080 -t &>/dev/null; then
  warn "Port 8080 in use, killing old process..."
  lsof -i :8080 -t 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 2
fi

"$ROOT_DIR/.venv/bin/uvicorn" gateway.main:app \
  --host 0.0.0.0 --port 8080 --reload \
  --app-dir "$ROOT_DIR/packages/gateway/src" \
  > "$ROOT_DIR/logs/gateway.log" 2>&1 &
GATEWAY_PID=$!
ok "Gateway started (PID $GATEWAY_PID)"

# ─── 6. Next.js Admin Web ────────────────────────
log "Starting Next.js (port 3000)..."
if lsof -i :3000 -t &>/dev/null; then
  warn "Port 3000 in use, killing old process..."
  lsof -i :3000 -t 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 2
fi

# Clean Turbopack cache to avoid stale Prisma client issues
# Use mv + background rm because APFS dataless dirs can be slow to delete
if [ -d "$ROOT_DIR/apps/admin-web/.next" ]; then
  mv "$ROOT_DIR/apps/admin-web/.next" "$ROOT_DIR/apps/admin-web/.next_trash_$$" 2>/dev/null
  rm -rf "$ROOT_DIR/apps/admin-web/.next_trash_$$" &>/dev/null &
  log "Cleared Next.js cache"
fi

cd "$ROOT_DIR/apps/admin-web"
npx next dev --port 3000 --hostname 0.0.0.0 > "$ROOT_DIR/logs/next.log" 2>&1 &
NEXT_PID=$!
cd "$ROOT_DIR"

# Wait for Next.js (use nc to avoid proxy issues)
log "Waiting for Next.js..."
for i in {1..30}; do
  if nc -z 127.0.0.1 3000 2>/dev/null; then
    sleep 2  # give it a moment to finish startup
    ok "Next.js ready (PID $NEXT_PID) — took ${i}s"
    break
  fi
  if [ "$i" -eq 30 ]; then
    err "Next.js failed to start after 30s. Check logs/next.log"
    tail -10 "$ROOT_DIR/logs/next.log"
    exit 1
  fi
  sleep 1
done

# ─── Done ─────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  SoulForge Dev Environment Ready${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Admin Web:  ${CYAN}http://localhost:3000${NC}"
echo -e "  AI Core:    ${CYAN}http://localhost:8100/docs${NC}"
echo -e "  Gateway:    ${CYAN}http://localhost:8080${NC}"
echo ""
echo -e "  Logs:       ${YELLOW}logs/ai-core.log${NC}"
echo -e "              ${YELLOW}logs/gateway.log${NC}"
echo -e "              ${YELLOW}logs/next.log${NC}"
echo ""
echo -e "  Press ${RED}Ctrl+C${NC} to stop all services"
echo ""

# Keep script alive, tailing logs
tail -f logs/ai-core.log logs/gateway.log logs/next.log 2>/dev/null
