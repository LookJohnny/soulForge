import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { Plus } from "lucide-react";

const statusMap = {
  PUBLISHED: { label: "已觉醒", color: "bg-amber-500/20 text-amber-400" },
  DRAFT: { label: "沉睡中", color: "bg-amber-900/20 text-amber-600" },
  ARCHIVED: { label: "已封印", color: "bg-white/5 text-white/30" },
};

export default async function CharactersPage() {
  const characters = await prisma.character.findMany({
    orderBy: { createdAt: "desc" },
    include: { voice: true },
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold rune-text">灵魂祭坛</h1>
          <p className="text-sm text-amber-600/40 mt-1">
            在此锻铸、管理与召唤灵魂
          </p>
        </div>
        <Link
          href="/dashboard/characters/new"
          className="btn-primary flex items-center gap-2 text-sm"
        >
          <Plus className="w-4 h-4" />
          锻铸新灵魂
        </Link>
      </div>

      {characters.length === 0 ? (
        <div className="text-center py-24">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-amber-700/10 flex items-center justify-center animate-candle">
            <span className="text-4xl">&#128367;</span>
          </div>
          <p className="text-amber-400/40 mb-2">祭坛上空无一物</p>
          <p className="text-sm text-amber-700/30">点亮圣火，锻铸你的第一个灵魂</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {characters.map((char) => {
            const personality = char.personality as Record<string, number>;
            const status =
              statusMap[char.status as keyof typeof statusMap] || statusMap.DRAFT;
            const soulPower = personality
              ? Math.round(
                  Object.values(personality).reduce((a, b) => a + b, 0) /
                    Object.values(personality).length
                )
              : 50;

            return (
              <Link
                key={char.id}
                href={`/dashboard/characters/${char.id}`}
                className="group block p-5 rounded-2xl glass hover:glow-purple transition-all duration-300"
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-700/30 to-amber-900/30 flex items-center justify-center text-lg group-hover:animate-candle">
                      {char.species === "兔子"
                        ? "🐰"
                        : char.species === "熊"
                          ? "🐻"
                          : char.species === "猫" || char.species === "小猫"
                            ? "🐱"
                            : "🕯️"}
                    </div>
                    <div>
                      <h2 className="font-semibold text-amber-200/90 group-hover:text-amber-300 transition-colors">
                        {char.name}
                      </h2>
                      <p className="text-xs text-amber-600/30">
                        {char.species} · {char.relationship || "朋友"}
                      </p>
                    </div>
                  </div>
                  <span
                    className={`px-2 py-0.5 text-[10px] rounded-full ${status.color}`}
                  >
                    {status.label}
                  </span>
                </div>

                {/* Backstory preview */}
                <p className="text-xs text-amber-600/25 line-clamp-2 mb-4 leading-relaxed italic">
                  {char.backstory || "此灵魂尚未书写铭文..."}
                </p>

                {/* Soul Power Bar */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-[10px] mb-1.5">
                    <span className="text-amber-600/25">灵魂强度</span>
                    <span className="text-amber-400/60">{soulPower}%</span>
                  </div>
                  <div className="h-1 rounded-full bg-amber-900/15 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-amber-700 to-amber-400 stat-bar-fill"
                      style={{ width: `${soulPower}%` }}
                    />
                  </div>
                </div>

                {/* Tags */}
                <div className="flex flex-wrap gap-1.5">
                  {char.catchphrases.slice(0, 2).map((p, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 text-[10px] rounded-full bg-amber-700/10 text-amber-400/50"
                    >
                      &ldquo;{p}&rdquo;
                    </span>
                  ))}
                  {char.voice && (
                    <span className="px-2 py-0.5 text-[10px] rounded-full bg-amber-600/10 text-amber-400/40">
                      &#9835; {char.voice.name}
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
