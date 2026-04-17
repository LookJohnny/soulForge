import { notFound } from "next/navigation";
import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { personalityToText } from "@soulforge/shared";
import type { PersonalityTraits } from "@soulforge/shared";
import ChatPanel from "@/components/chat-panel";
import { getCharacterEmoji, getCharacterGradient } from "@/lib/avatar";
import { requireBrandId } from "@/lib/server-auth";

const traitMeta: Record<string, { label: string; color: string }> = {
  extrovert: { label: "外向度", color: "from-blue-400 to-cyan-300" },
  humor:     { label: "幽默感", color: "from-amber-500 to-yellow-400" },
  warmth:    { label: "温暖度", color: "from-rose-500 to-orange-400" },
  curiosity: { label: "好奇心", color: "from-emerald-500 to-teal-400" },
  energy:    { label: "活力值", color: "from-amber-600 to-amber-400" },
};

export default async function CharacterDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const brandId = await requireBrandId();
  const { id } = await params;
  const character = await prisma.character.findFirst({
    where: { id, brandId },
    include: { voice: true },
  });

  if (!character) notFound();

  const personality = character.personality as unknown as PersonalityTraits;
  const personalityDesc = personalityToText(personality);
  const emoji = getCharacterEmoji(character.species);
  const gradient = getCharacterGradient(character.id);
  const values = Object.values(personality);
  const soulPower = values.length > 0
    ? Math.round(values.reduce((a, b) => a + b, 0) / values.length)
    : 50;

  return (
    <div className="max-w-5xl mx-auto">
      <Link
        href="/dashboard/characters"
        className="inline-flex items-center gap-1 text-[11px] text-white/20 hover:text-white/50 transition-colors mb-6"
      >
        ← 返回
      </Link>

      {/* Hero */}
      <div className="glass rounded-2xl p-7 mb-5 glow-gold relative overflow-hidden animate-fade-in">
        <div className="absolute top-0 right-0 w-64 h-64 bg-amber-500/3 rounded-full blur-3xl" />
        <div className="relative flex items-start gap-5">
          <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${gradient} flex items-center justify-center text-3xl shrink-0`}>
            {emoji}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-[26px] font-bold tracking-tight text-white/90">{character.name}</h1>
              <span className={`px-2.5 py-[3px] text-[10px] rounded-full font-medium ${
                character.status === "PUBLISHED" ? "bg-emerald-500/15 text-emerald-400/80" : "bg-white/[0.06] text-white/40"
              }`}>
                {character.status === "PUBLISHED" ? "已发布" : "草稿"}
              </span>
              {(character as { languageMode?: string }).languageMode === "VOCALIZED" && (
                <span className="px-2.5 py-[3px] text-[10px] rounded-full font-medium bg-violet-500/15 text-violet-300/80">
                  🐧 拟声角色
                </span>
              )}
            </div>
            <p className="text-[12px] text-white/30 mb-2">
              {character.species} · {character.relationship || "好朋友"} · {character.ageSetting ? `${character.ageSetting}岁` : "年龄未设定"}
            </p>
            <p className="text-[13px] text-white/40 italic">{personalityDesc}</p>
          </div>
          {/* Soul ring */}
          <div className="shrink-0">
            <div className="relative w-16 h-16">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="5" />
                <circle cx="50" cy="50" r="42" fill="none" stroke="url(#g)" strokeWidth="5" strokeLinecap="round"
                  strokeDasharray={`${soulPower * 2.64} ${264 - soulPower * 2.64}`} />
                <defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stopColor="#c9944a" /><stop offset="100%" stopColor="#d4a574" /></linearGradient></defs>
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-[18px] font-bold text-amber-300/80 tabular-nums">{soulPower}</span>
                <span className="text-[7px] text-white/20 tracking-wider">SOUL</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        {/* Backstory */}
        <div className="glass rounded-2xl p-5 animate-fade-in stagger-1">
          <h3 className="text-[11px] text-white/25 uppercase tracking-wider mb-3 font-medium">背景故事</h3>
          <p className="text-[13px] text-white/50 leading-relaxed whitespace-pre-line">
            {character.backstory || "这个角色还没有故事..."}
          </p>
        </div>

        {/* Personality */}
        <div className="glass rounded-2xl p-5 animate-fade-in stagger-2">
          <h3 className="text-[11px] text-white/25 uppercase tracking-wider mb-4 font-medium">性格属性</h3>
          <div className="space-y-3">
            {Object.entries(personality).map(([key, value]) => {
              const meta = traitMeta[key];
              if (!meta) return null;
              return (
                <div key={key} className="flex items-center gap-2.5">
                  <span className="text-[11px] text-white/30 w-12">{meta.label}</span>
                  <div className="flex-1 h-[3px] rounded-full bg-white/[0.04] overflow-hidden">
                    <div className={`h-full rounded-full bg-gradient-to-r ${meta.color} stat-bar-fill`} style={{ width: `${value}%` }} />
                  </div>
                  <span className="text-[11px] text-white/35 w-6 text-right tabular-nums">{value}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Speech */}
        <div className="glass rounded-2xl p-5 animate-fade-in stagger-3">
          <h3 className="text-[11px] text-white/25 uppercase tracking-wider mb-3 font-medium">说话风格</h3>
          {(character as { languageMode?: string; vocalizationPalette?: string[] }).languageMode === "VOCALIZED" && (() => {
            const palette = (character as { vocalizationPalette?: string[] }).vocalizationPalette || [];
            return palette.length > 0 ? (
              <div className="mb-3">
                <span className="text-[10px] text-white/20">拟声词库</span>
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {palette.map((v: string, i: number) => (
                    <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-violet-500/10 text-violet-300/70">&ldquo;{v}&rdquo;</span>
                  ))}
                </div>
              </div>
            ) : null;
          })()}
          {character.catchphrases.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] text-white/20">口头禅</span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {character.catchphrases.map((p, i) => (
                  <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-amber-500/8 text-amber-300/60">&ldquo;{p}&rdquo;</span>
                ))}
              </div>
            </div>
          )}
          {character.suffix && character.suffix !== "None" && (
            <div className="mb-3">
              <span className="text-[10px] text-white/20">句尾口癖</span>
              <p className="text-[13px] text-amber-300/60 mt-1">{character.suffix}</p>
            </div>
          )}
          <div>
            <span className="text-[10px] text-white/20">回复长度</span>
            <p className="text-[13px] text-white/40 mt-1">
              {character.responseLength === "SHORT" ? "简短" : character.responseLength === "MEDIUM" ? "适中" : "较长"}
            </p>
          </div>
        </div>

        {/* Topics & Voice */}
        <div className="glass rounded-2xl p-5 animate-fade-in stagger-4">
          <h3 className="text-[11px] text-white/25 uppercase tracking-wider mb-3 font-medium">话题与音色</h3>
          {character.topics.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] text-white/20">知识话题</span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {character.topics.map((t, i) => (
                  <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-emerald-500/8 text-emerald-300/60">{t}</span>
                ))}
              </div>
            </div>
          )}
          {character.forbidden.length > 0 && (
            <div className="mb-3">
              <span className="text-[10px] text-white/20">禁止话题</span>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {character.forbidden.map((f, i) => (
                  <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-red-500/8 text-red-400/50">{f}</span>
                ))}
              </div>
            </div>
          )}
          <div>
            <span className="text-[10px] text-white/20">音色</span>
            {(character as { voiceCloneRefId?: string; voiceCloneUrl?: string }).voiceCloneRefId ? (
              <p className="text-[13px] text-violet-300/70 mt-1">&#9835; 声音克隆 (Fish Audio) · {character.voiceSpeed}x</p>
            ) : (character as { voiceCloneUrl?: string }).voiceCloneUrl ? (
              <p className="text-[13px] text-amber-300/70 mt-1">&#9835; 克隆样本已上传，待生成 · {character.voiceSpeed}x</p>
            ) : character.voice ? (
              <p className="text-[13px] text-white/40 mt-1">&#9835; {character.voice.name} · {character.voiceSpeed}x</p>
            ) : (
              <p className="text-[12px] text-white/25 mt-1">自动匹配（基于性格向量）</p>
            )}
          </div>
        </div>
      </div>

      {/* Chat */}
      <div className="animate-fade-in stagger-5">
        <ChatPanel characterId={character.id} characterName={character.name} characterEmoji={emoji} />
      </div>
    </div>
  );
}
