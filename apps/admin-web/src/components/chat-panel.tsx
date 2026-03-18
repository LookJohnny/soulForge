"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Volume2, Loader2, MessageCircle } from "lucide-react";

const emotionEmojis: Record<string, string> = {
  happy: "😊", sad: "😢", shy: "😳", angry: "😤",
  playful: "😝", curious: "🤔", worried: "😟", calm: "😌",
};

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  audioBase64?: string;
  emotion?: string;
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
  const [streamingText, setStreamingText] = useState("");
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [currentEmotion, setCurrentEmotion] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const scrollToBottom = useCallback(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, []);

  useEffect(scrollToBottom, [messages, streamingText, scrollToBottom]);

  const playAudio = async (audioBase64: string, msgId: string) => {
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.pause();
      if (audioRef.current.src.startsWith("blob:")) URL.revokeObjectURL(audioRef.current.src);
      audioRef.current = null;
    }
    setPlayingId(msgId);

    let bytes: Uint8Array;
    try {
      const raw = atob(audioBase64);
      bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    } catch {
      setPlayingId(null);
      return;
    }

    const isMP3 = (bytes[0] === 0x49 && bytes[1] === 0x44) || (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0);
    const blob = new Blob([bytes], { type: isMP3 ? "audio/mpeg" : "audio/wav" });
    const url = URL.createObjectURL(blob);

    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => { setPlayingId(null); URL.revokeObjectURL(url); audioRef.current = null; };
    audio.onerror = () => { setPlayingId(null); URL.revokeObjectURL(url); audioRef.current = null; };
    try { await audio.play(); } catch { setPlayingId(null); URL.revokeObjectURL(url); }
  };

  /** Build conversation history for the API (last 20 messages) */
  const buildHistory = (msgs: Message[]) =>
    msgs.slice(-20).map((m) => ({ role: m.role, content: m.text }));

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { id: Date.now().toString(), role: "user", text: input.trim() };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput("");
    setLoading(true);
    setStreamingText("");

    const aiMsgId = (Date.now() + 1).toString();

    try {
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "chat",
          characterId,
          text: userMsg.text,
          history: buildHistory(updatedMessages.slice(0, -1)), // Exclude the current message
          withAudio: true,
          stream: true,
        }),
      });

      if (!res.ok) throw new Error("请求失败");

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No stream");

      const decoder = new TextDecoder();
      let fullText = "";
      let audioBase64: string | undefined;
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from buffer
        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // Keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);

            if (event.type === "text" && event.chunk) {
              fullText += event.chunk;
              setStreamingText(fullText);
            } else if (event.type === "text_replace") {
              fullText = event.text;
              setStreamingText(fullText);
            } else if (event.type === "emotion") {
              setCurrentEmotion(event.emotion);
            } else if (event.type === "audio") {
              audioBase64 = event.audio_base64;
            } else if (event.type === "done") {
              // Stream complete
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }

      // Finalize: add complete message
      const aiMsg: Message = {
        id: aiMsgId,
        role: "assistant",
        text: fullText || "...",
        audioBase64,
        emotion: currentEmotion || undefined,
      };
      setStreamingText("");
      setMessages((prev) => [...prev, aiMsg]);

      if (audioBase64) playAudio(audioBase64, aiMsgId);
    } catch {
      setStreamingText("");
      setMessages((prev) => [
        ...prev,
        { id: aiMsgId, role: "assistant", text: "连接失败，请确保 AI Core 正在运行" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="glass rounded-2xl overflow-hidden flex flex-col" style={{ height: 480 }}>
      {/* Header */}
      <div className="px-5 py-3 border-b border-white/[0.04] flex items-center gap-3">
        <MessageCircle className="w-4 h-4 text-amber-400/60" />
        <span className="text-[13px] font-medium text-white/50">
          与 {characterName} 对话
        </span>
        {currentEmotion && currentEmotion !== "calm" && (
          <span className="text-[12px] ml-1.5" title={currentEmotion}>
            {emotionEmojis[currentEmotion] || ""}
          </span>
        )}
        {messages.length > 0 && (
          <span className="text-[10px] text-white/20 ml-auto">
            {messages.filter((m) => m.role === "assistant").length} 条回复
          </span>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.length === 0 && !streamingText && (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="text-4xl mb-3">{characterEmoji}</div>
            <p className="text-[13px] text-white/25">跟{characterName}说点什么吧</p>
            <div className="flex flex-wrap gap-2 mt-4 justify-center">
              {["你好呀", "给我讲个故事", "你最喜欢什么"].map((hint) => (
                <button
                  key={hint}
                  onClick={() => setInput(hint)}
                  className="px-3 py-1.5 text-[11px] rounded-full bg-white/[0.03] border border-white/[0.06] text-white/30 hover:text-white/50 transition-colors"
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
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] ${
                  msg.role === "user"
                    ? "bg-amber-500/10 text-white/80 rounded-2xl rounded-br-sm"
                    : "bg-white/[0.03] border border-white/[0.04] rounded-2xl rounded-bl-sm"
                } px-4 py-2.5`}
              >
                {msg.role === "assistant" && (
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-[11px]">{characterEmoji}</span>
                    <span className="text-[10px] text-white/25">{characterName}</span>
                    {msg.emotion && msg.emotion !== "calm" && (
                      <span className="text-[10px]" title={msg.emotion}>{emotionEmojis[msg.emotion] || ""}</span>
                    )}
                  </div>
                )}
                <p className="text-[13px] text-white/70 leading-relaxed">{msg.text}</p>
                {msg.audioBase64 && (
                  <button
                    onClick={() => playAudio(msg.audioBase64!, msg.id)}
                    className={`mt-2 flex items-center gap-1.5 text-[10px] transition-colors ${
                      playingId === msg.id ? "text-amber-400" : "text-white/25 hover:text-white/50"
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

        {/* Streaming text — shows while LLM is generating */}
        {streamingText && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
            <div className="max-w-[80%] bg-white/[0.03] border border-white/[0.04] rounded-2xl rounded-bl-sm px-4 py-2.5">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[11px]">{characterEmoji}</span>
                <span className="text-[10px] text-white/25">{characterName}</span>
              </div>
              <p className="text-[13px] text-white/70 leading-relaxed">
                {streamingText}
                <span className="inline-block w-[2px] h-[14px] bg-amber-400/60 ml-0.5 animate-pulse align-text-bottom" />
              </p>
            </div>
          </motion.div>
        )}

        {/* Loading indicator (before stream starts) */}
        {loading && !streamingText && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
            <div className="bg-white/[0.03] border border-white/[0.04] rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 text-amber-400/60 animate-spin" />
                <span className="text-[11px] text-white/25">{characterName}正在思考...</span>
              </div>
            </div>
          </motion.div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-white/[0.04]">
        <form onSubmit={(e) => { e.preventDefault(); sendMessage(); }} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入消息..."
            disabled={loading}
            className="input-dark flex-1 text-[13px]"
          />
          <button type="submit" disabled={!input.trim() || loading} className="btn-primary px-4 disabled:opacity-30">
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
