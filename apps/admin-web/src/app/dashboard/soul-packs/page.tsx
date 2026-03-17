"use client";

import { useState, useEffect } from "react";
import { Package, Download, Upload, Flame } from "lucide-react";

interface Character { id: string; name: string; species: string; status: string; }
interface SoulPackInfo { id: string; characterId: string; version: string; fileSize: number; createdAt: string; }

export default function SoulPacksPage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [packs, setPacks] = useState<SoulPackInfo[]>([]);
  const [exporting, setExporting] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => { fetch("/api/characters").then((r) => r.json()).then(setCharacters); fetch("/api/soul-packs").then((r) => r.json()).then(setPacks); }, []);

  async function handleExport(characterId: string) {
    setExporting(characterId); setResult(null);
    try {
      const res = await fetch("/api/soul-packs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "export", characterId }) });
      if (res.ok) {
        const data = await res.json();
        const blob = new Blob([Uint8Array.from(atob(data.soulpack_b64), (c) => c.charCodeAt(0))], { type: "application/octet-stream" });
        const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${data.character_name || "character"}.soulpack`; a.click();
        setResult(`已导出: ${data.character_name} (${(data.size / 1024).toFixed(1)} KB)`);
      } else { setResult("导出失败"); }
    } catch { setResult("导出失败: AI Core 不可达"); }
    setExporting(null);
  }

  async function handleImport() {
    const input = document.createElement("input"); input.type = "file"; input.accept = ".soulpack";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]; if (!file) return;
      setImporting(true);
      const bytes = new Uint8Array(await file.arrayBuffer()); const b64 = btoa(String.fromCharCode(...bytes));
      try {
        const res = await fetch("/api/soul-packs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "import", soulpackB64: b64 }) });
        if (res.ok) { const d = await res.json(); setResult(`已导入: ${d.character?.name || "角色"}`); }
        else { setResult("导入失败: 密钥不匹配"); }
      } catch { setResult("导入失败"); }
      setImporting(false);
    };
    input.click();
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[26px] font-bold tracking-tight text-gold flex items-center gap-3">
            <Package className="w-6 h-6 text-amber-400" /> 灵魂包
          </h1>
          <p className="text-[13px] text-white/30 mt-1">导出角色为加密灵魂包</p>
        </div>
        <button onClick={handleImport} disabled={importing} className="btn-primary flex items-center gap-1.5 text-[13px]">
          <Upload className="w-3.5 h-3.5" /> {importing ? "导入中..." : "导入"}
        </button>
      </div>

      {result && <div className="p-3.5 rounded-xl bg-amber-500/5 border border-amber-500/10 text-[13px] text-amber-300/70 animate-scale-in">{result}</div>}

      <section className="glass rounded-2xl p-6 animate-fade-in">
        <h2 className="text-[14px] font-semibold text-white/50 mb-4">可导出角色</h2>
        <div className="space-y-2">
          {characters.map((char, i) => (
            <div key={char.id} className={`flex items-center justify-between p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.04] transition-all duration-300 hover:bg-white/[0.04] animate-fade-in stagger-${Math.min(i + 1, 6)}`}>
              <div className="flex items-center gap-2.5">
                <Flame className="w-4 h-4 text-amber-500/40" />
                <span className="text-[13px] text-white/70">{char.name}</span>
                <span className="text-[11px] text-white/20">{char.species}</span>
              </div>
              <button
                onClick={() => handleExport(char.id)}
                disabled={exporting === char.id}
                className="flex items-center gap-1.5 px-3 py-[6px] rounded-lg text-[11px] bg-amber-500/8 text-amber-300/60 border border-amber-500/10 hover:bg-amber-500/15 transition-all duration-300 disabled:opacity-40"
              >
                <Download className="w-3 h-3" />
                {exporting === char.id ? "导出中..." : "导出 .soulpack"}
              </button>
            </div>
          ))}
          {characters.length === 0 && <p className="text-[13px] text-white/20 text-center py-4">暂无角色</p>}
        </div>
      </section>

      {packs.length > 0 && (
        <section className="glass rounded-2xl p-6 animate-fade-in stagger-3">
          <h2 className="text-[14px] font-semibold text-white/50 mb-4">导出记录</h2>
          <div className="space-y-1.5">
            {packs.map((pack) => (
              <div key={pack.id} className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02] text-[12px]">
                <span className="text-white/40">v{pack.version}</span>
                <span className="text-white/20">{(pack.fileSize / 1024).toFixed(1)} KB</span>
                <span className="text-white/20">{new Date(pack.createdAt).toLocaleDateString("zh-CN")}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
