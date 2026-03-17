"use client";

import { useState, useRef } from "react";
import { Play, Square, Loader2 } from "lucide-react";

export default function VoicePreview({
  voiceId,
  voiceName,
}: {
  voiceId: string | null;
  voiceName: string;
}) {
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const preview = async () => {
    if (playing && audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setPlaying(false);
      return;
    }

    if (!voiceId) return;
    setLoading(true);

    try {
      const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "tts",
          text: `你好呀，我是${voiceName}，很高兴认识你！`,
          voice: voiceId,
        }),
      });

      if (!res.ok) throw new Error("TTS failed");
      const data = await res.json();

      if (data.audio_base64) {
        const audio = new Audio(`data:audio/wav;base64,${data.audio_base64}`);
        audioRef.current = audio;
        setPlaying(true);
        audio.onended = () => setPlaying(false);
        audio.onerror = () => setPlaying(false);
        audio.play();
      }
    } catch {
      // silent fail
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={preview}
      disabled={loading || !voiceId}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all ${
        playing
          ? "bg-purple-500/20 text-purple-300"
          : voiceId
            ? "glass text-white/40 hover:text-white/60"
            : "opacity-30 cursor-not-allowed text-white/20"
      }`}
    >
      {loading ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : playing ? (
        <Square className="w-3 h-3" />
      ) : (
        <Play className="w-3 h-3" />
      )}
      {loading ? "生成中..." : playing ? "停止" : "试听"}
    </button>
  );
}
