"use client";

import { useState, useRef, useEffect, useCallback, CSSProperties } from "react";
import { useParams, useRouter } from "next/navigation";

/* ── Emotion → Emoji ─────────────────────────── */
const emotionEmojis: Record<string, string> = {
  happy: "😊", sad: "😢", shy: "😳", angry: "😤",
  playful: "😝", curious: "🤔", worried: "😟", calm: "😌",
};

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  action?: string;
  thought?: string;
  audioBase64?: string;
  emotion?: string;
  stance?: string;
  ts: number;
}

/* ── ngrok-safe fetch ────────────────────────── */
const safeFetch = (url: string, init?: RequestInit) =>
  fetch(url, {
    ...init,
    headers: { ...init?.headers, "ngrok-skip-browser-warning": "1" },
  });

/* ── Time helpers ────────────────────────────── */
function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}
function shouldShowTime(prev: Message | undefined, curr: Message) {
  if (!prev) return true;
  return curr.ts - prev.ts > 5 * 60 * 1000;
}

/* ═══════════════════════════════════════════════
   Styles — all inline, guaranteed to render
   ═══════════════════════════════════════════════ */
const S = {
  page: {
    height: "100dvh",
    display: "flex",
    flexDirection: "column",
    background: "#f2f2f7",
    overflow: "hidden",
    WebkitTextSizeAdjust: "100%",
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif',
  } as CSSProperties,

  header: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "10px 16px",
    paddingTop: "calc(env(safe-area-inset-top, 0px) + 10px)",
    background: "rgba(242,242,247,0.92)",
    backdropFilter: "blur(24px) saturate(1.8)",
    WebkitBackdropFilter: "blur(24px) saturate(1.8)",
    borderBottom: "0.5px solid rgba(0,0,0,0.1)",
    zIndex: 10,
  } as CSSProperties,

  avatar: (size: number, gradient = "linear-gradient(135deg,#667eea,#764ba2)") => ({
    width: size,
    height: size,
    borderRadius: "50%",
    background: gradient,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#fff",
    fontSize: size * 0.42,
    fontWeight: 600,
    flexShrink: 0,
  }) as CSSProperties,

  headerName: {
    fontSize: 17,
    fontWeight: 600,
    color: "#000",
    margin: 0,
    lineHeight: 1.2,
  } as CSSProperties,

  headerSub: {
    fontSize: 12,
    color: "#8e8e93",
    margin: 0,
  } as CSSProperties,

  msgArea: {
    flex: 1,
    overflowY: "auto",
    overflowX: "hidden",
    padding: "12px 16px",
    WebkitOverflowScrolling: "touch",
  } as CSSProperties,

  empty: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    paddingTop: "22vh",
    textAlign: "center",
  } as CSSProperties,

  emptyEmoji: {
    width: 72,
    height: 72,
    borderRadius: "50%",
    background: "linear-gradient(135deg,#e0e7ff,#c7d2fe)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 36,
    marginBottom: 16,
  } as CSSProperties,

  hints: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    justifyContent: "center",
    padding: "0 16px",
    marginTop: 20,
  } as CSSProperties,

  hintBtn: {
    padding: "8px 16px",
    fontSize: 14,
    borderRadius: 18,
    background: "#fff",
    border: "1px solid rgba(0,0,0,0.08)",
    color: "#3a3a3c",
    WebkitTapHighlightColor: "transparent",
    boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
  } as CSSProperties,

  timeLabel: {
    textAlign: "center",
    fontSize: 11,
    color: "#8e8e93",
    margin: "16px 0 8px",
    fontWeight: 500,
  } as CSSProperties,

  row: (isUser: boolean) => ({
    display: "flex",
    justifyContent: isUser ? "flex-end" : "flex-start",
    alignItems: "flex-end",
    gap: 6,
    marginBottom: 6,
  }) as CSSProperties,

  bubble: (isUser: boolean) => ({
    maxWidth: "78%",
    padding: "10px 14px",
    background: isUser ? "#007aff" : "#fff",
    color: isUser ? "#fff" : "#1c1c1e",
    borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
    boxShadow: isUser ? "none" : "0 0.5px 2px rgba(0,0,0,0.08)",
  }) as CSSProperties,

  bubbleText: {
    fontSize: 16,
    lineHeight: 1.45,
    margin: 0,
    wordBreak: "break-word",
    whiteSpace: "pre-wrap",
  } as CSSProperties,

  audioBtn: (isUser: boolean, playing: boolean) => ({
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    marginTop: 6,
    fontSize: 12,
    color: playing ? (isUser ? "#fff" : "#007aff") : (isUser ? "rgba(255,255,255,0.7)" : "#8e8e93"),
    background: "none",
    border: "none",
    padding: "2px 0",
    WebkitTapHighlightColor: "transparent",
  }) as CSSProperties,

  inputBar: {
    padding: "8px 12px",
    paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 8px)",
    background: "rgba(242,242,247,0.92)",
    backdropFilter: "blur(24px) saturate(1.8)",
    WebkitBackdropFilter: "blur(24px) saturate(1.8)",
    borderTop: "0.5px solid rgba(0,0,0,0.1)",
  } as CSSProperties,

  inputRow: {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
    background: "#fff",
    borderRadius: 22,
    padding: "4px 4px 4px 16px",
    border: "1px solid rgba(0,0,0,0.1)",
  } as CSSProperties,

  textarea: {
    flex: 1,
    border: "none",
    outline: "none",
    fontSize: 16,
    lineHeight: 1.4,
    padding: "8px 0",
    background: "transparent",
    color: "#1c1c1e",
    resize: "none",
    maxHeight: 120,
    fontFamily: "inherit",
    WebkitAppearance: "none",
  } as CSSProperties,

  sendBtn: (enabled: boolean) => ({
    width: 36,
    height: 36,
    borderRadius: "50%",
    background: enabled ? "#007aff" : "#e5e5ea",
    color: enabled ? "#fff" : "#c7c7cc",
    border: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    WebkitTapHighlightColor: "transparent",
  }) as CSSProperties,

  typingRow: {
    display: "flex",
    alignItems: "flex-end",
    gap: 6,
    marginBottom: 6,
  } as CSSProperties,

  typingBubble: {
    background: "#fff",
    borderRadius: "18px 18px 18px 4px",
    padding: "12px 16px",
    boxShadow: "0 0.5px 2px rgba(0,0,0,0.08)",
    display: "flex",
    gap: 4,
    alignItems: "center",
  } as CSSProperties,

  cursor: {
    display: "inline-block",
    width: 2,
    height: 16,
    background: "#007aff",
    marginLeft: 2,
    verticalAlign: "text-bottom",
    borderRadius: 1,
    animation: "cursor-blink 1s step-end infinite",
  } as CSSProperties,
};

