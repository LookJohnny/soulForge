#!/bin/bash
# 一键拉起 SoulForge Live 全链路（本机约定：gateway 用 8081，8080 被 plush-nginx 占用）
#   docker compose up -d postgres redis   # 已在跑可跳过
#   ./scripts/live-up.sh                  # Ctrl-C 一起退出
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
export GATEWAY_PORT="${GATEWAY_PORT:-8081}"
uv run --package ai-core -- uvicorn ai_core.main:app --port 8100 &
uv run --package gateway -- uvicorn gateway.main:app --port "$GATEWAY_PORT" &
uv run python -m engine.server.server --port 8765 --time-scale 2 --llm-timeout 20 --social &
uv run python studio/server.py --port 8899 &
sleep 8
echo ""
echo "  ◈ /live       → http://127.0.0.1:8899/live"
echo "  ◈ 桌面壳      → open 'apps/desktop/src-tauri/target/debug/bundle/macos/SoulForge Live.app'"
echo "  ◈ gateway ws  → ws://127.0.0.1:$GATEWAY_PORT/ws   runtime → ws://127.0.0.1:8765/body"
echo ""
wait
