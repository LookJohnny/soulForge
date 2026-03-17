import { notFound } from "next/navigation";
import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { personalityToText } from "@soulforge/shared";
import type { PersonalityTraits } from "@soulforge/shared";
import ChatPanel from "@/components/chat-panel";

const traitMeta: Record<
  string,
  { label: string; emoji: string; color: string }
> = {
  extrovert: { label: "外向度", emoji: "💬", color: "from-blue-500 to-cyan-400" },
  humor: { label: "幽默感", emoji: "😄", color: "from-amber-500 to-yellow-400" },
  warmth: { label: "温暖度", emoji: "💖", color: "from-rose-500 to-pink-400" },
  curiosity: { label: "好奇心", emoji: "🔍", color: "from-emerald-500 to-green-400" },
  energy: { label: "活力值", emoji: "⚡", color: "from-purple-500 to-fuchsia-400" },
};

const speciesEmoji: Record<string, string> = {
  兔子: "🐰",
  熊: "🐻",
  猫: "🐱",
  狗: "🐶",
  狐狸: "🦊",
  企鹅: "🐧",
  龙: "🐉",
  独角兽: "🦄",
};

export default async function CharacterDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const character = await prisma.character.findUnique({
    where: { id },
    include: { voice: true },
  });

  if (!character) notFound();

  const personality = character.personality as unknown as PersonalityTraits;
  const personalityDesc = personalityToText(personality);
  const emoji = speciesEmoji[character.species] || "✨";
  const soulPower = Math.round(
    Object.values(personality).reduce((a, b) => a + b, 0) /
      Object.values(personality).length
  );

  return (
    <div className="max-w-5xl mx-auto">
      {/* Back link */}
      <Link
        href="/dashboard/characters"
        className="inline-flex items-center gap-1 text-xs text-white/25 hover:text-white/50 transition-colors mb-6"
      >
        ← 返回角色列表
      </Link>

      {/* Hero section */}
      <div className="glass rounded-2xl p-8 mb-6 glow-purple relative overflow-hidden">
        {/* Background glow */}
        <div className="absolute top-0 right-0 w-64 h-64 bg-purple-500/5 rounded-full blur-3xl" />

        <div className="relative flex items-start gap-6">
          {/* Avatar */}
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-purple-500/30 to-pink-500/30 flex items-center justify-center text-4xl shrink-0">
            {emoji}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-3xl font-bold text-white/95">
                {character.name}
              </h1>
              <span
                className={`px-2.5 py-0.5 text-[10px] rounded-full ${
                  character.status === "PUBLISHED"
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-amber-500/20 text-amber-400"
                }`}
              >
                {character.status === "PUBLISHED" ? "已发布" : "草稿"}
              </span>
            </div>
            <p className="text-sm text-white/35 mb-3">
              {character.species} · {character.relationship || "朋友"} ·{" "}
              {character.ageSetting ? `${character.ageSetting}岁` : "年龄未设定"}
            </p>
            <p className="text-sm text-white/50 italic">
              {personalityDesc}
            </p>
          </div>

          {/* Soul power ring */}
          <div className="shrink-0">
            <div className="relative w-20 h-20">
              <svg
                className="w-full h-full -rotate-90"
                viewBox="0 0 100 100"
              >
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  fill="none"
                  stroke="rgba(255,255,255,0.05)"
                  strokeWidth="5"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  fill="none"
                  stroke="url(#grad)"
                  strokeWidth="5"
                  strokeLinecap="round"
                  strokeDasharray={`${soulPower * 2.64} ${264 - soulPower * 2.64}`}
                />
                <defs>
                  <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#a855f7" />
                    <stop offset="100%" stopColor="#ec4899" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-xl font-bold text-white/85">
                  {soulPower}
                </span>
                <span className="text-[8px] text-white/25">SOUL</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Grid layout */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Backstory */}
        <div className="glass rounded-2xl p-6">
          <h3 className="text-xs text-white/35 uppercase tracking-wider mb-3">
            背景故事
          </h3>
          <p className="text-sm text-white/60 leading-relaxed">
            {character.backstory || "这个灵魂还没有故事..."}
          </p>
        </div>

        {/* Personality stats */}
        <div className="glass rounded-2xl p-6">
          <h3 className="text-xs text-white/35 uppercase tracking-wider mb-4">
            灵魂属性
          </h3>
          <div className="space-y-3">
            {Object.entries(personality).map(([key, value]) => {
              const meta = traitMeta[key];
              if (!meta) return null;
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-sm">{meta.emoji}</span>
                  <span className="text-xs text-white/35 w-12">
                    {meta.label}
                  </span>
                  <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r ${meta.color} stat-bar-fill`}
                      style={{ width: `${value}%` }}
                    />
                  </div>
                  <span className="text-xs text-white/40 w-7 text-right tabular-nums font-medium">
                    {value}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Speech style */}
        <div className="glass rounded-2xl p-6">
          <h3 className="text-xs text-white/35 uppercase tracking-wider mb-4">
            说话风格
          </h3>

          {character.catchphrases.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] text-white/25">口头禅</span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {character.catchphrases.map((p, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 text-xs rounded-full bg-purple-500/15 text-purple-300/80"
                  >
                    &ldquo;{p}&rdquo;
                  </span>
                ))}
              </div>
            </div>
          )}

          {character.suffix && (
            <div className="mb-3">
              <span className="text-[10px] text-white/25">句尾习惯</span>
              <p className="text-sm text-cyan-400/60 mt-1">
                {character.suffix}
              </p>
            </div>
          )}

          <div>
            <span className="text-[10px] text-white/25">回复长度</span>
            <p className="text-sm text-white/45 mt-1">
              {character.responseLength === "SHORT"
                ? "简短 (1-2句)"
                : character.responseLength === "MEDIUM"
                  ? "适中 (2-3句)"
                  : "较长 (4-5句)"}
            </p>
          </div>
        </div>

        {/* Topics & Voice */}
        <div className="glass rounded-2xl p-6">
          <h3 className="text-xs text-white/35 uppercase tracking-wider mb-4">
            话题与音色
          </h3>

          {character.topics.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] text-white/25">知识话题</span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {character.topics.map((t, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 text-xs rounded-full bg-emerald-500/15 text-emerald-300/70"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {character.forbidden.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] text-white/25">禁忌话题</span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {character.forbidden.map((f, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 text-xs rounded-full bg-red-500/15 text-red-300/70"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}

          {character.voice ? (
            <div>
              <span className="text-[10px] text-white/25">音色</span>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="text-sm text-white/50">
                  🎵 {character.voice.name}
                </span>
                {character.voice.tags.map((tag, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 text-[10px] rounded-full bg-cyan-500/10 text-cyan-400/50"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <p className="text-xs text-white/25 mt-1">
                语速: {character.voiceSpeed}x
              </p>
            </div>
          ) : (
            <div>
              <span className="text-[10px] text-white/25">音色</span>
              <p className="text-xs text-white/25 mt-1">未配置</p>
            </div>
          )}
        </div>
      </div>

      {/* Chat panel */}
      <div className="mt-6">
        <ChatPanel
          characterId={character.id}
          characterName={character.name}
          characterEmoji={emoji}
        />
      </div>
    </div>
  );
}
