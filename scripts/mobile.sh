#!/usr/bin/env bash
# ─────────────────────────────────────────────
# SoulForge 手机测试模式
# 启动所有服务 + ngrok 内网穿透
# Usage: ./scripts/mobile.sh
# ─────────────────────────────────────────────
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

# Ensure services are running
if ! nc -z 127.0.0.1 3000 2>/dev/null; then
  echo -e "${YELLOW}[!]${NC} Next.js not running. Starting dev.sh first..."
  ./scripts/dev.sh &
  DEV_PID=$!

  # Wait for Next.js
  for i in $(seq 1 60); do
    nc -z 127.0.0.1 3000 2>/dev/null && break
    sleep 1
  done
fi

echo -e "${GREEN}[✓]${NC} Services running"

# Get a character ID for the chat URL
CHAR_ID=$(docker exec soulforge-postgres psql -U soulforge -d soulforge -t -c \
  "SELECT id FROM characters ORDER BY created_at DESC LIMIT 1" 2>/dev/null | tr -d ' \n')

if [ -z "$CHAR_ID" ]; then
  echo "No characters found. Create one first in the admin panel."
  exit 1
fi

CHAR_NAME=$(docker exec soulforge-postgres psql -U soulforge -d soulforge -t -c \
  "SELECT name FROM characters WHERE id='$CHAR_ID'" 2>/dev/null | tr -d ' \n' | sed 's/^ *//')

echo ""
echo -e "${CYAN}Starting ngrok tunnel...${NC}"
echo ""

# Start ngrok in background
ngrok http 3000 --log=stdout > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!
sleep 3

# Extract the public URL
PUBLIC_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    tunnels = json.load(sys.stdin)['tunnels']
    for t in tunnels:
        if 'https' in t.get('public_url', ''):
            print(t['public_url'])
            break
    else:
        print(tunnels[0]['public_url'] if tunnels else 'ERROR')
except:
    print('ERROR')
" 2>/dev/null)

if [ "$PUBLIC_URL" = "ERROR" ] || [ -z "$PUBLIC_URL" ]; then
  echo "Failed to get ngrok URL. Check: http://127.0.0.1:4040"
  echo "You can also manually run: ngrok http 3000"
  kill $NGROK_PID 2>/dev/null
  exit 1
fi

CHAT_URL="${PUBLIC_URL}/chat/${CHAR_ID}"

echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  SoulForge 手机聊天已就绪${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "  角色: ${CYAN}${CHAR_NAME}${NC}"
echo ""
echo -e "  手机打开这个链接:"
echo -e "  ${CYAN}${CHAT_URL}${NC}"
echo ""
echo -e "  或扫描二维码 (需要安装 qrencode):"

# Try to generate QR code in terminal
if command -v qrencode &>/dev/null; then
  qrencode -t ANSIUTF8 "$CHAT_URL"
elif command -v python3 &>/dev/null; then
  python3 -c "
try:
    import qrcode
    qr = qrcode.QRCode(box_size=1, border=1)
    qr.add_data('$CHAT_URL')
    qr.print_ascii(invert=True)
except ImportError:
    print('  (安装 qrencode: brew install qrencode)')
" 2>/dev/null || echo "  (安装 qrencode: brew install qrencode)"
fi

echo ""
echo -e "  ngrok 管理面板: ${YELLOW}http://127.0.0.1:4040${NC}"
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
echo ""

cleanup() {
  echo ""
  echo "Stopping ngrok..."
  kill $NGROK_PID 2>/dev/null
  [ -n "$DEV_PID" ] && kill $DEV_PID 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

# Keep alive
wait $NGROK_PID
