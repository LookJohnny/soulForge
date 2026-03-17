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
        <h1 className="text-2xl font-bold rune-text">梵音圣殿</h1>
        <p className="text-sm text-amber-600/40 mt-1">聆听与管理灵魂的声音容器</p>
      </div>

      {voices.length === 0 ? (
        <div className="text-center py-24">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-amber-700/10 flex items-center justify-center">
            <Music className="w-8 h-8 text-amber-500/40" />
          </div>
          <p className="text-amber-400/40">圣殿中尚无梵音</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {voices.map((voice) => (
            <div
              key={voice.id}
              className="glass rounded-2xl p-5 hover:glow-purple transition-all duration-300 group"
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-600/20 to-amber-800/20 flex items-center justify-center">
                    <Music className="w-5 h-5 text-amber-400/60" />
                  </div>
                  <div>
                    <h2 className="font-semibold text-amber-200/85 group-hover:text-amber-300 transition-colors">
                      {voice.name}
                    </h2>
                    {voice.dashscopeVoiceId && (
                      <p className="text-[10px] text-amber-700/30 font-mono">
                        {voice.dashscopeVoiceId}
                      </p>
                    )}
                  </div>
                </div>
                <VoicePreview
                  voiceId={voice.dashscopeVoiceId}
                  voiceName={voice.name}
                />
              </div>

              <p className="text-xs text-amber-600/30 mb-4 leading-relaxed italic">
                {voice.description || "此梵音尚无铭述"}
              </p>

              {/* Waveform — sacred frequencies */}
              <div className="flex items-end gap-px h-8 mb-4">
                {Array.from({ length: 32 }).map((_, i) => {
                  const h =
                    Math.sin(i * 0.5 + voice.name.length) * 50 + 50;
                  return (
                    <div
                      key={i}
                      className="flex-1 rounded-full bg-gradient-to-t from-amber-600/25 to-amber-400/8"
                      style={{ height: `${Math.max(8, h)}%` }}
                    />
                  );
                })}
              </div>

              {/* Tags */}
              <div className="flex flex-wrap gap-1.5">
                {voice.tags.map((tag, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 text-[10px] rounded-full bg-amber-700/10 text-amber-400/50"
                  >
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