/* ════════════════════════════════════════════════
   Component
   ════════════════════════════════════════════════ */
/* ── Visitor ID (persisted in localStorage) ──── */
function getVisitorId(): string {
  if (typeof window === "undefined") return "ssr";
  let id = localStorage.getItem("sf_visitor");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("sf_visitor", id);
  }
  return id;
}

export default function MobileChatPage() {
  const { id: characterId } = useParams<{ id: string }>();
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [currentEmotion, setCurrentEmotion] = useState("calm");
  const [charName, setCharName] = useState("...");
  const [charSpecies, setCharSpecies] = useState("");
  const [charGreeting, setCharGreeting] = useState("");
  const [charHints, setCharHints] = useState<string[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const visitorIdRef = useRef("anonymous");

  /* ── Load character info + chat history ─────── */
  useEffect(() => {
    const vid = getVisitorId();
    visitorIdRef.current = vid;

    safeFetch(`/api/chat/${characterId}?visitor=${vid}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => {
        if (c) {
          setCharName(c.name);
          setCharSpecies(c.species || "");
          if (c.greeting) setCharGreeting(c.greeting);
          if (c.hints?.length) setCharHints(c.hints);

          // Restore chat history
          if (c.history?.length) {
            const restored: Message[] = c.history.map((m: any) => ({
              id: m.id,
              role: m.role,
              text: m.content,
              action: m.action || "",
              thought: m.thought || "",
              emotion: m.emotion || "",
              ts: new Date(m.createdAt).getTime(),
            }));
            setMessages(restored);
          }
          setHistoryLoaded(true);
        }
      })
      .catch(() => { setHistoryLoaded(true); });
  }, [characterId]);

  /* ── Scroll ────────────────────────────────── */
  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }, []);
  useEffect(scrollToBottom, [messages, streamingText, scrollToBottom]);

  /* ── Auto-resize textarea ──────────────────── */
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, [input]);

  /* ── Audio ─────────────────────────────────── */
  const playAudio = async (audioBase64: string, msgId: string) => {
    if (audioRef.current) {
      audioRef.current.pause();
      if (audioRef.current.src.startsWith("blob:")) URL.revokeObjectURL(audioRef.current.src);
      audioRef.current = null;
    }
    setPlayingId(msgId);
    try {
      const raw = atob(audioBase64);
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      const blob = new Blob([bytes], {
        type: bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0 ? "audio/mpeg" : "audio/wav",
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => { setPlayingId(null); URL.revokeObjectURL(url); };
      audio.onerror = () => { setPlayingId(null); URL.revokeObjectURL(url); };
      await audio.play();
    } catch { setPlayingId(null); }
  };

  /* ── History ───────────────────────────────── */
  const buildHistory = (msgs: Message[]) =>
    msgs.slice(-20).map((m) => ({ role: m.role, content: m.text }));

  /* ── Send ──────────────────────────────────── */
  const sendMessage = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;

    const now = Date.now();
    const userMsg: Message = { id: now.toString(), role: "user", text, ts: now };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput("");
    setLoading(true);
    setStreamingText("");
    inputRef.current?.blur();

    const aiId = (now + 1).toString();

    try {
      // Abort any in-flight request & set 45s timeout
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const timeout = setTimeout(() => controller.abort(), 45000);

      const res = await safeFetch(`/api/chat/${characterId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          history: buildHistory(updated.slice(0, -1)),
          withAudio: true,
          visitorId: visitorIdRef.current,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No stream");

      const decoder = new TextDecoder();
      let fullText = "";
      let action = "";
      let thought = "";
      let stance = "";
      const audioSegs: { index: number; base64: string }[] = [];
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6).trim());
            if (ev.type === "text" && ev.chunk) { fullText += ev.chunk; setStreamingText(fullText); }
            else if (ev.type === "text_replace") { fullText = ev.text; setStreamingText(fullText); }
            else if (ev.type === "action") action = ev.text || "";
            else if (ev.type === "thought") thought = ev.text || "";
            else if (ev.type === "emotion") { setCurrentEmotion(ev.emotion); stance = ev.stance || ""; }
            else if (ev.type === "audio") audioSegs.push({ index: ev.index ?? audioSegs.length, base64: ev.audio_base64 });
            else if (ev.type === "error") { fullText = ev.message || "服务出错"; break; }
            else if (ev.type === "done") break;
          } catch {}
        }
      }

      let mergedAudio: string | undefined;
      if (audioSegs.length > 0) {
        audioSegs.sort((a, b) => a.index - b.index);
        const chunks = audioSegs.map((s) => {
          const raw = atob(s.base64);
          const bytes = new Uint8Array(raw.length);
          for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
          return bytes;
        });
        const total = chunks.reduce((a, c) => a + c.length, 0);
        const merged = new Uint8Array(total);
        let off = 0;
        for (const c of chunks) { merged.set(c, off); off += c.length; }
        let bin = "";
        for (let i = 0; i < merged.length; i++) bin += String.fromCharCode(merged[i]);
        mergedAudio = btoa(bin);
      }

      const aiMsg: Message = { id: aiId, role: "assistant", text: fullText || "...", action, thought, audioBase64: mergedAudio, emotion: currentEmotion, stance, ts: Date.now() };
      setStreamingText("");
      setMessages((p) => [...p, aiMsg]);
      if (mergedAudio) playAudio(mergedAudio, aiId);
    } catch (err) {
      setStreamingText("");
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      const errText = isAbort ? "响应超时，请重试" : "连接失败，请检查网络";
      setMessages((p) => [...p, { id: aiId, role: "assistant", text: errText, ts: Date.now() }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !composingRef.current) { e.preventDefault(); sendMessage(); }
  };

  const hints = charHints.length > 0 ? charHints : ["你好呀", "给我讲个故事", "你最喜欢什么？", "今天心情怎么样"];
  const canSend = input.trim().length > 0 && !loading;

  /* ── Render ────────────────────────────────── */
  return (
    <div style={S.page} suppressHydrationWarning>

      {/* Header */}
      <div style={S.header}>
        <button onClick={() => router.push("/chat")} style={{
          background: "none", border: "none", padding: "4px 8px 4px 0", cursor: "pointer",
          color: "#007aff", fontSize: 16, WebkitTapHighlightColor: "transparent", flexShrink: 0,
        }}>
          <svg width="10" height="18" viewBox="0 0 10 18" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 1L1 9l8 8"/></svg>
        </button>
        <div style={S.avatar(36)}>{charName[0] || "?"}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={S.headerName}>{charName}</p>
          <p style={S.headerSub}>
            {loading ? <span style={{ color: "#34c759", fontWeight: 500 }}>正在输入…</span> : (
              <>{charSpecies || "在线"}{currentEmotion && currentEmotion !== "calm" ? ` ${emotionEmojis[currentEmotion] || ""}` : ""}</>
            )}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} style={S.msgArea}>
        {messages.length === 0 && !streamingText && (
          <div style={S.empty}>
            <div style={S.emptyEmoji}>{emotionEmojis[currentEmotion] || "😌"}</div>
            <p style={{ color: "#8e8e93", fontSize: 15, margin: 0 }}>{charGreeting || `跟 ${charName} 说点什么吧`}</p>
            <div style={S.hints}>
              {hints.map((h) => (
                <button key={h} style={S.hintBtn} onClick={() => sendMessage(h)}>{h}</button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={msg.id}>
            {shouldShowTime(messages[i - 1], msg) && <div style={S.timeLabel as CSSProperties}>{formatTime(msg.ts)}</div>}
            <div style={S.row(msg.role === "user")}>
              {msg.role === "assistant" && (
                <div style={S.avatar(28)}>{emotionEmojis[msg.emotion || currentEmotion] || charName[0]}</div>
              )}
              <div style={{ maxWidth: "78%" }}>
                {msg.action && msg.role === "assistant" && (
                  <p style={{ fontSize: 12, color: "#8e8e93", fontStyle: "italic", margin: "0 0 4px 4px" }}>
                    *{msg.action}*
                  </p>
                )}
                <div style={S.bubble(msg.role === "user")}>
                  <p style={S.bubbleText}>{msg.text}</p>
                  {msg.audioBase64 && (
                    <button style={S.audioBtn(msg.role === "user", playingId === msg.id)} onClick={() => playAudio(msg.audioBase64!, msg.id)}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
                      {playingId === msg.id ? "播放中…" : "语音"}
                    </button>
                  )}
                </div>
                {msg.thought && msg.role === "assistant" && (
                  <p style={{ fontSize: 11, color: "#aeaeb2", margin: "3px 0 0 4px", fontStyle: "italic" }}>
                    💭 {msg.thought}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Streaming */}
        {streamingText && (
          <div style={S.row(false)}>
            <div style={S.avatar(28)}>{emotionEmojis[currentEmotion] || charName[0]}</div>
            <div style={S.bubble(false)}>
              <p style={S.bubbleText}>{streamingText}<span style={S.cursor} /></p>
            </div>
          </div>
        )}

        {/* Typing dots */}
        {loading && !streamingText && (
          <div style={S.typingRow}>
            <div style={S.avatar(28)}>{charName[0] || "?"}</div>
            <div style={S.typingBubble}>
              {[0, 160, 320].map((d) => (
                <span key={d} style={{
                  width: 8, height: 8, borderRadius: "50%", background: "#8e8e93",
                  animation: `dot-bounce 1.2s ease-in-out ${d}ms infinite`,
                  display: "inline-block",
                }} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div style={S.inputBar}>
        <div style={S.inputRow}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
            placeholder="输入消息…"
            disabled={loading}
            rows={1}
            style={S.textarea}
            suppressHydrationWarning
          />
          <button style={S.sendBtn(canSend)} disabled={!canSend} onClick={() => sendMessage()}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
      </div>
    </div>
  );
}
