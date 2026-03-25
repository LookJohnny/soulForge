"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Heart, Loader2 } from "lucide-react";

const presets = [
  { key: "tsundere", name: "月宫铃奈", type: "傲娇少女", emoji: "😤", color: "from-rose-100 to-pink-50", desc: "嘴硬心软，说着'才不是为你呢'却偷偷关心你" },
  { key: "dojikko", name: "花丸小雪", type: "天然呆少女", emoji: "😊", color: "from-amber-100 to-yellow-50", desc: "迷迷糊糊但纯真善良，偶尔冒出惊人洞察力" },
  { key: "yandere", name: "绯樱真白", type: "温柔少女", emoji: "🥰", color: "from-red-100 to-rose-50", desc: "温柔体贴的完美女孩，有着极强的独占欲" },
  { key: "genki", name: "阳菜日向", type: "元气少女", emoji: "✨", color: "from-orange-100 to-amber-50", desc: "像太阳一样充满活力，永远积极向上" },
  { key: "kuudere", name: "冰堂静", type: "高冷少女", emoji: "❄️", color: "from-blue-100 to-cyan-50", desc: "表面冷冰冰，偶尔的关心比甜言蜜语更动人" },
  { key: "oneesama", name: "柊宫灵华", type: "温柔学姐", emoji: "🌸", color: "from-pink-100 to-violet-50", desc: "成熟温柔的大姐姐，像港湾一样让人安心" },
  { key: "shounen", name: "晓月辰", type: "阳光少年", emoji: "⚡", color: "from-cyan-100 to-blue-50", desc: "爱笑直率热血，喜欢就是喜欢从不遮掩" },
  { key: "prince", name: "暮影司", type: "腹黑王子", emoji: "🎭", color: "from-violet-100 to-purple-50", desc: "温文尔雅的学生会长，偶尔露出腹黑的一面" },
];

const scenes = [
  { key: "morning_call", label: "早安叫醒", emoji: "🌅", desc: "温柔地叫你起床" },
  { key: "goodnight", label: "晚安陪伴", emoji: "🌙", desc: "哄你入睡" },
  { key: "lunch_break", label: "午间闲聊", emoji: "🍱", desc: "关心你有没有好好吃饭" },
  { key: "after_work", label: "下班慰劳", emoji: "🏠", desc: "温柔地迎接你回来" },
  { key: "jealous", label: "吃醋", emoji: "😾", desc: "有点不高兴..." },
  { key: "missing", label: "想你了", emoji: "💭", desc: "撒娇地表达想念" },
  { key: "encourage", label: "加油鼓励", emoji: "💪", desc: "给你力量和支持" },
  { key: "date", label: "约会", emoji: "💕", desc: "甜蜜浪漫的时光" },
];

export default function IdolPage() {
  const router = useRouter();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleCreate = async (presetKey: string) => {
    setCreating(true);
    const preset = presets.find((p) => p.key === presetKey);
    if (!preset) {
      setCreating(false);
      return;
    }

    try {
      let payload: Record<string, unknown>;
      try {
        const presetRes = await fetch(`/api/idol/preset/${presetKey}`);
        if (presetRes.ok) {
          const json = await presetRes.json();
          const p = json.preset;
          payload = {
            name: p.name,
            archetype: p.archetype,
            species: p.species,
            backstory: p.backstory,
            personality: p.personality,
            relationship: p.relationship,
            catchphrases: p.catchphrases || [],
            suffix: p.suffix || null,
            topics: p.topics || [],
            forbidden: p.forbidden || [],
            responseLength: p.response_length || "SHORT",
          };
        } else {
          throw new Error(`Preset fetch failed: ${presetRes.status}`);
        }
      } catch (presetErr) {
        console.warn("Failed to fetch preset from AI Core, using fallback:", presetErr);
        payload = {
          name: preset.name,
          archetype: "HUMAN",
          species: preset.type,
          backstory: preset.desc,
          personality: { extrovert: 50, humor: 50, warmth: 50, curiosity: 50, energy: 50 },
          relationship: "暧昧对象",
          responseLength: "SHORT",
        };
      }

      const res = await fetch("/api/characters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const { id } = await res.json();
        router.push(`/dashboard/characters/${id}`);
      } else {
        const err = await res.json().catch(() => ({}));
        console.error("Character create failed:", err);
        alert(`创建失败: ${err.error || res.statusText}`);
      }
    } catch (e) {
      console.error("Character create error:", e);
      alert("创建失败，请检查网络连接");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="w-5 h-5 text-blue-500" />
          <h1 className="text-[28px] font-bold tracking-tight text-gray-900">虚拟偶像</h1>
        </div>
        <p className="text-[14px] text-gray-400 mt-1">
          选择一个人设模板，一键创建 24/7 AI 语音伴侣
        </p>
      </div>

      {/* Preset grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-12">
        {presets.map((preset, i) => (
          <div
            key={preset.key}
            role="button"
            tabIndex={0}
            onClick={() => !creating && setSelected(selected === preset.key ? null : preset.key)}
            onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !creating) { e.preventDefault(); setSelected(selected === preset.key ? null : preset.key); } }}
            className={`group text-left p-5 rounded-2xl transition-all duration-200 cursor-pointer animate-fade-in stagger-${Math.min(i + 1, 6)} ${
              selected === preset.key
                ? "ring-2 ring-blue-500/40 bg-blue-50/50 shadow-md"
                : "glass card-hover"
            }`}
          >
            <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${preset.color} flex items-center justify-center text-2xl mb-3 transition-transform duration-300 group-hover:scale-105`}>
              {preset.emoji}
            </div>
            <h3 className="text-[15px] font-semibold text-gray-900 mb-0.5">{preset.name}</h3>
            <p className="text-[11px] text-blue-500/70 font-medium mb-2">{preset.type}</p>
            <p className="text-[12px] text-gray-400 leading-relaxed line-clamp-2">{preset.desc}</p>
            {selected === preset.key && (
              <button
                onClick={(e) => { e.stopPropagation(); handleCreate(preset.key); }}
                disabled={creating}
                className="mt-3 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-[13px] font-medium bg-blue-500 text-white hover:bg-blue-600 transition-colors disabled:opacity-40 shadow-sm"
              >
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Heart className="w-3.5 h-3.5" />}
                {creating ? "创建中..." : "一键创建"}
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Scenes */}
      <div className="mb-8">
        <h2 className="text-[20px] font-bold tracking-tight text-gray-900 mb-1">互动场景</h2>
        <p className="text-[13px] text-gray-400 mb-5">创建角色后，可以通过 API 指定场景来触发不同的互动模式</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {scenes.map((scene) => (
            <div key={scene.key} className="glass rounded-xl p-4">
              <div className="text-xl mb-2">{scene.emoji}</div>
              <h4 className="text-[13px] font-medium text-gray-700 mb-0.5">{scene.label}</h4>
              <p className="text-[11px] text-gray-400">{scene.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
