"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Volume2, Loader2, MessageCircle } from "lucide-react";

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  audioBase64?: string;
  latencyMs?: number;
}

export default function ChatPanel({
  characterId,
  characterName,
  characterEmoji,
}: {
  characterId: string;
  characterName: string;
  characterEmoji: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const playAudio = async (audioBase64: string, msgId: string) => {
    // Stop previous audio safely
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.pause();
      if (audioRef.current.src.startsWith("blob:")) {
        URL.revokeObjectURL(audioRef.current.src);
      }
      audioRef.current = null;
    }
    setPlayingId(msgId);

    // Convert base64 to Blob URL
    let bytes: Uint8Array;
    try {
      const raw = atob(audioBase64);
      bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    } catch (e) {
      console.error("Base64 decode failed:", e, "length:", audioBase64.length);
      setPlayingId(null);
      return;
    }

    // Auto-detect audio format from header bytes
    const isWAV = bytes[0] === 0x52 && bytes[1] === 0x49; // "RI" (RIFF)
    const isMP3 = (bytes[0] === 0x49 && bytes[1] === 0x44) || // "ID" (ID3 tag)
                  (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0); // MPEG sync
    const mimeType = isWAV ? "audio/wav" : isMP3 ? "audio/mpeg" : "audio/wav";

    const blob = new Blob([bytes], { type: mimeType });
    const url = URL.createObjectURL(blob);

    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => {
      setPlayingId(null);
      URL.revokeObjectURL(url);
      audioRef.current = null;
    };
    audio.onerror = (e) => {
      console.error("Audio playback error:", e);
      setPlayingId(null);
      URL.revokeObjectURL(url);
      audioRef.current = null;
    };

    try {
      await audio.play();
    } catch (e) {
      console.warn("Audio play failed:", e);
      setPlayingId(null);
      URL.revokeObjectURL(url);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      text: input.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "chat",
          characterId,
          text: userMsg.text,
          withAudio: true,
        }),
      });

      if (!res.ok) throw new Error("请求失败");
      const data = await res.json();

      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        text: data.text || data.error || "...",
        audioBase64: data.audio_base64,
        latencyMs: data.latency_ms,
      };
      setMessages((prev) => [...prev, aiMsg]);

      // Auto-play audio
      if (aiMsg.audioBase64) {
        playAudio(aiMsg.audioBase64, aiMsg.id);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          text: "连接失败，请确保 AI Core 服务正在运行",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="glass rounded-2xl overflow-hidden flex flex-col" style={{ height: 480 }}>
      {/* Header */}
      <div className="px-5 py-3 border-b border-white/5 flex items-center gap-3">
        <MessageCircle className="w-4 h-4 text-purple-400/70" />
        <span className="text-sm font-medium text-white/60">
          与 {characterName} 对话
        </span>
        {messages.length > 0 && (
          <span className="text-[10px] text-white/20 ml-auto">
            {messages.filter((m) => m.role === "assistant").length} 条回复
          </span>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="text-4xl mb-3">{characterEmoji}</div>
            <p className="text-sm text-white/25">
              跟{characterName}说点什么吧
            </p>
            <div className="flex flex-wrap gap-2 mt-4 justify-center">
              {["你好呀！", "给我讲个故事", "你最喜欢什么？"].map((hint) => (
                <button
                  key={hint}
                  onClick={() => {
                    setInput(hint);
                  }}
                  className="px-3 py-1.5 text-xs rounded-full glass text-white/30 hover:text-white/50 transition-colors"
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        )}

        <AnimatePresence>
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] ${
                  msg.role === "user"
                    ? "bg-purple-500/20 text-white/80 rounded-2xl rounded-br-sm"
                    : "glass rounded-2xl rounded-bl-sm"
                } px-4 py-2.5`}
              >
                {msg.role === "assistant" && (
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-xs">{characterEmoji}</span>
                    <span className="text-[10px] text-white/25">
                      {characterName}
                    </span>
                    {msg.latencyMs && (
                      <span className="text-[10px] text-white/15 ml-auto">
                        {(msg.latencyMs / 1000).toFixed(1)}s
                      </span>
                    )}
                  </div>
                )}
                <p className="text-sm text-white/70 leading-relaxed">
                  {msg.text}
                </p>
                {msg.audioBase64 && (
                  <button
                    onClick={() => playAudio(msg.audioBase64!, msg.id)}
                    className={`mt-2 flex items-center gap-1.5 text-[10px] transition-colors ${
                      playingId === msg.id
                        ? "text-purple-400"
                        : "text-white/25 hover:text-white/50"
                    }`}
                  >
                    <Volume2 className={`w-3 h-3 ${playingId === msg.id ? "animate-pulse" : ""}`} />
                    {playingId === msg.id ? "播放中..." : "播放语音"}
                  </button>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex justify-start"
          >
            <div className="glass rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 text-purple-400 animate-spin" />
                <span className="text-xs text-white/30">
                  {characterName}正在思考...
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-white/5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage();
          }}
          className="flex gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入消息..."
            disabled={loading}
            className="input-dark flex-1 text-sm"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="btn-primary px-4 disabled:opacity-30"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
