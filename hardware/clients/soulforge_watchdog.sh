#!/bin/bash
# SoulForge/维智 大脑切换看门狗（跑在树莓派上，root，由 systemd timer 每分钟触发）
#
# 策略：网关健康 → 用 SoulForge 瘦客户端（云端大脑）；
#       网关连续 3 次检查失败（约 3 分钟）→ 降级本地维智（meimei）；
#       网关恢复 → 立即切回。
# 两个服务在 unit 里互为 Conflicts，start 其一会自动 stop 另一个。

# 用 Mac 的有线口 IP（192.168.1.172，稳定）；192.168.0.135 是会掉线的 WiFi 腿
GATEWAY_URL="${SF_GATEWAY_HEALTH_URL:-http://192.168.1.172:8080/ota/}"
FAILS_FILE=/run/soulforge-watchdog-fails
THRESHOLD=3

if curl -sf -m 5 "$GATEWAY_URL" >/dev/null; then
    echo 0 > "$FAILS_FILE"
    if ! systemctl is-active --quiet soulforge-client; then
        logger -t soulforge-watchdog "gateway up -> switching to soulforge-client"
        systemctl start soulforge-client
    fi
else
    fails=$(( $(cat "$FAILS_FILE" 2>/dev/null || echo 0) + 1 ))
    echo "$fails" > "$FAILS_FILE"
    if [ "$fails" -ge "$THRESHOLD" ] && ! systemctl is-active --quiet meimei; then
        logger -t soulforge-watchdog "gateway down x$fails -> falling back to meimei"
        systemctl start meimei
    fi
fi
