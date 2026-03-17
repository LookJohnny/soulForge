import { prisma } from "@/lib/prisma";
import { Music } from "lucide-react";
import VoicePreview from "@/components/voice-preview";

export default async function VoicesPage() {
  const voices = await prisma.voiceProfile.findMany({
    orderBy: { createdAt: "desc" },
  });

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-[26px] font-bold tracking-tight text-gold">音色</h1>
        <p className="text-[13px] text-white/30 mt-1">管理和试听角色音色库</p>
      </div>

      {voices.length === 0 ? (
        <div className="text-center py-28 animate-fade-in">
          <div className="w-16 h-16 mx-auto mb-5 rounded-2xl bg-white/[0.03] flex items-center justify-center">
            <Music className="w-7 h-7 text-white/20" />
          </div>
          <p className="text-white/30">还没有音色</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {voices.map((voice, i) => (
            <div
              key={voice.id}
              className={`glass rounded-2xl p-5 card-hover group animate-fade-in stagger-${Math.min(i + 1, 6)}`}
            >
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-[12px] bg-gradient-to-br from-amber-500/10 to-amber-700/8 flex items-center justify-center transition-transform duration-500 group-hover:scale-110">
                    <Music className="w-5 h-5 text-amber-400/50" />
                  </div>
                  <div>
                    <h2 className="font-semibold text-[14px] text-white/80 group-hover:text-amber-200 transition-colors duration-300">
                      {voice.name}
                    </h2>
                    {voice.dashscopeVoiceId && (
                      <p className="text-[10px] text-white/15 font-mono">{voice.dashscopeVoiceId}</p>
                    )}
                  </div>
                </div>
                <VoicePreview voiceId={voice.dashscopeVoiceId} voiceName={voice.name} />
              </div>

              <p className="text-[12px] text-white/20 mb-4 leading-relaxed">
                {voice.description || "暂无描述"}
              </p>

              {/* Waveform visualization */}
              <div className="flex items-end gap-[2px] h-7 mb-4 opacity-60 group-hover:opacity-100 transition-opacity duration-500">
                {Array.from({ length: 36 }).map((_, j) => {
                  const h = Math.sin(j * 0.5 + voice.name.length) * 50 + 50;
                  return (
                    <div
                      key={j}
                      className="flex-1 rounded-full bg-gradient-to-t from-amber-500/25 to-amber-400/5 transition-all duration-500"
                      style={{ height: `${Math.max(10, h)}%`, transitionDelay: `${j * 10}ms` }}
                    />
                  );
                })}
              </div>

              <div className="flex flex-wrap gap-1.5">
                {voice.tags.map((tag, j) => (
                  <span key={j} className="px-2 py-[2px] text-[10px] rounded-full bg-white/[0.04] text-white/30">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
