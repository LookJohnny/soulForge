"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronRight,
  ChevronLeft,
  User,
  Brain,
  MessageCircle,
  Shield,
  Flame,
  Check,
} from "lucide-react";
import type { PersonalityTraits } from "@soulforge/shared";

// ─── Step definitions ─────────────────────────────

const steps = [
  { id: "basic", label: "召唤", icon: User },
  { id: "personality", label: "注灵", icon: Brain },
  { id: "speech", label: "赐言", icon: MessageCircle },
  { id: "boundary", label: "禁忌", icon: Shield },
  { id: "preview", label: "铸魂", icon: Flame },
];

// ─── Personality config ────────────────────────────

const traitConfig: {
  key: keyof PersonalityTraits;
  label: string;
  low: string;
  high: string;
  color: string;
}[] = [
  {
    key: "extrovert",
    label: "外向度",
    low: "沉默隐者",
    high: "热情使徒",
    color: "from-blue-400 to-cyan-300",
  },
  {
    key: "humor",
    label: "幽默感",
    low: "庄严肃穆",
    high: "诙谐灵动",
    color: "from-amber-500 to-yellow-400",
  },
  {
    key: "warmth",
    label: "温暖度",
    low: "冷峻守望",
    high: "慈悲温暖",
    color: "from-rose-500 to-orange-400",
  },
  {
    key: "curiosity",
    label: "好奇心",
    low: "超然淡定",
    high: "求知若渴",
    color: "from-emerald-500 to-teal-400",
  },
  {
    key: "energy",
    label: "活力值",
    low: "沉静冥思",
    high: "神圣之焰",
    color: "from-amber-600 to-amber-400",
  },
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

// ─── Component ────────────────────────────────────

export default function NewCharacterPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    species: "",
    customSpecies: "",
    ageSetting: "",
    backstory: "",
    relationship: "好朋友",
    personality: {
      extrovert: 50,
      humor: 50,
      warmth: 50,
      curiosity: 50,
      energy: 50,
    } as PersonalityTraits,
    catchphrases: [""],
    suffix: "",
    topics: [""],
    forbidden: ["暴力", "恐怖"],
    responseLength: "SHORT" as "SHORT" | "MEDIUM" | "LONG",
  });

  const handleSubmit = async () => {
    setSaving(true);
    const payload = {
      ...form,
      species: form.species || form.customSpecies,
      ageSetting: form.ageSetting ? parseInt(form.ageSetting) : null,
      catchphrases: form.catchphrases.filter(Boolean),
      topics: form.topics.filter(Boolean),
      forbidden: form.forbidden.filter(Boolean),
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
      alert("锻铸仪式失败，请重试");
    }
  };

  const canNext = () => {
    if (step === 0)
      return form.name && (form.species || form.customSpecies);
    return true;
  };

  const soulPower = Math.round(
    Object.values(form.personality).reduce((a, b) => a + b, 0) /
      Object.values(form.personality).length
  );

  return (
    <div className="max-w-5xl mx-auto">
      {/* Step indicator — ritual stages */}
      <div className="flex items-center justify-center gap-1 mb-10">
        {steps.map((s, i) => (
          <div key={s.id} className="flex items-center">
            <button
              onClick={() => i <= step && setStep(i)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs transition-all ${
                i === step
                  ? "bg-amber-700/20 text-amber-300"
                  : i < step
                    ? "text-amber-500/50 hover:text-amber-300"
                    : "text-amber-800/20"
              }`}
            >
              {i < step ? (
                <Check className="w-3.5 h-3.5" />
              ) : (
                <s.icon className="w-3.5 h-3.5" />
              )}
              <span className="hidden md:inline">{s.label}</span>
            </button>
            {i < steps.length - 1 && (
              <div
                className={`w-8 h-px mx-1 ${i < step ? "bg-amber-600/30" : "bg-amber-900/10"}`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.25 }}
        >
          {/* ─── Step 0: Basic Info ─────────────────── */}
          {step === 0 && (
            <div className="max-w-2xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold rune-text mb-2">
                  召唤仪式
                </h2>
                <p className="text-sm text-amber-600/40">
                  选择容器与真名，召唤灵魂的雏形
                </p>
              </div>

              {/* Species selection */}
              <div className="mb-8">
                <label className="block text-xs text-amber-500/40 mb-3 uppercase tracking-wider">
                  选择容器
                </label>
                <div className="grid grid-cols-4 gap-3">
                  {speciesOptions.map((s) => (
                    <button
                      key={s.value}
                      type="button"
                      onClick={() =>
                        setForm({ ...form, species: s.value, customSpecies: "" })
                      }
                      className={`p-4 rounded-xl text-center transition-all duration-200 ${
                        form.species === s.value
                          ? "glass glow-purple ring-1 ring-amber-500/40"
                          : "glass hover:bg-amber-900/5"
                      }`}
                    >
                      <div className="text-3xl mb-1">{s.emoji}</div>
                      <div className="text-xs text-amber-400/50">{s.value}</div>
                    </button>
                  ))}
                </div>
                <div className="mt-3">
                  <input
                    value={form.customSpecies}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        customSpecies: e.target.value,
                        species: "",
                      })
                    }
                    className="input-dark w-full text-sm"
                    placeholder="或输入自定义容器形态..."
                  />
                </div>
              </div>

              {/* Name & details */}
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-amber-500/40 mb-2">
                      灵魂真名 *
                    </label>
                    <input
                      value={form.name}
                      onChange={(e) =>
                        setForm({ ...form, name: e.target.value })
                      }
                      className="input-dark w-full"
                      placeholder="如：棉花糖"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-amber-500/40 mb-2">
                      灵魂年岁
                    </label>
                    <input
                      type="number"
                      value={form.ageSetting}
                      onChange={(e) =>
                        setForm({ ...form, ageSetting: e.target.value })
                      }
                      className="input-dark w-full"
                      placeholder="如：5"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-amber-500/40 mb-2">
                    与宿主的羁绊
                  </label>
                  <div className="flex gap-2 flex-wrap">
                    {["好朋友", "守护者", "小跟班", "导师", "手足"].map(
                      (rel) => (
                        <button
                          key={rel}
                          type="button"
                          onClick={() =>
                            setForm({ ...form, relationship: rel })
                          }
                          className={`px-4 py-2 rounded-full text-sm transition-all ${
                            form.relationship === rel
                              ? "bg-amber-700/15 text-amber-300 ring-1 ring-amber-600/30"
                              : "glass text-amber-500/30 hover:text-amber-400/50"
                          }`}
                        >
                          {rel}
                        </button>
                      )
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-amber-500/40 mb-2">
                    起源铭文
                  </label>
                  <textarea
                    rows={3}
                    value={form.backstory}
                    onChange={(e) =>
                      setForm({ ...form, backstory: e.target.value })
                    }
                    className="input-dark w-full resize-none"
                    placeholder="书写灵魂的来历与前世..."
                  />
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 1: Personality Sculpting ──────── */}
          {step === 1 && (
            <div className="max-w-3xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold rune-text mb-2">
                  注灵仪式
                </h2>
                <p className="text-sm text-amber-600/40">
                  调和灵魂属性，塑造独一无二的灵魂本质
                </p>
              </div>

              {/* Soul power ring — sacred mandala */}
              <div className="flex justify-center mb-10">
                <div className="relative w-32 h-32">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                    <circle
                      cx="50"
                      cy="50"
                      r="42"
                      fill="none"
                      stroke="rgba(201,148,74,0.06)"
                      strokeWidth="6"
                    />
                    <circle
                      cx="50"
                      cy="50"
                      r="42"
                      fill="none"
                      stroke="url(#soul-gradient)"
                      strokeWidth="6"
                      strokeLinecap="round"
                      strokeDasharray={`${soulPower * 2.64} ${264 - soulPower * 2.64}`}
                      className="transition-all duration-500"
                    />
                    <defs>
                      <linearGradient
                        id="soul-gradient"
                        x1="0%"
                        y1="0%"
                        x2="100%"
                        y2="100%"
                      >
                        <stop offset="0%" stopColor="#c9944a" />
                        <stop offset="100%" stopColor="#d4a574" />
                      </linearGradient>
                    </defs>
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-3xl font-bold text-amber-300/90">
                      {soulPower}
                    </span>
                    <span className="text-[10px] text-amber-600/30">灵魂强度</span>
                  </div>
                </div>
              </div>

              {/* Trait sliders */}
              <div className="space-y-6">
                {traitConfig.map((trait) => {
                  const value = form.personality[trait.key];
                  return (
                    <div key={trait.key} className="glass rounded-xl p-5">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-sm font-medium text-amber-300/70">
                          {trait.label}
                        </span>
                        <span className="text-2xl font-bold text-amber-200/80 tabular-nums">
                          {value}
                        </span>
                      </div>

                      <div className="relative">
                        <div className="absolute inset-y-0 left-0 right-0 flex items-center">
                          <div className="w-full h-1.5 rounded-full bg-amber-900/15 overflow-hidden">
                            <div
                              className={`h-full rounded-full bg-gradient-to-r ${trait.color} transition-all duration-200`}
                              style={{ width: `${value}%` }}
                            />
                          </div>
                        </div>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={value}
                          onChange={(e) =>
                            setForm((prev) => ({
                              ...prev,
                              personality: {
                                ...prev.personality,
                                [trait.key]: parseInt(e.target.value),
                              },
                            }))
                          }
                          className="relative z-10 w-full"
                          style={{ background: "transparent" }}
                        />
                      </div>

                      <div className="flex justify-between mt-1.5">
                        <span className="text-[10px] text-amber-700/30">
                          {trait.low}
                        </span>
                        <span className="text-[10px] text-amber-700/30">
                          {trait.high}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ─── Step 2: Speech Style ──────────────── */}
          {step === 2 && (
            <div className="max-w-2xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold rune-text mb-2">
                  赐言仪式
                </h2>
                <p className="text-sm text-amber-600/40">
                  雕刻灵魂的语言印记与神谕风格
                </p>
              </div>

              <div className="space-y-6">
                {/* Suffix */}
                <div className="glass rounded-xl p-5">
                  <label className="block text-xs text-amber-500/40 mb-3 uppercase tracking-wider">
                    语尾神印
                  </label>
                  <input
                    value={form.suffix}
                    onChange={(e) =>
                      setForm({ ...form, suffix: e.target.value })
                    }
                    className="input-dark w-full"
                    placeholder="如：~喵  ~哦  ~嘻嘻"
                  />
                  <p className="text-[10px] text-amber-700/25 mt-2">
                    灵魂会在每句话末尾印上此神印
                  </p>
                </div>

                {/* Catchphrases */}
                <div className="glass rounded-xl p-5">
                  <label className="block text-xs text-amber-500/40 mb-3 uppercase tracking-wider">
                    口头神谕
                  </label>
                  <div className="space-y-2">
                    {form.catchphrases.map((phrase, i) => (
                      <div key={i} className="flex gap-2">
                        <input
                          value={phrase}
                          onChange={(e) => {
                            const list = [...form.catchphrases];
                            list[i] = e.target.value;
                            setForm({ ...form, catchphrases: list });
                          }}
                          className="input-dark flex-1"
                          placeholder={`神谕 ${i + 1}`}
                        />
                        {form.catchphrases.length > 1 && (
                          <button
                            type="button"
                            onClick={() => {
                              const list = form.catchphrases.filter(
                                (_, j) => j !== i
                              );
                              setForm({ ...form, catchphrases: list });
                            }}
                            className="px-3 text-amber-700/20 hover:text-red-400 transition-colors"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        setForm({
                          ...form,
                          catchphrases: [...form.catchphrases, ""],
                        })
                      }
                      className="text-xs text-amber-500/40 hover:text-amber-400 transition-colors"
                    >
                      + 添加神谕
                    </button>
                  </div>
                </div>

                {/* Response length */}
                <div className="glass rounded-xl p-5">
                  <label className="block text-xs text-amber-500/40 mb-3 uppercase tracking-wider">
                    言灵长度
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { value: "SHORT", label: "简短", desc: "1-2句" },
                      { value: "MEDIUM", label: "适中", desc: "2-3句" },
                      { value: "LONG", label: "详尽", desc: "4-5句" },
                    ].map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() =>
                          setForm({
                            ...form,
                            responseLength: opt.value as "SHORT" | "MEDIUM" | "LONG",
                          })
                        }
                        className={`p-4 rounded-xl text-center transition-all ${
                          form.responseLength === opt.value
                            ? "bg-amber-700/15 ring-1 ring-amber-600/30 text-amber-300"
                            : "bg-amber-900/5 text-amber-500/30 hover:bg-amber-900/10"
                        }`}
                      >
                        <div className="text-sm font-medium">{opt.label}</div>
                        <div className="text-[10px] text-amber-700/25 mt-0.5">
                          {opt.desc}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 3: Topics & Boundaries ───────── */}
          {step === 3 && (
            <div className="max-w-2xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold rune-text mb-2">
                  禁忌铭刻
                </h2>
                <p className="text-sm text-amber-600/40">
                  划定灵魂的知识领域与不可触碰的禁忌
                </p>
              </div>

              <div className="space-y-6">
                {/* Topics */}
                <div className="glass rounded-xl p-5">
                  <label className="block text-xs text-amber-500/40 mb-3 uppercase tracking-wider flex items-center gap-2">
                    <span className="text-emerald-400">&#9672;</span>
                    知识领域
                  </label>
                  <p className="text-[10px] text-amber-700/25 mb-3">
                    灵魂精通且乐于开示的领域
                  </p>
                  <div className="space-y-2">
                    {form.topics.map((topic, i) => (
                      <div key={i} className="flex gap-2">
                        <input
                          value={topic}
                          onChange={(e) => {
                            const list = [...form.topics];
                            list[i] = e.target.value;
                            setForm({ ...form, topics: list });
                          }}
                          className="input-dark flex-1"
                          placeholder="如：太空、美食、动物"
                        />
                        {form.topics.length > 1 && (
                          <button
                            type="button"
                            onClick={() =>
                              setForm({
                                ...form,
                                topics: form.topics.filter((_, j) => j !== i),
                              })
                            }
                            className="px-3 text-amber-700/20 hover:text-red-400 transition-colors"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        setForm({ ...form, topics: [...form.topics, ""] })
                      }
                      className="text-xs text-amber-500/40 hover:text-amber-400 transition-colors"
                    >
                      + 添加领域
                    </button>
                  </div>
                </div>

                {/* Forbidden */}
                <div className="glass rounded-xl p-5">
                  <label className="block text-xs text-amber-500/40 mb-3 uppercase tracking-wider flex items-center gap-2">
                    <span className="text-red-400">&#9670;</span>
                    禁忌封印
                  </label>
                  <p className="text-[10px] text-amber-700/25 mb-3">
                    灵魂绝对不得触及的禁忌之语
                  </p>
                  <div className="space-y-2">
                    {form.forbidden.map((item, i) => (
                      <div key={i} className="flex gap-2">
                        <input
                          value={item}
                          onChange={(e) => {
                            const list = [...form.forbidden];
                            list[i] = e.target.value;
                            setForm({ ...form, forbidden: list });
                          }}
                          className="input-dark flex-1"
                          placeholder="如：暴力、恐怖"
                        />
                        {form.forbidden.length > 1 && (
                          <button
                            type="button"
                            onClick={() =>
                              setForm({
                                ...form,
                                forbidden: form.forbidden.filter(
                                  (_, j) => j !== i
                                ),
                              })
                            }
                            className="px-3 text-amber-700/20 hover:text-red-400 transition-colors"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        setForm({
                          ...form,
                          forbidden: [...form.forbidden, ""],
                        })
                      }
                      className="text-xs text-red-500/30 hover:text-red-400 transition-colors"
                    >
                      + 添加禁忌
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 4: Preview ───────────────────── */}
          {step === 4 && (
            <div className="max-w-3xl mx-auto">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold rune-text mb-2">
                  灵魂铸造
                </h2>
                <p className="text-sm text-amber-600/40">
                  审视灵魂全貌，点燃圣火完成锻铸
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {/* Character card */}
                <div className="glass rounded-2xl p-6 glow-purple">
                  <div className="flex items-center gap-4 mb-5">
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-700/30 to-amber-900/30 flex items-center justify-center text-3xl">
                      {speciesOptions.find(
                        (s) => s.value === form.species
                      )?.emoji || "🕯️"}
                    </div>
                    <div>
                      <h3 className="text-xl font-bold text-amber-200/90">
                        {form.name || "未命名"}
                      </h3>
                      <p className="text-xs text-amber-600/30">
                        {form.species || form.customSpecies || "未选择容器"} ·{" "}
                        {form.relationship}
                      </p>
                    </div>
                  </div>

                  {form.backstory && (
                    <p className="text-xs text-amber-500/35 leading-relaxed mb-4 italic">
                      &ldquo;{form.backstory}&rdquo;
                    </p>
                  )}

                  {/* Mini stat bars */}
                  <div className="space-y-2">
                    {traitConfig.map((t) => (
                      <div key={t.key} className="flex items-center gap-2">
                        <span className="text-xs w-14 text-amber-500/30">
                          {t.label}
                        </span>
                        <div className="flex-1 h-1 rounded-full bg-amber-900/15 overflow-hidden">
                          <div
                            className={`h-full rounded-full bg-gradient-to-r ${t.color} stat-bar-fill`}
                            style={{
                              width: `${form.personality[t.key]}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs text-amber-500/30 w-7 text-right tabular-nums">
                          {form.personality[t.key]}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Speech preview */}
                <div className="glass rounded-2xl p-6 space-y-4">
                  <h4 className="text-sm font-medium text-amber-400/50">
                    言灵印记
                  </h4>

                  {form.suffix && (
                    <div>
                      <span className="text-[10px] text-amber-700/25">语尾神印</span>
                      <p className="text-sm text-amber-300/70 mt-1">
                        {form.suffix}
                      </p>
                    </div>
                  )}

                  {form.catchphrases.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-amber-700/25">口头神谕</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {form.catchphrases.filter(Boolean).map((p, i) => (
                          <span
                            key={i}
                            className="px-2.5 py-1 text-xs rounded-full bg-amber-700/10 text-amber-300/70"
                          >
                            &ldquo;{p}&rdquo;
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {form.topics.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-amber-700/25">
                        知识领域
                      </span>
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {form.topics.filter(Boolean).map((t, i) => (
                          <span
                            key={i}
                            className="px-2.5 py-1 text-xs rounded-full bg-emerald-500/10 text-emerald-300/70"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {form.forbidden.filter(Boolean).length > 0 && (
                    <div>
                      <span className="text-[10px] text-amber-700/25">禁忌封印</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {form.forbidden.filter(Boolean).map((f, i) => (
                          <span
                            key={i}
                            className="px-2.5 py-1 text-xs rounded-full bg-red-500/10 text-red-400/60"
                          >
                            {f}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div>
                    <span className="text-[10px] text-amber-700/25">言灵长度</span>
                    <p className="text-sm text-amber-400/50 mt-1">
                      {form.responseLength === "SHORT"
                        ? "简短 (1-2句)"
                        : form.responseLength === "MEDIUM"
                          ? "适中 (2-3句)"
                          : "详尽 (4-5句)"}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Navigation buttons */}
      <div className="flex justify-between mt-10 max-w-3xl mx-auto">
        <button
          type="button"
          onClick={() => setStep(Math.max(0, step - 1))}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm transition-all ${
            step === 0
              ? "opacity-0 pointer-events-none"
              : "glass text-amber-400/50 hover:text-amber-300"
          }`}
        >
          <ChevronLeft className="w-4 h-4" />
          上一步
        </button>

        {step < steps.length - 1 ? (
          <button
            type="button"
            onClick={() => setStep(step + 1)}
            disabled={!canNext()}
            className="btn-primary flex items-center gap-2 text-sm disabled:opacity-30"
          >
            下一步
            <ChevronRight className="w-4 h-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saving}
            className="btn-primary flex items-center gap-2 text-sm"
          >
            <Flame className="w-4 h-4" />
            {saving ? "锻铸中..." : "点燃圣火"}
          </button>
        )}
      </div>
    </div>
  );
}
