#!/usr/bin/env bash
# 复跑 docs/video-avatar-providers.md 里的结论。
# 默认只做不计费的校验探测；加 --billed 才会真正出片。
#
#   MINIMAX_API_KEY=... VIDU_API_KEY=... scripts/probe_video_providers.sh
#   MINIMAX_API_KEY=... VIDU_API_KEY=... scripts/probe_video_providers.sh --billed
set -u

MM_HOST="${MINIMAX_HOST:-https://api.minimax.io}"
VIDU_HOST="${VIDU_HOST:-https://api.vidu.com}"
BILLED=0
[ "${1:-}" = "--billed" ] && BILLED=1

mm() {
  curl -s -m 30 "$MM_HOST$1" \
    -H "Authorization: Bearer ${MINIMAX_API_KEY:?set MINIMAX_API_KEY}" \
    -H "Content-Type: application/json" ${2:+-d "$2"}
}

vd() {
  curl -s -m 90 "$VIDU_HOST$1" \
    -H "Authorization: Token ${VIDU_API_KEY:?set VIDU_API_KEY}" \
    -H "Content-Type: application/json" ${2:+-d "$2"}
}

err_msg() {
  python3 -c 'import sys,json
try: print(json.load(sys.stdin)["error"]["message"])
except Exception: print("(无法解析)")'
}

echo "### MiniMax 文本模型列表"
mm /v1/models | python3 -c 'import sys,json;print(", ".join(m["id"] for m in json.load(sys.stdin)["data"]))'

echo
echo "### H3 在 v1 上应被拒绝并指向 v2"
mm /v1/video_generation '{"model":"MiniMax-H3","prompt":"x","resolution":"__bad__"}' | head -c 200
echo

echo
echo "### H3 合法取值自述（故意传非法值，让接口报出枚举）"
echo "  [resolution] $(mm /v2/video_generation '{"model":"MiniMax-H3","content":[{"type":"text","text":"x"}],"duration":6,"resolution":"__bad__","ratio":"16:9"}' | err_msg)"
echo "  [duration]   $(mm /v2/video_generation '{"model":"MiniMax-H3","content":[{"type":"text","text":"x"}],"duration":999,"resolution":"480P","ratio":"16:9"}' | err_msg)"
echo "  [content]    $(mm /v2/video_generation '{"model":"MiniMax-H3","content":[{"type":"__bad__","text":"x"}],"duration":6,"resolution":"480P","ratio":"16:9"}' | err_msg)"

echo
echo "### Vidu /ent/v2 接受的模型（S2 不在其中）"
for m in viduq1 viduq1-classic vidu2.0 viduq2 viduq3 vidu-s2 s2 vidus2; do
  r=$(vd /ent/v2/text2video "{\"model\":\"$m\",\"prompt\":\"x\",\"resolution\":\"__bad__\"}")
  case "$r" in
    *"model is not supported"*) echo "  $m : 不支持" ;;
    *) echo "  $m : 支持" ;;
  esac
done

echo
echo "### Vidu S2 端点（校验层即可确认 vidu-s2 是否被接受）"
echo "  realtime  : $(vd /live/s_avatar/realtime '{"model":"vidu-s2"}' | head -c 130)"
echo "  component : $(vd /live/s_avatar/component '{"model":"vidu-s2"}' | head -c 130)"
echo "  offline   : $(vd /ent/s_avatar/offline '{"model":"vidu-s2","image":"https://scene.vidu.zone/media-asset/084945-xpk47RWYcBgJ27nJ.png","audio":"https://scene.vidu.zone/media-asset/085244-FrJjNf5tKjiZHQkf.mp3"}' | head -c 130)"

if [ "$BILLED" -eq 0 ]; then
  echo
  echo "（跳过真实出片。加 --billed 会消耗额度：H3 480P/4s；Vidu S2 实时会话不接 WS 时不计费。）"
  exit 0
fi

echo
echo "### H3 真实出片 480P/4s"
tid=$(mm /v2/video_generation '{"model":"MiniMax-H3","content":[{"type":"text","text":"A small orange robot on a desk waving hello, warm indoor lighting"}],"duration":4,"resolution":"480P","ratio":"16:9"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("task_id",""))')
echo "  task_id=$tid"
for i in $(seq 1 40); do
  r=$(mm "/v2/query/video_generation?task_id=$tid")
  st=$(echo "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["items"][0]["status"])' 2>/dev/null)
  echo "  [$i] $st"
  case "$st" in
    succeeded)
      echo "$r" | python3 -c 'import sys,json;print("  url:",json.load(sys.stdin)["items"][0]["content"]["url"])'
      break
      ;;
    failed)
      echo "$r"
      break
      ;;
  esac
  sleep 10
done

echo
echo "### Vidu S2 实时会话（不接 WebSocket，会 timeout 自动结束且不计费）"
vd /live/s_avatar/realtime '{"model":"vidu-s2","avatar":{"image_uri":"https://scene.vidu.zone/media-asset/084945-xpk47RWYcBgJ27nJ.png","persona":"A warm companion character."}}' \
  | python3 -c 'import sys,json
d=json.load(sys.stdin); l=d["live"]
print("  live_id:",l["id"],"status:",l["status"],"model:",l["model"])
print("  rtc 由 Vidu 提供:", bool(d.get("rtc",{}).get("app_id")))
print("  client_secret:", (d.get("client_secret","")[:24]+"...") if d.get("client_secret") else "无")'
