"use client";

import { useState, useEffect, useRef } from "react";
import { Upload, Mic, Check, Loader2, AlertCircle } from "lucide-react";

interface Character {
  id: string;
  name: string;
  species: string | null;
}

export default function VoiceClonePage() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [characterId, setCharacterId] = useState("");
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ fishAudioId: string; voiceId: string } | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/characters")
      .then((r) => r.json())
      .then((data) => setCharacters(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !title) return;

    setLoading(true);
    setError("");
    setResult(null);

    const form = new FormData();
    form.append("audio", file);
    form.append("title", title);
    if (characterId) form.append("characterId", characterId);

    try {
      const resp = await fetch("/api/voices/clone", { method: "POST", body: form });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: "Unknown error" }));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Clone failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Mic className="w-6 h-6 text-blue-500" />
        <h1 className="text-xl font-semibold text-gray-900">声音克隆</h1>
      </div>

      <p className="text-sm text-gray-500 mb-6">
        上传 10-60 秒的 MP3/WAV 音频，自动创建角色专属音色。基于 Fish Audio S1 声音克隆引擎。
      </p>

      <form onSubmit={handleSubmit} className="space-y-5 max-w-lg">
        {/* File upload */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">音频文件</label>
          <div
            onClick={() => fileRef.current?.click()}
            className="border-2 border-dashed border-gray-200 rounded-xl p-6 text-center cursor-pointer hover:border-blue-300 transition-colors"
          >
            <input
              ref={fileRef}
              type="file"
              accept="audio/mpeg,audio/wav,audio/mp3,.mp3,.wav"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file ? (
              <div className="flex items-center justify-center gap-2 text-sm text-gray-700">
                <Check className="w-4 h-4 text-green-500" />
                {file.name} ({(file.size / 1024).toFixed(0)} KB)
              </div>
            ) : (
              <div>
                <Upload className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-400">点击上传 MP3 或 WAV 文件</p>
                <p className="text-xs text-gray-300 mt-1">建议 10-60 秒清晰人声</p>
              </div>
            )}
          </div>
        </div>

        {/* Voice name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">音色名称</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例：暮影司专属音色"
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
          />
        </div>

        {/* Assign to character */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">绑定角色（可选）</label>
          <select
            value={characterId}
            onChange={(e) => setCharacterId(e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="">不绑定，稍后手动分配</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} {c.species ? `(${c.species})` : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={!file || !title || loading}
          className="w-full py-2.5 bg-blue-500 text-white rounded-lg text-sm font-medium disabled:opacity-40 hover:bg-blue-600 transition-colors flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              正在克隆音色...
            </>
          ) : (
            <>
              <Mic className="w-4 h-4" />
              开始克隆
            </>
          )}
        </button>
      </form>

      {/* Error */}
      {error && (
        <div className="mt-4 p-3 bg-red-50 text-red-600 rounded-lg text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Success */}
      {result && (
        <div className="mt-4 p-4 bg-green-50 rounded-lg">
          <div className="flex items-center gap-2 text-green-700 font-medium text-sm mb-2">
            <Check className="w-4 h-4" />
            音色克隆成功
          </div>
          <div className="text-xs text-gray-500 space-y-1">
            <p>Fish Audio ID: <code className="bg-white px-1 py-0.5 rounded">{result.fishAudioId}</code></p>
            <p>Voice Profile ID: <code className="bg-white px-1 py-0.5 rounded">{result.voiceId}</code></p>
          </div>
        </div>
      )}
    </div>
  );
}
