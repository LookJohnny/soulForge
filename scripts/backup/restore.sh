#!/usr/bin/env bash
# ─────────────────────────────────────────────
# SoulForge 完整恢复脚本
# 在全新机器上从 git clone 到完全跑起来
# ─────────────────────────────────────────────
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${CYAN}[SoulForge]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

# ── 1. Check prerequisites ──
log "Checking prerequisites..."
command -v docker &>/dev/null || { err "Docker not found. Install Docker Desktop first."; exit 1; }
command -v node &>/dev/null   || { err "Node.js not found. Install Node.js >= 18."; exit 1; }
command -v pnpm &>/dev/null   || { err "pnpm not found. Run: npm install -g pnpm"; exit 1; }
command -v uv &>/dev/null     || { err "uv not found. Install: https://docs.astral.sh/uv/"; exit 1; }
ok "Prerequisites OK"

# ── 2. Environment file ──
if [ ! -f .env ]; then
  warn ".env not found, copying from .env.example"
  cp .env.example .env
  err "Please edit .env and fill in your API keys, then run this script again."
  exit 1
fi
ok ".env exists"

# ── 3. Docker services ──
log "Starting Docker services..."
docker compose up -d postgres redis minio
sleep 3
ok "Docker services running"

# ── 4. Install dependencies ──
log "Installing Python dependencies..."
uv sync
ok "Python packages installed"

log "Installing Node.js dependencies..."
pnpm install
ok "Node packages installed"

# ── 5. Database migration ──
log "Running database migrations..."
cd packages/database
pnpm prisma migrate deploy
pnpm prisma generate
cd "$ROOT"
ok "Database migrated"

# ── 6. Restore database data (characters, users, etc.) ──
if [ -f scripts/backup/db_dump.sql ]; then
  log "Restoring database data..."
  # Only restore data, skip schema (already handled by Prisma migrate)
  docker exec -i soulforge-postgres psql -U soulforge -d soulforge \
    -c "SET session_replication_role = 'replica';" 2>/dev/null
  # Extract and run only COPY/INSERT statements from dump
  grep -E "^(COPY|INSERT|SELECT pg_catalog.setval)" scripts/backup/db_dump.sql | \
    docker exec -i soulforge-postgres psql -U soulforge -d soulforge 2>/dev/null || true
  docker exec -i soulforge-postgres psql -U soulforge -d soulforge \
    -c "SET session_replication_role = 'origin';" 2>/dev/null
  ok "Database data restored"
else
  warn "No database dump found at scripts/backup/db_dump.sql, skipping data restore"
fi

# ── 7. Cloudflare Tunnel (optional) ──
if command -v cloudflared &>/dev/null; then
  if [ -f ~/.cloudflared/config.yml ]; then
    ok "Cloudflare Tunnel config found"
    log "Start tunnel with: cloudflared tunnel run soulforge"
  else
    warn "Cloudflare Tunnel not configured. Run: cloudflared tunnel login"
  fi
else
  warn "cloudflared not installed. Install: brew install cloudflared"
fi

# ── 8. Done ──
echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  SoulForge 恢复完成${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "  启动开发环境:  ${CYAN}./scripts/dev.sh${NC}"
echo -e "  手机测试模式:  ${CYAN}./scripts/mobile.sh${NC}"
echo -e "  隧道:         ${CYAN}cloudflared tunnel run soulforge${NC}"
echo ""
echo -e "  管理后台:     ${CYAN}http://localhost:3000/dashboard${NC}"
echo -e "  手机聊天:     ${CYAN}https://chat.cheapsamm.xyz/chat${NC}"
echo ""
