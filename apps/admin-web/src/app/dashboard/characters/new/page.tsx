"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronRight,
  ChevronLeft,
  Flame,
  Check,
  Volume2,
  Loader2,
} from "lucide-react";
import type { PersonalityTraits } from "@soulforge/shared";

const steps = [
  { id: "basic", label: "基本信息" },
  { id: "personality", label: "性格" },
  { id: "speech", label: "说话风格" },
  { id: "voice", label: "音色 & 语言" },
  { id: "boundary", label: "话题边界" },
  { id: "preview", label: "预览" },
];

const traitConfig: {
  key: keyof PersonalityTraits;
  label: string;
  low: string;
  high: string;
  color: string;
}[] = [
  { key: "extrovert", label: "外向度", low: "内敛", high: "外向", color: "from-blue-400 to-cyan-300" },
  { key: "humor", label: "幽默感", low: "严肃", high: "幽默", color: "from-amber-500 to-yellow-400" },
  { key: "warmth", label: "温暖度", low: "冷酷", high: "温暖", color: "from-rose-500 to-orange-400" },
  { key: "curiosity", label: "好奇心", low: "淡定", high: "好奇", color: "from-emerald-500 to-teal-400" },
  { key: "energy", label: "活力值", low: "慵懒", high: "活力", color: "from-amber-600 to-amber-400" },
];

const archetypeOptions = [
  { value: "ANIMAL", label: "动物角色", emoji: "🐾", desc: "毛绒玩具 / 动物伙伴" },
  { value: "HUMAN", label: "人类角色", emoji: "👤", desc: "老师 / 朋友 / 偶像" },
  { value: "FANTASY", label: "幻想角色", emoji: "✨", desc: "精灵 / 机器人 / 仙女" },
  { value: "ABSTRACT", label: "语音助手", emoji: "🎙️", desc: "无具体形象的助手" },
];

const contentTierOptions = [
  { value: "children", label: "儿童模式", desc: "全量安全过滤" },
  { value: "adult", label: "成人模式", desc: "放开恋爱场景" },
];

const speciesOptions = [
  { value: "兔子", emoji: "🐰" },
  { value: "熊", emoji: "🐻" },
  { value: "猫", emoji: "🐱" },
  { value: "狗", emoji: "🐶" },
  { value: "狐狸", emoji: "🦊" },
  { value: "企鹅", emoji: "🐧" },
  { value: "龙", emoji: "🐉" },
  { value: "独角兽", emoji: "🦄" },
];

const humanRoles = ["温柔姐姐", "老师", "朋友", "少年", "学长", "偶像"];
const fantasyRoles = ["精灵", "机器人", "天使", "仙女", "恶魔", "吸血鬼"];

