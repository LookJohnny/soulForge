#!/bin/bash
# SoulForge Studio 一键启动（中枢 + 前端，Ctrl-C 一起退出）
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
uv run python -m engine.server.server --port 8765 --time-scale 2 &
sleep 2
uv run python studio/server.py --port 8899 --runtime-url ws://127.0.0.1:8765 &
echo ""
echo "  ◈ SoulForge Studio → http://127.0.0.1:8899   (Ctrl-C 退出)"
echo ""
wait
