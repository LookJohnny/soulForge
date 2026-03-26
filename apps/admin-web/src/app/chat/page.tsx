"use client";

import { useState, useEffect, useCallback, CSSProperties } from "react";
import { useRouter } from "next/navigation";

interface Character {
  id: string;
  name: string;
  species: string | null;
  archetype: string;
  backstory: string | null;
  avatar: string | null;
}

const safeFetch = (url: string) =>
  fetch(url, { headers: { "ngrok-skip-browser-warning": "1" } });

const ARCHETYPE_STYLE: Record<string, { gradient: string; emoji: string; label: string; tagColor: string }> = {
  ANIMAL:   { gradient: "linear-gradient(135deg, #f6d365 0%, #fda085 100%)", emoji: "🧸", label: "宠物", tagColor: "#f59e0b" },
  HUMAN:    { gradient: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)", emoji: "💜", label: "人物", tagColor: "#7c3aed" },
  FANTASY:  { gradient: "linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)", emoji: "✨", label: "奇幻", tagColor: "#ec4899" },
  ABSTRACT: { gradient: "linear-gradient(135deg, #89f7fe 0%, #66a6ff 100%)", emoji: "🤖", label: "助手", tagColor: "#3b82f6" },
};

export default function ChatListPage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const router = useRouter();

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    safeFetch("/api/chat")
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((list: Character[]) => {
        // Deduplicate by name (keep first)
        const seen = new Set<string>();
        const deduped = list.filter((c) => {
          if (seen.has(c.name)) return false;
          seen.add(c.name);
          return true;
        });
        setCharacters(deduped);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  /* ── Skeleton card for loading state ─────── */
  const SkeletonCard = ({ i }: { i: number }) => (
    <div style={{
      ...S.card, opacity: 0.5,
      animation: `skeleton-pulse 1.2s ease-in-out ${i * 0.15}s infinite`,
    }}>
      <div style={{ ...S.avatarBase, background: "#e5e5ea" }} />
      <div style={S.cardInfo}>
        <div style={{ width: 80, height: 14, background: "#e5e5ea", borderRadius: 4 }} />
        <div style={{ width: 50, height: 11, background: "#f0f0f3", borderRadius: 4, marginTop: 6 }} />
      </div>
    </div>
  );

  return (
    <div style={S.page} suppressHydrationWarning>
      <style dangerouslySetInnerHTML={{ __html: "" }} suppressHydrationWarning />

      <div style={S.header}>
        <h1 style={S.title}>SoulForge</h1>
        <p style={S.subtitle}>
          {loading ? "加载中…" : `${characters.length} 个角色可用`}
        </p>
      </div>

      <div style={S.grid}>
        {/* Loading skeleton */}
        {loading && [0, 1, 2].map((i) => <SkeletonCard key={i} i={i} />)}

        {/* Error state */}
        {!loading && error && (
          <div style={S.emptyBox}>
            <p style={{ color: "#8e8e93", fontSize: 15, margin: "0 0 12px" }}>加载失败</p>
            <button onClick={load} style={S.retryBtn}>重新加载</button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && characters.length === 0 && (
          <div style={S.emptyBox}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🎭</div>
            <p style={{ color: "#8e8e93", fontSize: 15, margin: 0 }}>暂无可用角色</p>
            <p style={{ color: "#aeaeb2", fontSize: 13, margin: "4px 0 0" }}>在管理后台创建并发布角色</p>
          </div>
        )}

        {/* Character cards */}
        {!loading && characters.map((c, i) => {
          const arch = ARCHETYPE_STYLE[c.archetype] || ARCHETYPE_STYLE.ANIMAL;
          return (
            <button
              key={c.id}
              style={{ ...S.card, animationDelay: `${i * 0.06}s` }}
              onClick={() => router.push(`/chat/${c.id}`)}
            >
              <div style={{ ...S.avatarBase, background: arch.gradient }}>
                <span style={{ color: "#fff", fontSize: 22, fontWeight: 700, lineHeight: 1, textShadow: "0 1px 2px rgba(0,0,0,0.15)" }}>
                  {c.name[0]}
                </span>
              </div>
              <div style={S.cardInfo}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <p style={S.cardName}>{c.name}</p>
                  <span style={{
                    fontSize: 10, fontWeight: 600, color: arch.tagColor,
                    background: `${arch.tagColor}15`, padding: "1px 6px",
                    borderRadius: 6, lineHeight: "16px", flexShrink: 0,
                  }}>{arch.label}</span>
                </div>
                {c.species && <p style={S.cardSpecies}>{c.species}</p>}
                {c.backstory && <p style={S.cardDesc as CSSProperties}>{c.backstory}</p>}
              </div>
              <span style={S.arrow}>›</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── Styles ──────────────────────────────────── */
const S: Record<string, CSSProperties> & { avatarBase: CSSProperties } = {
  page: {
    minHeight: "100dvh",
    background: "#f2f2f7",
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif',
    paddingTop: "env(safe-area-inset-top, 0px)",
    paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 20px)",
  },
  header: {
    padding: "24px 20px 16px",
  },
  title: {
    fontSize: 30,
    fontWeight: 700,
    color: "#1c1c1e",
    margin: 0,
    letterSpacing: "-0.02em",
  },
  subtitle: {
    fontSize: 14,
    color: "#8e8e93",
    margin: "6px 0 0",
    fontWeight: 400,
  },
  grid: {
    padding: "0 16px",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  card: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    padding: "14px 12px 14px 14px",
    background: "#fff",
    borderRadius: 16,
    border: "none",
    cursor: "pointer",
    textAlign: "left",
    WebkitTapHighlightColor: "transparent",
    boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
    animation: "card-appear 0.35s cubic-bezier(0.25,0.46,0.45,0.94) both",
  },
  avatarBase: {
    width: 52,
    height: 52,
    borderRadius: 14,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 24,
    flexShrink: 0,
  },
  cardInfo: {
    flex: 1,
    minWidth: 0,
  },
  cardName: {
    fontSize: 16,
    fontWeight: 600,
    color: "#1c1c1e",
    margin: 0,
    lineHeight: 1.3,
  },
  cardSpecies: {
    fontSize: 13,
    color: "#8e8e93",
    margin: "2px 0 0",
  },
  cardDesc: {
    fontSize: 12,
    color: "#aeaeb2",
    margin: "4px 0 0",
    lineHeight: 1.4,
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  } as CSSProperties,
  arrow: {
    color: "#c7c7cc",
    fontSize: 20,
    flexShrink: 0,
    marginLeft: 4,
  },
  emptyBox: {
    textAlign: "center",
    padding: "60px 20px",
  },
  retryBtn: {
    padding: "10px 24px",
    fontSize: 14,
    fontWeight: 500,
    color: "#fff",
    background: "#007aff",
    border: "none",
    borderRadius: 20,
    cursor: "pointer",
    WebkitTapHighlightColor: "transparent",
  },
};