export default function NewCharacterPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [form, setForm] = useState({
    archetype: "ANIMAL" as "ANIMAL" | "HUMAN" | "FANTASY" | "ABSTRACT",
    contentTier: "children" as "children" | "adult",
    name: "",
    species: "",
    customSpecies: "",
    ageSetting: "",
    backstory: "",
    relationship: "好朋友",
    personality: { extrovert: 50, humor: 50, warmth: 50, curiosity: 50, energy: 50 } as PersonalityTraits,
    catchphrases: [""],
    suffix: "",
    topics: [""],
    forbidden: ["暴力", "恐怖"],
    responseLength: "SHORT" as "SHORT" | "MEDIUM" | "LONG",
    // Vocalized mode: 咕咕嘎嘎 / doro-style non-verbal characters
    languageMode: "VERBAL" as "VERBAL" | "VOCALIZED",
    vocalizationPalette: [""],
    voiceCloneUrl: "",
    voiceCloneRefId: "",
    audioClipsRaw: [{ phrase: "", url: "" }],
  });
  const [cloning, setCloning] = useState(false);
  const [cloneError, setCloneError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setSaving(true);
    // Audio clips: collect non-empty { phrase, url } pairs into a map.
    // Only persisted for VOCALIZED characters where they're meaningful.
    const audioClips =
      form.languageMode === "VOCALIZED"
        ? form.audioClipsRaw
            .filter((c) => c.phrase && c.url)
            .reduce<Record<string, string>>((acc, c) => {
              acc[c.phrase] = c.url;
              return acc;
            }, {})
        : null;
    const audioClipsFinal = audioClips && Object.keys(audioClips).length > 0 ? audioClips : null;

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { audioClipsRaw: _ignored, customSpecies: _ignored2, contentTier: _ignored3, ...base } = form;
    const payload = {
      ...base,
      species: form.archetype === "ABSTRACT" ? null : (form.species || form.customSpecies || null),
      ageSetting: form.ageSetting ? parseInt(form.ageSetting) : null,
      catchphrases: form.catchphrases.filter(Boolean),
      topics: form.topics.filter(Boolean),
      forbidden: form.forbidden.filter(Boolean),
      vocalizationPalette: form.languageMode === "VOCALIZED" ? form.vocalizationPalette.filter(Boolean) : [],
      voiceCloneUrl: form.voiceCloneUrl || null,
      voiceCloneRefId: form.voiceCloneRefId || null,
      audioClips: audioClipsFinal,
    };
    const res = await fetch("/api/characters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const { id } = await res.json();
      router.push(`/dashboard/characters/${id}`);
    } else {
      setSaving(false);
      alert("创建失败，请重试");
    }
  };

  const triggerVoiceClone = async () => {
    const url = form.voiceCloneUrl.trim();
    if (!url) {
      setCloneError("请先填写音频 URL");
      return;
    }
    setCloning(true);
    setCloneError(null);
    try {
      const res = await fetch("/api/voice-clone/from-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audioUrl: url,
          title: form.name || "未命名角色",
          description: `${form.archetype} ${form.species || form.customSpecies || ""}`.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setCloneError(data.error || `克隆失败 (HTTP ${res.status})`);
        return;
      }
      if (!data.fishAudioId) {
        setCloneError("返回内容缺少 fishAudioId");
        return;
      }
      setForm((prev) => ({ ...prev, voiceCloneRefId: data.fishAudioId }));
    } catch (e) {
      setCloneError(e instanceof Error ? e.message : "网络错误");
    } finally {
      setCloning(false);
    }
  };

  const previewVoice = async () => {
    setPreviewing(true);
    try {
      const sampleText = `你好呀，我是${form.name || "角色"}，很高兴认识你！`;
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "tts", text: sampleText }),
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (data.audio_base64) {
        const raw = atob(data.audio_base64);
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        const isMP3 = (bytes[0] === 0x49 && bytes[1] === 0x44) || (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0);
        const blob = new Blob([bytes], { type: isMP3 ? "audio/mpeg" : "audio/wav" });
        const audio = new Audio(URL.createObjectURL(blob));
        audio.onended = () => URL.revokeObjectURL(audio.src);
        await audio.play();
      }
    } catch {
      // Silently fail — TTS might not be running
    }
    setPreviewing(false);
  };

  const canNext = () => {
    if (step === 0) {
      if (!form.name) return false;
      if (form.archetype === "ABSTRACT") return true;
      return form.species || form.customSpecies;
    }
    if (step === 3 && form.languageMode === "VOCALIZED") {
      // Vocalized characters need at least one palette entry so the prompt
      // can give the LLM something to draw from.
      return form.vocalizationPalette.some((v) => v.trim().length > 0);
    }
    return true;
  };

  const soulPower = Math.round(
    Object.values(form.personality).reduce((a, b) => a + b, 0) / Object.values(form.personality).length
  );

  return (
    <div className="max-w-4xl mx-auto">
      {/* Apple-style progress bar */}
      <div className="flex items-center justify-center gap-3 mb-12">
        {steps.map((s, i) => (
          <div key={s.id} className="flex items-center gap-3">
            <button
              onClick={() => i <= step && setStep(i)}
              className={`flex items-center gap-1.5 text-[12px] font-medium transition-all duration-300 ${
                i === step
                  ? "text-amber-300"
                  : i < step
                    ? "text-amber-500/50 hover:text-amber-400"
                    : "text-white/15"
              }`}
            >
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] transition-all duration-300 ${
                i < step
                  ? "bg-amber-500/20 text-amber-400"
                  : i === step
                    ? "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30"
                    : "bg-white/[0.04] text-white/20"
              }`}>
                {i < step ? <Check className="w-3 h-3" /> : i + 1}
              </div>
              <span className="hidden md:inline">{s.label}</span>
            </button>
            {i < steps.length - 1 && (
              <div className={`w-6 h-px transition-colors duration-300 ${i < step ? "bg-amber-500/25" : "bg-white/[0.04]"}`} />
            )}
          </div>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        >
          {/* ─── Step 0: Basic ───── */}
          {step === 0 && (
            <div className="max-w-xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-[22px] font-bold tracking-tight text-gold">基本信息</h2>
                <p className="text-[13px] text-white/25 mt-1">选择角色类型和基本设定</p>
              </div>

              {/* Archetype selector */}
              <div className="mb-6">
                <label className="block text-[11px] text-white/35 mb-3 font-medium tracking-wide uppercase">角色类型</label>
                <div className="grid grid-cols-4 gap-2.5">
                  {archetypeOptions.map((a) => (
                    <button
                      key={a.value}
                      type="button"
                      onClick={() => setForm({ ...form, archetype: a.value as typeof form.archetype, species: "", customSpecies: "" })}
                      className={`p-3.5 rounded-2xl text-center transition-all duration-300 ${
                        form.archetype === a.value
                          ? "bg-violet-500/10 ring-1 ring-violet-500/25 scale-[1.02]"
                          : "bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.04]"
                      }`}
                    >
                      <div className="text-2xl mb-0.5">{a.emoji}</div>
                      <div className="text-[11px] text-white/40">{a.label}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Species/role selector — conditional by archetype */}
              {form.archetype === "ANIMAL" && (
                <div className="mb-6">
                  <label className="block text-[11px] text-white/35 mb-3 font-medium tracking-wide uppercase">物种</label>
                  <div className="grid grid-cols-4 gap-2.5">
                    {speciesOptions.map((s) => (
                      <button
                        key={s.value}
                        type="button"
                        onClick={() => setForm({ ...form, species: s.value, customSpecies: "" })}
                        className={`p-3.5 rounded-2xl text-center transition-all duration-300 ${
                          form.species === s.value
                            ? "bg-amber-500/10 ring-1 ring-amber-500/25 scale-[1.02]"
                            : "bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.04]"
                        }`}
                      >
                        <div className="text-2xl mb-0.5">{s.emoji}</div>
                        <div className="text-[11px] text-white/40">{s.value}</div>
                      </button>
                    ))}
                  </div>
                  <input value={form.customSpecies} onChange={(e) => setForm({ ...form, customSpecies: e.target.value, species: "" })} className="input-dark w-full text-[13px] mt-2.5" placeholder="或输入自定义物种..." />
                </div>
              )}
              {form.archetype === "HUMAN" && (
                <div className="mb-6">
                  <label className="block text-[11px] text-white/35 mb-3 font-medium tracking-wide uppercase">角色类型</label>
                  <div className="flex gap-2 flex-wrap">
                    {humanRoles.map((r) => (
                      <button key={r} type="button" onClick={() => setForm({ ...form, species: r, customSpecies: "" })}
                        className={`px-3.5 py-[7px] rounded-full text-[12px] transition-all duration-300 ${form.species === r ? "bg-violet-500/12 text-violet-300 ring-1 ring-violet-500/20" : "bg-white/[0.03] text-white/30 hover:text-white/50 border border-white/[0.04]"}`}>{r}</button>
                    ))}
                  </div>
                  <input value={form.customSpecies} onChange={(e) => setForm({ ...form, customSpecies: e.target.value, species: "" })} className="input-dark w-full text-[13px] mt-2.5" placeholder="或输入自定义角色..." />
                </div>
              )}
              {form.archetype === "FANTASY" && (
                <div className="mb-6">
                  <label className="block text-[11px] text-white/35 mb-3 font-medium tracking-wide uppercase">角色类型</label>
                  <div className="flex gap-2 flex-wrap">
                    {fantasyRoles.map((r) => (
                      <button key={r} type="button" onClick={() => setForm({ ...form, species: r, customSpecies: "" })}
                        className={`px-3.5 py-[7px] rounded-full text-[12px] transition-all duration-300 ${form.species === r ? "bg-cyan-500/12 text-cyan-300 ring-1 ring-cyan-500/20" : "bg-white/[0.03] text-white/30 hover:text-white/50 border border-white/[0.04]"}`}>{r}</button>
                    ))}
                  </div>
                  <input value={form.customSpecies} onChange={(e) => setForm({ ...form, customSpecies: e.target.value, species: "" })} className="input-dark w-full text-[13px] mt-2.5" placeholder="或输入自定义角色..." />
                </div>
              )}

              <div className="space-y-4">
                {/* Content tier */}
                <div>
                  <label className="block text-[11px] text-white/35 mb-2 font-medium">内容分级</label>
                  <div className="flex gap-2">
                    {contentTierOptions.map((t) => (
                      <button key={t.value} type="button" onClick={() => setForm({ ...form, contentTier: t.value as typeof form.contentTier })}
                        className={`px-3.5 py-[7px] rounded-full text-[12px] transition-all duration-300 ${form.contentTier === t.value ? "bg-amber-500/12 text-amber-300 ring-1 ring-amber-500/20" : "bg-white/[0.03] text-white/30 hover:text-white/50 border border-white/[0.04]"}`}>
                        {t.label}
                        <span className="text-[10px] text-white/20 ml-1">({t.desc})</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] text-white/35 mb-1.5 font-medium">名字 *</label>
                    <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input-dark w-full" placeholder={form.archetype === "ANIMAL" ? "如：棉花糖" : "如：小雪"} />
                  </div>
                  <div>
                    <label className="block text-[11px] text-white/35 mb-1.5 font-medium">年龄设定</label>
                    <input type="number" value={form.ageSetting} onChange={(e) => setForm({ ...form, ageSetting: e.target.value })} className="input-dark w-full" placeholder="如：5" />
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] text-white/35 mb-2 font-medium">与用户的关系</label>
                  <div className="flex gap-2 flex-wrap">
                    {(form.archetype === "HUMAN" && form.contentTier === "adult"
                      ? ["暧昧对象", "恋人", "青梅竹马", "暗恋对象"]
                      : ["好朋友", "守护者", "小跟班", "导师", "兄弟姐妹"]
                    ).map((rel) => (
                      <button key={rel} type="button" onClick={() => setForm({ ...form, relationship: rel })}
                        className={`px-3.5 py-[7px] rounded-full text-[12px] transition-all duration-300 ${form.relationship === rel ? "bg-amber-500/12 text-amber-300 ring-1 ring-amber-500/20" : "bg-white/[0.03] text-white/30 hover:text-white/50 border border-white/[0.04]"}`}>{rel}</button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] text-white/35 mb-1.5 font-medium">背景故事</label>
                  <textarea rows={3} value={form.backstory} onChange={(e) => setForm({ ...form, backstory: e.target.value })} className="input-dark w-full resize-none" placeholder="描述角色的来历和世界观..." />
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 1: Personality ─── */}
          {step === 1 && (
            <div className="max-w-2xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-[22px] font-bold tracking-tight text-gold">性格</h2>
                <p className="text-[13px] text-white/25 mt-1">调节角色的灵魂属性</p>
              </div>

              {/* Soul ring */}
              <div className="flex justify-center mb-10">
                <div className="relative w-28 h-28">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="5" />
                    <circle
                      cx="50" cy="50" r="42" fill="none"
                      stroke="url(#g)" strokeWidth="5" strokeLinecap="round"
                      strokeDasharray={`${soulPower * 2.64} ${264 - soulPower * 2.64}`}
                      className="transition-all duration-700"
                    />
                    <defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stopColor="#c9944a" /><stop offset="100%" stopColor="#d4a574" /></linearGradient></defs>
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-[28px] font-bold text-amber-300/90 tabular-nums">{soulPower}</span>
                    <span className="text-[9px] text-white/20 tracking-wider uppercase">Soul</span>
                  </div>
                </div>
              </div>

              <div className="space-y-5">
                {traitConfig.map((trait, i) => {
                  const value = form.personality[trait.key];
                  return (
                    <div key={trait.key} className={`glass rounded-2xl p-5 animate-fade-in stagger-${i + 1}`}>
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-[13px] font-medium text-white/60">{trait.label}</span>
                        <span className="text-[20px] font-bold text-white/70 tabular-nums">{value}</span>
                      </div>
                      <div className="relative">
                        <div className="absolute inset-y-0 left-0 right-0 flex items-center">
                          <div className="w-full h-[3px] rounded-full bg-white/[0.04] overflow-hidden">
                            <div className={`h-full rounded-full bg-gradient-to-r ${trait.color} transition-all duration-300`} style={{ width: `${value}%` }} />
                          </div>
                        </div>
                        <input
                          type="range" min={0} max={100} value={value}
                          onChange={(e) => setForm((prev) => ({ ...prev, personality: { ...prev.personality, [trait.key]: parseInt(e.target.value) } }))}
                          className="relative z-10 w-full" style={{ background: "transparent" }}
                        />
                      </div>
                      <div className="flex justify-between mt-1">
                        <span className="text-[10px] text-white/15">{trait.low}</span>
                        <span className="text-[10px] text-white/15">{trait.high}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ─── Step 2: Speech ─── */}
          {step === 2 && (
            <div className="max-w-xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-[22px] font-bold tracking-tight text-gold">说话风格</h2>
                <p className="text-[13px] text-white/25 mt-1">定义角色的语言特征</p>
              </div>
              <div className="space-y-5">
                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase">句尾口癖</label>
                  <input value={form.suffix} onChange={(e) => setForm({ ...form, suffix: e.target.value })} className="input-dark w-full" placeholder="如：~喵  ~哦  ~嘻嘻" />
                  <p className="text-[10px] text-white/15 mt-1.5">角色在每句话结尾加上此后缀</p>
                </div>

                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase">口头禅</label>
                  <div className="space-y-2">
                    {form.catchphrases.map((phrase, i) => (
                      <div key={i} className="flex gap-2">
                        <input value={phrase} onChange={(e) => { const l = [...form.catchphrases]; l[i] = e.target.value; setForm({ ...form, catchphrases: l }); }} className="input-dark flex-1" placeholder={`口头禅 ${i + 1}`} />
                        {form.catchphrases.length > 1 && (
                          <button type="button" onClick={() => setForm({ ...form, catchphrases: form.catchphrases.filter((_, j) => j !== i) })} className="px-3 text-white/15 hover:text-red-400 transition-colors">×</button>
                        )}
                      </div>
                    ))}
                    <button type="button" onClick={() => setForm({ ...form, catchphrases: [...form.catchphrases, ""] })} className="text-[11px] text-amber-500/40 hover:text-amber-400 transition-colors">+ 添加</button>
                  </div>
                </div>

                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-3 font-medium tracking-wide uppercase">回复长度</label>
                  <div className="grid grid-cols-3 gap-2.5">
                    {[{ value: "SHORT", label: "简短", desc: "1-2句" }, { value: "MEDIUM", label: "适中", desc: "2-3句" }, { value: "LONG", label: "较长", desc: "4-5句" }].map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setForm({ ...form, responseLength: opt.value as "SHORT" | "MEDIUM" | "LONG" })}
                        className={`p-3.5 rounded-xl text-center transition-all duration-300 ${
                          form.responseLength === opt.value
                            ? "bg-amber-500/10 ring-1 ring-amber-500/20 text-amber-300"
                            : "bg-white/[0.02] text-white/30 hover:bg-white/[0.04] border border-white/[0.04]"
                        }`}
                      >
                        <div className="text-[13px] font-medium">{opt.label}</div>
                        <div className="text-[10px] text-white/20 mt-0.5">{opt.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 3: Voice & Language Mode ─── */}
          {step === 3 && (
            <div className="max-w-xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-[22px] font-bold tracking-tight text-gold">音色 & 语言</h2>
                <p className="text-[13px] text-white/25 mt-1">角色是说人话，还是用拟声词表达？</p>
              </div>
              <div className="space-y-5">
                {/* Language mode toggle */}
                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-3 font-medium tracking-wide uppercase">语言模式</label>
                  <div className="grid grid-cols-2 gap-2.5">
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, languageMode: "VERBAL" })}
                      className={`p-4 rounded-xl text-left transition-all duration-300 ${
                        form.languageMode === "VERBAL"
                          ? "bg-amber-500/10 ring-1 ring-amber-500/25 text-amber-300"
                          : "bg-white/[0.02] text-white/35 hover:bg-white/[0.04] border border-white/[0.04]"
                      }`}
                    >
                      <div className="text-[14px] font-medium">🗣️ 正常说话</div>
                      <div className="text-[10px] text-white/25 mt-1">角色用中文对话（默认）</div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, languageMode: "VOCALIZED" })}
                      className={`p-4 rounded-xl text-left transition-all duration-300 ${
                        form.languageMode === "VOCALIZED"
                          ? "bg-violet-500/10 ring-1 ring-violet-500/25 text-violet-300"
                          : "bg-white/[0.02] text-white/35 hover:bg-white/[0.04] border border-white/[0.04]"
                      }`}
                    >
                      <div className="text-[14px] font-medium">🐧 只用拟声词</div>
                      <div className="text-[10px] text-white/25 mt-1">咕咕嘎嘎 / doro 类非语言角色</div>
                    </button>
                  </div>
                </div>

                {/* Vocalization palette — only for VOCALIZED */}
                {form.languageMode === "VOCALIZED" && (
                  <div className="glass rounded-2xl p-5">
                    <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase">拟声词库 *</label>
                    <p className="text-[10px] text-white/15 mb-3">角色能发出的全部音节（例：咕、嘎、咕咕、嘎嘎 / doro、哆啰）</p>
                    <div className="space-y-2">
                      {form.vocalizationPalette.map((v, i) => (
                        <div key={i} className="flex gap-2">
                          <input
                            value={v}
                            onChange={(e) => {
                              const l = [...form.vocalizationPalette];
                              l[i] = e.target.value;
                              setForm({ ...form, vocalizationPalette: l });
                            }}
                            className="input-dark flex-1"
                            placeholder={`音节 ${i + 1}（如：咕咕）`}
                            maxLength={24}
                          />
                          {form.vocalizationPalette.length > 1 && (
                            <button
                              type="button"
                              onClick={() =>
                                setForm({
                                  ...form,
                                  vocalizationPalette: form.vocalizationPalette.filter((_, j) => j !== i),
                                })
                              }
                              className="px-3 text-white/15 hover:text-red-400 transition-colors"
                            >
                              ×
                            </button>
                          )}
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() =>
                          setForm({ ...form, vocalizationPalette: [...form.vocalizationPalette, ""] })
                        }
                        className="text-[11px] text-violet-400/50 hover:text-violet-300 transition-colors"
                      >
                        + 添加音节
                      </button>
                    </div>
                  </div>
                )}

                {/* Voice clone URL */}
                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase">声音克隆样本（可选）</label>
                  <p className="text-[10px] text-white/15 mb-3">
                    Fish Audio 声音克隆：粘贴 10 秒以上清晰原声的 URL，点&ldquo;立即克隆&rdquo;生成专属音色 ID。留空则系统按性格自动匹配预设音色。
                  </p>
                  <div className="flex gap-2">
                    <input
                      value={form.voiceCloneUrl}
                      onChange={(e) => {
                        setForm({ ...form, voiceCloneUrl: e.target.value, voiceCloneRefId: "" });
                        setCloneError(null);
                      }}
                      className="input-dark flex-1"
                      placeholder="https://.../voice-sample.mp3"
                      type="url"
                    />
                    <button
                      type="button"
                      onClick={triggerVoiceClone}
                      disabled={cloning || !form.voiceCloneUrl.trim()}
                      className="px-4 py-2 rounded-xl text-[12px] bg-violet-500/12 text-violet-300/80 border border-violet-500/20 hover:bg-violet-500/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed whitespace-nowrap"
                    >
                      {cloning ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          克隆中...
                        </span>
                      ) : form.voiceCloneRefId ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Check className="w-3.5 h-3.5" />
                          重新克隆
                        </span>
                      ) : (
                        "立即克隆"
                      )}
                    </button>
                  </div>
                  {form.voiceCloneRefId && (
                    <p className="text-[10px] text-violet-300/70 mt-2 break-all">
                      ✓ 克隆成功 · ID:{" "}
                      <code className="font-mono text-violet-300/90">{form.voiceCloneRefId}</code>
                    </p>
                  )}
                  {cloneError && (
                    <p className="text-[10px] text-red-400/80 mt-2">⚠ {cloneError}</p>
                  )}
                  <p className="text-[10px] text-white/15 mt-1.5">
                    版权提醒：商用请确认样本已获授权。Fish Audio 克隆通常需要 5-30 秒。
                  </p>
                </div>

                {/* Audio clips — only for VOCALIZED */}
                {form.languageMode === "VOCALIZED" && (
                  <div className="glass rounded-2xl p-5">
                    <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase">预录音效片段（可选）</label>
                    <p className="text-[10px] text-white/15 mb-3">
                      将&ldquo;音节 → 原声音频 URL&rdquo;一一对应。匹配时直接播放原音，跳过 TTS 合成。
                    </p>
                    <div className="space-y-2">
                      {form.audioClipsRaw.map((c, i) => (
                        <div key={i} className="flex gap-2">
                          <input
                            value={c.phrase}
                            onChange={(e) => {
                              const l = [...form.audioClipsRaw];
                              l[i] = { ...l[i], phrase: e.target.value };
                              setForm({ ...form, audioClipsRaw: l });
                            }}
                            className="input-dark w-1/3"
                            placeholder="音节"
                            maxLength={24}
                          />
                          <input
                            value={c.url}
                            onChange={(e) => {
                              const l = [...form.audioClipsRaw];
                              l[i] = { ...l[i], url: e.target.value };
                              setForm({ ...form, audioClipsRaw: l });
                            }}
                            className="input-dark flex-1"
                            placeholder="https://.../clip.mp3"
                            type="url"
                          />
                          {form.audioClipsRaw.length > 1 && (
                            <button
                              type="button"
                              onClick={() =>
                                setForm({
                                  ...form,
                                  audioClipsRaw: form.audioClipsRaw.filter((_, j) => j !== i),
                                })
                              }
                              className="px-3 text-white/15 hover:text-red-400 transition-colors"
                            >
                              ×
                            </button>
                          )}
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() =>
                          setForm({ ...form, audioClipsRaw: [...form.audioClipsRaw, { phrase: "", url: "" }] })
                        }
                        className="text-[11px] text-violet-400/50 hover:text-violet-300 transition-colors"
                      >
                        + 添加片段
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ─── Step 4: Boundaries ─── */}
          {step === 4 && (
            <div className="max-w-xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-[22px] font-bold tracking-tight text-gold">话题边界</h2>
                <p className="text-[13px] text-white/25 mt-1">设定角色知道和不该谈的内容</p>
              </div>
              <div className="space-y-5">
                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />知识话题</label>
                  <p className="text-[10px] text-white/15 mb-2.5">角色擅长聊的话题</p>
                  <div className="space-y-2">
                    {form.topics.map((topic, i) => (
                      <div key={i} className="flex gap-2">
                        <input value={topic} onChange={(e) => { const l = [...form.topics]; l[i] = e.target.value; setForm({ ...form, topics: l }); }} className="input-dark flex-1" placeholder="如：太空、美食" />
                        {form.topics.length > 1 && <button type="button" onClick={() => setForm({ ...form, topics: form.topics.filter((_, j) => j !== i) })} className="px-3 text-white/15 hover:text-red-400 transition-colors">×</button>}
                      </div>
                    ))}
                    <button type="button" onClick={() => setForm({ ...form, topics: [...form.topics, ""] })} className="text-[11px] text-amber-500/40 hover:text-amber-400 transition-colors">+ 添加</button>
                  </div>
                </div>

                <div className="glass rounded-2xl p-5">
                  <label className="block text-[11px] text-white/35 mb-2 font-medium tracking-wide uppercase flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-red-400" />禁止话题</label>
                  <p className="text-[10px] text-white/15 mb-2.5">角色绝对不会提的内容</p>
                  <div className="space-y-2">
                    {form.forbidden.map((item, i) => (
                      <div key={i} className="flex gap-2">
                        <input value={item} onChange={(e) => { const l = [...form.forbidden]; l[i] = e.target.value; setForm({ ...form, forbidden: l }); }} className="input-dark flex-1" placeholder="如：暴力、恐怖" />
                        {form.forbidden.length > 1 && <button type="button" onClick={() => setForm({ ...form, forbidden: form.forbidden.filter((_, j) => j !== i) })} className="px-3 text-white/15 hover:text-red-400 transition-colors">×</button>}
                      </div>
                    ))}
                    <button type="button" onClick={() => setForm({ ...form, forbidden: [...form.forbidden, ""] })} className="text-[11px] text-red-400/30 hover:text-red-400 transition-colors">+ 添加</button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 5: Preview ─── */}
          {step === 5 && (
            <div className="max-w-2xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-[22px] font-bold tracking-tight text-gold">预览</h2>
                <p className="text-[13px] text-white/25 mt-1">确认角色设定</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="glass rounded-2xl p-6 glow-gold animate-fade-in">
                  <div className="flex items-center gap-3.5 mb-5">
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-amber-500/15 to-amber-700/10 flex items-center justify-center text-2xl">
                      {speciesOptions.find((s) => s.value === form.species)?.emoji || "✨"}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-[18px] font-bold text-white/90">{form.name || "未命名"}</h3>
                        {form.languageMode === "VOCALIZED" && (
                          <span className="px-2 py-[2px] text-[10px] rounded-full bg-violet-500/12 text-violet-300/80 border border-violet-500/20">
                            🐧 拟声
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-white/25">{form.species || form.customSpecies || "未选物种"} · {form.relationship}</p>
                    </div>
                  </div>
                  {form.backstory && <p className="text-[12px] text-white/25 leading-relaxed mb-4 italic">&ldquo;{form.backstory}&rdquo;</p>}
                  <div className="space-y-2">
                    {traitConfig.map((t) => (
                      <div key={t.key} className="flex items-center gap-2">
                        <span className="text-[11px] w-12 text-white/25">{t.label}</span>
                        <div className="flex-1 h-[2px] rounded-full bg-white/[0.04] overflow-hidden">
                          <div className={`h-full rounded-full bg-gradient-to-r ${t.color} stat-bar-fill`} style={{ width: `${form.personality[t.key]}%` }} />
                        </div>
                        <span className="text-[11px] text-white/25 w-6 text-right tabular-nums">{form.personality[t.key]}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="glass rounded-2xl p-6 space-y-4 animate-fade-in stagger-2">
                  <h4 className="text-[12px] font-medium text-white/35 uppercase tracking-wide">语言 & 话题</h4>
                  {form.languageMode === "VOCALIZED" && form.vocalizationPalette.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-white/20">拟声词库</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {form.vocalizationPalette.filter(Boolean).map((v, i) => (
                          <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-violet-500/8 text-violet-300/70">&ldquo;{v}&rdquo;</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {form.suffix && <div><span className="text-[10px] text-white/20">句尾口癖</span><p className="text-[13px] text-amber-300/70 mt-0.5">{form.suffix}</p></div>}
                  {form.catchphrases.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-white/20">口头禅</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">{form.catchphrases.filter(Boolean).map((p, i) => <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-amber-500/8 text-amber-300/60">&ldquo;{p}&rdquo;</span>)}</div>
                    </div>
                  )}
                  {form.topics.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-white/20">知识话题</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">{form.topics.filter(Boolean).map((t, i) => <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-emerald-500/8 text-emerald-300/60">{t}</span>)}</div>
                    </div>
                  )}
                  {form.forbidden.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-white/20">禁止话题</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">{form.forbidden.filter(Boolean).map((f, i) => <span key={i} className="px-2 py-[2px] text-[11px] rounded-full bg-red-500/8 text-red-400/50">{f}</span>)}</div>
                    </div>
                  )}
                  <div><span className="text-[10px] text-white/20">回复长度</span><p className="text-[13px] text-white/40 mt-0.5">{form.responseLength === "SHORT" ? "简短" : form.responseLength === "MEDIUM" ? "适中" : "较长"}</p></div>
                </div>
              </div>

              {/* Voice preview */}
              <div className="mt-4 glass rounded-2xl p-5 animate-fade-in stagger-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="text-[12px] font-medium text-white/35 uppercase tracking-wide">音色预览</h4>
                    <p className="text-[11px] text-white/20 mt-0.5">系统会根据性格自动匹配音色</p>
                  </div>
                  <button
                    type="button"
                    onClick={previewVoice}
                    disabled={previewing}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl text-[12px] bg-amber-500/8 text-amber-300/60 border border-amber-500/12 hover:bg-amber-500/15 transition-colors disabled:opacity-40"
                  >
                    {previewing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Volume2 className="w-3.5 h-3.5" />}
                    {previewing ? "生成中..." : "试听音色"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Nav buttons */}
      <div className="flex justify-between mt-10 max-w-2xl mx-auto">
        <button
          type="button"
          onClick={() => setStep(Math.max(0, step - 1))}
          className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[13px] transition-all duration-300 ${
            step === 0 ? "opacity-0 pointer-events-none" : "text-white/35 hover:text-white/60 hover:bg-white/[0.03]"
          }`}
        >
          <ChevronLeft className="w-4 h-4" /> 上一步
        </button>
        {step < steps.length - 1 ? (
          <button type="button" onClick={() => setStep(step + 1)} disabled={!canNext()} className="btn-primary flex items-center gap-1.5 text-[13px] disabled:opacity-25">
            下一步 <ChevronRight className="w-4 h-4" />
          </button>
        ) : (
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary flex items-center gap-2 text-[13px]">
            <Flame className="w-4 h-4" /> {saving ? "创建中..." : "完成创建"}
          </button>
        )}
      </div>
    </div>
  );
}
