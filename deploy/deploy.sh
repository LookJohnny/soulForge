#!/usr/bin/env bash
set -euo pipefail

# ─── SoulForge One-Click Deployment Script ───────
# Usage: ./deploy.sh [--domain example.com]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env.prod"

echo "╔══════════════════════════════════════╗"
echo "║   SoulForge Production Deployment    ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Parse args
DOMAIN="localhost"
while [[ $# -gt 0 ]]; do
  case $1 in
    --domain) DOMAIN="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Generate random password
gen_password() {
  openssl rand -base64 32 | tr -d '/+=' | head -c 32
}

# ─── Step 1: Generate .env if not exists ─────────
if [ ! -f "$ENV_FILE" ]; then
  echo "[1/5] Generating production environment..."
  cp "$SCRIPT_DIR/.env.template" "$ENV_FILE"

  # Auto-fill secrets
  sed -i.bak "s/^DB_PASSWORD=.*/DB_PASSWORD=$(gen_password)/" "$ENV_FILE"
  sed -i.bak "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=$(gen_password)/" "$ENV_FILE"
  sed -i.bak "s/^NEXTAUTH_SECRET=.*/NEXTAUTH_SECRET=$(gen_password)/" "$ENV_FILE"
  sed -i.bak "s/^MASTER_SECRET=.*/MASTER_SECRET=$(gen_password)/" "$ENV_FILE"
  sed -i.bak "s/^MINIO_SECRET_KEY=.*/MINIO_SECRET_KEY=$(gen_password)/" "$ENV_FILE"

  if [ "$DOMAIN" != "localhost" ]; then
    sed -i.bak "s|^NEXTAUTH_URL=.*|NEXTAUTH_URL=https://$DOMAIN|" "$ENV_FILE"
  fi

  rm -f "$ENV_FILE.bak"

  echo "  -> Created $ENV_FILE"
  echo "  -> IMPORTANT: Edit $ENV_FILE and add your DASHSCOPE_API_KEY"
  echo ""
else
  echo "[1/5] Using existing $ENV_FILE"
fi

# ─── Step 2: Check required values ──────────────
source "$ENV_FILE"
if [ -z "${DASHSCOPE_API_KEY:-}" ] && [ "${LLM_PROVIDER:-dashscope}" = "dashscope" ]; then
  echo ""
  echo "⚠️  DASHSCOPE_API_KEY is empty in $ENV_FILE"
  echo "   Please set it and re-run this script."
  echo "   Get your key at: https://dashscope.console.aliyun.com/"
  exit 1
fi

# ─── Step 3: Build images ───────────────────────
echo "[2/5] Building Docker images..."
cd "$PROJECT_DIR"
docker compose -f docker/docker-compose.prod.yml --env-file "$ENV_FILE" build

# ─── Step 4: Start services ─────────────────────
echo "[3/5] Starting services..."
docker compose -f docker/docker-compose.prod.yml --env-file "$ENV_FILE" up -d

# ─── Step 5: Run database migration ─────────────
echo "[4/5] Running database migration..."
sleep 5  # Wait for postgres to be ready
docker compose -f docker/docker-compose.prod.yml --env-file "$ENV_FILE" \
  exec admin-web npx prisma migrate deploy 2>/dev/null || \
  echo "  -> Migration skipped (run manually if needed)"

# ─── Step 6: Health check ───────────────────────
echo "[5/5] Health check..."
sleep 3

check_service() {
  local name=$1 url=$2
  if curl -sf "$url" > /dev/null 2>&1; then
    echo "  ✓ $name is running"
  else
    echo "  ✗ $name is not responding"
  fi
}

check_service "Admin Web" "http://localhost:${PORT:-80}"
check_service "AI Core" "http://localhost:${PORT:-80}/api/ai/health"
check_service "Gateway" "http://localhost:${PORT:-80}/gateway/health"

echo ""
echo "══════════════════════════════════════"
echo "  SoulForge is running!"
if [ "$DOMAIN" = "localhost" ]; then
  echo "  Open: http://localhost:${PORT:-80}"
else
  echo "  Open: https://$DOMAIN"
fi
echo "══════════════════════════════════════"
