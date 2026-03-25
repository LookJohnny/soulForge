import { prisma } from "@/lib/prisma";
import { Cpu, Wifi, WifiOff, Wrench } from "lucide-react";
import { requireBrandId } from "@/lib/server-auth";

const statusConfig = {
  ACTIVE: {
    label: "在线",
    color: "bg-emerald-500/20 text-emerald-400",
    dot: "bg-emerald-400",
    icon: Wifi,
  },
  OFFLINE: {
    label: "离线",
    color: "bg-white/5 text-white/30",
    dot: "bg-white/20",
    icon: WifiOff,
  },
  MAINTENANCE: {
    label: "维护中",
    color: "bg-amber-500/20 text-amber-400",
    dot: "bg-amber-400",
    icon: Wrench,
  },
};

export default async function DevicesPage() {
  const brandId = await requireBrandId();
  const devices = await prisma.device.findMany({
    where: { character: { brandId } },
    orderBy: { updatedAt: "desc" },
    include: { character: true },
  });

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-[26px] font-bold tracking-tight text-gold">设备</h1>
        <p className="text-[13px] text-white/30 mt-1">查看已连接的设备状态</p>
      </div>

      {devices.length === 0 ? (
        <div className="text-center py-24">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-amber-500/10 flex items-center justify-center">
            <Cpu className="w-8 h-8 text-amber-400/50" />
          </div>
          <p className="text-white/30 mb-2">还没有设备</p>
          <p className="text-xs text-white/20">
            当ESP32设备连接到Gateway后会自动显示在这里
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((device) => {
            const status =
              statusConfig[device.status as keyof typeof statusConfig] ||
              statusConfig.OFFLINE;
            const StatusIcon = status.icon;

            return (
              <div
                key={device.id}
                className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 flex items-center justify-center">
                      <StatusIcon className="w-5 h-5 text-amber-400/70" />
                    </div>
                    <div>
                      <p className="text-xs font-mono text-white/60">
                        {device.id.slice(0, 17)}
                      </p>
                      <p className="text-xs text-white/25 mt-0.5">
                        {device.hardwareModel || "ESP32-S3"}
                      </p>
                    </div>
                  </div>
                  <span
                    className={`flex items-center gap-1.5 px-2 py-0.5 text-[10px] rounded-full ${status.color}`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${status.dot} ${device.status === "ACTIVE" ? "animate-pulse" : ""}`}
                    />
                    {status.label}
                  </span>
                </div>

                {device.character && (
                  <div className="mb-3 px-3 py-2 rounded-lg bg-amber-500/8">
                    <span className="text-[10px] text-white/25">绑定角色</span>
                    <p className="text-sm text-amber-300/70">
                      {device.character.name}
                    </p>
                  </div>
                )}

                <div className="flex items-center justify-between text-[10px] text-white/20">
                  <span>
                    固件 {device.firmwareVer || "-"}
                  </span>
                  <span>
                    {device.lastSeen
                      ? new Date(device.lastSeen).toLocaleString("zh-CN", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "从未上线"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
