import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { Plus } from "lucide-react";
import { getCharacterEmoji, getCharacterGradient } from "@/lib/avatar";
import { requireBrandId } from "@/lib/server-auth";

const statusMap = {
  PUBLISHED: { label: "已发布", color: "bg-emerald-100 text-emerald-600" },
  DRAFT: { label: "草稿", color: "bg-gray-100 text-gray-500" },
  ARCHIVED: { label: "已归档", color: "bg-gray-50 text-gray-400" },
};

const archetypeMap: Record<string, { label: string; color: string }> = {
  ANIMAL: { label: "动物", color: "bg-amber-100 text-amber-600" },
  HUMAN: { label: "人类", color: "bg-violet-100 text-violet-600" },
  FANTASY: { label: "幻想", color: "bg-cyan-100 text-cyan-600" },
  ABSTRACT: { label: "助手", color: "bg-emerald-100 text-emerald-600" },
};

export default async function CharactersPage() {
  const brandId = await requireBrandId();
  const characters = await prisma.character.findMany({
    where: { brandId },
    orderBy: { createdAt: "desc" },
    include: { voice: true },
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight text-gray-900">角色</h1>
          <p className="text-[14px] text-gray-400 mt-1">
            创建和管理你的 AI 角色
          </p>
        </div>
        <Link
          href="/dashboard/characters/new"
          className="btn-primary flex items-center gap-2 text-[13px]"
        >
          <Plus className="w-4 h-4" />
          创建角色
        </Link>
      </div>

      {characters.length === 0 ? (
        <div className="text-center py-28 animate-fade-in">
          <div className="w-16 h-16 mx-auto mb-5 rounded-2xl bg-gradient-to-br from-blue-50 to-blue-100 flex items-center justify-center">
            <span className="text-3xl">🕯️</span>
          </div>
          <p className="text-gray-500 text-[15px]">还没有角色</p>
          <p className="text-[13px] text-gray-400 mt-1">点击上方按钮创建你的第一个角色</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {characters.map((char, i) => {
            const personality = char.personality as Record<string, number>;
            const status =
              statusMap[char.status as keyof typeof statusMap] || statusMap.DRAFT;
            const pVals = Object.values(personality || {});
            const soulPower = pVals.length > 0
              ? Math.round(pVals.reduce((a, b) => a + b, 0) / pVals.length)
              : 50;

            return (
              <Link
                key={char.id}
                href={`/dashboard/characters/${char.id}`}
                className={`group block p-5 rounded-2xl glass card-hover animate-fade-in stagger-${Math.min(i + 1, 6)}`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-[12px] bg-gradient-to-br ${getCharacterGradient(char.id)} flex items-center justify-center text-lg transition-transform duration-300 group-hover:scale-105`}>
                      {getCharacterEmoji(char.species)}
                    </div>
                    <div>
                      <h2 className="font-semibold text-[15px] text-gray-900 group-hover:text-blue-600 transition-colors duration-200">
                        {char.name}
                      </h2>
                      <p className="text-[11px] text-gray-400">
                        {char.species} · {char.relationship || "朋友"}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {archetypeMap[char.archetype as string] && (
                      <span className={`px-2 py-[2px] text-[9px] rounded-full font-medium ${archetypeMap[char.archetype as string].color}`}>
                        {archetypeMap[char.archetype as string].label}
                      </span>
                    )}
                    <span className={`px-2.5 py-[3px] text-[10px] rounded-full font-medium ${status.color}`}>
                      {status.label}
                    </span>
                  </div>
                </div>

                {/* Backstory */}
                <p className="text-[12px] text-gray-400 line-clamp-2 mb-4 leading-relaxed">
                  {char.backstory || "这个角色还没有故事..."}
                </p>

                {/* Soul Power */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-[10px] mb-1.5">
                    <span className="text-gray-400">灵魂强度</span>
                    <span className="text-blue-500 font-medium tabular-nums">{soulPower}%</span>
                  </div>
                  <div className="h-[3px] rounded-full bg-gray-100 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 stat-bar-fill"
                      style={{ width: `${soulPower}%` }}
                    />
                  </div>
                </div>

                {/* Tags */}
                <div className="flex flex-wrap gap-1.5">
                  {char.catchphrases.slice(0, 2).map((p, j) => (
                    <span
                      key={j}
                      className="px-2 py-[2px] text-[10px] rounded-full bg-gray-100 text-gray-500"
                    >
                      &ldquo;{p}&rdquo;
                    </span>
                  ))}
                  {char.voice && (
                    <span className="px-2 py-[2px] text-[10px] rounded-full bg-blue-50 text-blue-500">
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
